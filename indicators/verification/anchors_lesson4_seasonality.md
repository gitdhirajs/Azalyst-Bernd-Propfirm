# Lesson 4 — Seasonality — Verification Anchors

Source: `D:\Trading\Output\Bernd_Skorupinski Campus Blueprint OTC\Bernd Skorupinski - Campus Blueprint - OTC - 2025 Course\5. Module 3 Market Analysis and Forecasting Fundamentals\Lesson 4. Seasonality`
Indicator: **Seasonality Index - v4** (script list in `frame_000349.jpg` shows the underlying script is named **"OTC True Seasonality v4"** in the Personal favorites list — the on-chart pane label abbreviates it to "Seasonality Index - v4").
68 sampled frames total; ~26 read for this pass. Only frames actually opened are cited below.

---

## Settings dialogs (full field/value tables)

Only ONE settings-dialog frame exists in the sample: **frame_000384.jpg** (ts 0:06:23, transcript: "To open the settings, just double click on the line and then you see this new window here.")

Dialog title: **"Seasonality Index - v4"**, tabs: **Inputs | Style | Visibility** (only Inputs tab captured/visible; Style and Visibility were not opened in any sampled frame).

**Inputs tab — full field list and default values (as first opened):**

| Field | Type | Value (default, as shown) |
|---|---|---|
| Average Years | number | **5** |
| Project # Bars into Future | number | **45** |
| Align First Future Bar with Close | checkbox | **unchecked** |
| Start Future Projection 1 Year Before End | checkbox | **unchecked** |
| Show Debug Info | checkbox | **unchecked** |

Bottom controls: "Defaults ▾" dropdown, Cancel, Ok. No other input fields are present in this dialog — the full input list is exactly the 5 rows above (2 numeric, 3 boolean). No Style or Visibility tab was captured in this sample, so their fields (line color/width, precision, visibility-per-timeframe, etc.) are NOT documented here.

At the moment this dialog was open, the pane title read `Seasonality Index - v4 5 45` and the right-axis/legend value was `164.59` (see anchor table).

**Average Years change confirmed:** frame_000538.jpg (ts 0:08:57, transcript: *"Let me just change ten now and then just click on OK."*) — the pane title changed from `Seasonality Index - v4 5 45` to **`Seasonality Index - v4 10 45`**. Project # Bars into Future stayed at 45; only Average Years was changed (5 → 10). No frame shows the dialog re-opened at this point (the title-bar text is the only visual confirmation), but it is unambiguous and directly cross-referenced against the spoken transcript at the same timestamp.

Visible shape change: yes — comparing frame_000384 (5yr) and frame_000538 (10yr) at the *same* chart location (Feb–Apr 2025 forward-projection window), the line's absolute values shift down slightly (164.59 → ~162–164 range) and the projection segment's local wiggle pattern changes shape (compare the "double hump" of the 5yr version vs. the flatter, differently-timed oscillation of the 10yr version around the same dates). All subsequent frames in the lesson (frame_000562 onward) use the `v4 10 45` setting — Bernd keeps 10 years for the remainder of the practical walkthrough and never reverts to 5.

---

## Scale and projection findings

### Q3 — What scale does the seasonality line use?

**Finding: the line is on its own arbitrary/cumulative scale — it is NOT price units and NOT a fixed 0–100 or ±100 percentage/index band.**

Evidence — y-axis tick labels read directly off the seasonality pane, all for the *same* symbol/settings (SB1!, 1D, Average Years=10, Project=45), at different scroll positions in history:

| Frame | Chart window shown | Seasonality-pane y-axis ticks (top→bottom, as printed) |
|---|---|---|
| frame_000384 (AvgYears=5) | Oct 2024 – Apr 2025 | 172.00, 168.00, 164.00, 160.00, 156.00, 152.00, 148.00 |
| frame_000538 (AvgYears=10, same window) | Oct 2024 – Apr 2025 | 172.00, 168.00, 164.00, 160.00 (visible) |
| frame_000640 | ~2019–2025 zoomed out | 68.00 (badge 67.44 visible near top of pane) |
| frame_000562 | 2021–2025 zoomed out | 72.50, 70.00, 67.50, 65.00, 62.50, 60.00, 57.50, 55.00 |
| frame_000666 (2023 window) | Jul '20 – Sep '23 | 72.50, 70.00, 67.50, 65.00, 62.50, 60.00, 57.50, 55.00 |
| frame_000701 (2021 window) | 2020 – Aug '21 | 68.00, 66.00, 64.00, 62.00, 60.00, 58.00, 56.00, 54.00 |

