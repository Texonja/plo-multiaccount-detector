from collections import Counter, defaultdict
import unittest

from test_parser import action, xml_hand
from plo_multiaccount_detector.behavior_stats import pot_before_actions, sizing_events
from plo_multiaccount_detector.hand_sample import HandSample
from plo_multiaccount_detector.multiaccount import MultiaccountRun, add_hand, build_splits


BLINDS = action("A", 1, .5) + action("B", 2, 1)


def bet_sizes(hand):
    events, histogram = defaultdict(set), defaultdict(Counter)
    sizing_events(hand, hand.active_players, events, histogram)
    return events, histogram


class SizingTests(unittest.TestCase):
    def test_reconstruct_pot_and_classify_first_bets_on_three_streets(self):
        pre = action("C", 23, 3.5) + action("B", 3, 2.5)
        flop = action("C", 5, 3) + action("B", 3, 3)
        turn = action("B", 5, 10.125) + action("C", 3, 10.125)
        river = action("C", 5, 30) + action("B", 23, 70)
        hand = xml_hand([BLINDS, pre, flop, turn, river])
        pots = [(a.street, pot, amount) for a, pot, _, amount in pot_before_actions(hand) if a.action == "bet"]
        self.assertEqual(pots, [("FLOP", 7.5, 3), ("TURN", 13.5, 10.125), ("RIVER", 33.75, 30)])
        events, histogram = bet_sizes(hand)
        self.assertEqual(events["C"], {"opens", "pot_open", "flop_first_bets", "flop_small_bet",
                                       "river_first_bets", "river_non_small_bets", "river_large_bet"})
        self.assertEqual(events["B"], {"turn_first_bets", "turn_non_small_bets"})
        self.assertEqual(histogram["FLOP"][3], 1)
        self.assertEqual(histogram["TURN"][7], 1)
        self.assertEqual(histogram["RIVER"][9], 1)

    def test_all_in_first_actions_skip_sizing_but_still_fund_the_pot(self):
        pre = action("C", 7, 3.5) + action("B", 23, 8) + action("A", 3, 7.5)
        flop = action("B", 7, 5) + action("A", 23, 10)
        hand = xml_hand([BLINDS, pre, flop])
        events, histogram = bet_sizes(hand)
        self.assertFalse(events)
        self.assertFalse(histogram)
        self.assertEqual(next(pot for a, pot, _, _ in pot_before_actions(hand) if a.street == "FLOP"), 19.5)

    def test_open_size_uses_increment_after_blind_and_ninety_five_percent(self):
        for total, expected in ((2.875, True), (2.874, False)):
            with self.subTest(total=total):
                events, _ = bet_sizes(xml_hand([BLINDS, action("A", 23, total)]))
                self.assertEqual(events["A"], {"opens", "pot_open"} if expected else {"opens"})

    def test_sizing_opportunities_survive_both_splits(self):
        run, sample = MultiaccountRun(), HandSample()
        for hand_id, size in ((20, 3.5), (21, 2.5)):
            hand = xml_hand([BLINDS, action("C", 23, size)], hand_id)
            from datetime import datetime
            hand.timestamp = datetime(2025, 3, hand_id)
            add_hand(run, hand, table_sizes_for_stats={5}, sample=sample)
        for split in build_splits(sample).values():
            self.assertEqual(split.player_stats["C@0"].behavior, {"opens": 1, "pot_open": 1})
            self.assertEqual(split.player_stats["C@1"].behavior, {"opens": 1})
