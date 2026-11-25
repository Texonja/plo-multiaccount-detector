"""Player-side multiaccount / ghost-player candidate scoring.

This module intentionally does not prove multiaccounting. It flags pairs that:
- have very similar 5-handed/6-handed playing-profile stats;
- have enough comparable sample to justify manual review;
- may either have zero observed shared hands (account replacement / multiaccount risk)
  or many observed shared hands (possible coordinated bot/RTA/collusion cluster risk).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import combinations
import csv
import json
from pathlib import Path
from typing import Any

import numpy as np

from .hh_parser import ParsedHand
from .hand_sample import CORE_FLAGS, EXTRA_FLAGS, HandSample, timestamp_key
from .behavior_stats import EXTRA_STATS, GROUPS, behavior_events, sizing_distribution, stat_specs
from .grid_prior import GridScores, fit_grid_priors
from .neighbors import NeighborRanks, ReportShortlist
from .likelihood import STATS, LikelihoodScores, fit_priors

VOLUNTARY_PREFLOP = {"call", "bet", "raise"}
PFR_ACTIONS = {"bet", "raise"}
POSTFLOP_STREETS = {"FLOP", "TURN", "RIVER"}
GENERIC_PLAYER_PREFIX = "Player "


DEFAULT_CONFIG: dict[str, Any] = {
    "table_sizes_for_stats": [6, 5],
    "min_sample_to_compare": 50,
    "min_points_to_report": 100,
    "min_score_to_report": 2.0,
    "max_candidates": 2000,
    "neighbor_list_size": 50,
    "behavior_groups": dict.fromkeys(GROUPS, False),
    "exclude_generic_ipoker_players": True,
    "points": {
        "vpip": [
            {"relative_diff_lte": 7.0, "points": 5},
            {"relative_diff_lte": 5.0, "points": 10},
            {"relative_diff_lte": 2.5, "points": 20},
            {"relative_diff_lte": 1.5, "points": 30},
            {"relative_diff_lte": 1.0, "points": 40},
            {"relative_diff_lte": 0.5, "points": 50}
        ],
        "pfr": [
            {"relative_diff_lte": 10.0, "points": 5},
            {"relative_diff_lte": 7.0, "points": 10},
            {"relative_diff_lte": 3.0, "points": 20},
            {"relative_diff_lte": 2.0, "points": 30},
            {"relative_diff_lte": 1.5, "points": 40},
            {"relative_diff_lte": 1.0, "points": 50}
        ],
        "threebet": [
            {"relative_diff_lte": 30.0, "points": 5},
            {"relative_diff_lte": 25.0, "points": 10},
            {"relative_diff_lte": 20.0, "points": 20},
            {"relative_diff_lte": 15.0, "points": 30},
            {"relative_diff_lte": 10.0, "points": 40},
            {"relative_diff_lte": 5.0, "points": 50}
        ],
        "wtsd": [
            {"relative_diff_lte": 7.0, "points": 5},
            {"relative_diff_lte": 5.0, "points": 10},
            {"relative_diff_lte": 2.5, "points": 20},
            {"relative_diff_lte": 1.5, "points": 30},
            {"relative_diff_lte": 1.0, "points": 40},
            {"relative_diff_lte": 0.5, "points": 50}
        ],
        "wonsd": [
            {"relative_diff_lte": 7.0, "points": 5},
            {"relative_diff_lte": 5.0, "points": 10},
            {"relative_diff_lte": 2.5, "points": 20},
            {"relative_diff_lte": 1.5, "points": 30},
            {"relative_diff_lte": 1.0, "points": 40},
            {"relative_diff_lte": 0.5, "points": 50}
        ],
        "sample": {
            "gt": [
                {"sample_gt": 1000, "points": 20},
                {"sample_gt": 2000, "points": 25},
                {"sample_gt": 3000, "points": 30},
                {"sample_gt": 4000, "points": 40}
            ],
            "lt": [
                {"sample_lt": 100, "points": -20},
                {"sample_lt": 250, "points": -10}
            ]
        }
    }
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(base))
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    if path is None:
        return json.loads(json.dumps(DEFAULT_CONFIG))
    p = Path(path)
    if not p.exists():
        return json.loads(json.dumps(DEFAULT_CONFIG))
    return deep_merge(DEFAULT_CONFIG, json.loads(p.read_text(encoding="utf-8")))


@dataclass
class PlayerProfile:
    hands: int = 0
    vpip: int = 0
    pfr: int = 0
    threebet: int = 0
    threebet_opportunities: int = 0
    saw_flop: int = 0
    went_to_showdown: int = 0
    won_at_showdown: int = 0
    first_seen: str = ""
    last_seen: str = ""
    behavior: dict[str, int] = field(default_factory=dict)

    def stat_count(self, field_name):
        if field_name == "hands" or field_name in CORE_FLAGS:
            return getattr(self, field_name)
        return self.behavior.get(field_name, 0)

    def vpip_pct(self) -> float:
        return pct(self.vpip, self.hands)

    def pfr_pct(self) -> float:
        return pct(self.pfr, self.hands)

    def threebet_pct(self) -> float:
        # True 3bet percentage reconstructed from preflop action flow:
        # actual first re-raise / opportunities to first re-raise after an open.
        return pct(self.threebet, self.threebet_opportunities)

    def wtsd_pct(self) -> float:
        # WTSD reconstructed from raw hand history: showdowns / saw-flop hands.
        return pct(self.went_to_showdown, self.saw_flop)

    def wonsd_pct(self) -> float:
        # Won$SD reconstructed from raw hand history: won money at showdown / showdowns.
        return pct(self.won_at_showdown, self.went_to_showdown)


@dataclass
class MultiaccountRun:
    hands_parsed: int = 0
    parse_errors: int = 0
    player_stats: dict[str, PlayerProfile] = field(default_factory=lambda: defaultdict(PlayerProfile))
    sizing_histogram: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    observed_hands: Counter = field(default_factory=Counter)
    shared_pair_counts: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    parse_error_rows: list[dict[str, str]] = field(default_factory=list)


def pair_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def pct(n: float, d: float) -> float:
    return 100.0 * n / d if d else 0.0


def is_generic_player(name: str) -> bool:
    if not name.startswith(GENERIC_PLAYER_PREFIX):
        return False
    return name[len(GENERIC_PLAYER_PREFIX):].strip().isdigit()


def _live_sets(hand: ParsedHand) -> tuple[set[str], set[str]]:
    """Players live at the flop and after the final betting action."""
    live = set(hand.active_players)
    reached_flop = len(hand.board) >= 3
    preflop_folds = set()
    for action in hand.actions:
        if action.street in POSTFLOP_STREETS:
            reached_flop = True
        if action.action == "fold":
            live.discard(action.player)
            if action.street == "PREFLOP":
                preflop_folds.add(action.player)
    saw_flop = set(hand.active_players) - preflop_folds if reached_flop else set()
    showdown = saw_flop & live
    return saw_flop, showdown if len(showdown) >= 2 else set()


def add_hand(run: MultiaccountRun, hand: ParsedHand, *, table_sizes_for_stats: set[int], name_suffix: str = "", sample: HandSample | None = None) -> None:
    run.hands_parsed += 1
    if not name_suffix:
        # Attendance uses all parsed tables, including seats outside the stat sample.
        run.observed_hands.update({seat.player for seat in hand.seats.values()})
    players = sorted(hand.active_players)
    if len(players) < 2:
        return

    # Shared table evidence is tracked across all observed PLO table sizes.
    # The count is kept because zero shared hands and high shared-hand volume
    # mean different things for manual review.
    for a, b in combinations(sorted(p + name_suffix for p in players), 2):
        run.shared_pair_counts[a, b] += 1

    # Playing-profile stats are intentionally restricted to configured table
    # sizes, by default 6-handed and 5-handed only.
    table_size = len(players)
    if table_size not in table_sizes_for_stats:
        return

    per_player_vpip: set[str] = set()
    per_player_pfr: set[str] = set()
    per_player_3bet: set[str] = set()
    per_player_3bet_opp: set[str] = set()

    # Reconstruct true 3bet opportunities from preflop action order.
    # A 3bet opportunity exists when a player acts after exactly one preflop
    # raise has occurred. If that action is a raise, it is the actual 3bet.
    # Actions after the first re-raise are 4bet/5bet territory and are not
    # counted as 3bet opportunities.
    preflop_raise_count = 0
    for action in hand.actions:
        actor = action.player
        if actor not in players:
            continue
        if action.street != "PREFLOP":
            continue
        if action.action in VOLUNTARY_PREFLOP:
            per_player_vpip.add(actor)
        if preflop_raise_count == 1 and action.action in {"fold", "call", "raise", "bet"}:
            per_player_3bet_opp.add(actor)
            if action.action in PFR_ACTIONS:
                per_player_3bet.add(actor)
        if action.action in PFR_ACTIONS:
            per_player_pfr.add(actor)
            preflop_raise_count += 1

    saw_flop, showdown_players = _live_sets(hand)
    net = hand.net_by_player()

    increments = (
        per_player_vpip, per_player_pfr, per_player_3bet, per_player_3bet_opp,
        saw_flop, showdown_players, {p for p in showdown_players if net.get(p, 0.0) > 0},
    )
    behavior = behavior_events(hand, set(players), run.sizing_histogram)
    ts = hand.timestamp.isoformat(sep=" ") if hand.timestamp else ""
    date_key = timestamp_key(hand.timestamp) if sample is not None else 0
    for p in players:
        ps = run.player_stats[p + name_suffix]
        ps.hands += 1
        if not ps.first_seen or (ts and ts < ps.first_seen):
            ps.first_seen = ts
        if ts and ts > ps.last_seen:
            ps.last_seen = ts
        flags = 0
        for (field, bit), participants in zip(CORE_FLAGS.items(), increments):
            if p in participants:
                setattr(ps, field, getattr(ps, field) + 1)
                flags |= bit
        for field_name in behavior.get(p, ()):
            ps.behavior[field_name] = ps.behavior.get(field_name, 0) + 1
            flags |= EXTRA_FLAGS[field_name]
        if sample is not None:
            sample.add(p, date_key, hand.hand_id, flags)


def build_splits(sample):
    splits = {name: MultiaccountRun() for name in ("chronological", "parity")}
    for player in sample.records:
        for split_name, halves in sample.halves(player).items():
            for half, flags in enumerate(halves):
                if not len(flags):
                    continue
                fields = {field: int(np.count_nonzero(flags & bit)) for field, bit in CORE_FLAGS.items()}
                present = int(np.bitwise_or.reduce(flags))
                behavior = {field: int(np.count_nonzero(flags & bit))
                            for field, bit in EXTRA_FLAGS.items() if present & bit}
                splits[split_name].player_stats[f"{player}@{half}"] = PlayerProfile(
                    hands=len(flags), behavior=behavior, **fields
                )
    return splits


def add_split_hand(run, hand, *, table_sizes_for_stats):
    add_hand(run, hand, table_sizes_for_stats=table_sizes_for_stats, name_suffix=f"@{hand.hand_id % 2}")


def relative_diff_pct(a: float, b: float) -> float:
    a = float(a)
    b = float(b)
    mx = max(abs(a), abs(b))
    if mx <= 0:
        return 0.0
    return 100.0 * abs(a - b) / mx


def similarity_pct(a: float, b: float) -> float:
    return max(0.0, 100.0 - relative_diff_pct(a, b))


def points_for_relative_diff(diff_pct: float, rules: list[dict[str, Any]]) -> int:
    points = 0
    for rule in rules:
        if diff_pct <= float(rule.get("relative_diff_lte", 0)):
            points = max(points, int(rule.get("points", 0)))
    return points


def sample_points(sample: int, sample_cfg: dict[str, Any]) -> int:
    # Negative penalties first, with the most severe small-sample rule winning.
    neg = 0
    for rule in sample_cfg.get("lt", []):
        if sample < int(rule.get("sample_lt", 0)):
            neg = min(neg, int(rule.get("points", 0)))
    if neg:
        return neg
    pos = 0
    for rule in sample_cfg.get("gt", []):
        if sample > int(rule.get("sample_gt", 0)):
            pos = max(pos, int(rule.get("points", 0)))
    return pos


def _component_values(ps: PlayerProfile) -> dict[str, float]:
    return {
        "vpip": ps.vpip_pct(),
        "pfr": ps.pfr_pct(),
        "threebet": ps.threebet_pct(),
        "wtsd": ps.wtsd_pct(),
        "wonsd": ps.wonsd_pct(),
    }


def score_pair(a: str, b: str, pa: PlayerProfile, pb: PlayerProfile, config: dict[str, Any], *, mutual_hands: int) -> dict[str, object]:
    point_cfg = config["points"]
    av = _component_values(pa)
    bv = _component_values(pb)
    sample = min(pa.hands, pb.hands)

    row: dict[str, object] = {
        "player_a": a,
        "player_b": b,
        "mutual_hands": mutual_hands,
        "player_a_sample_hands": pa.hands,
        "player_b_sample_hands": pb.hands,
        "min_sample_hands": sample,
        "player_a_first_seen": pa.first_seen,
        "player_a_last_seen": pa.last_seen,
        "player_b_first_seen": pb.first_seen,
        "player_b_last_seen": pb.last_seen,
    }

    total = 0
    for stat in ("vpip", "pfr", "threebet", "wtsd", "wonsd"):
        diff = relative_diff_pct(av[stat], bv[stat])
        pts = points_for_relative_diff(diff, point_cfg[stat])
        sim = similarity_pct(av[stat], bv[stat])
        row[f"player_a_{stat}"] = round(av[stat], 2)
        row[f"player_b_{stat}"] = round(bv[stat], 2)
        row[f"{stat}_match_pct"] = round(sim, 2)
        row[f"{stat}_diff_pct"] = round(diff, 2)
        row[f"{stat}_points"] = pts
        total += pts

    # Denominators used by the reconstructed non-trivial stats. These help
    # manual reviewers distinguish strong percentage matches from small-denominator noise.
    row["player_a_threebet_opp"] = pa.threebet_opportunities
    row["player_b_threebet_opp"] = pb.threebet_opportunities
    row["player_a_saw_flop"] = pa.saw_flop
    row["player_b_saw_flop"] = pb.saw_flop
    row["player_a_showdowns"] = pa.went_to_showdown
    row["player_b_showdowns"] = pb.went_to_showdown

    sp = sample_points(sample, point_cfg.get("sample", {}))
    row["sample_points"] = sp
    total += sp
    row["legacy_points"] = total
    row["risk_points"] = total
    return row


BEHAVIOR_COLUMNS = [
    "active_behavior_groups",
    *(column for key, _, _, _ in EXTRA_STATS
      for column in (f"player_a_{key}", f"player_b_{key}",
                     f"player_a_{key}_opportunities", f"player_b_{key}_opportunities", f"{key}_log10_lr")),
]
REPORT_COLUMNS = [
    # Identity / review-priority fields
    "player_a", "player_b", "mutual_rank", "rank_a_to_b", "rank_b_to_a", "score", "legacy_beta_score", *(f"{key}_log10_lr" for key, _, _ in STATS),
    "legacy_points", "risk_points", "mutual_hands",
    "player_a_sample_hands", "player_b_sample_hands", "min_sample_hands", "sample_points",

    # Match columns grouped together for fast spreadsheet review
    "vpip_match_pct", "pfr_match_pct", "threebet_match_pct", "wtsd_match_pct", "wonsd_match_pct",

    # Relative differences grouped together
    "vpip_diff_pct", "pfr_diff_pct", "threebet_diff_pct", "wtsd_diff_pct", "wonsd_diff_pct",

    # Point contribution grouped together
    "vpip_points", "pfr_points", "threebet_points", "wtsd_points", "wonsd_points",

    # Reconstructed player stats
    "player_a_vpip", "player_b_vpip",
    "player_a_pfr", "player_b_pfr",
    "player_a_threebet", "player_b_threebet",
    "player_a_wtsd", "player_b_wtsd",
    "player_a_wonsd", "player_b_wonsd",

    # Denominators for sample-sensitive stats
    "player_a_threebet_opp", "player_b_threebet_opp",
    "player_a_saw_flop", "player_b_saw_flop",
    "player_a_showdowns", "player_b_showdowns",

    # Observed date range
    "player_a_first_seen", "player_a_last_seen", "player_b_first_seen", "player_b_last_seen",
    *BEHAVIOR_COLUMNS,
]


def eligible_players(profiles, config, *, split=False):
    minimum = int(config["min_sample_to_compare"])
    return sorted(name for name, profile in profiles.items()
                  if profile.hands >= minimum and not (
                      config["exclude_generic_ipoker_players"] and
                      is_generic_player(name[:-2] if split else name)))


def find_candidates(run, config, priors=None, *, grid_prior=None, totals=None):
    if priors is None:
        priors = fit_priors(run.player_stats.values())
    names = eligible_players(run.player_stats, config)
    profiles = [run.player_stats[name] for name in names]
    groups = config["behavior_groups"]
    active_stats = stat_specs(groups)
    report_stats = stat_specs()
    if grid_prior is None:
        grid_prior = fit_grid_priors(run.player_stats.values(), report_stats)
    model = GridScores(profiles, grid_prior, active_stats, report_stats=report_stats)
    beta = LikelihoodScores(profiles, priors)
    neighbors = NeighborRanks(model, len(names), int(config["neighbor_list_size"]))
    shortlist = ReportShortlist(float(config["min_score_to_report"]), int(config["max_candidates"]))
    flagged = 0
    for i in range(len(names) - 1):
        scores = model.row(i, slice(i + 1, None))
        flagged += len(shortlist.add_row(i, scores, neighbors.upper_row(i)))
    if totals is not None:
        totals.update(eligible_players=len(names), pairs_above_threshold=flagged)
    rows = []
    for i, j, score in shortlist.ordered_pairs():
        a, b = names[i], names[j]
        row = score_pair(a, b, profiles[i], profiles[j], config,
                         mutual_hands=run.shared_pair_counts.get((a, b), 0))
        forward, reverse, mutual = neighbors.pair(i, j)
        row.update(score=round(score, 9), rank_a_to_b=forward, rank_b_to_a=reverse, mutual_rank=mutual)
        row["legacy_beta_score"] = round(float(beta.row(i, j)), 9)
        row.update({f"{key}_log10_lr": round(float(value), 9)
                    for key, value in model.components(i, j, include_report_stats=True).items()})
        row["active_behavior_groups"] = ",".join(group for group in GROUPS if groups.get(group))
        for side, profile in (("a", profiles[i]), ("b", profiles[j])):
            for key, successes, trials, _ in EXTRA_STATS:
                n = profile.stat_count(trials)
                row[f"player_{side}_{key}"] = round(pct(profile.stat_count(successes), n), 2) if n else ""
                row[f"player_{side}_{key}_opportunities"] = n
        rows.append(row)
    return rows


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in REPORT_COLUMNS})


def write_csv_any(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_top_markdown(path: Path, rows: list[dict[str, object]], *, top: int = 50, self_test=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# PLO candidate pairs")
    lines.append("")
    lines.append("Pairs are ordered by mutual rank, then by descending score.")
    lines.append("")
    if self_test:
        lines.extend(["## Split-half self-test", "", self_test, "",
                      "Chronological halves come from different periods of the same account. Parity halves share the same period.", ""])
    lines.append("| # | Player A | Player B | Mutual rank | Score (log10 LR) | Mutual hands | A hands | B hands | Min sample | VPIP match | PFR match | 3bet match | WTSD match | WonSD match |")
    lines.append("|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for i, r in enumerate(rows[:top], start=1):
        lines.append(
            f"| {i} | {r['player_a']} | {r['player_b']} | {r['mutual_rank']} | {r['score']:.3f} | {r['mutual_hands']} | "
            f"{r['player_a_sample_hands']} | {r['player_b_sample_hands']} | {r['min_sample_hands']} | "
            f"{r['vpip_match_pct']} | {r['pfr_match_pct']} | {r['threebet_match_pct']} | {r['wtsd_match_pct']} | {r['wonsd_match_pct']} |"
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def probable_owners(run):
    return [{"account": name, "label": "probable database owner", "hands": count,
             "fraction_of_parsed_hands": count / run.hands_parsed}
            for name, count in sorted(run.observed_hands.items()) if 2 * count > run.hands_parsed]


def write_summary(path: Path, *, run: MultiaccountRun, rows: list[dict[str, object]], config: dict[str, Any], input_path: str, priors, grid_prior, totals, self_test=None) -> None:
    summary = {
        "input_path": input_path,
        "hands_parsed": run.hands_parsed,
        "parse_errors": run.parse_errors,
        "unique_players_with_stats_sample": len(run.player_stats),
        "shared_pair_count": len(run.shared_pair_counts),
        "candidate_count": len(rows),
        "grid_prior": grid_prior,
        "bet_sizing_distribution": sizing_distribution(run.sizing_histogram),
        "active_stats": [key for key, _, _ in stat_specs(config["behavior_groups"])],
        "legacy_beta_priors": priors,
        "probable_database_owners": probable_owners(run),
        **totals,
        "self_test": self_test,
        "score_units": "log10 likelihood ratio",
        "config": config,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
