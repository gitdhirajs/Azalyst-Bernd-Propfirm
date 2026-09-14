# Lecture reference: scope and known contradictions

Companion to `D:\Trading\New folder\blueprint-master-reference.html` (the DeepSeek-rebuilt
"Source-Verified Reference"). That folder is read-only, so the scope paragraph and the
corrections live here. Written 2026-09-14 during the lecture-code reconciliation
(`RECONCILE_REPORT_2026-09-14.md`).

Every lecture citation below was re-checked against the OTC 2025 course frames:
`D:\Trading\Output\Bernd_Skorupinski Campus Blueprint OTC\Bernd Skorupinski - Campus Blueprint - OTC - 2025 Course\`
(the same 28 lessons as `D:\Trading\Output\All PDFs\Book 2 - Campus Blueprint OTC 2025\`; the PDFs
carry only one transcript fragment per keyframe, so slides and settings dialogs are the evidence).

## Scope (add to node 00 of the master reference)

> **In scope:** the 28 OTC / Campus Fund 2025 lessons only.
> **Out of scope:** Funded Trader Weekly Outlooks, Funded Trader Signals, Practical Application,
> Beginner Breakout Rooms, the Hybrid AI course, live sessions and individual chapter frames.
> A rule marked "unsourced" or "removed" in the master reference means it is not part of
> the 28-lesson curriculum. It does not mean the rule is wrong. Several of those rules
> are cited in code to out-of-scope sessions:
> - the weekly distal-only stop (CW43)
> - gap as leg-out (Ch.171)
> - CL daily ZigZag 5% (frame 4397)
> - half-target breakeven (live sessions)
> - Q5/Q6 skipped on with-trend zones (Hybrid AI Module 1)
>
> For what the running engine does, the code wins. For what the method teaches, the lectures win.

The citation classes are not equivalent. A numbered lesson slide is stronger evidence than a single
remark in a live stream. The code has mixed both, and the Phase notes in `CLAUDE.md` record which
source each rule came from.

## Contradictions inside the master reference, resolved against the frames

| # | Master reference says | …and also says | What the OTC 2025 frames show | Code |
|---|---|---|---|---|
| 1 | "There is no 30 setting in the lectures." | Table: indices "13 days short · 30 days long"; FX "10 short · 30 long". | M3 L3 slide `frame_000645`, column "Time Frame setting (daily chart)": stocks/indices 13 short / 30 long; FX, metals, energies, ags 10 short / 30 long. `frame_001253`: "change the ROC from 10 to 13" for Apple. These are daily ROC lengths, so **30 is a lecture setting** and the "no 30" correction is wrong. The default dialog is ROC 10 (`frame_000808`). | `cycle_per_symbol` uses 30 for stocks, YM, SI, grains, softs; 10 elsewhere. No short/long pair |
| 2 | Settings: thresholds 75 / −75. | Usage: buy "≤ −80", sell "≥ +80". | Settings dialog `frame_000808` and legend `frame_001253`: **75 / −75**. No "80" or "purple" is said or shown; the instructor calls it "the red line". The ±80 wording is not from these lessons. | ±75 on every class |
| 3 | Profit margin "< 1:2 → ZONE FAILS". | "≥ 3:1 minimum regardless of trend". | M2 L6 table `frame_001570`: Great ≥1:5, Acceptable ≥1:3, Not acceptable <1:2 (the 1:2–1:3 band is unlabelled). Cheat sheet `frame_002069`: "Price must travel minimum 3:1 away from zone **regardless of trend**", measured on the preferred version. Both are in the lesson; the cheat sheet is the operative minimum. | Scores 10/7/5 at 5×/3×/2×, 0 below. **With-trend zones skip Q5** (Hybrid AI, out of scope). Counter-trend <2× is hard-rejected; a sideways zone <2× still ranks. `profit_margin_min_ratio: 3.0` is read but unused |
| 4 | Stop = distal − 33% of height. | "Stop just above/below distal". | The lesson itself is inconsistent. M2 L7 entry-type slides `frame_000455/000514/000585`: "just below the Distal Line". L7 "Stop (loss)" slide `frame_000166` "We used the 33% rule" and practical `frame_000917/000925`: stop at Fib −0.33. **No distal-only stop for weekly trades in these lessons.** | Weekly/monthly income: distal only (CW43, out of scope); LTF/pattern: −33% |
| 5 | COT = `140 × (net − low)/(high − low) − 20`, −20..120. | Pine pack `COTIndex_OTC.txt` uses 0–100. | M3 L2 `frame_001829`: TradingView "COT Pos. Indices", Weeks Look Back 26, Historical Hi/Los 156, "Show 0 and 100 Lines", **Upper Bound Level 120**. Legend `frame_001728` (Gold, 26/156): **20.66 / 80.28** / 38.59. CFTC report 2025-01-28 reproduces the first two exactly on 0–100 (commercials 20.66, non-commercials 80.28); V2 gives 8.92 / 92.39. The lines run 0–100 and touch the dashed 120 / −20 bound lines only at what the instructor calls a "multi year extreme" (`frame_002329`). **The node 14 formula is wrong**; 120/−20 are bound lines, not a stretched scale. Confirms C-57. | 0–100 default since C-57 |

## Other lecture facts checked against frames (M2 L3–L5)

- **Trend** (L4 `frame_000378/000466/000552`): 6 recent pivots; uptrend "Required: 2 x HL" ("Higher Highs not necessarily required"); downtrend "Required: 2 x LH"; sideways when no clear trend. Code matches.
- **Location** (L3 `frame_000658`): nearest HTF supply and demand zones, range between their distal lines split into 3 equal sections (high / equilibrium / low). Code matches (33/66).
- **Action matrix** (L5 `frame_001484`): matches the master reference node 08. Bracketed (Long)/(Short) at equilibrium are "reduced profit potential and lower probability … better to avoid" (`frame_001011`).
- **Trade management** (L4 `frame_001472`): Trend BE 2:1, T1 4:1, T2 trail HTF; Counter-trend and Sideways BE 1:1, T1 2:1, T2 trail LTF / opposing LTF zone; Anticipatory BE 1:1, T1 4:1, T2 trail HTF. No partial-close percentages; **no 0.5R breakeven**; no risk % anywhere in L3–L5.
- **COT usage** (M3 L2 `frame_001533`): finite markets and FX majors, weekly chart only; trade with commercials at extremes, against retailers at extremes; non-commercials = divergence early warning; "NOT a timing tool".
- **Seasonality** (M3 L4 `frame_000384`): Seasonality Index v4 defaults 5 years / 45 bars, changed to 10 live (`frame_000538`); Palladium and Natural Gas called unreliable (`frame_000951`).
- **Targets** (M4 `frame_001042`): "a 1 to 4 target, 1 to 3 target, whatever you want to do".

## Where the Field Map misdescribes the code

`Blueprint_Field_Map.html` was written from `methodology/`, not from the code. Verified 2026-09-14:

- **Trend.** The Map says higher highs + higher lows. The code requires only higher lows for an uptrend and only lower highs for a downtrend (asymmetric). That matches the lectures.
- **Counter-trend exit.** The Map says counter-trend trades close 100% at T2. The paper trader applies the same exit ladder to every trade; the counter-trend close exists only behind `BP_TYPE_LADDERS=1`, which defaults OFF.
- **Trailing.** The Map says the stop trails the last zone's distal line. `apply_zone_trailing()` is never called; the stop trails `price ∓ 1R` after the T2 partial.

## This repo's `main` vs the local fp-5k-config engine

This file was written against the local `fp-5k-config` code and copied here. `gitdhirajs/main`
split from it at 8806da6 (Phase 46) and differs as follows on the items above:

| Item | `gitdhirajs/main` (this repo) | local fp-5k-config |
|---|---|---|
| COT scale | **140×−20** by default; `BP_COT_0_100=1` switches to 0–100 | 0–100 by default (C-57) |
| Forex COT group | Non-Commercials; `BP_RETAIL_CONTRARIAN=1` switches to Retailers contrarian | Retailers contrarian (C-22) |
| CL=F COT group | Commercials 26w; `BP_RETAIL_CONTRARIAN=1` switches to Retailers contrarian | Retailers contrarian (C-44) |
| `apply_zone_trailing()` | Deleted in 50eeb05 | Present, never called |
| Counter-trend T2 close | `BP_TYPE_LADDERS=1` (default OFF) | `BP_TYPE_LADDERS=1` (default OFF, added 2026-09-14) |
| Explosive `> 0.70` | `BP_EXPLOSIVE_STRICT=1` (default OFF) | `BP_EXPLOSIVE_STRICT=1` (default OFF) |

Local also carries many later changes this repo does not have (C-series audit fixes, E-01..E-05
reporting fixes, portfolio risk gates, cycle override default OFF, measurement tooling).
