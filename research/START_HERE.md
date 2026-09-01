# START HERE — Bernd trading-system audit, resume point
Last updated: 2026-08-26

> ## >>> To continue in a NEW CHAT: paste the block from `PASTE_THIS_TO_CLAUDE.md`. <<<
> That file is the single, current continuation prompt. Everything else below is background.
>
> Newest session notes, in order:
>   `SESSION_2026-08-26.md`  <- current state, OPEN list in section 11
>   `SESSION_2026-08-24.md`  <- execution-layer forensics (E-01..E-06)
>   `SESSION_2026-08-23.md`
>
> **Two things on this page were true in August and are now settled or wrong:**
>
> 1. "some Funded Trader Signals sessions may not be Bernd at all" — SETTLED. The whole
>    Signals series is instructors: 2023 = Jan Skorupinski, 2024 = Clemens Winkler.
>    Weekly Outlook is Bernd (verified: Zoom name label, CW10-2024 frame_003120).
>    Practical Application = Chris Dietenberger. See `gemini/presenter_map.json`.
>    User decision 2026-08-26: score against all four POOLED.
> 2. "OCR was tried and rejected" — the Gemini frame pipeline in `gemini/` IS effectively
>    OCR-with-a-VLM, and it is useful, but only with agreement across reads. A single read
>    is not evidence: the same legend token reads as `$DXY`, `@SDXY`, `$OXY`, `@SOXY`.
>
> Folder map:
>   `PASTE_THIS_TO_CLAUDE.md`     — THE continuation prompt (start here)
>   `SESSION_2026-08-*.md`        — session notes, newest first
>   `audit/CODE_FINDINGS.md`      — every finding C-01..C-87, with evidence
>   `audit/validation/`           — end-to-end harness + results
>   `audit/replay/`               — numeric verification scripts
>   `audit/tv_fixtures/`          — TradingView fixtures + CORRECTED Pine files
>   `audit/per_chapter/`          — 52 frame-by-frame lecture audits
>   `gemini/`                     — Gemini frame-reading pipeline + `presenter_map.json`
>   `analysis_2026-08-23/`        — Discord log forensics (`parse_discord_log.py`)
>   `python_snapshot/`            — copy of the edited .py files as of 2026-08-19
> The live working copies remain at `D:\Trading\Azalyst Bernd Skorupinski\`.
>
> The measurement harness now lives with the code, not here:
>   `Propfirm Trading Dashboard\goldtest\PRESENTER_AND_HONEST_SCORE.md`  — the honest scoreline
>   `Propfirm Trading Dashboard\goldtest\ab_paired.py`                   — paired A/B + McNemar
>   `Propfirm Trading Dashboard\goldtest\score_by_presenter.py`          — per-presenter split

This is the designated folder for all Claude work on Bernd's indicator audit / trading system.
If you're opening a new chat / lost track of where things are: paste the path to THIS file
(`D:\Trading\Claude for Bernd\START_HERE.md`) to Claude first. Everything below is on disk,
nothing lives only in chat history.

## What this project is
Auditing Bernd Skorupinski's TradeStation screen-recording videos (Funded Trader Weekly Outlook
+ OTC course lessons) frame-by-frame using actual VISION reads to find the REAL indicator parameters
he uses, then checking the Python trading system (`Propfirm Trading Dashboard`) against them.
Goal: fix any real discrepancies before the system trades a live prop-firm account.

## Where everything actually lives
- **Live working folder** (queue, launched list, all chapter reports):
  `D:\Trading\Azalyst Bernd Skorupinski\_audit_ftw_vision\`
  - `PROGRESS.md` — the full state snapshot, policies, and rules. **Read this next.**
  - `CODE_FINDINGS.md` — every finding (C-01 through C-87), with evidence, and what was
    applied/withdrawn/still-open. This is the technical record.
  - `queue.txt` — Weekly Outlook chapters not yet audited.
  - `launched.txt` — chapters that have been sent to a vision agent.
  - `per_chapter/*.md` — one file per completed chapter audit (52 done; the mirror in
    `audit/per_chapter/` here has all 52).
- **The Python system being fixed**: `D:\Trading\Azalyst Bernd Skorupinski\Propfirm Trading Dashboard\`
  - Files touched so far: `BP_indicators.py`, `BP_rules_engine.py`, `run_scanner.py`.
  - It's a git repo — every change so far is a plain edit to a clean file, fully revertible with
    `git diff` / `git checkout --`.
- **Canonical PineScript sources** (ground truth for indicator formulas):
  `D:\Trading\Bernd_Skorupinski Campus Blueprint OTC\OTC Tradingview Indicator Pack\`
  plus `D:\Trading\Azalyst Bernd Skorupinski\pinescript\COT V2 120-20.txt`

## Status as of 2026-08-19 — FROZEN SNAPSHOT, the counts below are stale
> Checked against disk 2026-08-26: `queue.txt` is **empty** (the vision backlog is 100%
> complete, 52 chapter reports, not 36 with 9 left), and `CODE_FINDINGS.md` runs to
> **C-87**, not C-37. No vision agents are running. The rest of this section is kept
> because the policy and model-split notes in it still hold.

- 36 chapter reports done (33 Weekly Outlook + 3 OTC Module 3 lessons); findings logged
  through **C-37** in CODE_FINDINGS.md.
- **9 chapters left in queue.txt**; 5 vision agents still running as of this save
  (CW21, CW16, CW24, CW17, CW19 — all 2023). If a report file is missing for a chapter
  listed in launched.txt, relaunch that chapter.
- **Policy update 2026-08-19: user authorized PARALLEL agent batches** ("run more agents for
  completing chaptr n then finding issues for fixing") — the earlier one-at-a-time rule is
  lifted. Wave 1 (9 chapters, equity-era + multi-market priority) launched alongside CW10-2023;
  18 chapters remain in queue.txt for wave 2+. Sonnet still reads frames, Opus still does all
  code analysis/fixes — that split is unchanged.
- **CW05 FX Edition DONE — the forex COT question is resolved and the fix is applied (C-22).**
- Model split: **Sonnet reads frames** (cheap, mechanical, high-volume). **Opus does the code
  analysis and fixes** (the main/default loop). Do not swap this.

### Applied to the Python (verified, not reverted)
1. `BP_indicators.py` `Valuation.calculate` — fixed a real ROC misalignment bug (reference now
   reindexed onto the symbol's own index with forward-fill before computing both ROCs, matching
   how Pine's `security()` actually works). Only affects crypto; every same-calendar symbol
   (futures/equities/forex/metals) is regression-verified bit-identical.
2. `BP_rules_engine.py` — equities Valuation `Length`: **30 → 13**.
3. `run_scanner.py` — equities Valuation references: **Bonds+Gold → Bonds only**.
4. `BP_indicators.py` `get_bias` — **forex COT group: Non-Commercials → RETAIL (contrarian)**
   (CODE_FINDINGS C-22). The decisive CW05 FX Edition re-read proved the code's own citation
   wrong: "retail/retailers" is the only group he names on every FX pair, contrarian direction
   confirmed twice (CW05 DXY + CW08 Euro), and 5x more since. Momentum-trigger primary_col
   updated too. `detect_divergence` deliberately left on non-commercials (separate evidence).
5. **CRUDE OIL split into its own `crude_oil` class → RETAIL contrarian** (C-44). Three live
   chapters (CW47/CW08/CW11) name retail on crude, contrarian, none name commercials. Scoped to
   CL=F only. Routing added in BOTH mirrored sites + `get_bias` + 156w list + momentum col.
6. **C-48 CRITICAL — contrarian 156w strength was INVERTED** (`get_bias`): it awarded 'strong'
   exactly when the 26w and 156w windows CONTRADICTED each other. Affected every forex pair and
   crude (i.e. our own fixes 4 and 5 rode on top of it). Now tests group position, not bias.
7. **C-49 CRITICAL — USD-base pairs (USDJPY/USDCHF/USDCAD) got a 180-degree inverted COT** from
   the opposing-currency cross-check; could open a long on evidence that says short. Fixed.
8. **C-50 — scanner dashboard charted a different trader group than the engine traded** (symbol
   never passed into routing; for CL=F literally the opposite line). Fixed.
9. **C-51 CRITICAL — ETF proxy price could leak into the TRADABLE path via a cache key that
   omitted `allow_proxy`** → entry/stop/lots computed on GLD (~$310) instead of gold (~$3,400),
   roughly 10x position size on a real ticket. Fixed; proxy data is now quarantined.
10. `BP_rules_engine.py` — implemented the long-deferred **timeframe-aware `cycle_per_symbol`**
   (GAP-14/GAP-15, C-46): entries may now be `{daily: 30, weekly: 13}`. Behaviour-neutral until
   an entry is converted — see the OPEN DECISION below.

All verified by `_audit_ftw_vision/replay/test_c44_crude_retail.py`,
`test_c46_timeframe_cycle.py` and `test_c48_c51_code_fixes.py` (all pass), plus end-to-end
scans of CL=F and USDCHF=X.

### Explicitly withdrawn (do NOT redo these)
- COT index formula "fix" — looked wrong from live-session evidence alone, but an OTC teaching
  lesson proved the code's `140x-20` formula is correct (dialog literally has `Upper Bound
  Level=120`, and the plotted line was read at -20/120/126.21 — impossible on a 0-100 scale).
- ZigZag % removal — it's absent from every Weekly Outlook chapter, but that's because it lives
  in the Practical Application / OTC corpus, not because it's unused.

### Open, unresolved, needs more evidence before touching code
- ~~Forex COT trader group~~ — **RESOLVED 2026-08-19 (C-22, fix applied)**: CW05 FX Edition
  re-read settled it — RETAIL, contrarian, on every FX pair. See "Applied" item 4 above.
  Corroborated 4x since (CW03, CW01, CW49 Swiss Franc, CW08 Euro).
- ~~WeeklyLookBack 20-vs-26~~ — **RESOLVED (C-33)**: CW40 Precious Metals holds a Format Study
  dialog reading `WeeksLookBack = 26`, with Bernd on tape: "I would say 20 look back. It's 26
  look back is 26. Yes." Our 26 default is correct. The lone `20` on a crude chart was a stale
  per-chart leftover.
- ~~Valuation Length 30 sightings~~ — **RESOLVED (C-31)**: 30 is his deliberate LONG-TERM
  toggle, not a changed default. Proof on tape (CW05 Soybeans 13:34): "we can change between
  long term valuation and short term valuation... Now I'm checking long term valuation." The
  code comment at `BP_rules_engine.py:170-192` had already reasoned this out correctly.
- **`equity_indices` Length 10-vs-13 — QUANTIFIED (C-37) then largely defused (C-38). Kept at
  10; risk now LOW.** Measured impact is real (flips the index valuation bias on ~30% of bars,
  opposite readings on 1.3-3.1% — script `_audit_ftw_vision/replay/valuation_length_sensitivity.py`),
  BUT C-38 found he ran **two different valuation tools by era**: a single-ref
  `Campus Valuation Index` (bonds only, Length 13 per an Apr-2023 @YM dialog) in 2023, and the
  3-ref `_CampusValuationTool_V2` from Oct-2023 on. Our code models the 3-REF tool, and every
  2024 reading of that tool is **10**, un-truncated, twice. Several "13" sightings belong to the
  other tool entirely. Still worth grabbing any 2024-25 index dialog if one appears, but this is
  no longer the audit's main risk.
- **OPEN DECISION #1 (C-53, HIGH) — Valuation runs on the WRONG TIMEFRAME.** He reads Valuation
  on **DAILY** charts (corpus tally ~95 daily vs 6 weekly; the 2025 TradingView lesson uses 1D
  for both AUDUSD and AAPL). Our scanner computes it from the **weekly** HTF series, and fetches
  the 3 reference series weekly too — so "ROC Length 10" means 10 WEEKS for us and 10 DAYS for
  him. Measured: 2 of 5 symbols disagree on the latest bar, incl. crude flipping bullish->bearish
  (`replay/valuation_daily_vs_weekly.py`). Fix touches the fundamentals pipeline + ref fetching,
  so it is NOT applied. **Resolve this before C-46** — the config's "30=daily / 13=weekly"
  reasoning assumed a daily Valuation that doesn't exist today.
- ~~COT formula 0-100 vs -20..120~~ — **RESOLVED AND FIXED (C-57).** Proof chain: (1) his
  TradingView COT feed IS the CFTC futures-only series — 8/8 raw net values off his chart match
  to 0.01K at a constant -6d bar/report offset; (2) so Python-from-CFTC == Pine-on-his-chart;
  (3) his displayed 34.43 is reproduced EXACTLY by the 0-100 form (ours now gives 34.43, diff
  0.002), while the old 140x-20 gives 28.21 and matches nothing in 40 years. The scale is now a
  parameter (`lower_bound`/`upper_bound`, default 0/100) applied to ALL four scale sites incl.
  the 156w and all-time overlays. Measured effect: the old form made **26.9% MORE extreme calls**
  than he does. Legacy behaviour: `COTIndex(lower_bound=-20, upper_bound=120)`.
- **TradingView housekeeping**: the user's previously UNSAVED "18BAR" Pine draft was saved to
  My Scripts as *"The 18-Bar Trend System (Rosputnia / Williams)"* before any editing (it is now
  safer than before, and still on the chart). A scratch "AUDIT COT" indicator remains on that
  chart and should be removed by hand.
- **OPEN DECISION #3 (C-46)** — `cycle_per_symbol` sets **30 for all ~40 stocks**,
  which silently overrides the class default of 13, so the C-14 fix is inert in production.
  Measured impact of 30-vs-13 on stocks: bias differs on ~40% of bars, **OPPOSITE direction on
  15-19%**. Evidence is genuinely split (13: OTC slide + on-camera AAPL edit + MSFT dialog +
  CW18/CW21/CW24/CW25; 30: CW23 shows all 11 stocks at 30, plus the cheatsheet "30 & 10-d
  cycles"). BUT Valuation runs on **HTF = weekly** bars, and the config's own comment calls 30
  the *daily* value and 13 the *weekly* one. Mechanism to fix it is now in place; recommended
  action is to convert the stock entries to `{daily: 30, weekly: 13}`. **Not done unilaterally —
  it changes live trading behaviour.**
- **C-52 lists 12 more reviewer findings not actioned** (seasonality dead on ~21 forex pairs due
  to an absolute price threshold; valuation refs with no date overlap degenerating silently;
  `at_zone` hard-coded True; data-outage-reads-as-neutral; position size computed before zone
  refinement; partial current bar not dropped; 6 symbols missing CFTC codes incl. OJ=F;
  intraday strategy structurally broken; paper-trader state can self-wipe). See CODE_FINDINGS.
- Sugar (SB=F) / OJ (OJ=F) are the only symbols left on the Non-Commercials soft-commodity path
  (code calls the corpus "silent" on them); CW01 hinted Sugar may be Commercials like the other
  ags. Watch for a spoken group name on a Sugar/OJ frame (C-34).
- ~~Seasonality standalone check~~ — CLOSED 2026-08-19 (CODE_FINDINGS C-18): traced every
  consensus path; a signal always requires a qualified zone matching the consensus, so
  seasonality can never fire a trade alone. Confirm-only requirement already satisfied.

## NUMERIC REPLAY VALIDATION — ✅ COMPLETE (2026-08-19). Results (full detail in CODE_FINDINGS
R-01/R-02/R-03 + scripts in `_audit_ftw_vision/replay/` + `replay_fixtures.json`):
- **Valuation: VALIDATED** — 9/9 date-exact AUDUSD fixtures match our Python (6 strong, 0 mismatch).
- **COT: VALIDATED** — our formula is verbatim the canonical V2 Pine; dialog inputs
  (26/156/FuturesOnly/120/80/50/20/-20) all match; the scary "126.21 > 120" reading was traced to
  a reference-line/drawing readout, not a series value — anomaly closed, no change.
- **Seasonality: VALIDATED (shape)** — our curve's local Feb top lands 0-1 days from his marked
  dates in 2021/2022/2023, with the same post-top decline and rising-January projection. Exact
  index units not comparable (his "v4" script source unavailable).
- **ZigZag: not testable from these lessons** — no numeric readouts; validate later from the
  Practical Application corpus.
Bottom line: after the 3 applied fixes, **all four indicators now check out against the lecture
evidence at every level we can measure.**

## Chapter-queue status at this save — STALE, this block is older than the one above
> Two things here are dead: the queue is **empty** (63/63 Weekly Outlook chapters read, 52
> reports on disk), and the forex COT-group question below is **RESOLVED** — C-22, retail
> contrarian, applied. See item 4 in "Applied to the Python" above, which is in this same
> file and says the opposite.

19 chapter reports in `per_chapter/` (16 Weekly Outlook + 3 OTC lessons); 33 chapters left in
`queue.txt`. The Weekly Outlook queue continues one-at-a-time (Sonnet reads frames, Opus does
code work) after / alongside the replay-validation task. CW05 - FX Edition remains the decisive
chapter for the unresolved forex COT-group question (now a 3-way conflict — see CODE_FINDINGS
C-15/C-17; latest data point: NG explicitly retail-fade in CW07-2024).
