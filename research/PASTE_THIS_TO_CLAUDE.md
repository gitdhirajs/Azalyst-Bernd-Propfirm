# PASTE THE BLOCK BELOW INTO A NEW CLAUDE CHAT

Copy everything between the ``` lines. Nothing else is needed — the files it names carry the rest.

_Rewritten 2026-08-26. Previous version saved as `PASTE_THIS_TO_CLAUDE.md.bak-2026-08-26`.
It was written before the presenter identities were settled, before the execution-layer
reporting bugs were fixed, and it repeated an E-03 justification that turned out to be wrong._

```
Read these first, in order:
  D:\Trading\Claude for Bernd\SESSION_2026-08-31.md         <- newest, read this first
  D:\Trading\Claude for Bernd\SESSION_2026-08-28.md
  D:\Trading\Claude for Bernd\SESSION_2026-08-26.md
  D:\Trading\Claude for Bernd\SESSION_2026-08-24.md         <- section 8 is the older OPEN list
  D:\Trading\Claude for Bernd\audit\CODE_FINDINGS.md        (C-01..C-111)
  D:\Trading\Azalyst Bernd Skorupinski\Propfirm Trading Dashboard\goldtest\PRESENTER_AND_HONEST_SCORE.md

CONTEXT
We are checking a Python prop-firm trading system against the calls made by Bernd
Skorupinski and three Online Trading Campus instructors working under him (Jan
Skorupinski, Clemens Winkler, Chris Dietenberger). They all teach HIS method with HIS
indicator pack. DECIDED 2026-08-26 by the user: score against ALL FOUR POOLED (479
cases), not Bernd alone.

I lost 2 prop-firm challenges trusting earlier "verified / 100% correct" claims that were
not actually verified. Do NOT tell me something is correct. Tell me what was measured, on
how many samples, and what it got wrong. Every claim carries its sample size.

READ THIS FIRST -- TWO LINES OF WORK ARE CLOSED, DO NOT REOPEN THEM

  STAGE-1 ACCURACY IS ARITHMETICALLY CLOSED (C-113/C-114). A maximally overfit lookup
  table over the seven bias components caps at 71.4% IN-SAMPLE. Out of sample, 575
  feature subsets across three independent families (engine indicators, plain price
  features, zone-derived features) produce a best result of -0.47 points versus a
  constant. All 15 features together: 96.5% in-sample, 50.1% out. The engine's own
  additive-vote architecture scores -8.47. Do not tune _bias_consensus. There is no
  signal in those inputs. Run goldtest/bias_ceiling.py before touching any rule layer.

  ENTRY MECHANICS ARE CLOSED (C-112/C-119). The same limit-at-zone-proximal mechanic
  wins on THEIR zones (8:1, p=0.039) and LOSES on ours (2:5 and 4:5). Fisher exact on
  the two discordant splits: p=0.035. The edge is WHICH ZONE is chosen, not where in it
  the order sits. Midpoint entry, depth sweeps and C-104 are all measured and none is
  the lever.

  NOTHING IN THIS PROJECT IS STATISTICALLY SIGNIFICANT (C-127). The one result that
  reached p<0.05 -- "their drawn entry beats the same call at market", 8:1, p=0.039 --
  was inflated by duplicate readings of a single position tool and by same-day direction
  contradictions in the frame extraction. Collapsed properly it is 4:0, p=0.125. The
  effect direction never reverses across any de-duplication rule, so it is a real lead;
  it is not established, and the sample cannot reach significance at this size.

  READ THE RAW FRAMES BEFORE TRUSTING AN EXTRACTION. Every aggregate check passed --
  dedupe, scale validation, class separation -- and the contradiction was only visible in
  the IMAGE (PA=F 2023-03-21 extracted as both a long and a short at the same entry).

  BEFORE BELIEVING ANY RESULT: python goldtest/verdict.py --arm 'myarm?.json'
  Four gates, weakest decides. All five arms tested to date return NOT supported.

  NEVER POOL CORPORA. signals (issued) +8.5 pts vs null, weekly (anticipated) -10.6,
  practical (course) -29.6. Pooling them cancels the only positive result in the project
  and is what kept C-101 insignificant through three re-measurements (C-115/C-117/C-122).

