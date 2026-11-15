"""Read a detector report without changing its rows or ranking."""
from __future__ import annotations

import csv
from dataclasses import dataclass
import json
from math import isfinite
from pathlib import Path

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


def decimal(value):
    n = number(value)
    return "—" if n is None else f"{n:.2f}"


@dataclass
class Report:
    path: Path
    rows: list[dict[str, str]]
    summary: dict

    @classmethod
    def read(cls, path: Path) -> "Report":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not {"player_a", "player_b", "risk_points"}.issubset(reader.fieldnames or ()):
                raise ValueError("The CSV must include player_a, player_b and risk_points.")
            rows = list(reader)
        if any(not row.get("player_a") or not row.get("player_b") for row in rows):
            raise ValueError("A player name is missing from the report.")
        summary = {}
        summary_path = path.parent / "summary.json"
        if summary_path.is_file() and path.name == CSV_NAME:
            with summary_path.open(encoding="utf-8-sig") as stream:
                summary = json.load(stream)
            if not isinstance(summary, dict):
                raise ValueError("Invalid summary.json format.")
        return cls(path, rows, summary)

    def source(self, project: Path):
        name = self.summary.get("input_path")
        if not isinstance(name, str) or not name:
            return None
        for base in (self.path.parent, project):
            candidate = base / name
            if candidate.is_file():
                return candidate.resolve()
        return None
