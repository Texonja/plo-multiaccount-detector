# PLO Multiaccount Detector 0.9

A local desktop tool for reviewing PLO accounts with similar playing profiles.

## Run on Windows

Extract the Windows ZIP and double-click **PLO-Detector.exe**. It includes Python, Tkinter, NumPy, the backup and the sample report. [Published Windows release (0.9)](https://github.com/Texonja/plo-multiaccount-detector/releases/tag/v0.9)

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

The active stat contributions add on a base-10 log scale. A contribution of +1 gives the shared-frequency explanation ten times as much weight for that stat. Negative values favor separate frequencies. A player with zero opportunities contributes exactly zero to that comparison. Conditioning PFR on VPIP reduces the overlap between the two preflop measures. Other correlations and changes in opponents or stakes can still affect the total. **The score ranks similarity. It does not give the probability of a shared identity.**

The report uses 5- and 6-handed play and requires 50 hands per account by default. Each eligible player gets a list of their 50 closest neighbors by score. **Mutual rank** is the worse of the two directional ranks. A missing direction receives 51. A mutual rank of 1 means each is the other's closest match. `neighbor_list_size` controls the list length. Ties within a list use the account name.

The report filters at score 2.8, orders by ascending mutual rank and then descending score, and keeps up to 2,000 pairs. On the 150,000-hand sample, **4,793 pairs** pass the filter and **2,000** appear in the report. Shared hands and dates provide review context. Any account seated in more than half of all parsed hands is labeled **probable database owner** and retains its normal eligibility. The CSV includes the previous Beta score in `legacy_beta_score` for comparison, alongside the earlier points columns.

## Behavioral stats

- **Bet sizing** uses the incremental chips committed by the time of the action, including blinds. Each first postflop bet is small through 40% of the pot, medium through 75%, or large above 75%. The model scores small out of all bets, then large out of non-small bets. Preflop, the first raise counts as pot-sized at 95% or more of the pot-limit maximum, measured in additional chips after accounting for the blind and call. The first raise may follow a limper. Type 7 all-ins fund the pot and are excluded from sizing samples. The fraction histograms in `summary.json` use inclusive upper edges with a final overflow bin. The sample includes 61 bets above their reconstructed pot. The action log leaves the exact cause unresolved.
- **Positional RFI** tracks open-raises with no prior voluntary investment. It derives EP, CO, BTN and SB from the button and active seats. A player who limps uses an opportunity. Missing button information leaves RFI unobserved.
- **Frequency stats** count a flop c-bet chance when the last preflop raiser can bet an unopened flop. Folds to c-bets and flop check-raises use responses to the initial bet before an intervening raise. Fold to 3Bet uses the first preflop raiser's response to a 3Bet before a 4Bet.

**Playing profile** shows the new stats with both players' opportunity counts. **Scoring** lists the terms included in the total. Set `bet_sizing`, `positional_rfi`, and `postflop_frequency` under `behavior_groups` in `config.json` to select the groups included in scoring. The CSV includes all measured rates, opportunities and component LRs.

## Split-half self-test

The primary split orders each account's stat-sample hands by timestamp, breaking ties by hand ID. The first and second halves come from different periods of the same account, with no deliberate style change. Parity splits by even and odd hand IDs within the same period. Hands with missing timestamps remain in parity and the full profile. Priors use the full sample.

### Ablation

Each group was added separately to the five-stat model at score 2.0. A group passes with at least a 1-percentage-point chronological top-10 gain and no drop in chronological P@500. P@K is calculated using the report's threshold, mutual-rank order, score tiebreak and 2,000-row cap. Top-K hit rate and median rank use raw score ranks for each twin, with ties counted at the best shared rank.

| Configuration | Split | Top 1 | Top 10 | Top 50 | Median rank | P@100 | P@500 | P@1,000 | Twins passing |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Five stats | Chronological | 4.1% | 16.1% | 39.8% | 78.5 | 19.0% | 9.0% | 5.8% | 115 / 831 |
| Five stats | Parity | 8.5% | 29.2% | 57.9% | 34 | 39.0% | 18.0% | 12.1% | 182 / 826 |
| + Bet sizing | Chronological | 14.3% | 37.5% | 68.1% | 21 | 54.0% | 21.6% | 13.6% | 372 / 831 |
| + Bet sizing | Parity | 29.5% | 58.4% | 83.1% | 6 | 90.0% | 46.6% | 29.2% | 521 / 826 |
| + Positional RFI | Chronological | 4.6% | 18.8% | 41.8% | 70 | 24.0% | 10.0% | 7.0% | 260 / 831 |
| + Positional RFI | Parity | 10.2% | 31.4% | 60.4% | 29 | 54.0% | 20.6% | 13.1% | 379 / 826 |
| + Frequency stats | Chronological | 6.1% | 22.0% | 45.5% | 63 | 30.0% | 11.0% | 7.4% | 153 / 831 |
| + Frequency stats | Parity | 13.7% | 35.5% | 63.3% | 26 | 62.0% | 25.2% | 15.5% | 240 / 826 |
| Passing groups combined | Chronological | 16.3% | 42.0% | 69.7% | 17 | 60.0% | 26.2% | 16.6% | 450 / 831 |
| Passing groups combined | Parity | 32.8% | 60.5% | 84.9% | 5 | 93.0% | 51.0% | 32.2% | 607 / 826 |

All three groups passed and are enabled by default.

### Choosing the score threshold

The sweep uses the final model on the chronological split from 0.5 to 7.0, with a finer sweep near the strongest results. Selected rows are shown below. The same HM2 sample was used for group selection and threshold tuning.

| Score threshold | P@100 | P@500 | P@1,000 | Report rows |
| ---: | ---: | ---: | ---: | ---: |
| 0.5 | 60.0% | 26.2% | 16.6% | 2,000 |
| 2.0 | 60.0% | 26.2% | 16.6% | 2,000 |
| 2.5 | 60.0% | 26.2% | 16.7% | 2,000 |
| 2.7 | 60.0% | 26.2% | 16.8% | 2,000 |
| 2.8 | 60.0% | 26.4% | 17.0% | 2,000 |
| 2.9 | 60.0% | 26.4% | 16.8% | 2,000 |
| 3.0 | 60.0% | 26.4% | 16.5% | 2,000 |
| 3.5 | 60.0% | 25.4% | 15.8% | 2,000 |
| 4.5 | 60.0% | 22.4% | 13.4% | 1,136 |
| 5.0 | 60.0% | 19.4% | — | 589 |

The default is **2.8**. It ties for the best P@500 and has the highest P@1,000 among the tested cutoffs, with P@100 at 60%.

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
python tools/build_windows.py PLO-Detector-0.9-Windows-x64.zip
```