WHERE THINGS ACTUALLY STAND (all measured on pinned data, 479 scoreable cases)

  Stage 1 (direction). No demonstrable edge over a constant "always long".
      Bernd rows        176/339 = 51.9%   vs always-long 47.8%   McNemar p=0.279
      instructor rows    79/140 = 56.4%   vs always-long 62.1%   McNemar p=0.341
    The old 74/160 goldtest score measured MEMORISATION -- ~20 phases of _bias_consensus
    tuning against the very cases being scored, plus 18 hardcoded symbol branches.

  Stage 2 (execution). Fires 5 times in 510 cases with defaults -- and those 5 resolve
    to ONE decided trade. The baseline is not conservative, it is untested: its failure
    is hidden by inactivity. "Zero Stage-2 false positives" in CLAUDE.md is an IN-SAMPLE
    property of that inactivity. Do not repeat it.

    WHY it fires so rarely was found on 2026-08-28 (C-110). `rank_zones` sorts every
    same-type zone in the loaded history by composite score, which contains no term for
    where price is now, so rank-1 is routinely a zone from YEARS earlier that price never
    revisits -- median 904 bars old, median 6.29R from the entry the trader actually drew.
    Their zone is nearly always in the candidate pool, 0.11R away, ranked ~60th of 93.
    Ordering reachable zones first (`BP_ZONE_REACHABLE`, default OFF) takes signals from
    5 to 55 and changes direction accuracy on ZERO of 510 cases.

    Do NOT turn it on yet. Those 55 signals measure -0.32R at the zone entry against a
    drift-matched null of +0.23R. 55 signals that lose money is worse than 5 that do
    nothing. Decide it on expectancy, never on signal count.

    The seven-qualifier composite does not beat a PSEUDO-RANDOM ordering of its own
    candidate pool (4.74R vs 5.91R median entry error; "nearest to price" alone gets
    2.64R). Five of seven qualifiers are near-constants on the trading path -- Q1 repeats
    the detection gate verbatim, Q5/Q6 are hardcoded to 10.0 on trend-aligned zones, and
    Q5's underlying measurement scores zone AGE rather than profit margin (C-108, C-109).
    Repairing them individually was measured and ALL of it failed.

  Trade OUTCOMES can now be measured -- goldtest/replay_trades.py drives the real
    PaperTrader bar-by-bar over pinned bars. E-03 measured on it: both filled trades
    scratched at 0.00R with breakeven_at_half_target ON and reached T3 (+3.00R each)
    with it OFF. n=2, and BOTH are path-ambiguous, so the direction is established and
    the magnitude is not. Default NOT flipped. run_forward_test.py scored those same
    three as 3 wins / +3.0R, so its win column overstates -- it models no breakeven, no
    partials, no trailing, and not the resting order E-05 cancels.

  Root cause of the flatness: Valuation is silent 64% of the time, COT 73%, and BOTH on
    45% of cases. On half the corpus the two indicators the method treats as decisive
    contribute nothing, so Location (bearish 45% -- everything sat near an all-time high)
    plus whatever heuristic fills the vacuum decides the answer.

  HARD CEILING, do not try to tune past it: the ground truth contradicts itself.
    Bernd shorts an equity index on 3 of 71 index calls (4%); Jan/Clemens on 14 of 30
    (47%). Same symbol, both directional, within 10 days: 48 agreements and 11 DIRECT
    CONTRADICTIONS (e.g. NQ=F Bernd long 2023-02-12 vs Jan short 2023-02-14). No rule set
    can match both sides. They sit exactly where the engine is weakest.

THE INDICATORS ARE NOT THE PROBLEM. They reproduce Bernd's lecture frames exactly
(COT 85.10 / 18.10 / 74.56). What has no measured out-of-sample skill is the
bias-consensus rule layer built on top of them.

RULES OF WORK, learned the hard way -- do not skip:
1. Never score a hypothesis only on the rows the engine got wrong. That guarantees any
   alternative wins. It falsely "proved" two fixes (C-63, C-68) before the full sample
   killed both.
2. Use goldtest\ab_paired.py for every A/B -- paired, case-level, McNemar. Raw
   percentages are unsafe: runs differ in how many cases error out (31 vs 35), so a +/-2
   delta can be pure attrition.
3. Compare arms that differ in ONE variable. An A/B on 2026-08-26 was confounded because
   the baseline was taken before a default was flipped, and it silently reproduced the
   other flag's numbers exactly.
