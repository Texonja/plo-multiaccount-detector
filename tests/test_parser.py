import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from plo_multiaccount_detector.hh_parser import parse_ipoker_xml_hand_history_fast
from plo_multiaccount_detector.multiaccount import MultiaccountRun, add_hand, probable_owners
from plo_multiaccount_detector.pgcopy import pg_copy_unescape


def xml_hand(rounds, number=20):
    seats = ''.join(f'<player seat="{i}" name="{p}" chips="100"/>' for i, p in enumerate("ABCDE", 1))
    body = ''.join(f'<round no="{i}">{data}</round>' for i, data in enumerate(rounds))
    return parse_ipoker_xml_hand_history_fast(f'<game gamecode="{number}">{seats}{body}</game>')


def action(player, kind, amount):
    return f'<action player="{player}" type="{kind}" sum="{amount}"/>'


class ParserTests(unittest.TestCase):
    def test_all_in_call_preserves_later_threebet_opportunity(self):
        blinds = action("A", 1, .5) + action("B", 2, 1)
        pre = action("C", 23, 3) + action("A", 7, 2.5) + action("B", 23, 8)
        hand = xml_hand([blinds, pre])
        self.assertEqual([(a.action, a.amount, a.to_amount) for a in hand.actions[2:]],
                         [("raise", 3, 3), ("call", 2.5, 3), ("raise", 7, 8)])
        run = MultiaccountRun()
        add_hand(run, hand, table_sizes_for_stats={5})
        self.assertEqual(run.player_stats["A"].pfr, 0)
        self.assertEqual(run.player_stats["B"].threebet_opportunities, 1)
        self.assertEqual(run.player_stats["B"].threebet, 1)

    def test_raise_to_carries_blinds_and_never_removes_chips(self):
        hand = xml_hand([action("A", 2, 1),
                         action("A", 23, 4) + action("A", 23, 3) + action("B", 7, 4)])
        self.assertEqual([(a.action, a.amount, a.to_amount) for a in hand.actions[1:]],
                         [("raise", 3, 4), ("raise", 0, 4), ("call", 4, 4)])

    def test_all_in_bet_raise_and_short_call(self):
        flop = action("A", 7, 3) + action("B", 7, 8) + action("C", 7, 2)
        hand = xml_hand(["", "", flop])
        self.assertEqual([a.action for a in hand.actions], ["bet", "raise", "call"])

    def test_board_runout_without_flop_action(self):
        pre = ''.join(action(p, 0, 0) for p in "CDE") + action("A", 7, 10) + action("B", 7, 10)
        hand = xml_hand(["", pre, '<cards type="Flop">S2 D3 H4</cards>'])
        run = MultiaccountRun()
        add_hand(run, hand, table_sizes_for_stats={5})
        for p in "ABCDE":
            self.assertEqual(run.player_stats[p].saw_flop, int(p in "AB"))
            self.assertEqual(run.player_stats[p].went_to_showdown, int(p in "AB"))

    def test_owner_uses_all_parsed_hands_and_strict_majority(self):
        run = MultiaccountRun()
        first = xml_hand([])
        second = xml_hand([], 21)
        second.seats = {k: v for k, v in second.seats.items() if v.player == "A"}
        for hand in (first, second):
            add_hand(run, hand, table_sizes_for_stats={6})
        self.assertEqual(probable_owners(run), [{"account": "A", "label": "probable database owner",
                                                 "hands": 2, "fraction_of_parsed_hands": 1.0}])
        self.assertFalse(run.player_stats)

    def test_copy_escaping(self):
        cases = [(None, None), (r"\N", None), ("", ""), (r"\\N", r"\N"),
                 (r"\t\r\n\b\v\f", "\t\r\n\b\v\f"), (r"\1017", "A7"),
                 (r"\7", "\x07"), (r"\q", "q"), ("end\\", "end\\")]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(pg_copy_unescape(raw), expected)
