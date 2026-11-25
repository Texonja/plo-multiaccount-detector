from datetime import datetime
import itertools
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from plo_multiaccount_detector.hand_sample import HandSample
from plo_multiaccount_detector.grid_prior import fit_grid_priors
from plo_multiaccount_detector.likelihood import fit_priors
from plo_multiaccount_detector.multiaccount import MultiaccountRun, PlayerProfile, add_hand, add_split_hand, build_splits, load_config, score_pair
from plo_multiaccount_detector.neighbors import NeighborRanks
from plo_multiaccount_detector.validation import LegacyScores, evaluate, validate
from test_parser import action, xml_hand


class ValidationTests(unittest.TestCase):
    def test_split_preserves_participants_but_twins_never_share_hands(self):
        split = MultiaccountRun()
        for hand_id in (15, 16, 17):
            add_split_hand(split, xml_hand([], hand_id), table_sizes_for_stats={5})
        self.assertEqual(split.player_stats["A@0"].hands, 1)
        self.assertEqual(split.player_stats["A@1"].hands, 2)
        self.assertEqual(split.shared_pair_counts["A@1", "B@1"], 2)
        self.assertTrue(all(a[-1] == b[-1] for a, b in split.shared_pair_counts))

    def test_chronological_sort_uses_timestamp_then_id_and_parity_keeps_undated(self):
        sample = HandSample()
        full = MultiaccountRun()
        for hand_id, day, call in ((6, 1, False), (9, 2, True), (8, 2, False),
                                   (2, 3, True), (3, None, True)):
            hand = xml_hand(["", action("A", 3 if call else 0, int(call))], hand_id)
            hand.timestamp = datetime(2025, 3, day) if day else None
            add_hand(full, hand, table_sizes_for_stats={5}, sample=sample)
        splits = build_splits(sample)
        early, late = (splits["chronological"].player_stats[f"A@{i}"] for i in (0, 1))
        even, odd = (splits["parity"].player_stats[f"A@{i}"] for i in (0, 1))
        self.assertEqual((early.hands, early.vpip, late.hands, late.vpip), (2, 0, 2, 2))
        self.assertEqual((even.hands, even.vpip, odd.hands, odd.vpip), (3, 1, 2, 2))
        self.assertEqual(sample.undated, 5)

    def test_tied_ranks_orphan_and_threshold(self):
        run = MultiaccountRun()
        for name in ("A@0", "A@1", "B@0", "B@1", "orphan@0", "Player 3@0"):
            run.player_stats[name] = PlayerProfile(hands=150, vpip=30, pfr=10)
        config = load_config()
        config["min_score_to_report"] = -100
        full = [PlayerProfile(hands=12, vpip=4, pfr=1), PlayerProfile(hands=10, vpip=7, pfr=2)]
        result = validate(run, fit_priors(full), config, fit_grid_priors(full))
        self.assertEqual((result["eligible_accounts"], result["known_pairs"], result["compared_pairs"]), (5, 2, 10))
        for method in ("lr", "legacy"):
            stats = result[method]
            self.assertEqual([(r["optimistic"], r["pessimistic"]) for r in stats["twin_ranks"]], [(1, 4)] * 4)
            self.assertEqual(stats["by_smaller_half"]["150-500"]["accounts"], 4)
            self.assertEqual(stats["threshold"]["precision"], .2)
            self.assertEqual(stats["threshold"]["recall"], 1)
            self.assertIsNone(stats["precision_at_k"]["100"])

    def test_mutual_rank_is_symmetric_and_missing_is_k_plus_one(self):
        import numpy as np

        class Model:
            def row(self, i, others):
                rows = [[0, 5, 5, 1], [5, 0, 9, 6], [5, 9, 0, 2], [1, 6, 2, 0]]
                return np.array(rows[i])[others]

        ranks = NeighborRanks(Model(), 4, 2)
        self.assertEqual(ranks.pair(0, 1), (1, 3, 3))
        self.assertEqual(ranks.pair(1, 0), (3, 1, 3))
        self.assertEqual(ranks.pair(1, 2), (1, 1, 1))
        for i, j in itertools.combinations(range(4), 2):
            self.assertEqual(ranks.pair(i, j)[2], ranks.pair(j, i)[2])
            self.assertEqual(ranks.upper_row(i)[j - i - 1], ranks.pair(i, j)[2])

    def test_report_precision_filters_then_orders_and_caps(self):
        import numpy as np

        class Model:
            def row(self, i, others):
                scores = [
                    [0, 1.9, 0, 0, 0, 0],
                    [1.9, 0, 0, 0, 0, 0],
                    [0, 0, 0, 2, 3, 0],
                    [0, 0, 2, 0, 2.5, 0],
                    [0, 0, 3, 2.5, 0, 2.1],
                    [0, 0, 0, 0, 2.1, 0],
                ]
                return np.array(scores[i])[others]

        names = ["A@0", "A@1", "B@0", "B@1", "C@0", "D@0"]
        profiles = [PlayerProfile(hands=150) for _ in names]
        with patch("plo_multiaccount_detector.validation.LIMITS", (2, 3, 4)):
            result = evaluate(Model(), names, profiles, [1, 0, 3, 2, None, None], 2.0, 50, 3)
        self.assertEqual(result["threshold"]["flagged_pairs"], 4)
        self.assertEqual(result["threshold"]["true_pairs_flagged"], 1)
        self.assertEqual(result["report_pairs"], 3)
        self.assertEqual(result["precision_at_k_mutual_rank"], {"2": 0, "3": 1 / 3, "4": None})
        self.assertEqual(result["precision_at_k_mutual_rank_unfiltered"]["2"], .5)
        self.assertEqual(result["precision_at_k"]["3"], 0)
        self.assertEqual(result["mutual_rank_one"], {"known_twins": 1, "known_twins_passing_filter": 0})

    def test_vector_legacy_matches_csv_calculation(self):
        config = load_config()
        profiles = [PlayerProfile(hands=n, vpip=n//3, pfr=n//5, threebet=n//43, threebet_opportunities=n//4,
                                  saw_flop=n//2, went_to_showdown=n//6, won_at_showdown=n//10)
                    for n in (65, 99, 100, 250, 1001, 4001)]
        model = LegacyScores(profiles, config)
        for i, j in itertools.combinations(range(len(profiles)), 2):
            expected = score_pair("A", "B", profiles[i], profiles[j], config, mutual_hands=200)
            self.assertEqual(model.row(i, slice(None))[j], expected["legacy_points"])
