from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time

from .hm2_backup import iter_hm2_handhistories
from .hand_histories import ArchiveCounts, iter_archive_hands
from .validation import self_test_line, validate_splits
from .hand_sample import HandSample
from .behavior_stats import stat_specs
from .grid_prior import fit_grid_priors
from .likelihood import fit_priors
from .hh_parser import parse_hand_history
from .multiaccount import (
    MultiaccountRun,
    add_hand,
    build_splits,
    find_candidates,
    load_config,
    write_csv,
    write_csv_any,
    write_summary,
    write_top_markdown,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="plo-multiaccount-detector",
        description="HM2-focused PLO multiaccount / ghost-player candidate detector.",
    )
    p.add_argument("--input", required=True, help="HM2 backup, SQL dump or folder of iPoker XML hand histories (including subfolders)")
    p.add_argument("--out", required=True, help="Output directory")
    p.add_argument("--config", default=None, help="Config JSON path")
    p.add_argument("--max-hands", type=int, default=None, help="Quick test limit")
    p.add_argument("--site-id", type=int, default=4, help="HM2 pokersite_id; 4 is iPoker in the supplied backup")
    p.add_argument("--contains", default="Omaha PL", help="Substring in the backup hand history or the XML session game type")
    p.add_argument("--top", type=int, default=100, help="Rows in Markdown summary")
    p.add_argument("--no-validate", action="store_true", help="Skip split-half self-test")
    p.add_argument("--no-dedupe", action="store_true", help="Do not deduplicate by site+gamenumber")
    p.add_argument("--progress-every", type=int, default=25000, help="Progress interval in processed rows; 0 disables")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Input not found: {input_path}", file=sys.stderr)
        return 2

    config_path = args.config
    if config_path is None:
        local = Path.cwd() / "config.json"
        if local.exists():
            config_path = str(local)
    config = load_config(config_path)
    table_sizes = {int(x) for x in config.get("table_sizes_for_stats", [6, 5])}

    run = MultiaccountRun()
    sample = None if args.no_validate else HandSample()
    start = time.time()
    rows_seen = 0
    seen_keys: set[tuple[int, int]] = set()
    archive = ArchiveCounts() if input_path.is_dir() else None

    def record_error(source, message):
        if len(run.parse_error_rows) < 1000:
            run.parse_error_rows.append({"hand_id": source, "error": message[:500]})

    options = dict(max_hands=args.max_hands, raw_handhistory_contains=args.contains)
    if archive is not None:
        input_path = input_path.resolve()
        rows = iter_archive_hands(input_path, counts=archive, on_error=record_error, **options)
    else:
        rows = iter_hm2_handhistories(input_path, **options)

    try:
        for row in rows:
            rows_seen += 1
            if args.site_id is not None and row.pokersite_id != args.site_id:
                continue
            key = (row.pokersite_id, row.gamenumber)
            if not args.no_dedupe and key in seen_keys:
                if archive is not None:
                    archive.duplicates += 1
                continue
            try:
                hand = parse_hand_history(row.handhistory, fallback_hand_id=row.gamenumber)
                add_hand(run, hand, table_sizes_for_stats=table_sizes, sample=sample)
                if not args.no_dedupe:
                    seen_keys.add(key)
            except Exception as exc:
                run.parse_errors += 1
                record_error(str(row.gamenumber or row.filename or row.handhistory_id), str(exc))

            if args.progress_every and rows_seen % args.progress_every == 0:
                print(
                    f"processed_rows={rows_seen:,} parsed={run.hands_parsed:,} players={len(run.player_stats):,} elapsed={time.time()-start:.1f}s",
                    file=sys.stderr,
                )
    except KeyboardInterrupt:
        print("Interrupted. Writing partial report...", file=sys.stderr)

    if archive is not None and not run.hands_parsed:
        print(f"No matching iPoker hands found. XML files checked: {archive.xml_files}. "
              f"Read errors: {archive.read_errors}. Hand errors: {run.parse_errors}.", file=sys.stderr)
        return 2

    priors = fit_priors(run.player_stats.values())
    grid_prior = fit_grid_priors(run.player_stats.values(), stat_specs())
    totals = {"hand_history_import": asdict(archive)} if archive is not None else {}
    candidates = find_candidates(run, config, priors, grid_prior=grid_prior, totals=totals)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    validation_path = out / "validation.json"
    self_test = None
    if sample is not None:
        result = validate_splits(build_splits(sample), priors, config, grid_prior, undated=sample.undated)
        validation_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        self_test = self_test_line(result)
    else:
        validation_path.unlink(missing_ok=True)
    write_csv(out / "multiaccount_candidates.csv", candidates)
    write_top_markdown(out / "top_candidates.md", candidates, top=args.top, self_test=self_test)
    write_summary(out / "summary.json", run=run, rows=candidates, config=config, input_path=str(input_path),
                  priors=priors, grid_prior=grid_prior, totals=totals, self_test=self_test)
    if run.parse_error_rows:
        write_csv_any(out / "parse_errors.csv", run.parse_error_rows)
    else:
        (out / "parse_errors.csv").unlink(missing_ok=True)

    print(f"Done. Parsed {run.hands_parsed:,} hands. Candidates: {len(candidates):,}. Output: {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