The axis range visibly sits anywhere from the high-50s (2020–2022 windows) up to the high-160s/172 (the current/2025 window) for the **identical indicator instance on the identical symbol** — it is only the visible chart pane that changes, not the settings. Sugar (SB1!) price itself over the same span moved roughly $10→$27→$19, which does not linearly explain a drift from ~55 to ~172 either. This is consistent with the indicator plotting a **cumulative/compounding index value that drifts secularly over the full multi-year price history** rather than a bounded oscillator or a price-unit overlay. Because of this drift, an absolute numeric legend value (e.g. "162.11") is only meaningful relative to nearby bars in the same viewport/date range — it is not a fixed percentage-above/below-mean reading and not comparable in isolation across far-apart dates without the full series.

No frame in this sample shows an axis label at a round percentage boundary (e.g. 0, 50, 100, -100) or a price-matching value (Sugar traded ~$19.30 while the pane read ~148–172), which rules out both "percentage/index (0–100 or ±100)" and "price units" as the scale.

### Q4 — Does the forward projection start at the last bar or one bar after?

**Finding: the color transition from grey (historical) to orange (forward projection) occurs at (or within ~1 pixel of) the same x-coordinate as the last real price candle — i.e., it starts at the last bar, not one bar after.**

Method: frame_000361.jpg (clean, no dialog/crosshair overlay) was cropped and pixel-measured in two places:
- Price pane: the rightmost real candle (last OHLC bar, red body with wick) sits at original-image x ≈ 677px.
- Seasonality pane: the grey→orange color transition in the plotted line sits at original-image x ≈ 678px.

The two x-coordinates coincide within measurement error (≤1–3px against a candle-to-candle spacing of roughly 15–20px on that chart), so the orange projection segment visually begins essentially at the last actual bar's column, not a full bar later. This is a pixel-measurement inference (image was resized/cropped for inspection), not a value read directly off an on-screen label, so it is flagged as **derived, not verbatim-read**.

Additional projection notes from other frames:
- The projection is plotted in a **distinct orange/amber color** vs. the grey historical line (visible in frame_000361, frame_000384, frame_000538, frame_000640, frame_000730/734/736/737, frame_000827).
- The projection's right-most endpoint carries a static right-axis badge (e.g. "69.13" in frames 666/669/701/704, "164.59"/"162.11" in frames 384/538) that stays constant across many frames sharing the same chart view — consistent with it being the fixed last-bar projected value for that viewport, not a moving crosshair readout. This badge is **not independently verifiable today** per the task's rule (last-value badges excluded from verification) and is only noted for completeness.

---

## Per-symbol configuration

Only **one symbol** is demonstrated anywhere in the sampled frames:

| Symbol | Full name | Exchange | Timeframe | Average Years used | Project Bars used |
|---|---|---|---|---|---|
| SB1! | Sugar No. 11 Futures | ICEUS | 1D (Daily) | 5 (initial default) → changed to 10 mid-lesson | 45 (unchanged throughout) |

No other ticker, asset class, or timeframe appears in any frame read for this lesson (frame_000836 and later are talking-head slides with no chart, confirming the practical demo used only Sugar). The frame_000349 indicator-search dialog (title "Indicators, metrics, and strategies") shows the same "Personal" favorites list used across the OTC course: OTC COT Commercial Net Position, OTC COT Index (starred), OTC COT Non-Commercial Net Position, OTC Speculators Net Positions, "OTC True ...sonality v4" (Seasonality — text truncated by the cursor in the frame), OTC Valuation Tool.

---

## Verification anchors

All rows below are on symbol **SB1! (Sugar No. 11 Futures, ICEUS)**, timeframe **1D**, indicator settings **Average Years = 10, Project # Bars into Future = 45** (i.e. all AFTER the frame_000538 change), unless noted. All "legend_value" entries are the number printed immediately after the pane title text `Seasonality Index - v4 10 45` (top-left of the indicator pane) at the moment of a crosshair hover — this is the CROSSHAIR-tracked reading, distinct from any right-axis "last value" badge. The `date_on_chart` is the highlighted date pill at the bottom axis directly under the crosshair's vertical dashed line.

