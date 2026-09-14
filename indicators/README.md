# Fixed Indicators — OTC 2025 Course, Module 3

All four rebuilt against the settings dialogs Bernd opens on screen in
**Module 3 — Market Analysis and Forecasting Fundamentals**, Lessons 2 / 3 / 4.
(Lessons 1 and 5 skipped — no indicator settings shown.)

Frame source:
`D:\Trading\Output\Bernd_Skorupinski Campus Blueprint OTC\Bernd Skorupinski - Campus Blueprint - OTC - 2025 Course\5. Module 3 Market Analysis and Forecasting Fundamentals`

| # | File | Replaces | Confidence |
|---|---|---|---|
| 1 | `COT Pos Indices.pine` | `COTIndex_OTC.txt` | ✅ **Verified** — dialog + pixel-measured scale |
| 2 | `COT Net.pine` | `COTReport_OTC.txt` | ✅ Verified from chart title (no dialog frame exists) |
| 3 | `CampusValuationTool.pine` | `Valuation_OTC.txt` | ✅ **Verified** — full dialog read |
| 4 | `Seasonality Index - v4.pine` | `Seasonality_OTC.txt` | ⚠️ **Reconstruction** — inputs verified, algorithm inferred |

Originals kept in `_originals_for_comparison/` for side-by-side.

---

## TradingView deployment status (2026-08-24)

All four compiled and added to a dedicated TradingView layout — **"Blueprint Indicator
Verification"** (`/chart/Xl1AvSF5/`), tested on `GC1!` weekly. Saved to My Scripts as:

| Script name in TradingView | Source file | Compile | Live title string on chart |
|---|---|---|---|
| `BP Fixed - COT Pos. Indices` | `COT Pos Indices.pine` | ✅ | `COT Pos. Indices 26 156 Futures Only 120 80 50 20 -20 1` |
| `BP Fixed - COT Net` | `COT Net.pine` | ✅ | `COT Net Futures Only` |
| `BP Fixed - CampusValuationTool` | `CampusValuationTool.pine` | ✅ | `CampusValuationTool ZB1! GC1! DXY 10 100 100 -100 75 -75` |
| `BP Fixed - Seasonality Index v4` | `Seasonality Index - v4.pine` | ✅ | `Seasonality Index - v4 5 45` |

Every title string is an exact match to the corresponding settings dialog in the lecture frames.

### Bug fixed during deployment — `COT Pos Indices.pine`

The file **did not compile as originally written**. The historical-extreme `bgcolor()` call spanned
four lines, and its final continuation line was indented **8 spaces — a multiple of 4**, which Pine
v5 parses as the start of a new block rather than a continuation:

```
Error at 77:270  Mismatched input 'end of line without line continuation' expecting ')'
```

Fixed by lifting the condition into a named variable (continuation lines now at 14 spaces, not a
multiple of 4):

```pine
histExtreme = (showComm    and (commHist    >= upperExtreme or commHist    <= lowerExtreme)) or
              (showNonComm and (nonCommHist >= upperExtreme or nonCommHist <= lowerExtreme)) or
              (showNonRept and (nonReptHist >= upperExtreme or nonReptHist <= lowerExtreme))
bgcolor(markExtremes and histExtreme ? color.new(color.gray, 90) : na, title="Historical Hi/Lo extreme")
```

The other three files were scanned for the same defect — all their multiple-of-4 indents are
legitimate block bodies (function/if/for), not continuations. No changes needed.

### ⚠️ What is NOT yet verified

Compile + title-string match confirms **identity and configuration**. It does **not** confirm
**numeric output**. Only one date-specific value has been cross-checked, and it did **not** match:

| Anchor | Lecture frame | Live TradingView | Status |
|---|---|---|---|
| GC1! 1W, Mon 24 Oct '22, Commercial Index | **85.10%** (`Lesson 2/frame_002099.jpg`) | **99.14%** | ❌ unresolved |

Caveat on that comparison: the price bar reached via Bar Replay showed
O1649.9 H1674.3 L1621.1 C1656.3, whereas the lecture frame shows O1662.9 H1679.4 L1640.7 C1644.8 —
so the crosshair may have landed one bar off rather than the indicator being wrong. Needs a clean
re-test before concluding anything.

**Remaining work:** ~37 extracted date+value anchors across the three lessons are still unchecked
against live output (see `_anchors/` notes). Settings-correct ≠ output-correct.

---

## 1. COT Pos. Indices  ✅

**Frames:** `Lesson 2/frame_001829.jpg` (dialog, 0:30:28), `frame_002069.jpg`, `frame_002415.jpg`,
`frame_002099.jpg` (measured pane).

| Field | Value |
|---|---|
| Weeks Look Back | **26** |
| Weeks Look Back for Historical Hi/Los | **156** |
| Report Type | **Futures Only** |
| Show Commercial / NonCommercial / Nonreportable Index | ✅ |
| Show Reference Lines | ✅ |
| Show 0 and 100 Lines | ✅ (own colour picker) |
| Upper Bound Level | **120** |
| Below fold (from title string) | 80, 50, 20, −20, 1 |

The dialog is never scrolled in any of the four frames, so 80 / 50 / 20 / −20 / 1 come from the
title string rather than being read directly.

### The scale — measured, not eyeballed

Calibrating `frame_002099` off the 100-line (y=472) and 0-line (y=587), the seven reference
lines land at **119.1 / 100.0 / 80.0 / 50.4 / 20.4 / 0.0 / −19.1** → 120 / 100 / 80 / 50 / 20 / 0 / −20.

The blue commercials curve reaches a **maximum of 120.9%**, sitting on the 120 line, with 50
plot columns above the 100-line. It never reaches 125.

