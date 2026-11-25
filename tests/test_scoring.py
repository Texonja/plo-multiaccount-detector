import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from plo_multiaccount_detector.grid_prior import GridScores, fit_grid_priors
from plo_multiaccount_detector.likelihood import STATS, LikelihoodScores, fit_priors
from plo_multiaccount_detector.multiaccount import PlayerProfile, load_config, score_pair
from plo_multiaccount_detector.report_view import Report, export_rows


def vpip_component(x, n, y, m):
    priors = {key: {"alpha": 2, "beta": 8} for key, _, _ in STATS}
    model = LikelihoodScores([PlayerProfile(hands=n, vpip=x), PlayerProfile(hands=m, vpip=y)], priors)
    return float(model.components(0, 1)["vpip"])


class ScoreTests(unittest.TestCase):
    def test_old_config_and_score_csv_convert_once(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            config = folder / "config.json"
            config.write_text('{"min_score_to_report": 3.5}', encoding="utf-8")
            self.assertEqual(load_config(config)["min_score_points_to_report"], 35)
            self.assertEqual(load_config()["min_score_points_to_report"], 28)
            old = folder / "old.csv"
            old.write_text("player_a,player_b,score,legacy_beta_score,vpip_match_pct\n"
                           "A,B,12.45,4.2,94.5\n", encoding="utf-8")
            report = Report.read(old)
            row = report.rows[0]
            self.assertEqual((row["score"], row["score_log10_lr"], row["legacy_beta_score"]),
                             ("124.5", "12.45", "42.0"))
            self.assertEqual(row["vpip_match_pct"], "94.5")
            target = folder / "export.csv"
            export_rows(report, [0], target)
            self.assertEqual(Report.read(target).rows, report.rows)
            old.write_text("player_a,player_b,risk_points\nA,B,80\n", encoding="utf-8")
            self.assertEqual(Report.read(old).rows[0]["risk_points"], "80")

    def test_zero_trials_and_symmetry(self):
        self.assertEqual(vpip_component(0, 0, 5, 20), 0.0)
        self.assertEqual(vpip_component(1, 4, 8, 9), vpip_component(8, 9, 1, 4))
        # One success each with a Beta(2,8) prior: E[p²] / E[p]².
        self.assertAlmostEqual(vpip_component(1, 1, 1, 1), math.log10((6 / 110) / .04))

    def test_sample_size_and_rarity(self):
        self.assertGreater(vpip_component(20, 100, 20, 100), vpip_component(2, 10, 2, 10))
        self.assertGreater(vpip_component(90, 100, 90, 100), vpip_component(20, 100, 20, 100))

    def test_grid_lr_for_outliers_and_missing_opportunities(self):
        population = [PlayerProfile(hands=100, vpip=20 + i % 15) for i in range(120)]
        population += [PlayerProfile(hands=100, vpip=88 + i % 4) for i in range(10)]
        accounts = [PlayerProfile(hands=100, vpip=89), PlayerProfile(hands=100, vpip=90), PlayerProfile()]
        prior = fit_grid_priors(population)
        grid = GridScores(accounts, prior)
        beta = LikelihoodScores(accounts, fit_priors(population))
        self.assertEqual(len(prior["theta"]), 400)
        self.assertAlmostEqual(sum(prior["weights"]["vpip"]), 1)
        self.assertEqual(float(grid.row(0, 2)), 0)
        self.assertLess(grid.components(0, 1)["vpip"], beta.components(0, 1)["vpip"])
        self.assertAlmostEqual(float(grid.row(0, 1)), float(grid.row(1, 0)))

    def test_grid_lr_matches_direct_joint_probability(self):
        import numpy as np
        prior = fit_grid_priors([])
        accounts = [PlayerProfile(hands=2, vpip=1), PlayerProfile(hands=1, vpip=1)]
        theta = np.asarray(prior["theta"])
        weights = np.asarray(prior["weights"]["vpip"])
        first, second = theta * (1 - theta), theta
        joint = sum(weights * first * second)
        expected = math.log10(joint / (sum(weights * first) * sum(weights * second)))
        model = GridScores(accounts, prior)
        self.assertAlmostEqual(model.components(0, 1)["vpip"], expected)
        self.assertAlmostEqual(model.row(0, 1), 10 * sum(model.components(0, 1).values()))

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
