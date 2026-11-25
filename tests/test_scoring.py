import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from plo_multiaccount_detector.likelihood import STATS, LikelihoodScores, fit_priors
from plo_multiaccount_detector.multiaccount import PlayerProfile, load_config, score_pair


def vpip_component(x, n, y, m):
    priors = {key: {"alpha": 2, "beta": 8} for key, _, _ in STATS}
    model = LikelihoodScores([PlayerProfile(hands=n, vpip=x), PlayerProfile(hands=m, vpip=y)], priors)
    return float(model.components(0, 1)["vpip"])


class ScoreTests(unittest.TestCase):
    def test_zero_trials_and_symmetry(self):
        self.assertEqual(vpip_component(0, 0, 5, 20), 0.0)
        self.assertEqual(vpip_component(1, 4, 8, 9), vpip_component(8, 9, 1, 4))
        # One success each with a Beta(2,8) prior: E[p²] / E[p]².
        self.assertAlmostEqual(vpip_component(1, 1, 1, 1), math.log10((6 / 110) / .04))

    def test_sample_size_and_rarity(self):
        self.assertGreater(vpip_component(20, 100, 20, 100), vpip_component(2, 10, 2, 10))
        self.assertGreater(vpip_component(90, 100, 90, 100), vpip_component(20, 100, 20, 100))

    def test_legacy_pair_from_v07_sample(self):
        a = PlayerProfile(hands=93, vpip=57, threebet_opportunities=43, saw_flop=54,
                          went_to_showdown=8, won_at_showdown=2)
        b = PlayerProfile(hands=65, vpip=27, threebet_opportunities=32, saw_flop=27,
                          went_to_showdown=4, won_at_showdown=1)
        row = score_pair("SeatLegend", "tiger_nova", a, b, load_config(), mutual_hands=0)
        self.assertEqual(row["legacy_points"], 180)
        self.assertEqual([row[k + "_points"] for k in ("vpip","pfr","threebet","wtsd","wonsd","sample")],
                         [0, 50, 50, 50, 50, -20])

    def test_fit_empty_and_no_information(self):
        priors = fit_priors([PlayerProfile()])
        self.assertTrue(all(p == {"alpha": 1, "beta": 1} for p in priors.values()))
