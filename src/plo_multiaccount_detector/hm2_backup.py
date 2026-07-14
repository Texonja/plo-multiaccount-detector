"""HM2 backup / dump reader.

The safest first adapter for this project is the raw `handhistories` table. It
contains the original iPoker hand-history text, which is more stable for our
purpose than HM2 report CSVs.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import io
import zipfile
from typing import Iterator, TextIO

from .pgcopy import pg_copy_unescape


@dataclass(frozen=True)
class HM2HandRow:
    handhistory_id: int
    gamenumber: int
    pokersite_id: int
    handhistory: str
    filename: str | None
    handtimestamp: str | None
    gametype_id: int | None
    tourneynumber: str | None


class HM2BackupError(RuntimeError):
    pass


def _open_dump_from_zip(path: Path) -> TextIO:
    zf = zipfile.ZipFile(path)
    names = zf.namelist()
    sql_name = "db/HoldemManager2.sql"
    if sql_name not in names:
        candidates = [name for name in names if name.lower().endswith(".sql")]
        if not candidates:
            raise HM2BackupError("No SQL dump found inside backup archive")
        sql_name = candidates[0]
    raw = zf.open(sql_name, "r")
    raw._hm2_zip_owner = zf  # type: ignore[attr-defined]
    return io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")


def open_hm2_dump(path: str | Path) -> TextIO:
    """Open a `.pghembk` zip backup or plain `.sql` dump as text."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    if zipfile.is_zipfile(p):
        return _open_dump_from_zip(p)
    return p.open("r", encoding="utf-8", errors="replace", newline="")


def _split_raw_copy_row(line: str, expected_fields: int) -> list[str]:
    line = line.rstrip("\n")
    if line.endswith("\r"):
        line = line[:-1]
    parts = line.split("\t")
    if len(parts) != expected_fields:
        raise ValueError(f"Expected {expected_fields} COPY fields, got {len(parts)}")
    return parts


def _nullable(value: str | None) -> str | None:
    if value in (None, r"\N", ""):
        return None
    return value


def iter_hm2_handhistories(
    path: str | Path,
    *,
    max_hands: int | None = None,
    raw_handhistory_contains: str | None = None,
) -> Iterator[HM2HandRow]:
    """Yield rows from the HM2 `handhistories` COPY block.

    This does not restore PostgreSQL. It streams the dump and decodes only the
    table needed by v1.

    `raw_handhistory_contains` is checked before PostgreSQL unescaping. It makes
    large backups much faster when the run is intentionally limited to PLO.
    """
    copy_prefix = "COPY handhistories ("
    in_copy = False
    emitted = 0

    with open_hm2_dump(path) as dump:
        for line_no, line in enumerate(dump, start=1):
            if not in_copy:
                if line.startswith(copy_prefix):
                    in_copy = True
                continue

            if line.rstrip("\r\n") == r"\.":
                break

            try:
                raw_fields = _split_raw_copy_row(line, expected_fields=8)
            except Exception as exc:
                raise HM2BackupError(f"Failed to split COPY row at SQL line {line_no}: {exc}") from exc

            raw_hh = raw_fields[3]
            if raw_handhistory_contains and raw_handhistory_contains not in raw_hh:
                continue

            try:
                handhistory = pg_copy_unescape(raw_hh)
                filename = pg_copy_unescape(raw_fields[4])
                tourneynumber = pg_copy_unescape(raw_fields[7])
            except Exception as exc:
                raise HM2BackupError(f"Failed to unescape COPY row at SQL line {line_no}: {exc}") from exc

            if handhistory is None:
                continue

            yield HM2HandRow(
                handhistory_id=int(raw_fields[0] or 0),
                gamenumber=int(raw_fields[1] or 0),
                pokersite_id=int(raw_fields[2] or 0),
                handhistory=handhistory,
                filename=_nullable(filename),
                handtimestamp=_nullable(raw_fields[5]),
                gametype_id=int(raw_fields[6]) if raw_fields[6] not in (None, r"\N", "") else None,
                tourneynumber=_nullable(tourneynumber),
            )
            emitted += 1
            if max_hands is not None and emitted >= max_hands:
                break

    if not in_copy:
        raise HM2BackupError("Could not find COPY block for HM2 handhistories table")
