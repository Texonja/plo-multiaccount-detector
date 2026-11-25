from collections import Counter, defaultdict
from datetime import datetime
import unittest

from test_parser import action, xml_hand
from plo_multiaccount_detector.behavior_stats import behavior_events, pot_before_actions, sizing_events
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
            hand.timestamp = datetime(2025, 3, hand_id)
            add_hand(run, hand, table_sizes_for_stats={5}, sample=sample)
        for split in build_splits(sample).values():
            self.assertEqual(split.player_stats["C@0"].behavior, {"opens": 1, "pot_open": 1})
            self.assertEqual(split.player_stats["C@1"].behavior, {"opens": 1})


class FrequencyTests(unittest.TestCase):
    def events(self, pre, flop="", *, button=4, blinds=BLINDS):
        hand = xml_hand([blinds, pre, flop])
        hand.button_seat = button
        return behavior_events(hand, hand.active_players, defaultdict(Counter))

    def test_rfi_uses_active_seat_order_and_excludes_limped_pots(self):
        blinds = action("E", 1, .5) + action("A", 2, 1)
        folded = ""
        for player, position in (("B", "ep"), ("C", "co"), ("D", "btn"), ("E", "sb")):
            with self.subTest(position=position):
                success = self.events(folded + action(player, 23, 3), blinds=blinds)
                self.assertIn(f"rfi_{position}", success[player])
                self.assertIn(f"rfi_{position}_opps", success[player])
                miss = self.events(folded + action(player, 0, 0), blinds=blinds)
                self.assertIn(f"rfi_{position}_opps", miss[player])
                self.assertNotIn(f"rfi_{position}", miss[player])
            folded += action(player, 0, 0)
        limped = self.events(action("B", 3, 1) + action("C", 23, 4), blinds=blinds)
        self.assertNotIn("rfi_co_opps", limped["C"])
        self.assertNotIn("rfi_ep", limped["B"])

    def test_flop_cbet_requires_the_last_raiser_to_act_with_no_bet(self):
        pre = action("C", 23, 3) + action("B", 23, 9) + action("C", 3, 6)
        checked_to = action("C", 4, 0)
        for kind, size, success in ((5, 6, True), (4, 0, False)):
            events = self.events(pre, checked_to + action("B", kind, size))
            self.assertIn("flop_cbet_opps", events["B"])
            self.assertEqual("flop_cbet" in events["B"], success)
        donk = self.events(pre, action("C", 5, 6) + action("B", 3, 6))
        self.assertNotIn("flop_cbet_opps", donk["B"])

    def test_fold_to_flop_cbet_excludes_actions_after_raise(self):
        pre = action("C", 23, 3) + action("D", 3, 3) + action("B", 3, 2)
        bet = action("B", 4, 0) + action("C", 5, 4)
        events = self.events(pre, bet + action("D", 0, 0) + action("B", 3, 4))
        self.assertTrue({"fold_to_flop_cbet", "fold_to_flop_cbet_opps"} <= events["D"])
        self.assertIn("fold_to_flop_cbet_opps", events["B"])
        self.assertNotIn("fold_to_flop_cbet", events["B"])
        after_raise = self.events(pre, bet + action("D", 23, 12) + action("B", 0, 0))
        self.assertNotIn("fold_to_flop_cbet_opps", after_raise["B"])

    def test_fold_to_3bet_only_when_the_opener_faces_a_three_bet(self):
        pre = action("C", 23, 3) + action("D", 23, 9)
        for kind, size, success in ((0, 0, True), (3, 6, False)):
            events = self.events(pre + action("C", kind, size))
            self.assertIn("fold_to_3bet_opps", events["C"])
            self.assertEqual("fold_to_3bet" in events["C"], success)
        after_fourbet = self.events(pre + action("E", 23, 27) + action("C", 0, 0))
        self.assertNotIn("fold_to_3bet_opps", after_fourbet["C"])

    def test_flop_check_raise_requires_check_then_a_bet(self):
        pre = action("C", 23, 3) + action("B", 3, 2)
        checked_then_bet = action("B", 4, 0) + action("C", 5, 3)
        for kind, size, success in ((23, 9, True), (3, 3, False)):
            events = self.events(pre, checked_then_bet + action("B", kind, size))
            self.assertIn("flop_check_raise_opps", events["B"])
            self.assertEqual("flop_check_raise" in events["B"], success)
        raise_without_check = self.events(pre, action("C", 5, 3) + action("B", 23, 9))
        self.assertNotIn("flop_check_raise_opps", raise_without_check["B"])
