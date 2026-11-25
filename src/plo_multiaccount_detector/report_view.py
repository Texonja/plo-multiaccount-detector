"""Read and export detector reports in current score units."""
from __future__ import annotations

import csv
from dataclasses import dataclass
import json
from math import isfinite
from pathlib import Path
import tempfile
from .score_units import POINTS_PER_LOG10_LR

CSV_NAME = "multiaccount_candidates.csv"
STATS = (("vpip", "VPIP"), ("pfr", "PFR"), ("threebet", "3Bet"),
         ("wtsd", "WTSD"), ("wonsd", "W$SD"))


def number(value):
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (TypeError, ValueError):
        return None


def integer(value):
    n = number(value)
    return "—" if n is None else f"{n:,.0f}"


def decimal(value, places=2):
    n = number(value)
    return "—" if n is None else f"{n:.{places}f}"


@dataclass
class Report:
    path: Path
    rows: list[dict[str, str]]
    summary: dict
    fields: list[str]

    @classmethod
    def read(cls, path: Path) -> "Report":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            fields = list(reader.fieldnames or ())
            if not {"player_a", "player_b"}.issubset(fields) or not {"score", "risk_points"}.intersection(fields):
                raise ValueError("The CSV must include player_a, player_b and either score or risk_points.")
            rows = list(reader)
        if any(not row.get("player_a") or not row.get("player_b") for row in rows):
            raise ValueError("A player name is missing from the report.")
        # The raw-score column travels with exports, even without summary.json.
        if "score" in fields and "score_log10_lr" not in fields:
            fields.insert(fields.index("score") + 1, "score_log10_lr")
            for row in rows:
                row["score_log10_lr"] = row["score"]
                for key in ("score", "legacy_beta_score"):
                    value = number(row.get(key))
                    if value is not None:
                        row[key] = str(round(value * POINTS_PER_LOG10_LR, 9))
        summary = {}
        summary_path = path.parent / "summary.json"
        if summary_path.is_file() and path.name == CSV_NAME:
            with summary_path.open(encoding="utf-8-sig") as stream:
                summary = json.load(stream)
            if not isinstance(summary, dict):
                raise ValueError("Invalid summary.json format.")
        return cls(path, rows, summary, fields)

    def source(self, project: Path):
        name = self.summary.get("input_path")
        if not isinstance(name, str) or not name:
            return None
        for base in (self.path.parent, project):
            candidate = base / name
            if candidate.is_file() or candidate.is_dir():
                return candidate.resolve()
        return None


def export_rows(report, order, target):
    if target.resolve() == report.path.resolve():
        raise ValueError("Choose a different filename for the export.")
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=target.parent, delete=False,
                                         encoding="utf-8-sig", newline="") as stream:
            temp = Path(stream.name)
            writer = csv.DictWriter(stream, fieldnames=report.fields)
            writer.writeheader()
            writer.writerows(report.rows[i] for i in order)
        temp.replace(target)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
