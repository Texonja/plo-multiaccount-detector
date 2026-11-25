# PLO Multiaccount Detector 0.8

A local desktop tool for reviewing PLO accounts with similar playing profiles.

## Run on Windows

Extract the **0.8 Windows x64 ZIP**, then double-click **PLO-Detector.exe**. The runtime, Tkinter, NumPy, backup and sample report are included. The [published 0.7 release](https://github.com/Texonja/plo-multiaccount-detector/releases/tag/v0.7) uses the earlier points-based report.

| Ribbon action | What it does |
| --- | --- |
| Open backup | Analyze an HM2 `.pghembk` backup or SQL dump. |
| Analyze | Rebuild the report from the current backup using `config.json`. |
| Open report | Open a candidate CSV, including a 0.7 report. Keep its original `summary.json` alongside it for database totals. |
| Export CSV | Save visible pairs in the current order with all report columns. |

Select a pair to see its playing profiles. **Scoring** shows how each stat contributes to the total. Click a heading to sort, **Ctrl+F** to find a player and **Esc** to clear the search.

## Scoring

The score compares two explanations for the counts observed in each stat. In the first, both accounts have the same underlying frequency. In the second, each account has a frequency drawn independently from the player population. The detector fits a beta distribution for each stat by maximum likelihood on all full-run profiles, including small samples. The fitted parameters are in `summary.json`.

| Stat | Successes / opportunities |
| --- | --- |
| VPIP | Hands with a voluntary preflop investment / hands dealt |
| PFR given VPIP | Hands raised preflop / hands with a voluntary investment |
| 3Bet | Hands with a first re-raise / hands with an opportunity to first re-raise |
| WTSD | Showdowns / flops seen |
| W$SD | Winning showdowns / showdowns |

The five contributions add on a base-10 log scale. A contribution of +1 gives the shared-frequency explanation ten times as much weight for that stat. Negative values favor separate frequencies. A player with zero opportunities contributes exactly zero to that comparison. Conditioning PFR on VPIP reduces the overlap between the two preflop measures. Other correlations and changes in opponents or stakes can still affect the total. **The score ranks similarity. It does not give the probability of a shared identity.**

By default the detector uses 5- and 6-handed play, requires 50 hands per account and excludes generic iPoker seat names. A threshold of **2.5** produces **1,753 pairs** from 1,247 eligible players in the 150,000-hand sample. The **2,000-row cap** keeps larger reports practical. Both values are configurable. Shared hands across table sizes and first/last observation dates are available for review and carry zero weight. The CSV retains 0.7 per-stat points, the sample adjustment and the old total in `legacy_points` and `risk_points`.

## Split-half self-test

Each parsed hand also feeds an even- or odd-hand-ID profile. Two halves of the same account have zero shared hands and form a known pair. Each half competes against every other eligible account, including accounts whose own twin is too small. Both methods use the same split. The LR uses priors fitted on the unsplit profiles. This is an **idealized upper bound** for retrieval under favorable conditions: same player, same period, no deliberate style change.

The sample has 1,669 eligible split accounts, 826 known pairs and 1,391,946 unordered comparisons. Hit rates use the 1,652 accounts with an eligible twin. Ranges give the two possible ends of a tie. Precision@K uses descending score and breaks ties by account names.

| Parser | Score | Twin in top 1 | Twin in top 10 | Twin in top 50 | Median twin rank | Precision@100 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 0.7 | Legacy points | 2.6–3.1% | 8.5–11.0% | 22.6–27.7% | 209–298.5 | 14% |
| 0.7 | LR | 8.5% | 28.6% | 57.1% | 37 | 14% |
| 0.8 | Legacy points | 2.8–3.5% | 8.1–10.4% | 22.5–27.8% | 209–299 | 9% |
| 0.8 | LR | 8.4% | 28.9% | 57.8% | 36.5 | 13% |

| Hands in smaller half | Accounts | Twin in LR top 10 with 0.7 parser | With 0.8 parser |
| --- | ---: | ---: | ---: |
| 50–149 | 992 | 13.7% | 14.8% |
| 150–499 | 456 | 43.2% | 42.1% |
| 500–1,499 | 150 | 60.0% | 61.3% |
| 1,500+ | 54 | 90.7% | 87.0% |

At the 0.8 report threshold, LR flags 4,015 split pairs, including 98 known twins (2.44% precision, 11.86% recall). Legacy scoring flags 2,294 at 100 points, including 47 twins (2.05% precision, 5.69% recall). These counts use every qualifying pair before the display cap. Just 13 of the first 100 LR pairs are twins. Five aggregate statistics leave many distinct accounts with similar profiles. Establishing a common operator requires independent evidence.

The [sample report](sample_output/top_candidates.md) gives the shortlist. [Validation results](sample_output/validation.json) include individual twin ranks, sample-size groups, threshold metrics and precision at 100, 500, 1,000 and 1,500 pairs. A complete run took 67.8 seconds on Windows x64 with CPython 3.14.8 and NumPy 2.5.3. Desktop analyses write new reports under `reports/`. The GUI opens the bundled sample at startup.

## iPoker parser and sample audit

Type 23 is a raise to the stated street total. A raise to 1.75 from a posted blind of 0.50 adds 1.25. Type 7 adds its full amount to the previous contribution. Its new street total determines whether the action calls, bets or raises. Blinds carry into preflop. A dealt flop counts even when the board runs out without further betting.

On the sample, parsed action amounts reconcile with the XML player `bet` in 769,270 of 769,435 player-hands (99.98%). Version 0.8 reconciled 727,280 (94.52%). Reproduce the check with `python tools/audit_ipoker.py database.pghembk`.

## Run from source

Use Python 3.10+ with Tkinter. In the project directory install the runtime dependency, then double-click **OPEN_DETECTOR.bat**.

```powershell
python -m pip install -r requirements.txt
```

**RUN_MULTIACCOUNT_REPORT.bat** runs the batch workflow. In PowerShell the equivalent CLI invocation is:

```powershell
$env:PYTHONPATH = "src"
python -m plo_multiaccount_detector --input database.pghembk --out reports/my_run
```

Add `--no-validate` to skip the self-test. Run the test suite with `python -m unittest discover -s tests`.

To build the portable ZIP using 64-bit python.org Python on Windows with Tcl/Tk installed:

```powershell
python -m pip install -r requirements.txt distlib==0.4.2
python tools/build_windows.py PLO-Detector-0.8-Windows-x64.zip
```
