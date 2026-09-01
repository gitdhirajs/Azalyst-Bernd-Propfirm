# Holdout results — 2024-04-01 to 2026-08-25

The 510-case development corpus spans 2023-01-01..2024-03-10 and is thoroughly
in-sample: every tuning phase, flag and analysis used it. This window is ~29
months no tuning has touched — the first genuinely out-of-sample test this
project has run. 39 symbols, weekly strategy.

Gate 1 (accuracy) is NOT measurable here: a forward period has no ground-truth
calls. Gates 3 and 4 — expectancy vs a drift-matched null, and whether the zone
entry beats the same call at market — are the money questions and do run.

CAVEAT: COT runs from stale pins (the fresh-fetch path blocks on the CFTC bulk
download). Per C-113 COT scores exactly at the always-long baseline, i.e. zero
information, so this costs nothing measurable — but it is a real limitation.

CAVEAT: the calendar was inert (C-126) — check_blackout() was called without a
date, so it evaluated the wall clock. LIVE trading WILL gate where this did not.

## BASELINE — shipped defaults, no flags

Signals file: `oos_base_signals.json`  —  verified 2026-08-31 23:52

```
signals  D:/Trading/Azalyst Bernd Skorupinski/Propfirm Trading Dashboard/goldtest/oos_base_signals.json   15 usable signals
  no ground-truth calls exist for a forward period, so gate 1 is skipped

  [  --] accuracy (paired McNemar)    no ground truth in a forward period
  [  --] signal population            15 trades (nothing to compare against)
  [FAIL] expectancy vs drift null     50.0% (6/12) +0.50R vs null 31.1%  exact p=0.1354
  [  OK] zone entry beats market      entry 4 / market 2 on 12 paired  p=0.6875

  VERDICT: NOT supported -- do not flip the default
  Reference: their signals corpus wins gate 4 at 4:0, p=0.125 -- consistent in direction under every de-duplication rule, NOT significant (C-127).
```

```
pin search order: ['D:\\Trading\\Azalyst Bernd Skorupinski\\Propfirm Trading Dashboard\\ohlcv_extended'] then D:\Trading\Azalyst Bernd Skorupinski\Propfirm Trading Dashboard\ohlcv_snapshot
15 signals loaded

=== AT THE SIGNAL'S ENTRY (target 2.0R) ===
  signals 15   never filled 3   decided 12   still open 0   no data 0
  win rate        6/12 = 50.0%
  per TRADE TAKEN +0.50R
  per OPPORTUNITY +0.40R   (unfilled counted as 0R, n=15)

=== CONTROL: same call at MARKET (target 2.0R) ===
  signals 15   never filled 0   decided 13   still open 2   no data 0
  win rate        5/13 = 38.5%
  per TRADE TAKEN +0.15R
  per OPPORTUNITY +0.15R   (unfilled counted as 0R, n=13)

=== DRIFT-MATCHED NULL: same symbols and directions, 30 random dates each ===
  signals 450   never filled 0   decided 440   still open 10   no data 0
  win rate        133/440 = 30.2%
  per TRADE TAKEN -0.09R
  per OPPORTUNITY -0.09R   (unfilled counted as 0R, n=440)
  ^ THIS is the number to beat when the sample is directionally lopsided,
    not the driftless 33.3% below.

  random walk, no drift, by theory:  33.3% win   +0.00R   <- exact, not simulated
  their published KPI slide:          40.0% win   +0.20R at 2.0R
```
