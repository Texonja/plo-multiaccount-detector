from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import time

from .hm2_backup import iter_hm2_handhistories
from .validation import self_test_line, validate_splits
from .hand_sample import HandSample
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
    p.add_argument("--input", required=True, help="HM2 .pghembk backup or plain HM2 PostgreSQL .sql dump")
    p.add_argument("--out", required=True, help="Output directory")
    p.add_argument("--config", default=None, help="Config JSON path")
    p.add_argument("--max-hands", type=int, default=None, help="Quick test limit")
    p.add_argument("--site-id", type=int, default=4, help="HM2 pokersite_id; 4 is iPoker in the supplied backup")
    p.add_argument("--contains", default="Omaha PL", help="Fast raw hand-history substring filter")
    p.add_argument("--top", type=int, default=100, help="Rows in Markdown summary")
    p.add_argument("--no-validate", action="store_true", help="Skip split-half self-test")
    p.add_argument("--no-dedupe", action="store_true", help="Do not deduplicate by site+gamenumber")
    p.add_argument("--progress-every", type=int, default=25000, help="Progress interval in processed rows; 0 disables")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
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

    try:
        for row in iter_hm2_handhistories(input_path, max_hands=args.max_hands, raw_handhistory_contains=args.contains):
            rows_seen += 1
            if args.site_id is not None and row.pokersite_id != args.site_id:
                continue
            key = (row.pokersite_id, row.gamenumber)
            if not args.no_dedupe and key in seen_keys:
                continue
            seen_keys.add(key)
            try:
                hand = parse_hand_history(row.handhistory, fallback_hand_id=row.gamenumber)
                add_hand(run, hand, table_sizes_for_stats=table_sizes, sample=sample)
            except Exception as exc:
                run.parse_errors += 1
                if len(run.parse_error_rows) < 1000:
                    run.parse_error_rows.append({"hand_id": str(row.gamenumber or row.handhistory_id), "error": str(exc)[:500]})

            if args.progress_every and rows_seen % args.progress_every == 0:
                print(
                    f"processed_rows={rows_seen:,} parsed={run.hands_parsed:,} players={len(run.player_stats):,} elapsed={time.time()-start:.1f}s",
                    file=sys.stderr,
                )
    except KeyboardInterrupt:
        print("Interrupted. Writing partial report...", file=sys.stderr)

    priors = fit_priors(run.player_stats.values())
    grid_prior = fit_grid_priors(run.player_stats.values())
    totals = {}
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

    print(f"Done. Parsed {run.hands_parsed:,} hands. Candidates: {len(candidates):,}. Output: {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
