"""Known-twin retrieval on interleaved hand-ID halves."""
import numpy as np

from .behavior_stats import stat_specs
from .grid_prior import GridScores
from .neighbors import NeighborRanks, ReportShortlist
from .likelihood import LikelihoodScores
from .multiaccount import _component_values, eligible_players, sample_points


LIMITS = (100, 500, 1000, 1500)
BUCKETS = ((50, 150), (150, 500), (500, 1500), (1500, None))
ASSUMPTION = "Known twins come from the same account with no deliberate style change."


class LegacyScores:
    def __init__(self, profiles, config):
        values = [_component_values(profile) for profile in profiles]
        self.rules = config["points"]
        self.values = {key: np.array([v[key] for v in values])
                       for key in ("vpip", "pfr", "threebet", "wtsd", "wonsd")}
        self.hands = np.array([p.hands for p in profiles])
        self.adjustment = np.array([sample_points(n, self.rules.get("sample", {})) for n in self.hands])

    def row(self, i, others):
        scores = np.where(self.hands[i] <= self.hands[others], self.adjustment[i], self.adjustment[others])
        for key, values in self.values.items():
            a, b = values[i], values[others]
            maximum = np.maximum(a, b)
            diff = np.divide(100 * np.abs(a - b), maximum, out=np.zeros_like(b), where=maximum > 0)
            points = np.zeros(len(b), dtype=int)
            for rule in self.rules[key]:
                np.maximum(points, int(rule["points"]), out=points, where=diff <= float(rule["relative_diff_lte"]))
            scores += points
        return scores


def _rank_summary(records):
    result = {"accounts": len(records)}
    for bound in ("optimistic", "pessimistic"):
        ranks = np.array([r[bound] for r in records])
        result[bound] = {
            "median_rank": float(np.median(ranks)) if len(ranks) else None,
            **{f"top_{k}_rate": float(np.mean(ranks <= k)) if len(ranks) else None for k in (1, 10, 50)},
        }
    return result


class PrecisionAtK:
    """Merge each upper-triangle row into a bounded, stably ordered shortlist."""
    def __init__(self):
        self.scores = np.empty(0)
        self.ranks = np.empty(0, dtype=int)
        self.labels = np.empty(0, dtype=bool)

    def add(self, scores, labels, ranks=None):
        pooled = np.concatenate((self.scores, scores))
        if ranks is None:
            keep = np.argsort(-pooled, kind="stable")[:max(LIMITS)]
        else:
            rank_pool = np.concatenate((self.ranks, ranks))
            keep = np.lexsort((-pooled, rank_pool))[:max(LIMITS)]
            self.ranks = rank_pool[keep]
        self.scores = pooled[keep]
        self.labels = np.concatenate((self.labels, labels))[keep]

    def result(self):
        return _precision_at_k(self.labels)


def _precision_at_k(labels):
    return {str(k): float(np.mean(labels[:k])) if len(labels) >= k else None for k in LIMITS}


