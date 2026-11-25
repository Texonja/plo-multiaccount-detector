# PLO Multiaccount Detector 0.8.2

A local desktop tool for reviewing PLO accounts with similar playing profiles.

## Run on Windows

Download and extract the ZIP, then double-click **PLO-Detector.exe**. It includes Python, Tkinter, NumPy, the backup and the sample report. [Download for Windows x64](https://github.com/Texonja/plo-multiaccount-detector/releases/download/v0.8.2/PLO-Detector-0.8.2-Windows-x64.zip)

| Ribbon action | What it does |
| --- | --- |
| Open backup | Analyze an HM2 `.pghembk` backup or SQL dump. |
| Analyze | Rebuild the report from the current backup using `config.json`. |
| Open report | Open a candidate CSV, including 0.7 and 0.8 reports. Keep its original `summary.json` alongside it for database totals. |
| Export CSV | Save visible pairs in the current order with all report columns. |

Select a pair to see its playing profiles. **Scoring** shows how each stat contributes to the total. Click a heading to sort, **Ctrl+F** to find a player and **Esc** to clear the search.

## Scoring

The score compares two explanations for the counts observed in each stat. In the first, both accounts have the same underlying frequency. In the second, each account has a frequency drawn independently from the player population. For each stat, the detector estimates how common 400 possible playing frequencies are between 0.0025 and 0.9975. It fits these weights to all full-run profiles with 300 expectation-maximization steps. After each step it smooths the grid with a Gaussian kernel (three grid steps of standard deviation) and normalizes it. The grid can capture several common playing styles. The fitted weights are in `summary.json` under `grid_prior`.

| Stat | Successes / opportunities |
| --- | --- |
| VPIP | Hands with a voluntary preflop investment / hands dealt |
| PFR given VPIP | Hands raised preflop / hands with a voluntary investment |
| 3Bet | Hands with a first re-raise / hands with an opportunity to first re-raise |
| WTSD | Showdowns / flops seen |
| W$SD | Winning showdowns / showdowns |

The five contributions add on a base-10 log scale. A contribution of +1 gives the shared-frequency explanation ten times as much weight for that stat. Negative values favor separate frequencies. A player with zero opportunities contributes exactly zero to that comparison. Conditioning PFR on VPIP reduces the overlap between the two preflop measures. Other correlations and changes in opponents or stakes can still affect the total. **The score ranks similarity. It does not give the probability of a shared identity.**

The report uses 5- and 6-handed play and requires 50 hands per account by default. Each eligible player gets a list of their 50 closest neighbors by score. **Mutual rank** is the worse of the two directional ranks. A missing direction receives 51. A mutual rank of 1 means each is the other's closest match. `neighbor_list_size` controls the list length. Ties within a list use the account name.

The report filters at score 2.0, orders by ascending mutual rank and then descending score, and keeps up to 2,000 pairs. On the 150,000-hand sample, **3,453 pairs** pass the filter and **2,000** appear in the report. Shared hands and dates provide review context. Any account seated in more than half of all parsed hands is labeled **probable database owner** and retains its normal eligibility. The CSV includes the previous Beta score in `legacy_beta_score` for comparison, alongside the earlier points columns.

## Split-half self-test

Even and odd hand IDs form two profiles per account. An eligible half competes against all other eligible accounts. Priors are fitted once on the full profiles. This is an idealized upper bound for finding a known twin in the same period without a deliberate style change.

The sample contains 1,669 eligible halves, 826 known twins and 1,391,946 unordered pairs. Precision@K is the share of known twins among the first K rows produced by the report pipeline. The self-test applies the score threshold, sorts by ascending mutual rank and descending score, then applies the report cap. Account names break ties. Neighbor ranks are computed from all eligible profiles before filtering.

| Grid score pipeline | Precision@100 | @500 | @1,000 | @1,500 |
| --- | ---: | ---: | ---: | ---: |
| 0.8.1 report · score ≥2.5 | 34.0% | 13.4% | 7.4% | 5.3% |
| 0.8.2 report · score ≥2.0 | 39.0% | 18.0% | 12.1% | 9.0% |
| Unfiltered · mutual rank | 39.0% | 16.8% | 11.2% | 9.3% |
| Unfiltered · raw score | 18.0% | 9.2% | 6.1% | 4.9% |

| Score filter | Split pairs passing | Known twins passing | Mutual-rank-1 twins passing |
| --- | ---: | ---: | ---: |
| ≥2.5 | 1,845 | 83 / 826 | 31 / 46 |
| ≥2.0 | 7,838 | 182 / 826 | 44 / 46 |

The score and population prior are the same as in 0.8.1. By raw score, an account's twin appears in its top 10 in 29.2% of cases. The shortlist is for manual review. Establishing a common operator requires separate evidence.

The GUI opens the sample at startup. Desktop analyses write to `reports/`. [Sample shortlist](sample_output/top_candidates.md) · [Full validation and individual ranks](sample_output/validation.json)

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
python tools/build_windows.py PLO-Detector-0.8.2-Windows-x64.zip
```
