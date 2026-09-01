# RUN — the commands, and what they will and will not do

Written 2026-08-31. Every command below was executed to confirm it starts and does what
this file says. Read the STATE section before running anything.

---

## STATE — read this first

**No configuration of this system has demonstrated an edge.** As of 2026-08-31:

- Direction accuracy is **52.75%** on 510 cases, against **50.39%** for answering "long"
  every time. The difference is not significant (p=0.279).
- Stage-1 accuracy is **arithmetically closed** (C-113/C-114). A lookup table that
  memorises the best answer for every combination of the bias components caps at 71.4%
  IN-SAMPLE; out of sample, 575 feature subsets across three independent families produce
  a best result of **-0.47 points versus a constant**.
- **Nothing in the project is statistically significant** (C-127). The one result that
  reached p<0.05 was inflated by duplicate readings of a single position tool; collapsed
  properly it is 4:0, p=0.125.
- With defaults the engine fires **5 signals in 510 cases**, resolving to ONE decided
  trade. That is not conservatism, it is an untested system whose failure is hidden by
  inactivity.

There is live paper state already: `paper_trader_state.json` holds **$5,067.75 with 4 open
positions** (separate books exist for allcoins and allmarkets). Running the scanner will
act on that state.

I am not a licensed advisor and this is not advice about your money. It is what was
measured.

---

## 1. The production command

    cd "D:\Trading\Azalyst Bernd Skorupinski\Propfirm Trading Dashboard"
    python run_scanner.py

Runs the weekly scan across the 41-symbol watchlist from `BP_config.yaml`, updates the
paper trader, and serves a dashboard at <http://127.0.0.1:8765/dashboard.html>.
Logs to `scanner_weekly.log` (summary) and `scanner.log` (full).

It restores paper-trader state on start, so it continues the existing book rather than
starting flat. There is no `--help`: invoking it runs a scan.

**Set no environment variables.** All 28 `BP_*` flags default OFF and every one of them is
experimental. The shipped config is the only configuration that has been measured
end-to-end.

## 2. Verify nothing is silently enabled

    cd "D:\Trading\Azalyst Bernd Skorupinski\Propfirm Trading Dashboard"
    env | grep "^BP_"                                     # must print nothing
    grep -nE "fair_zone_scan|require_big_brother|prefer_midpoint_entry" BP_config.yaml

Expected: no `BP_*` variables, and `prefer_midpoint_entry: false`. Anything else means a
flag is on and the run is not the measured configuration.

## 3. Before believing ANY change

    python goldtest/verdict.py --arm "myarm?.json"

Four gates, weakest decides. Exit code 0/1 so it can gate a commit.

    1  accuracy, paired McNemar on cases scored in BOTH arms
    2  did the emitted TRADE POPULATION change (invalidates outcome comparison)
    3  expectancy vs a DRIFT-MATCHED null, never the driftless 1/3
    4  does the zone entry beat the same call at market, paired

All arms tested to date return **NOT supported**. Gate 4 is the one that matters: it is
the direct measure of whether zone selection stopped being inverted.

To produce an arm to test:

    for i in 0 1 2 3 4 5; do
      MYFLAG=1 python goldtest/run_goldtest.py --cases-file goldtest/full510_shard$i.yaml \
        --output goldtest/myarm$i.json --ohlcv-snapshot read --cot-snapshot read &
    done; wait

Six shards, ~50 minutes. Run them in the background; snapshots are pinned because two
unpinned runs of identical code scored 54.2% and 51.7%.

## 4. Out-of-sample (the only honest test)

The 510-case corpus spans 2023-01-01..2024-03-10 and is thoroughly in-sample — every
tuning phase and every analysis used it. Anything after **2024-03-10** is untouched.

    python run_forward_test.py --strategy weekly \
      --start 2024-04-01 --end 2026-08-25 \
      --emit-signals goldtest/oos_signals.json \
      --ohlcv-snapshot fill --cot-snapshot read
    python goldtest/verdict.py --signals-file goldtest/oos_signals.json

~17 min/symbol × 39 symbols ≈ 8 hours. Run ONE arm at a time: two engines halve each
other's speed and make a healthy run look hung.

Gate 1 is skipped there — a forward period has no ground-truth calls — so this answers
whether the system makes money, not whether it agrees with anyone.

`--cot-snapshot fill` blocks on the CFTC bulk download; use `read`.

---

## Known limitations that affect any run

- **The calendar never evaluates the scan date** (C-126). `BP_rules_engine.py:767` calls
  `check_blackout()` with no argument, which defaults to `datetime.utcnow()`. Every
  backtest ever run here had calendar gating effectively inert, while LIVE trading WILL
  gate on holidays and events. **Live behaviour differs from every backtest.**
  `BP_CALENDAR_ASOF=1` fixes it but must not be used yet — the curated tables only cover
  2025-2026, so enabling it makes the engine behave differently in different years.
- **Curated event dates cover 2025-2026 only.** 2024 has zero events per quarter; 2027 is
  missing. Extending them needs published FOMC/ECB/BoE/CPI schedules — a human. Do not
  guess them.
- **COT carries no measurable signal** (C-113): `cot` and `cot_strength` score exactly at
  the always-long baseline.

## Flags that exist but must stay OFF

Implemented, documented, and **never validated**. Each needs a `verdict.py` pass first:

    BP_ZONE_REACHABLE      order reachable zones first (C-110). Signals 5 -> 55, but those
                           55 measure -0.32R against a +0.23R null.
    BP_NEAREST_FRESH       "find nearest zone, first fresh" -- his stated step 1 (C-124)
    BP_Q5_BOUNDED          profit margin over a bounded horizon instead of all history (C-123)
    BP_REQUIRE_BIG_BROTHER his "Rule 6: HTF Coverage" (C-124); removes 26% of candidates
    BP_CALENDAR_ASOF       pass the scan date to the calendar (C-126) — blocked on the tables
    BP_MIDPOINT_ENTRY      measured, no effect on identical trades (C-112)
