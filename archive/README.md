# archive/

Kept for history, not used by the scanner, the GitHub workflows or the goldtest.
Moved here on 2026-09-15 with `git mv`, so each file's history is intact.

| Path | What it is |
|---|---|
| `AUDIT_PHASE_28*.md`, `_audit_phase28/` | Phase 28 audit reports and the scripts behind them |
| `Propfirm Trading Dashboard/backtest_10yr_*.{csv,json}` | 10-year backtest outputs (`backtest_10yr*.bat` regenerates them) |
| `Propfirm Trading Dashboard/wf_*_2020.*`, `wf_smoke_test.csv` | walk-forward outputs (`walk_forward_30yr.bat` regenerates them) |
| `Propfirm Trading Dashboard/full_history_cot_20260513_*.csv` | one-off COT history dumps (`run_full_history_cot.py`) |
| `Propfirm Trading Dashboard/goldtest/gold_results_phase2*.json`, `gold_diff.html` | Phase 26/28 goldtest result snapshots |

Left in place on purpose: `goldtest/gold_results.json` (default output of `run_goldtest.py`) and
`_validate_expansion_result.json` (read by `_gen_allcoins_config.py`).