```
index = lowerBound + (upperBound - lowerBound) * (net - lowest(net,26)) / (highest(net,26) - lowest(net,26))
      = 140 * p - 20
```

The 0 and 100 lines are *inner* reference lines with their own toggle — **not** the index bounds.

**CFTC cross-check (GC1! weekly, commercials):**

| Weekly bar | Report | p | 140p−20 |
|---|---|---|---|
| Mon 26 Sep '22 | 2022-09-27 | 1.0000 (26w high) | **120.00** |
| Mon 28 Aug '23 | 2023-08-29 | 0.7908 | **90.71** |

**Verify:** load on GC1! weekly. Title must read
`COT Pos. Indices 26 156 Futures Only 120 80 50 20 -20 1`, and the Sep '22 peak must sit on the
top yellow line at 120.00%.

**Unconfirmed:** `Weeks Look Back for Historical Hi/Los` (156) drives the historical-extreme
background shading here. The field name is confirmed; its exact use in his build is not visible
(his chart shows 3 plots, so it is not a fourth line).

---

## 2. COT Net  ✅

**Frame:** `Lesson 2/frame_002993.jpg` (6E1! weekly, 0:49:52).

He runs this as **two panes, one group each**:

* `COT Comm Net Futures Only` — commercials, **blue**
* `COT Fund Net Futures Only` — fund managers, **orange**

Transcript @49:38: *"I look for the COT commercial net positions and I load … I also go to load
this one. So like before, we have the commercials in blue and the fund managers in orange."*

Raw net contracts (displayed in K), zero line, no normalisation — *"provides unrestricted data,
this makes it easier to spot absolute extremes in positioning"* (@44:01).

One script covers both panes — add it twice and toggle the group in each copy.

**Changes vs `COTReport_OTC.txt`:** added the Report Type dropdown (the .txt hardcoded
`includeOptions = false`); added per-group toggles; matched his colours; added the HG / LBR CFTC
code fixes that exist in the COT Index script but were missing here.

No settings-dialog frame for this indicator exists in the lesson, so its inputs beyond
Report Type are inferred from the title.

---

## 3. CampusValuationTool  ✅

**Frames:** `Lesson 3/frame_000808.jpg` (AUDUSD daily, full dialog), `frame_001240.jpg`,
`frame_001253.jpg` (AAPL daily).

| Field | AUDUSD (forex) | AAPL (stock) |
|---|---|---|
| Reference Symbol 1 | `CBOT_DL:ZB1!` ✅ | ✅ |
| Reference Symbol 2 | `COMEX_DL:GC1!` ✅ | ✅ |
| Reference Symbol 3 | `TVC:DXY` ✅ | ❌ unselected |
| ROC Length | **10** | **13** |
| Rescale Length | 100 | 100 |
| Rescale Maximum / Minimum | 100 / −100 | 100 / −100 |
| Upper / Lower Threshold | **75 / −75** | **75 / −75** |

Confirms two existing repo settings: forex uses **all three** references (not DXY-only), and the
forex threshold is **±75, not ±69**.

**Changes vs `Valuation_OTC.txt`:** ported v4 → v5; symbols **reordered** to ZB1! / GC1! / DXY
(the .txt had DXY / GC1! / ZB1!, and the order matters because he unselects "reference symbol
three, the dollar"); added the three Show toggles; exposed Rescale Maximum / Minimum as inputs
(the .txt hardcoded `* 200 - 100`, which *is* 100 / −100); exposed the thresholds; guarded
divide-by-zero.

**Verify:** title must read `CampusValuationTool ZB1! GC1! DXY 10 100 100 -100 75 -75`.

---

## 4. Seasonality Index - v4  ⚠️ reconstruction

**Frames:** `Lesson 4/frame_000384.jpg` and `frame_000538.jpg` (Sugar SB1! daily).

| Seasonality Index - v4 (2025) | Seasonality_OTC.txt (older) |
|---|---|
| Average Years: **5** → changed on-screen to **10** | `_lookback` default 15 |
| Project # Bars into Future: **45** | `_future` default 30 |
| Align First Future Bar with Close (off) | trading-day mode (fixed 252 / variable) |
| Start Future Projection 1 Year Before End (off) | smoothing, offset, colour, width |
| Show Debug Info (off) | |

This is a **different indicator**, not a retuned one — `Seasonality_OTC.txt` has been superseded.

**Read this before trusting it.** Only the *inputs* are visible in the frames; the v4 algorithm
is not. The maths in this file is `Seasonality_OTC.txt`'s (average bar-to-bar delta per
trading-day-of-year bin, de-trended, scaled to the visible price range) fitted to the v4 input
surface. The two behavioural flags are implemented to the plain reading of their labels.
**Expect the shape to match and the exact path to differ.** The OTC inputs absent from his
dialog are pinned at their defaults.

**Verify:** title must read `Seasonality Index - v4 5 45`.

---

## Two open conflicts with the Python engine

Neither has been changed — both would move goldtest numbers.

1. **AAPL ROC.** `BP_config.yaml` sets `AAPL: 30` (and the other mega-caps to 30), citing
   Ch.117 / the Cheatsheet. This lesson shows him explicitly setting **13** for Apple daily
   (*"I'm going to change the ROC from 10 to 13"*, @20:52). Genuine source conflict.

2. **Seasonality forward projection.** Lesson shows **45 bars**; `BP_indicators.py` uses 30 days
   (Phase 31). Also `DEFAULT_LOOKBACKS = (5, 10, 15)` includes 15, which never appears in this
   lesson — only 5 and 10 are demonstrated. Not a contradiction, just unattested here.
