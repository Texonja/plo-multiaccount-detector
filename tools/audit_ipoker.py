"""Reconcile parsed iPoker action amounts against player bet attributes in an HM2 backup."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from plo_multiaccount_detector.hh_parser import parse_ipoker_xml_hand_history_fast, parse_money
from plo_multiaccount_detector.hm2_backup import iter_hm2_handhistories


def audit(path):
    counts = Counter()
    seen = set()
    for row in iter_hm2_handhistories(path, raw_handhistory_contains="Omaha PL"):
        if row.pokersite_id != 4 or row.gamenumber in seen:
            continue
        seen.add(row.gamenumber)
        h = parse_ipoker_xml_hand_history_fast(row.handhistory)
        totals = [Counter() for _ in range(3)]
        streets = [defaultdict(Counter) for _ in totals]
        parsed = Counter()
        calls = 0
        for action in h.actions:
            typ = re.search(r'type="(\d+)"', action.raw)[1]
            if typ not in {"1", "2", "3", "5", "7", "23"}:
                continue
            cents = round(parse_money(re.search(r'sum="([^"]*)"', action.raw)[1]) * 100)
            name = action.player
            parsed[name] += round(action.amount * 100)
            calls += int(typ == "7" and action.street == "PREFLOP" and action.action == "call")
            for method in range(3):
                # 0: both incremental. 1: type 23 is a street total.
                # 2: same as 1, with any excess big blind posted as dead money.
                bets = streets[method][action.street]
                if method == 0 and typ == "7" and action.street == "PREFLOP":
                    call = bets[name] + cents <= max(bets.values(), default=0)
                    counts["preflop_all_in_labels_changed_by_raise_to"] += call != (action.action == "call")
                delta = max(0, cents - bets[name]) if method and typ == "23" else cents
                totals[method][name] += delta
                bets[name] += min(delta, round(100 * h.big_blind)) if method == 2 and typ == "2" else delta
        counts["hands"] += 1
        counts["preflop_all_in_calls"] += calls
        counts["hands_with_preflop_all_in_calls"] += bool(calls)
        if len(h.board) >= 3 and not any(a.street == "FLOP" for a in h.actions):
            counts["flops_without_actions"] += 1
            counts["flops_without_actions_5_6_handed"] += len(h.active_players) in (5, 6)
        for name in h.active_players:
            counts["player_hands"] += 1
            declared = round(100 * h.contributions.get(name, 0))
            counts["parsed_amount_matches"] += parsed[name] == declared
            for key, values in zip(("both_incremental", "raise_to", "raise_to_with_dead_blind"), totals):
                counts[key + "_matches"] += values[name] == declared
            excess = totals[0][name] - declared
            if excess > 0:
                unmatched = sum(max(0, bets[name] - max((v for p, v in bets.items() if p != name), default=0))
                                for bets in streets[0].values())
                counts["incremental_residual_equals_unmatched_wager"] += unmatched == excess
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path)
    print(json.dumps(audit(parser.parse_args().backup), indent=2))