4. Every experimental change goes in as a flag DEFAULT OFF. Measure, then decide. Ten
   hypotheses have been tested this way; nine were rejected.
5. After applying any flag, re-run with NO env vars and confirm 0 rows differ.
   "Applied" is not the same as "active".
6. Grounding in what the traders SAY/DO raises the prior. It does NOT replace the
   measurement. C-87 had 219 frames behind it and failed. "Seasonality must not originate
   a direction" was spec-grounded off the 2024-04-03 slide and changed 1 prediction in 479.
7. Before trusting a finding in a session note, check it against the code and git log.
   E-03's headline claim did not survive that check (see SESSION_2026-08-26.md section 6).
8. Parse timestamps. Comparing str(ts)[:10] against '2026-07-27' on "19 Jul 2026 22:11"
   compares "19 Jul 202" as a string and gave a confident, exactly-backwards answer.
9. Check WHICH CALL SITE your sample came from. `rank_zones` has three; two rank HTF
   zones and one ranks the LTF zones that actually trade. A whole session's conclusion
   ("level_on_top is dead on 100% of zones") was measured on a diagnostic path where
   that field is 0.00 by construction, and was exactly backwards (C-107).
10. When a finding shrinks every time the data improves, that is the finding. C-101 went
   +0.56R -> +0.40R -> +0.18R as a stale file, a price-scale bug and 18 dropped setups
   were fixed. Each summary looked reasonable; only per-case detail showed the errors.
11. Never treat a value eyeballed off a video still as a parameter. Read the settings
   dialog, or require agreement across model reads. "@SOXY" sat in CLAUDE.md as an
   unidentified symbol for months; across 4,446 Gemini frame reads that slot is "$DXY"
   1081 times and "@SOXY" 7 times, 5 of which another model read as "$DXY" on the same
   image. It was OCR noise.

HOW TO MEASURE ANYTHING
  cd "D:\Trading\Azalyst Bernd Skorupinski\Propfirm Trading Dashboard\goldtest"
  for i in 0 1 2 3 4 5; do
    MYFLAG=1 python -u run_goldtest.py --cases-file full_shard$i.yaml \
      --cot-snapshot read --ohlcv-snapshot read --output myarm$i.json > myarm$i.log 2>&1 &
  done
  python goldtest/verdict.py --arm 'myarm?.json'       # <- RUN THIS. All four gates.
  python ab_paired.py 'base?.json' 'myarm?.json'       # accuracy gate on its own
  python score_by_presenter.py 'myarm?.json'           # per-presenter split

  verdict.py exists because EVERY false positive in this project passed at least one
  honest-looking test. It runs four gates and reports the weakest:
    1 accuracy, paired McNemar on cases scored in BOTH arms (unpaired % is attrition-unsafe)
    2 did the emitted TRADE POPULATION change? if so, outcome deltas are not the flag (C-112)
    3 expectancy vs a DRIFT-MATCHED null, never the driftless 1/3 (C-111)
    4 does the zone entry beat the same call at market, paired? theirs wins this 8:1
      p=0.039; both of our arms LOSE it. A change that does not move gate 4 has not
      touched the defect that matters (C-119).
  All five arms tested to date return NOT supported. Exit code gates a commit.

  For EXPECTANCY IN R -- the metric that matters:
  python goldtest/expectancy.py --from-goldtest 'myarm?.json' --control --drift-null 40
     --control    re-runs each signal entered at MARKET, isolating the entry price.
     --drift-null REQUIRED whenever the sample is directionally lopsided (C-111).
                  The exact 1/3 null is only valid on a DRIFTLESS series. The C-110 arm
                  was 33 of 34 LONG in 2023: its drift-matched null is 41.0% / +0.23R,
                  not 33.3% / 0.00R. Quoting the wrong null understated the bar by 7.7
                  points all through the 2026-08-26 session.
     --pin-dir ohlcv_extended   resolves setups whose pin ends before the call date.

  For TRADE OUTCOMES rather than direction -- money, not agreement:
  python goldtest/replay_trades.py --from-goldtest 'c88guard?.json' --ab
  python run_forward_test.py --emit-signals sigs.json --ohlcv-snapshot fill  # generator
  python goldtest/replay_trades.py --signals-file sigs.json --ab             # evaluator
  Read the path_ambiguous column before quoting anything from it. A bar that touches
  both the breakeven-arm level and the entry decides the trade by intra-bar ordering
  that daily bars do not record, and update_positions always resolves it in favour of
  the breakeven because it checks that first.

  Snapshots are PINNED (CFTC revises history; Yahoo re-splices). Two unpinned runs of the
  same code scored 54.2% and 51.7% -- ~2.5pp of noise, larger than most effects tested.
  Six shards take ~50 min. Run them in the BACKGROUND, not foreground (2-min tool timeout).

