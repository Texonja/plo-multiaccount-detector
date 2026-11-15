# PLO Multiaccount Detector 0.7

A local workspace for reviewing pairs of PLO players with similar playing profiles.

## Run on Windows

To run the detector on Windows without downloading or building the source code separately, use the portable ZIP. [Download for Windows x64](https://github.com/Texonja/plo-multiaccount-detector/releases/download/v0.7/PLO-Detector-0.7-Windows-x64.zip)

Choose **Extract All**, then double-click **PLO-Detector.exe** in the extracted folder. The sample report opens immediately. Python and Tkinter are included.

| Ribbon action | What it does |
| --- | --- |
| Open backup | Analyze an HM2 `.pghembk` backup or SQL dump. |
| Analyze | Rebuild the report from the current backup using `config.json`. |
| Open report | Open an existing candidate CSV. Keep `summary.json` next to the original CSV for database totals. |
| Export CSV | Save the visible pairs in their current order with all report columns. |

Select a row to compare players. **Playing profile** shows both players' stats and samples. **Scoring** shows the relative differences and points. Click a column heading to sort. **Ctrl+F** finds a player in either seat and **Esc** clears the search.

## Sample

`database.pghembk` contains 150,000 anonymized hands. Its original report is in `sample_output/` with 2,713 player profiles and 1,507 candidate pairs. New analyses write to dated folders under `reports/`.

## Scoring

The detector reconstructs VPIP, PFR, 3Bet, WTSD and W$SD from 5- and 6-handed play. Each stat contributes points according to its relative difference between players. The smaller hand sample determines the sample adjustment. Shared hands count observed hands in which both players were seated.

Thresholds, sample sizes and the report limit are in `config.json`. Points prioritize pairs for manual review. Confirming a shared identity requires separate evidence.

## Run from source

With Python 3.10+ and Tkinter installed, double-click **OPEN_DETECTOR.bat** in the source checkout.

`RUN_MULTIACCOUNT_REPORT.bat` runs the original batch workflow against `database.pghembk` and writes CSV, Markdown and JSON reports. For CLI options in PowerShell, run the following in the project directory.

```powershell
$env:PYTHONPATH = "src"
python -m plo_multiaccount_detector --help
```

To build the portable ZIP on Windows x64, use the python.org distribution with Tcl/Tk and run the following from the project directory.

```powershell
python -m pip install distlib==0.4.2
python tools/build_windows.py PLO-Detector-0.7-Windows-x64.zip
```
