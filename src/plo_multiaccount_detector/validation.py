"""Known-twin retrieval on interleaved hand-ID halves."""
import numpy as np

from .likelihood import LikelihoodScores
from .multiaccount import _component_values, eligible_players, sample_points


LIMITS = (100, 500, 1000, 1500)
BUCKETS = ((50, 150), (150, 500), (500, 1500), (1500, None))
ASSUMPTION = "Idealized upper bound: same player, same period, no deliberate style change."


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


def evaluate(model, names, profiles, twins, threshold):
    ranks = []
    flagged_pairs = true_flagged = 0
    best_scores = np.empty(0)
    best_labels = np.empty(0, dtype=bool)
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
        flagged = upper >= threshold
        flagged_pairs += int(np.count_nonzero(flagged))
        true_flagged += int(np.count_nonzero(labels & flagged))
        pooled = np.concatenate([best_scores, upper])
        keep = np.argsort(-pooled, kind="stable")[:max(LIMITS)]
        best_scores = pooled[keep]
        best_labels = np.concatenate([best_labels, labels])[keep]

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
        "precision_at_k": {str(k): float(np.mean(best_labels[:k])) if len(best_labels) >= k else None
                           for k in LIMITS},
        "twin_ranks": ranks,
    }


def validate(split, priors, config):
    names = eligible_players(split.player_stats, config, split=True)
    positions = {name: i for i, name in enumerate(names)}
    profiles = [split.player_stats[name] for name in names]
    twins = [positions.get(name[:-1] + ("1" if name[-1] == "0" else "0")) for name in names]
    return {
        "assumption": ASSUMPTION, "split": "hand_id % 2",
        "precision_at_k_ties": "Descending score, then ascending account names. Null when fewer than K pairs exist.",
        "eligible_accounts": len(names), "known_pairs": sum(j is not None for j in twins) // 2,
        "compared_pairs": len(names) * (len(names) - 1) // 2,
        "lr": evaluate(LikelihoodScores(profiles, priors), names, profiles, twins, config["min_score_to_report"]),
        "legacy": evaluate(LegacyScores(profiles, config), names, profiles, twins, config["min_points_to_report"]),
    }


def self_test_line(result):
    overall = result["lr"]["overall"]
    if not overall["accounts"]:
        return "Self-test: no eligible twin pairs."
    low = overall["pessimistic"]["top_10_rate"]
    high = overall["optimistic"]["top_10_rate"]
    rate = f"{low:.1%}" if low == high else f"{low:.1%}–{high:.1%}"
    return f"Self-test: twin in the top 10 for {rate} of {overall['accounts']:,} accounts."