A SECOND MODEL IS AVAILABLE -- USE IT FOR CROSS-CHECKS
  python "D:\Trading\Claude for Bernd\gemini\ask.py" -q "..." -f FILE -f FILE -o out.md
  D:\Trading\Claude for Bernd\gemini_cli.bat            (interactive Gemini CLI, same key)
  Gemini holds 1M tokens, so it can read CLAUDE.md (197KB) + CODE_FINDINGS.md (227KB)
  whole, where you would have to summarise -- and summarising is where claims lose their
  sample sizes. Use it to RE-DERIVE a finding from the primary file, not to restate one.
  Both keys are free-tier: the flash models work, every pro model returns 429. Context
  and the key/model table are in GEMINI.md.

MY PRIORITY THIS SESSION (do it, don't ask me first):

  READ THIS FIRST -- 2026-08-27 changed what this project is optimising.

  Direction agreement is NOT the edge. Measured on the traders' own drawn setups,
  same symbol, same date, same risk, only the entry price differing:

      their call, entered at the level they drew   52.0% win   +0.56R   (n=25)
      their call, entered at MARKET                22.2% win   -0.33R   (n=36)
      random walk, no drift, BY THEORY             33.3% win   +0.00R

  Their direction acted on at market is WORSE THAN RANDOM. The entry price is the
  whole edge. Our own Stage-1 sits at 52.7% vs always-long 50.4% -- the same coin
  flip -- so 20 phases of _bias_consensus tuning optimised a signal that pays
  nothing. DO NOT TUNE STAGE 1 FURTHER. See C-101.

  The defect, measured against 38 position tools the traders drew (C-103, C-104):
      our entry is a median 0.89R from theirs; 47% are >1R off, i.e. a different
      trade -- their target sits where we are still underwater.
      Cause: we enter at the zone EDGE, they enter at the MIDPOINT.
      Zone midpoint cuts the error to 0.31R and brings our risk from 2.71x theirs
      to 1.38x. Now wired as entry.prefer_midpoint_entry / BP_MIDPOINT_ENTRY=1,
      DEFAULT FALSE pending a bigger sample.

  What is left, in order:

  1. Grow the drawn-setup sample and RE-RUN the entry-error measurement. The
     Signals frame pass is at 2162/2509 (gemini/supervise_frames.py --corpus
     signals resumes through quota walls). Practical is 100% done: 29 setups, all
     in the LTF Entries / Location / Zoning sessions. Target ~60-80 setups, then
     re-measure midpoint vs edge. That decides whether the default flips.
  2. DEDUPE before any expectancy number (C-105). run_goldtest emits the same
     trade on consecutive scans -- 11 signals were 4 distinct trades, one BABA
     setup counted 8 times. Dedupe on (symbol, entry, stop) or one trade
     dominates the average.
  3. Copy the 2027 FOMC / ECB / BoE dates into BP_calendar.py from the banks'
     published schedules. C-90 made NFP and NYSE holidays rule-derived and
     validated them 24/24; bank dates cannot be derived and must not be guessed.
  4. Decide on CLAUDE.md / AGENTS.md. Auto-loaded in the code repo, still claim
     "production-safe" and "zero false positives". 16 lines listed in
     gemini/out/stale_claims_audit.md.
  5. Root-cause the NaN upstream. C-89 stops it reaching the trader (it was
     disabling stops silently) but not BP_data_fetcher producing one.

  DO NOT re-run: C-82 fair zone scan, the cycle override, BP_VAL_STRICT_THRESHOLDS,
  BP_VAL_FRAME_LENGTH, BP_BASKET_INHERIT. All measured on 479/510 cases: coin
  flips, inert, or significantly negative. Details in CODE_FINDINGS C-82/96/97/98.
```

---

## If you want to point it at one specific job instead, append one of these

> **Five of the six below were done on 2026-08-26 and are kept only as a record of what
> they turned into. Do not hand them out as work again.** Only *"Attack the
> indicator-silence problem"* is still unclaimed.
>
> | job | outcome |
> |---|---|
> | Build the trade-outcome replay harness | **DONE** — `goldtest/replay_trades.py`. E-03 measured: n=2, both path-ambiguous, direction one-way. See section 13 + "E-03 MEASURED" in `SESSION_2026-08-26.md`. |
> | Audit the goldtest labels (C-85) | **DONE** — see `C-85 RESOLVED` in `CODE_FINDINGS.md`. 2 of 3 disagreements favour the goldtest, and C-85's own NG=F verdict was wrong. 93 labels re-audited against the transcripts by `gemini/audit_goldtest_labels.py`. |
> | Attack the indicator-silence problem | **STILL OPEN — this is the one to take.** |
> | Fix the nan% price bug | **DONE** — C-89. It was not a display bug: a NaN price stops the stop firing. Guarded at source. Upstream cause in `BP_data_fetcher` still undiagnosed. |
> | C-82's zone-scan bug | **DONE and REJECTED** — coin flip on 479 cases (p=1.000 both groups), shorts go DOWN, Stage-2 goes 5 to 0. Do not re-run it. |
> | Refresh the economic calendar | **DONE except the bank dates** — C-90. NFP + NYSE holidays are rule-derived and validated 24/24. FOMC/ECB/BoE 2027 must be copied from the published schedules by a human. |


**Build the trade-outcome replay harness** (the biggest missing capability — nothing can
currently measure whether a change makes or loses money):
```
First: build a bar-by-bar replay that drives BP_paper_trader.PaperTrader over historical
signals, so trade OUTCOMES can be measured, not just direction. Neither existing harness
can do this: run_goldtest.py scores Stage-1 bias only, and run_forward_test.py never
instantiates PaperTrader -- it just checks whether T1 or the stop is hit first, with no
breakeven, no partials, no trailing. Use pinned OHLCV so it is deterministic. Then settle
E-03 with it: breakeven_at_half_target true vs false, reporting trades reaching +1R,
scratches, wins, losses, total R and total P&L.
```

**Audit the goldtest labels** (C-85 — still never checked, item 6 on the OPEN list):
```
First: audit gold_cases_oos.yaml and gold_cases_lectures.yaml against the source
transcripts, the way C-64 audited lecture_verdicts_partial.csv. They disagree with the
transcript-sourced labels on ~3 rows and have never been verified. Report the agreement
rate with sample size. Note the labelling convention is LOOSE (a conditional call counts):
an empirical test of the strict convention dropped agreement 85.1% -> 74.5%.
```

**Attack the indicator-silence problem** (the actual root cause of the flat Stage-1 score):
```
First: Valuation reads neutral on 64% of cases and COT on 73%, and both are neutral on 45%.
Establish WHY before changing any threshold -- is it genuinely neutral data, a threshold
that is too wide, a missing CFTC code, or a data gap? Break the silence rate down by asset
class and by year, and show me which of those four causes dominates. Do not tune a
threshold until that is answered.
```

**Fix the nan% price bug** (open since 2026-08-23, still un-root-caused):
```
First: pending rows print "(nan% away)" -- seen on CL=F and ^GDAXI in the Discord log.
Find where the nan enters (fetch, proxy fallback, or the pct computation in
run_scanner.py) and fix it at source. A nan silently defeats every distance comparison,
including the E-05 drift cancel added on 2026-08-26, because every nan comparison is False.
```

**C-82's zone-scan bug** (item 8, real and still unfixed):
```
First: fix C-82's zone-scan bug. It is confirmed real. It is NOT expected to raise the
score on its own -- measure it anyway and report the delta with sample size.
```

**Refresh the economic calendar** (fires a WARNING on every run right now):
```
First: BP_calendar.py's hardcoded high-impact events and US federal holidays end in 2026,
which is the current year -- every goldtest run now logs "EconomicCalendar: hardcoded
events end in 2026". After year-end the event-blackout logic silently becomes a no-op and
the system will trade through NFP and FOMC. Refresh _HIGH_IMPACT_* and
_US_FEDERAL_HOLIDAYS_* through 2027.
```
