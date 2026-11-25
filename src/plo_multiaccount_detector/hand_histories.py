"""Read iPoker session XML files from an HM2 hand-history archive."""
from dataclasses import dataclass
import os
from pathlib import Path
import xml.etree.ElementTree as ET

from .hm2_backup import HM2HandRow


@dataclass
class ArchiveCounts:
    xml_files: int = 0
    read_errors: int = 0
    duplicates: int = 0


def iter_archive_hands(folder: Path, *, max_hands, raw_handhistory_contains, counts, on_error):
    emitted = 0

    def record_error(path, error):
        counts.read_errors += 1
        on_error(str(Path(path).relative_to(folder)), str(error))

    for directory, subfolders, filenames in os.walk(
        folder, onerror=lambda exc: record_error(exc.filename, exc)
    ):
        subfolders.sort()
        for filename in sorted(filenames):
            if not filename.lower().endswith(".xml"):
                continue
            path = Path(directory) / filename
            counts.xml_files += 1
            try:
                session = ET.parse(path).getroot()
            except (ET.ParseError, LookupError, OSError, ValueError) as exc:
                record_error(path, exc)
                continue
            if session.tag != "session":
                continue
            general = session.find("general")
            game_type = session.findtext("general/gametype", "")
            if raw_handhistory_contains and raw_handhistory_contains not in game_type:
                continue
            header = ET.tostring(general, encoding="unicode") if general is not None else ""
            for game in session.iterfind("game"):
                code = game.get("gamecode", "")
                game_id = int(code) if code.isascii() and code.isdigit() else 0
                fragment = ET.tostring(game, encoding="unicode")
                yield HM2HandRow(game_id, game_id, 4, f"<session>{header}{fragment}</session>",
                                 str(path), None, None, None)
                emitted += 1
                if max_hands is not None and emitted >= max_hands:
                    return
