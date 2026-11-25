import itertools
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from plo_multiaccount_detector.likelihood import fit_priors
from plo_multiaccount_detector.multiaccount import MultiaccountRun, PlayerProfile, add_split_hand, load_config, score_pair
from plo_multiaccount_detector.validation import LegacyScores, validate
from test_parser import xml_hand


class ValidationTests(unittest.TestCase):
    def test_split_preserves_participants_but_twins_never_share_hands(self):
        split = MultiaccountRun()
        for hand_id in (15, 16, 17):
            add_split_hand(split, xml_hand([], hand_id), table_sizes_for_stats={5})
        self.assertEqual(split.player_stats["A@0"].hands, 1)
        self.assertEqual(split.player_stats["A@1"].hands, 2)
        self.assertEqual(split.shared_pair_counts["A@1", "B@1"], 2)
        self.assertTrue(all(a[-1] == b[-1] for a, b in split.shared_pair_counts))

    def test_tied_ranks_orphan_and_threshold(self):
        run = MultiaccountRun()
        for name in ("A@0", "A@1", "B@0", "B@1", "orphan@0", "Player 3@0"):
            run.player_stats[name] = PlayerProfile(hands=150, vpip=30, pfr=10)
        config = load_config()
        config["min_score_to_report"] = -100
        result = validate(run, fit_priors([PlayerProfile(hands=12, vpip=4, pfr=1),
                                           PlayerProfile(hands=10, vpip=7, pfr=2)]), config)
        self.assertEqual((result["eligible_accounts"], result["known_pairs"], result["compared_pairs"]), (5, 2, 10))
        for method in ("lr", "legacy"):
            stats = result[method]
            self.assertEqual([(r["optimistic"], r["pessimistic"]) for r in stats["twin_ranks"]], [(1, 4)] * 4)
            self.assertEqual(stats["by_smaller_half"]["150-500"]["accounts"], 4)
            self.assertEqual(stats["threshold"]["precision"], .2)
            self.assertEqual(stats["threshold"]["recall"], 1)
            self.assertIsNone(stats["precision_at_k"]["100"])

    def test_vector_legacy_matches_csv_calculation(self):
        config = load_config()
        profiles = [PlayerProfile(hands=n, vpip=n//3, pfr=n//5, threebet=n//43, threebet_opportunities=n//4,
                                  saw_flop=n//2, went_to_showdown=n//6, won_at_showdown=n//10)
                    for n in (65, 99, 100, 250, 1001, 4001)]
        model = LegacyScores(profiles, config)
        for i, j in itertools.combinations(range(len(profiles)), 2):
            expected = score_pair("A", "B", profiles[i], profiles[j], config, mutual_hands=200)
            self.assertEqual(model.row(i, slice(None))[j], expected["legacy_points"])