def evaluate(model, names, profiles, twins, threshold, neighbor_list_size, max_candidates):
    ranks = []
    flagged_pairs = true_flagged = rank_one_twins = rank_one_twins_flagged = 0
    neighbors = NeighborRanks(model, len(names), neighbor_list_size)
    by_score, by_mutual = PrecisionAtK(), PrecisionAtK()
    report = ReportShortlist(threshold, max_candidates)
    indexes = np.arange(len(names))
    known_pairs = sum(j is not None for j in twins) // 2
    for i, name in enumerate(names):
        scores = model.row(i, slice(None))
        j = twins[i]
        if j is not None:
            score = scores[j]
            ranks.append({
                "account": name, "twin": names[j], "smaller_half_hands": min(profiles[i].hands, profiles[j].hands),
                "optimistic": 1 + int(np.count_nonzero((scores > score) & (indexes != i))),
                "pessimistic": int(np.count_nonzero((scores >= score) & (indexes != i))),
            })
        # Count unordered pairs only once. Keep the best K using stable,
        # descending score order; the input order breaks ties by account names.
        upper = scores[i + 1:]
        labels = np.zeros(len(upper), dtype=bool)
        if j is not None and j > i:
            labels[j - i - 1] = True
        mutual_ranks = neighbors.upper_row(i)
        eligible = report.add_row(i, upper, mutual_ranks)
        flagged_pairs += len(eligible)
        true_flagged += int(np.count_nonzero(labels[eligible]))
        rank_one = labels & (mutual_ranks == 1)
        rank_one_twins += int(np.count_nonzero(rank_one))
        rank_one_twins_flagged += int(np.count_nonzero(rank_one[eligible]))
        by_score.add(upper, labels)
        by_mutual.add(upper, labels, mutual_ranks)

    report_twins = [twins[i] == j for i, j, _ in report.ordered_pairs()]
    buckets = {}
    for lo, hi in BUCKETS:
        group = [r for r in ranks if r["smaller_half_hands"] >= lo and
                 (hi is None or r["smaller_half_hands"] < hi)]
        buckets[f"{lo}-{hi}" if hi else f"{lo}+"] = _rank_summary(group)
    return {
        "overall": _rank_summary(ranks), "by_smaller_half": buckets,
        "threshold": {"minimum": threshold, "flagged_pairs": flagged_pairs, "true_pairs_flagged": true_flagged,
                      "precision": true_flagged / flagged_pairs if flagged_pairs else None,
                      "recall": true_flagged / known_pairs if known_pairs else None},
        "report_pairs": len(report_twins),
        "precision_at_k_mutual_rank": _precision_at_k(report_twins),
        "precision_at_k_mutual_rank_unfiltered": by_mutual.result(),
        "precision_at_k": by_score.result(),
        "mutual_rank_one": {"known_twins": rank_one_twins, "known_twins_passing_filter": rank_one_twins_flagged},
        "twin_ranks": ranks,
    }


def validate(split, priors, config, grid_prior):
    names = eligible_players(split.player_stats, config, split=True)
    positions = {name: i for i, name in enumerate(names)}
    profiles = [split.player_stats[name] for name in names]
    twins = [positions.get(name[:-1] + ("1" if name[-1] == "0" else "0")) for name in names]
    size = int(config["neighbor_list_size"])
    cap = int(config["max_candidates"])
    return {
        "neighbor_list_size": size,
        "assumption": ASSUMPTION, "split": "hand_id % 2",
        "max_candidates": cap,
        "precision_at_k_scope": {
            "precision_at_k_mutual_rank": "Apply the report threshold, sort by ascending mutual rank and descending score, then apply the report cap.",
            "precision_at_k_mutual_rank_unfiltered": "Same order across all eligible pairs, without the threshold or cap.",
            "precision_at_k": "Descending score across all eligible pairs, without the threshold or cap.",
        },
        "precision_at_k_ties": "Break ties by ascending account names. Each result is null if fewer than K pairs are available.",
        "eligible_accounts": len(names), "known_pairs": sum(j is not None for j in twins) // 2,
        "compared_pairs": len(names) * (len(names) - 1) // 2,
        "lr": evaluate(GridScores(profiles, grid_prior, stat_specs(config["behavior_groups"])), names, profiles, twins, float(config["min_score_points_to_report"]), size, cap),
        "legacy_beta": evaluate(LikelihoodScores(profiles, priors), names, profiles, twins, float(config["min_score_points_to_report"]), size, cap),
        "legacy": evaluate(LegacyScores(profiles, config), names, profiles, twins, float(config["min_points_to_report"]), size, cap),
    }


def validate_splits(splits, priors, config, grid_prior, *, undated=0):
    result = {"primary_split": "chronological", "undated_player_hands": undated, "splits": {}}
    for name, split in splits.items():
        metrics = validate(split, priors, config, grid_prior)
        if name == "chronological":
            metrics["split"] = "Per account, first and second halves ordered by timestamp, then hand ID."
            metrics["assumption"] = f"{ASSUMPTION} Chronological halves come from different periods."
        else:
            metrics["assumption"] = f"{ASSUMPTION} Parity halves share the same period."
        result["splits"][name] = metrics
    return result


def self_test_line(result):
    labels = []
    for name, title in (("chronological", "Chronological"), ("parity", "Parity")):
        metrics = result["splits"][name]["lr"]
        precision = metrics["precision_at_k_mutual_rank"]["100"]
        value = f"{precision:.0%}" if precision is not None else "N/A"
        labels.append(f"{title} {value}")
    return f"Self-test · precision@100 · {' / '.join(labels)}"
