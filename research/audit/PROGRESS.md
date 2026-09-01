# FTW Vision Audit — Resume Point
Last updated: 2026-08-18. EVERYTHING BELOW IS SAVED TO DISK — this file, `CODE_FINDINGS.md`,
`queue.txt`, `launched.txt`, and every file in `per_chapter/` are plain files on D:\, not chat
state. **A new chat / new session can pick this up with zero loss** — just point it at this file
first. Nothing important lives only in conversation history.

**Designated top-level folder for all Claude work on this project:**
`D:\Trading\Claude for Bernd\START_HERE.md` — a short pointer/summary doc that links back here.
If starting a brand new chat, read that file first; it's easier to find than this one.

## Model split (user requested)
- **Frame reading → Sonnet.** All per-chapter vision audit agents are launched with
  `model: sonnet`. It's high-volume mechanical vision extraction; no need for a bigger model.
- **Code fixing → Opus (main loop).** The actual diffing of findings against CODE_BASELINE.md
  and any resulting changes to the Python trading system stay with the main/Opus loop. Do NOT
  delegate the code-fix reasoning to the cheap frame-reading agents.

## NEWEST STATE (2026-08-18, later save — supersedes counts below)
19 reports done (16 Weekly Outlook: +CW03-2023, +CW11-2024-NoIndices, +CW07-2024-AllMarkets since
the snapshot below; 3 OTC lessons). 33 queued. **Current main task = NUMERIC REPLAY VALIDATION of
the 4 indicators against date-tagged frame readouts — full plan in CODE_FINDINGS.md ("NEW MAIN
TASK") and in `D:\Trading\Claude for Bernd\START_HERE.md`.** Fixtures not yet extracted.

## STATE SNAPSHOT (keep this current) — verified against disk 2026-08-18
- **17 chapter reports done** in `per_chapter/` (14 Weekly Outlook + 3 OTC Module 3 lessons):
  CW05-2023, CW12-2023, CW18-2023, CW20-2023, CW40-2023-PM, CW41-2023, CW42-2023-PM,
  CW43-2023-EquityStocks, CW02-2024-LIVE, CW04-2024, CW07-2024-Corn, CW09-2024-AllMarkets,
  MARCH-2024-roadmap, CW11-2024-AllMarketsNoIndices, + OTC-M3-L2-COT, OTC-M3-L3-Valuation,
  OTC-M3-L4-Seasonality.
- **35 Weekly Outlook chapters still queued** in `queue.txt` (63 total, 14 Weekly Outlook done
  + 3 OTC = 17 reports, so 63-14=49... reconcile: some launched chapters may still be in-flight
  from the very first parallel batch and never reported back — check `launched.txt` (28 entries)
  against `per_chapter/` for any Weekly Outlook chapter that's launched but has no report; those
  are either still running or died silently and need a fresh launch, not a resume).
- Main task = work through `queue.txt` one at a time (per the one-by-one policy set mid-session).
- **Code changes APPLIED so far** (all documented with full evidence in `CODE_FINDINGS.md`):
  1. `BP_indicators.py` `Valuation.calculate` — reference now reindexed onto the symbol index with
     ffill before taking ROCs (Pine `security()` parity). Regression-verified: same-calendar
     symbols bit-identical (`max|new-old|=0.0`), only crypto changes.
  2. `BP_rules_engine.py` `VALUATION_LENGTH_BY_CLASS['equities']` — 30 -> **13**.
  3. `run_scanner.py` `VALUATION_REFS['equities']` — `["ZB=F","GC=F"]` -> **`["ZB=F"]`** (bonds only).
  All three verified importing/loading correctly after the edit. None reverted.
- **Withdrawn / do NOT act on**: the COT `140x-20` formula (C-07) — OTC lesson proved the code is
  CORRECT (dialog shows `Upper Bound Level=120`, crosshair reads -20/120/126.21 — impossible on a
  0-100 scale); and ZigZag removal (C-03) — wrong corpus, it lives in Practical Application/OTC,
  not Weekly Outlook.
- **Open, needs more evidence — DO NOT act on these without more chapters**:
  - **C-15 forex COT trader group** — highest blast radius open item, would invert every forex
    signal if changed. Now a 3-way conflict, not 2-way: code says Non-Commercials, OTC teaching
    lesson said Commercials, CW11 (live) showed RETAIL explicitly on AUD/CHF and on Crude Oil.
    Working theory: he may read whichever group is AT AN EXTREME that week rather than having one
    fixed "primary" group — if true this is a structural fix, not a simple swap. Needs several
    more live FX chapters.
  - `equity_indices` Length 10-vs-13 (dated split: 2023 chapters show 13, 2024 chapters show 10 —
    could be genuine evolution over time, needs a recent-era index dialog to confirm).
  - Whether seasonality can trigger a signal ALONE in the Python — OTC lesson says it should be
    confirm-only ("not a standalone tool"); this needs a CODE investigation (read
    `BP_rules_engine.py` around the seasonality bias consumption), not more frames.
- **TARGET CHAPTER for C-15**: `2024/27.01.2024 - Funded Trader Weekly Outlook CW05 - FX Edition`
  (was ~queue position 24 as of last count — re-check `queue.txt` for current position after more
  chapters have been dequeued). `run_scanner.py:186` cites this exact session as its own evidence
  for the forex 3-ref config, so it is the single most decisive remaining chapter in the audit.

## DETOUR COMPLETE (user-directed) — OTC Module 3 indicator lessons
Before finishing the Weekly Outlook queue, the user directed a targeted verification pass at the
OTC course's three indicator lessons, because TEACHING sessions open settings dialogs and state
parameters aloud — exactly the evidence the live sessions keep truncating. Launched in parallel
(3 agents, a deliberate exception to the one-by-one policy since they answer disjoint questions):

  - `Lesson 3. Valuation` (94 frames) -> `per_chapter/OTC-M3-L3_Valuation.md`
    settles: stock `Length` (10 vs 13 vs code's 30), reference legs on stocks (Gold on/off)
  - `Lesson 2. Commitment of Traders (COT)` (234 frames) -> `per_chapter/OTC-M3-L2_COT.md`
    settles: C-07 COT scale (0..100 vs -20..120), WeeksLookBack per class, trader-group routing
  - `Lesson 4. Seasonality` (68 frames) -> `per_chapter/OTC-M3-L4_Seasonality.md`
    settles: AverageYears / multi-lookback design, projection mechanics

Base path:
`D:\Trading\Output\Bernd_Skorupinski Campus Blueprint OTC\Bernd Skorupinski - Campus Blueprint - OTC - 2025 Course\5. Module 3 Market Analysis and Forecasting Fundamentals`

**NOTE — different corpus.** These are OTC course lessons, not Weekly Outlook. Corpus matters (see
C-03: ZigZag is absent from all 14 Weekly Outlooks purely because it lives in the teaching corpora).
Where OTC and Weekly Outlook disagree, record BOTH and decide deliberately which the live scanner
should model — do not let the most recent audit silently win.

**After these three land: resume the Weekly Outlook queue, one chapter at a time, from `queue.txt`
(36 remaining).** That remains the main task.

## Processing policy (changed mid-session — user requested)
From this point on: chapters are launched ONE AT A TIME, sequentially. Launch → wait for that
agent's completion notification → log/diff its findings → only then launch the next chapter
from `queue.txt`. Do NOT launch a new batch/wave in parallel. This applies once the pre-existing
13-14 in-flight chapters from the earlier parallel batch have all landed (those are left to
finish on their own, not killed — but nothing new gets added on top of them).

## How to resume (read this first, any new session)
1. This file + `queue.txt` + `launched.txt` + `per_chapter/*.md` are the full state. Nothing
   lives only in chat/session memory — everything needed to continue is on disk here.
2. Read `EXTRACTION_SPEC.md` (the exact instructions every vision agent must follow — vision
   reads only, never OCR, never fabricate a number) and `CODE_BASELINE.md` (what to diff
   findings against) before launching anything.
3. Cross-check `launched.txt` (16 chapters sent out) against `per_chapter/` (chapters actually
   finished) — see status table below. Anything launched but with NO matching per_chapter file
   is either still running or died without a notification; re-launch it using the same prompt
   pattern as the CW02-2024-LIVE retry (see chat history / EXTRACTION_SPEC.md for the template).
4. Do NOT start `Practical Application` or `Funded Trader Signals` folders until all 63
   Weekly Outlook chapters have a per_chapter file. User was explicit about this ordering.
5. Do NOT launch the remaining 47 queued chapters (still untouched in `queue.txt`) until the
   current batch of 16 confirms clean (this was the plan before the reset — re-confirm with
   user if picking this up much later, but the ordering rule in #4 always holds).

## Status as of last check
- Total Weekly Outlook chapters: 63 (47× 2023, 16× 2024)
- Completed (file exists in per_chapter/): 2
  - `2024-03-03_MARCH_roadmap_equity_indices.md` (158 frames total, 91 read, high-confidence findings)
  - `2024-01-06_CW02_LIVE.md` (156/156 frames read, 12 findings, no blockers — retry succeeded).
    Notable: title-bar confirms `_CampusValuationTool_V2` roc length = **13** (not 10) across
    many symbols/frames — bears on open question Q5 in CODE_BASELINE.md. Also flags 2 unresolved
    internal discrepancies (AverageYears 5 vs 10 on Campus Algo Forecast; single-panel vs
    paired-panel CampusValuationTool_V2 rendering) — not silently resolved, needs corroboration
    across more chapters before treated as settled.
- Launched but NOT yet confirmed complete (13): re-check per_chapter/ for these before re-launching
  anything — a file may have landed since this was written.
  - 2024/02.03.2024 - Funded Trader Weekly Outlook CW10 - All markets wo Indices
  - 2023/28.05.2023 - LIVE - PREP THE MONTH AHEAD
  - 2023/26.02.2023 - Funded Trader Weekly Outlook CW09
  - 2023/01.01.2023 - Prep the week ahead CW01
  - 2023/08.01.2023 - Funded Trader Weekly Outlook CW02
  - 2023/12.02.2023 - Funded Trader Weekly Outlook CW07
  - 2023/22.01.2023 - Funded Trader Weekly Outlook CW04
  - 2023/03.09.2023 - Funded Trader Weekly Outlook CW36
  - 2023/09.09.2023 - Funded Trader Weekly Outlook CW37
  - 2023/23.09.2023 - Funded Trader Weekly Outlook CW39
  - 2023/16.09.2023 - Funded Trader Weekly Outlook CW38
  - 2023/11.03.2023 - Funded Trader Weekly Outlook CW11
  - 2023/18.02.2023 - Funded Trader Weekly Outlook CW08
  - 2024/10.03.2024 - Funded Trader Weekly Outlook CW11 - Equity Indices and Stocks
- 2023-03-18 CW12: DONE. 119/119 frames, 21 findings, no blockers.
  `per_chapter/2023-03-18_CW12.md`. Notable: Campus Valuation Index Length **live-edited
  30→13 on screen** for @US — SECOND chapter now pointing at 13 (not code's default 10),
  corroborating the CW02-2024-LIVE finding. Also: ZigZag %, COT Index, COT Report all ABSENT
  from this chapter entirely (anomaly, flagged). Multi-symbol CampusValuationTool_V2 variant
  ("@US","@GC","$DXY") only appears on @BTC here — single-symbol Valuation Index (ref="@US"
  only) is what's used on everything else (@US, @YM, @RTY, 10 individual equities).
- 2023-05-13 CW20: FAILED — not a content/legibility issue, hit the session usage limit
  ("You've hit your session limit · resets 6:40pm Asia/Kolkata"). Needs a clean retry after
  reset, using the same prompt as CW12/CW02-2024-LIVE (see chat history near this point, or
  reconstruct from EXTRACTION_SPEC.md — nothing indicator-specific was learned from this attempt,
  it never got frames read). It IS still in `launched.txt` but has no per_chapter file — treat
  as "needs retry", not "done".
- Not yet started: 45 chapters in `queue.txt` (after CW12 and CW20 removed from queue; CW20
  needs to go back in mentally as "retry" since it never completed)

- 2023-05-13 CW20: DONE (retry succeeded). 112/113 frames, 21 findings, no blockers.
  `per_chapter/2023-05-13_CW20.md`. Notable:
  - Valuation Length=13 confirmed a THIRD time (now CW02-2024-LIVE, CW12-2023, CW20-2023 all
    agree on 13, not code's default 10) — this is looking increasingly settled, not noise.
  - NEW nuance: Valuation `ReferenceSymbol` is NOT fixed — switches between `"@dx"` (only on
    @NQ chart) and `"@us"`/`"@US"` (everywhere else in this chapter). Prior chapters only ever
    showed "@US". Worth watching whether "@dx"-as-ref recurs on other index/NQ-adjacent charts.
  - Campus Algo Forecast `AverageYears` varies by instrument class: 4 (BTC), 15→10 live-edited
    (NQ), 10 (RTY/YM/SF/USDCHF), 5 (most stocks) — NOT a single global default. One unresolved
    NFLX conflict (dialog showed 5 but was Cancelled; persisted chart value is 10) — flagged,
    not guessed.
  - Campus COT Index lookback/length param stayed inside TradeStation's own "..." truncation in
    EVERY frame this chapter — genuinely never confirmed, correctly left unconfirmed.
  - ZigZag % absent AGAIN — 4th chapter in a row with zero ZigZag sightings. Pattern building:
    may not actually be used in Weekly Outlook sessions at all (contra code baseline assumption
    that it's a live indicator). Needs more chapters before treated as settled, but stop
    expecting it to show up.

- 2023-10-14 CW42 Precious Metals: DONE. 86/110 frames, 10 findings, no blockers.
  `per_chapter/2023-10-14_CW42_PreciousMetals.md`. HEADLINE finding, needs careful handling:
  - Gold-standard Format Study dialog (2x) for **`_CampusValuationTool_V2`** (the MULTI-ref
    indicator: ReferenceSymbol1="@US", ReferenceSymbol2="@GC", ReferenceSymbol3="$DXY" — this is
    the one that matches the code's actual `CampusValuationTool_V2` by name/ref-count) confirms
    **Length = 10**, thresholds ±75. This is the code's assumed default — MATCHES, not a bug.
  - This is DIFFERENT from the `Campus Valuation Index` (single-ref, only `ReferenceSymbol`)
    seen in CW02-2024-LIVE/CW12-2023/CW20-2023 with Length=13. **Working theory: these are two
    distinct indicators, not one indicator read inconsistently** — "Campus Valuation Index"
    (single-ref, Length=13) may not correspond to anything in the current Python code at all,
    while "_CampusValuationTool_V2" (multi-ref, Length=10) is the one the code baseline actually
    models and it checks out. DO NOT collapse these into one "Length is either 10 or 13"
    conclusion — track them as two separate indicator names going forward, confirm/refute the
    theory as more chapters land.
  - `ReferenceSymbol2` stays hardcoded to `"@GC"` even when the indicator is applied to Silver,
    Platinum, Palladium charts — Gold is used as a fixed benchmark leg regardless of the chart's
    own symbol. Worth checking against `run_scanner.py` VALUATION_REFS — does the code do this
    per-symbol, or does it also hardcode GC as a ref leg for other metals?
  - ZigZag % absent AGAIN — now 5 of 5 chapters with zero sightings. Very likely genuinely not
    used live in these sessions, whatever the code baseline assumes.
  - `Campus Smart Money Index` / `Campus Smart Money RAW` — confirmed as two distinct indicators
    (bounded 0-120 w/ 80/20 thresholds vs unbounded), neither had a settings dialog opened, so
    lookback lengths remain genuinely unconfirmed (correctly left as such, not guessed).

- 2024-01-20 CW04: DONE. 107/107 frames, 7 findings, no blockers (no Format Study dialog opened
  this chapter, so most params are title-bar-only / lower confidence, correctly flagged as such).
  `per_chapter/2024-01-20_CW04.md`. Notable:
  - ZigZag % absent AGAIN — now **6 of 6 chapters, zero sightings**. No longer just a pattern,
    treat as effectively confirmed: ZigZag is very likely not live-used in these sessions at all,
    contra whatever the code baseline assumes about it being active.
  - Only the multi-ref V2-family Valuation tool appeared this chapter (no single-ref "Campus
    Valuation Index" sighting) — on futures/index (Corn, Palladium, Gold, AUD, NASDAQ, Soybeans):
    `_CampusValuationTool_V2`, all 3 refs True, roc_length=10 (MATCHES CW42 and code default).
  - **Real discrepancy vs CODE_BASELINE.md**: on stock charts (WMT, likely BABA), the
    non-underscore `CampusValuationTool_V2` shows ref2 (@GC, Gold) DISABLED — `True,False,...` —
    not DXY. CODE_BASELINE.md's Q1 assumes it's DXY that's off for equities; this suggests it
    might be Gold instead, at least for some stocks. Needs corroboration from more equity-heavy
    chapters before changing code, but this is a concrete character-read finding, not a guess.
  - Campus Algo Forecast: `(10,100,False,False,False)` on futures/index vs `(5,100,...)` on BABA
    stock — consistent with CW42's finding that AverageYears is lower for individual stocks.
  - Two indicators used constantly but not in the original tracked list: "Campus Smart Money
    Index" and "Campus Smart Money RAW" — should be added as first-class tracked indicators
    going forward (already showed up in CW42 too).
  - COT title reads **"COT Net Position ( 1 )"** here, not "COT Index (26, 80, 20)" as assumed —
    no Format Study dialog opened to confirm if this is a genuinely different study or just a
    different default render. Open question, not resolved.

## STOP condition — RESOLVED
Session usage limit reset. Continuing one-by-one through `queue.txt`.

## Rules that must NOT be relaxed on resume
- Vision reads only. No OCR. No inventing/guessing a parameter value — mark `confidence: low`
  instead. This is the entire point of the audit (prior OCR pass in `_python_vision_output/`
  garbled exactly the characters that matter and must not be trusted or reused).
- Every finding gets diffed against CODE_BASELINE.md, not just collected.
- This feeds a live prop-firm trading system — no partial/rushed conclusions. Report the full
  discrepancy list only once all 63 Weekly Outlook chapters are done.
