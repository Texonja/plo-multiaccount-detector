from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from plo_multiaccount_detector.cli import main
from plo_multiaccount_detector.hand_histories import ArchiveCounts, iter_archive_hands
from plo_multiaccount_detector.hh_parser import parse_hand_history
from plo_multiaccount_detector.report_view import CSV_NAME, Report


def session(ids, game_type="Omaha PL"):
    header = (f"<general><gametype>{game_type}</gametype><tablename>Table One</tablename>"
              "<smallblind>0.5</smallblind><bigblind>1</bigblind></general>")
    games = []
    for game_id in ids:
        players = "".join(f'<player name="Seat{seat}-{game_id}" seat="{seat}" chips="80"/>'
                          for seat in range(1, 6))
        games.append(f'<game sample="true" gamecode="{game_id}"><general>'
                     f'<startdate>2025-01-01 12:30:00</startdate><players>{players}</players>'
                     f'</general><round no="0"><action player="Seat1-{game_id}" type="1" sum="0.5"/>'
                     f'</round></game>')
    return "<session>" + header + "".join(games) + "</session>"


class ArchiveTests(unittest.TestCase):
    def test_import_uses_one_game_at_a_time_and_recurses(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "01"
            day = folder / "02"
            day.mkdir(parents=True)
            (folder / "session.xml").write_text(session([10, 11]), encoding="utf-16")
            (day / "more.XML").write_text(session([11, 12]), encoding="utf-8")
            (day / "nl.xml").write_text(session([13], "Holdem NL"), encoding="utf-8")
            (day / "broken.xml").write_text("<session>", encoding="utf-8")
            (day / "notes.txt").write_text("notes", encoding="utf-8")
            counts = ArchiveCounts()
            errors = []
            rows = iter_archive_hands(folder, max_hands=None, raw_handhistory_contains="Omaha PL",
                                      counts=counts, on_error=lambda path, err: errors.append(path))
            hands = [parse_hand_history(row.handhistory) for row in rows]
            self.assertEqual([h.hand_id for h in hands], [10, 11, 11, 12])
            self.assertEqual((counts.xml_files, counts.read_errors), (4, 1))
            self.assertEqual(errors, [str(Path("02/broken.xml"))])
            for h in hands:
                self.assertEqual((h.table_name, h.small_blind, h.big_blind), ("Table One", .5, 1))
                self.assertEqual((len(h.seats), len(h.actions), h.timestamp.year), (5, 1, 2025))
                self.assertEqual(h.actions[0].player, f"Seat1-{h.hand_id}")

            out = Path(temp) / "report"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--input", str(folder), "--out", str(out), "--no-validate"]), 0)
            report = Report.read(out / CSV_NAME)
            self.assertEqual(report.source(Path(temp)), folder.resolve())
            self.assertEqual(report.summary["hands_parsed"], 3)
            self.assertEqual(report.summary["hand_history_import"],
                             {"xml_files": 4, "read_errors": 1, "duplicates": 1})
            self.assertIn("broken.xml", (out / "parse_errors.csv").read_text(encoding="utf-8-sig"))

    def test_empty_or_non_plo_folder_reports_no_matching_hands(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            out = source / "out"
            for xml_count in (0, 1):
                if xml_count:
                    (source / "holdem.xml").write_text(session([1], "Holdem NL"), encoding="utf-8")
                errors = io.StringIO()
                with redirect_stderr(errors):
                    self.assertNotEqual(main(["--input", str(source), "--out", str(out)]), 0)
                self.assertIn(f"XML files checked: {xml_count}", errors.getvalue())
                self.assertFalse(out.exists())
