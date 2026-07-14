# PLO Multiaccount / Similar-Profile Detector v0.6

A working Python prototype for finding **multiaccount, ghost-player, account-replacement, bot-farm, RTA-profile, or collusion-cluster review candidates** in PLO hand-history data.

The tool does **not** prove cheating. It creates a ranked list of suspicious player pairs for manual review.

## Quick start

This repository includes a 150,000-hand anonymized HM2-style sample backup named:

```text
database.pghembk
```

To test the tool on Windows:

```text
RUN_MULTIACCOUNT_REPORT.bat
```

The report will be written to:

```text
reports/multiaccount_report_YYYY-MM-DD_HH-MM-SS/
```

Main files:

```text
multiaccount_candidates.csv
top_candidates.md
summary.json
```

## Included sample database

The included `database.pghembk` is a 150,000-hand anonymized HM2-style backup sample. Real player nicknames were replaced with varied synthetic poker-style aliases. Original hand IDs, table names and session identifiers were also replaced.

The sample is included only so the project can be tested immediately without requiring the reviewer to have Holdem Manager 2 or a private poker database.

To run the detector on your own HM2 backup, replace `database.pghembk` with your own HM2 `.pghembk` file.

## What the tool looks for

The detector compares pairs of players using reconstructed 5-handed and 6-handed PLO stats:

- VPIP
- PFR
- 3bet
- WTSD
- Won$SD

4-handed, 3-handed and heads-up hands are ignored for stat comparison because they create much higher style variance and smaller comparable samples.

The current stats are reconstructed from raw hand-history action flow rather than imported from HM2's internal HUD/stat cache:

- **VPIP** = voluntarily put money in pot preflop / hands
- **PFR** = preflop raise / hands
- **3bet** = actual first preflop re-raise / opportunity to make the first preflop re-raise
- **WTSD** = went to showdown / saw flop
- **Won$SD** = won money at showdown / went to showdown

The output also includes denominators for sample-sensitive stats:

- `player_a_threebet_opp`, `player_b_threebet_opp`
- `player_a_saw_flop`, `player_b_saw_flop`
- `player_a_showdowns`, `player_b_showdowns`

These denominators matter. A 3bet match over 20 opportunities is not the same signal as a 3bet match over 800 opportunities.

## How to read `mutual_hands`

`mutual_hands` is the number of observed hands where both players were seated in the same hand in the supplied player-side database.

- `mutual_hands = 0` plus high profile similarity can suggest a possible multiaccount, ghost-player, or account-replacement candidate. For example, one account may have stopped playing or been banned, then another similar-profile account appears.
- high `mutual_hands` plus high profile similarity is different. Those accounts clearly co-existed at the same tables, so it is better read as a possible bot-farm, RTA-profile, or collusion-cluster review signal.

Neither case is proof. The goal is review prioritization.

## Risk points

Risk points are configurable in `config.json`.

The current logic uses relative percentage difference between two stats:

```text
relative_diff = abs(A - B) / max(A, B) * 100
```

Example:

```text
A VPIP = 26.3
B VPIP = 25.8
relative_diff = 1.90%
```

Each stat gives points when the relative difference is below configured thresholds.

### VPIP

- within 7% difference: 5 points
- within 5% difference: 10 points
- within 2.5% difference: 20 points
- within 1.5% difference: 30 points
- within 1% difference: 40 points
- within 0.5% difference: 50 points

### PFR

- within 10% difference: 5 points
- within 7% difference: 10 points
- within 3% difference: 20 points
- within 2% difference: 30 points
- within 1.5% difference: 40 points
- within 1% difference: 50 points

### 3bet

- within 30% difference: 5 points
- within 25% difference: 10 points
- within 20% difference: 20 points
- within 15% difference: 30 points
- within 10% difference: 40 points
- within 5% difference: 50 points

### WTSD

Same thresholds as VPIP.

### Won$SD

Same thresholds as VPIP.

### Sample points

The sample used is the smaller 5-handed/6-handed hand sample of the two players being compared.

- sample > 1000: +20 points
- sample > 2000: +25 points
- sample > 3000: +30 points
- sample > 4000: +40 points
- sample < 250: -10 points
- sample < 100: -20 points

These values are intentionally initial calibration values and should be adjusted after manual review on larger data sets.

## Output columns

The CSV is ordered for fast manual review:

1. player names, risk points, mutual hands and sample fields;
2. all match columns grouped together: `vpip_match_pct`, `pfr_match_pct`, `threebet_match_pct`, `wtsd_match_pct`, `wonsd_match_pct`;
3. relative differences;
4. per-stat point contribution;
5. reconstructed VPIP/PFR/3bet/WTSD/Won$SD values for both players;
6. denominators for 3bet, WTSD and Won$SD;
7. first/last seen timestamps based on observed hands.

## Important limitation

This prototype works only with **player-side data** extracted from a Holdem Manager 2 backup or an HM2-style hand-history dump.

Player-side data can identify suspicious statistical patterns, but it cannot prove identity or coordination.

A real operator-side investigation would be much stronger with additional evidence such as:

- action timing and session timing;
- IP address overlap;
- hardware fingerprint overlap;
- network fingerprint overlap;
- device / OS / client telemetry;
- account creation and login history;
- cashier / transfer / affiliate relationships.

Those data sources would make it much easier to separate real multiaccount candidates from regular players with similar strategies.

## Current status

This is a portfolio / proof-of-work prototype. It is meant to show practical thinking around poker integrity review, not to replace a full operator-side fraud platform.