| frame | timestamp | symbol | timeframe | date_on_chart | legend_value | confidence | notes |
|---|---|---|---|---|---|---|---|
| frame_000384 | 0:06:23 | SB1! | 1D | (no crosshair; settings dialog open) | 164.59 | high | AvgYears=**5** (pre-change). Value is the pane-title inline number with no crosshair active — effectively the last-bar value for that viewport. |
| frame_000538 | 0:08:57 | SB1! | 1D | Tue 04 Mar '25 | 162.11 | medium | AvgYears just changed 5→10. Value read from the right-axis "+"-badge at the crosshair's y-height (dashed horizontal line touching the plotted line), NOT the top-left inline legend — no trailing number was visible next to the pane title in this frame. |
| frame_000666 | 0:11:05 | SB1! | 1D | Wed 10 May '23 | 62.18 | high | Pane-title inline legend value; date pill highlighted (grey/active) at bottom axis. |
| frame_000669 | 0:11:08 | SB1! | 1D | Tue 21 Feb '23 | 66.36 | high | Transcript at this timestamp: "the indicator ... accurate ... on the 23rd of February" (Bernd's spoken date is 2 days later than the exact crosshair date shown). |
| frame_000687 | 0:11:26 | SB1! | 1D | Mon 31 Oct '22 | 65.99 | high | |
| frame_000689 | 0:11:27–28 | SB1! | 1D | Tue 22 Feb '22 | 65.64 | high | |
| frame_000701 | 0:11:40 | SB1! | 1D | Tue 22 Jun '21 | 57.37 | medium-high | A separate static blue vertical reference line ("Wed 24 Feb '21") is also drawn on the chart — do not confuse it with the crosshair date, which is the grey-highlighted pill "Tue 22 Jun '21". |
| frame_000704 | 0:11:41–43 | SB1! | 1D | Fri 26 Mar '21 | 58.99 | high | |
| frame_000716 | 0:11:55 | SB1! | 1D | Thu 27 Feb '20 | 62.33 | high | |
| frame_000719 | 0:11:58 | SB1! | 1D | Fri 13 Mar '20 | 59.43 | high | |
| frame_000730 | 0:12:09 | SB1! | 1D | Tue 28 Jul '20 | 58.04 | medium-high | A static blue reference line ("Tue 23 Feb '21") also present; crosshair date is the grey-highlighted pill "Tue 28 Jul '20". |
| frame_000734 | 0:12:13 | SB1! | 1D | Mon 12 Sep '22 | 57.94 | high | |
| frame_000736 | 0:12:15 | SB1! | 1D | Fri 19 Jan '24 | 67.01 | high | |
| frame_000737 | 0:12:16 | SB1! | 1D | Thu 02 Jan '25 | 68.45 | high | Crosshair sits just before the grey→orange projection transition; this is the "future projection" section of the transcript ("if we now look into our future projection..."). |
| frame_000827 | 0:13:46 | SB1! | 1D | Thu 02 Jan '25 | 68.45 | high (cross-verified) | Independent frame, same date and same value as frame_000737 — exact match, high-confidence duplicate confirmation of that anchor. |
| frame_000640 | 0:10:39 | SB1! | 1D | ambiguous — no single highlighted crosshair date pill (only static blue year-marker reference lines: Mon 04 Mar '19, Thu 27 Feb '20, Wed 24 Feb '21, Wed 23 Feb '22, Wed 22 Feb '23) | 63.38 | low | Legend value present but cannot be tied to one specific date with confidence — mouse cursor is a plain pointer icon, not an engaged crosshair. Not used as a clean anchor. |

---

## Frames inspected but unusable

| frame | reason |
|---|---|
| frame_000562 | Zoomed-out multi-year view (2021–2025) with mixed static reference lines and a genuine crosshair (price=10.80, seasonality=69.12 at date column "Thu 27 Apr '23" highlighted); used only for y-axis scale evidence (Q3) — date/value pairing judged less reliable than the dedicated anchors above because multiple highlighted date pills compete in the same frame. |
| frame_000640 | See anchor table — legend value present (63.38) but no unambiguous single crosshair date; used only to note the right-axis badge behavior, not as a clean anchor. |
| frame_000349 | Indicator search/browse dialog ("Indicators, metrics, and strategies") — useful for confirming the script name/list, not a data point. |
| frame_000836 | Talking-head-only slide (no chart visible) — part of the post-practical "limitations" discussion (transcript ts 0:13:55 onward). Confirms no further symbols/settings are demonstrated after frame_000827. |
| frame_000361 | Clean full-chart view used purely for the Q4 pixel-measurement (grey→orange transition point vs. last candle position); not a data-value anchor itself. |

Frames NOT opened in this pass (68 total sampled; ~26 opened): frame_000001/2/6/7/10/28/41/45/53/75/139/152/161/168/178/182/192/210/225/238/278/307/316/318/324/326/675/688/702/765/853/862/870/886/892/900/913/938/951/963/987/1014/1021/1048/1055/1070. Based on the full transcript.json read (all 68 entries), these fall into two buckets: (a) intro/outro conceptual slides with no chart (transcript text confirms pure narration, e.g. "It allows us to define specific periods to be a bull or bear..."), or (b) minor in-between frames of sequences already anchored above (e.g. frame_000675/688/702 sit between already-captured crosshair frames in the same February-comparison sequence). Given the budget guidance to sample ~20–30 frames, these were deprioritized as low-yield.
