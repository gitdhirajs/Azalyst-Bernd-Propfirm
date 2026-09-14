# Exhaustive Frame Audit — Module 3, Lesson 4: Seasonality
## Target indicator: "Seasonality Index - v4" (TradingView pane title)

Source folder: `D:\Trading\Output\Bernd_Skorupinski Campus Blueprint OTC\Bernd Skorupinski - Campus Blueprint - OTC - 2025 Course\5. Module 3 Market Analysis and Forecasting Fundamentals\Lesson 4. Seasonality`

Total frames in folder: **68** (frame_000001.jpg – frame_001070.jpg, non-contiguous). **All 68 read in this pass** — no sampling.

---

## Frame-by-frame log

| Frame | Timestamp | Category | Finding |
|---|---|---|---|
| 000001 | 0:00:00 | other | Animated logo intro (blue circuit-line wipe). No content. |
| 000002 | 0:00:01 | other | Animated logo intro continues, "OTC" logo resolving. No content. |
| 000006 | 0:00:05 | other | Talking head, Bernd (as "Clemens Winkler" per lower-third later) intro shot, office w/ chart monitors in background (unreadable at this res). |
| 000007 | 0:00:06 | other | Title card "Module 3 – Lesson 4: Seasonality", presenter "Clemens Winkler", OTC logo, Trustpilot badge. No indicator content. |
| 000010 | 0:00:09 | other | Talking head. |
| 000028 | 0:00:27 | other | Talking head. |
| 000041 | 0:00:40 | other | Split-screen: talking head + agenda slide "Seasonality: Introduction to Seasonality / Cycles and Patterns / Seasonality Indicator" (bullet 1 highlighted). |
| 000045 | 0:00:44 | other | Talking head. |
| 000053 | 0:00:52 | other | Split-screen agenda slide again, bullet 2 "Cycles and Patterns" arrow-highlighted. |
| 000075 | 0:01:14 | other | Slide "The Importance of Seasonality" — bullets on patterns/cycles/forward guidance. No numbers. |
| 000139 | 0:02:18 | other | Talking head. |
| 000152 | 0:02:31 | other | Slide "The Importance of Seasonality" (2nd variant) — bullets on identifying bull/bear periods. No numbers. |
| 000161 | 0:02:40 | other | Talking head. |
| 000168 | 0:02:47 | other | Same slide, bullet 2 arrow-highlighted. |
| 000178 | 0:02:57 | other | Talking head. |
| 000182 | 0:03:01 | other | Same slide, no new bullet highlight change of note. |
| 000192 | 0:03:11 | other | Talking head. |
| 000210 | 0:03:29 | other | Slide "How Does Seasonality Work?" — bullets: "Uses lookback periods (e.g., 5, 10, or 15 years)". Generic textual mention of lookback options, not indicator-specific default. |
| 000225 | 0:03:44 | other | Talking head. |
| 000238 | 0:03:57 | other | Same "How Does Seasonality Work?" slide repeated. |
| 000278 | 0:04:37 | other | Talking head. |
| 000307 | 0:05:06 | symbol-change (pre-indicator) | TradingView-style platform, "US 30 Cash · 1W" (Dow/US30 CFD), weekly candles Oct'22–2025. **No Seasonality indicator loaded yet** — this is intro context before switching to the actual demo symbol. |
| 000316 | 0:05:15 | anchor (price only, not seasonality) | Same US30 1W chart, crosshair at date "09 Sep '24", OHLC/price legend only (44,796.35 / 24.00). No indicator pane. Not a Seasonality anchor. |
| 000318 | 0:05:17 | symbol-change | Browser switched to TradingView.com tab, symbol **SB1! (Sugar No. 11 Futures · 1D · ICEUS)**, OHLC O19.47 H19.53 L19.26 C19.30 −0.15 (−0.77%). No Seasonality pane yet (about to be loaded — this is the symbol/timeframe the entire practical demo uses). |
| 000324 | 0:05:23 | anchor (price only) | Same SB1!/1D chart, crosshair date "Thu 30 Jan '25", right-axis price badge "21.30" — this is a **price** value, indicator not yet loaded. Not a seasonality anchor. |
| 000326 | 0:05:25 | dialog (indicator browser) | "Indicators, metrics, and strategies" browser, Personal tab. Full list of custom scripts visible: **OTC COT Commercial Net Position**, **OTC COT Index** (starred/favorite), **OTC COT Non-Commercial Net Position**, **OTC Speculators Net Positons** [sic, typo in original], **OTC True ...sonality v4** (cursor partially obscures "Se" — reads as "OTC True [Se]asonality v4"), **OTC Valuation Tool**. This is the marketplace/library listing name; differs from the on-chart pane title (see below). |
| 000349 | 0:05:48 | dialog/anchor | Indicator now applied. Pane label reads **"Seasonality Index - v4 5 45  164.59"** (params inline: 5 = Average Years, 45 = Project Bars; trailing 164.59 = current/last value at default settings). Pane y-axis ticks: 172.00, 168.00, [164.59 dashed "current" line], 160.00, 156.00, 152.00, 148.00. |
| 000361 | 0:06:00 | other | Talking head, "indicators are already loaded into the charts" — transition frame, no chart visible. |
| **000384** | 0:06:23 | **dialog (full)** | **Settings dialog "Seasonality Index - v4", Inputs tab** (see Settings dialogs section below for full transcription). Confirms prior sampled-pass finding exactly. |
| **000538** | 0:08:57 | **dialog/anchor** | Average Years changed on-screen **5 → 10** (Project Bars unchanged at 45). Pane label now "Seasonality Index - v4 10 45" (no trailing value visible in this exact frame — likely mid-recalculation). Crosshair at date **"Tue 04 Mar '25"**; a floating axis-badge on the indicator pane's own y-scale shows **"162.11"** at the crosshair height (this is a Y-coordinate-under-cursor readout, not confirmed identical to the top-left legend value — LOW/MODERATE confidence, see notes). Y-axis ticks still 172.00→148.00 at this instant (stale from the pre-change 5yr series, about to rescale). |
| 000562 | 0:09:21 | scale-note / symbol-config | Chart zoomed out (2019/2021–2025 view). Indicator now fully recalculated for Average Years=10: **y-axis ticks are now 72.50, 70.00, 67.50, 65.00, 62.50, 60.00, 57.50, 55.00** — a completely different absolute range than the 148–172 range seen minutes earlier under Average Years=5. Confirms the plotted scale is **not fixed/bounded**; it depends heavily on the Average Years parameter (cumulative-type series). Four solid-blue drawn vertical marker lines visible at "Wed 24 Feb '21", "Wed 23 Feb '22", "Wed [22 Feb '23, partly cut]", "Thu 27 Apr '23" — Bernd's own annotations marking recurring pattern dates, not crosshair reads. Floating axis-badge "69.12" near cursor (not confidently tied to a specific date — no distinct crosshair-only date box visible). |
| 000640 | 0:10:39 | anchor (multi-marker, low pairing confidence) | Five solid-blue drawn vertical lines at "Mon 04 Mar '19", "Thu 27 Feb '20", "Wed 24 Feb '21", "Wed 23 Feb '22", "Wed 22 Feb '23" — illustrates the recurring same-week-of-February pattern across 5 years (matches transcript: "The same thing happened in February... 2022, 2021, 2020 and also here in 2019"). Pane legend "63.38", axis-badge "63.94". No single value confidently paired with one specific date (5 markers, cursor position not distinctly resolved to one). Treated as a **per-symbol configuration / pattern-illustration frame**, not a clean crosshair anchor. |
| 000660 | 0:10:59 | **anchor (high confidence)** | Crosshair aligned with drawn/highlighted date **"Wed 10 May '23"**. Pane legend **"Seasonality Index - v4 10 45 62.18"**. → **SB1!/1D, Wed 10 May '23 → 62.18** (matches prior sampled-pass finding exactly — confirmed, not new). |
| 000666 | 0:11:05 | anchor (moderate confidence) | Crosshair vertical line near "Wed 22 Feb '23" (highlighted box); "Mon 01 May '23" also boxed nearby (secondary marker). Pane legend **"...62.24"**. → SB1!/1D, Wed 22 Feb '23 → 62.24 (moderate confidence; two boxes present). |
| 000667 | 0:11:06 | anchor (moderate confidence) | Crosshair at "Tue 21 Feb '23" (boxed). Pane legend **"...66.36"**. → SB1!/1D, Tue 21 Feb '23 → 66.36. |
| 000669 | 0:11:08 | anchor (LOW confidence — possible last-value artifact) | Drawing-tool toolbar open (line width "2px" selector) — Bernd is placing an annotation, not actively scrubbing crosshair. Date box shows "Thu 23 Feb '23". Pane legend **"...69.12"**. **Flagged**: the identical value 69.12 recurs in frame 000702 tied to a *different* date ("Wed 24 Feb '21"), suggesting 69.12 may be a static current/last-value readout rather than a genuine per-date crosshair value in one or both of these frames. See Confidence notes. |
| 000675 | 0:11:14 | other | Same view as 669, mouse moved off pane (hand cursor over indicator area, main-chart legend/OHLC static). No new distinguishable numeric anchor beyond 669's ambiguity. |
| 000687 | 0:11:26 | **anchor (high confidence)** | Crosshair/date box **"Mon 31 Oct '22"** (solid highlighted). Pane legend **"...65.99"**. → **SB1!/1D, Mon 31 Oct '22 → 65.99** (matches prior sampled-pass finding exactly — confirmed, not new). |
| 000688 | 0:11:27 | anchor (high confidence) | Single date box **"Wed 23 Feb '22"** highlighted, no competing box. Pane legend **"...60.39"**. → SB1!/1D, Wed 23 Feb '22 → 60.39. |
| 000689 | 0:11:28 | anchor (high confidence) | Single date box **"Tue 22 Feb '22"** highlighted. Pane legend **"...65.64"**. → SB1!/1D, Tue 22 Feb '22 → 65.64. |
| 000701 | 0:11:40 | anchor (moderate confidence) | Two date boxes: "Wed 24 Feb '21" (solid/bright blue — matches a drawn vertical marker line at that x) and "Tue 22 Jun '21" (lighter/gray box, positioned right under the "+" cursor). Pane legend **"...57.37"**. Best-effort pairing (cursor proximity): → SB1!/1D, Tue 22 Jun '21 → 57.37, with Wed 24 Feb '21 being a separate drawn reference marker (no value attached). |
| 000702 | 0:11:41 | anchor (LOW confidence — likely last-value artifact) | Single solid-blue box "Wed 24 Feb '21"; cursor is a resize-handle icon (dragging pane divider), not the "+" crosshair; OHLC legend shows the symbol's static live quote (O19.47 H19.53 L19.26 C19.30 −0.15/−0.77%) rather than a scrubbed historical bar. Pane legend **"...69.12"**. Given the static-quote OHLC and non-crosshair cursor, this **69.12 is likely the indicator's current/last value**, not a value specifically at "Wed 24 Feb '21". Flagged low-confidence as a dated anchor. |
| 000704 | 0:11:43 | anchor (moderate confidence) | Two date boxes: "Wed 24 Feb '21" (bright blue, left) and "Fri 26 Mar '21" (gray, right, under "+" cursor at x≈760). Pane legend **"...58.99"**. Best-effort: → SB1!/1D, Fri 26 Mar '21 → 58.99. |
| 000716 | 0:11:55 | anchor (moderate confidence) | Two date boxes: "Tue 04 Feb '20" (gray, cursor "+" sits roughly between the two, slightly closer to this one) and "Thu 27 Feb '20" (bright blue). Pane legend **"...62.33"**. Best-effort: → SB1!/1D, Tue 04 Feb '20 → 62.33. |
| 000719 | 0:11:58 | **anchor (high confidence)** | Date box **"Fri 13 Mar '20"** aligned with "+" cursor (x≈670); companion box "Thu 27..." (cut off, likely "Thu 27 Feb '20") is a separate drawn marker. Pane legend **"...59.43"**. → **SB1!/1D, Fri 13 Mar '20 → 59.43** (matches prior sampled-pass finding exactly — confirmed, not new). |
| 000730 | 0:12:09 | anchor (LOW confidence — date unclear) | Two solid drawn-marker boxes "Tue 28 Jul '20" and "Tue 23 Feb '21", but the "+" crosshair (x≈410) sits well to the left of both, with no distinct date box directly under it. Per the visible month ticks (May…Jul…Sep…Nov…2021), x≈410 falls between "May" and "Jul" → approx. **June 2020** (exact day not legible). Pane legend **"...58.04"**. Recorded as approximate/unconfirmed date. |
| 000734 | 0:12:13 | anchor (moderate confidence) | Two date boxes: "Wed 23 Feb '22" (bright blue, drawn marker) and "Mon 12 Sep '22" (gray, under/near "+" cursor at x≈769). Pane legend **"...57.94"**. Best-effort: → SB1!/1D, Mon 12 Sep '22 → 57.94. |
| 000736 | 0:12:15 | anchor (moderate confidence) | Single date box "Fri 19 Jan '24" (gray), cursor nearby. Pane legend **"...67.01"**. → SB1!/1D, Fri 19 Jan '24 → 67.01. Forward-projection (orange) segment visible starting further right, not yet reached by cursor here. |
| **000737** | 0:12:16 | **anchor + scale/projection note (high confidence)** | Date box **"Thu 02 Jan '25"**, cursor/crosshair aligned with it. Pane legend **"...68.45"**. → **SB1!/1D, Thu 02 Jan '25 → 68.45** (matches prior sampled-pass finding exactly — confirmed, not new). **Critical for projection-start question**: the orange (forward-projected) segment's leftmost visible point touches the crosshair position exactly at this date — i.e., the color change from gray (historical) to orange (projected) occurs AT "Thu 02 Jan '25", which reads as at/adjacent to "today" for this recording. Supports: **projection starts at the same bar as the last real candle, not one bar after.** |
| 000765 | 0:12:44 | anchor (high confidence, inside forward-projection zone) | Date box **"Wed 29 Jan '25"**, well inside the orange projected segment. Pane legend **"...69.03"**. → SB1!/1D, Wed 29 Jan '25 → 69.03 (this is a **projected/future** value, not historical — useful for verifying the forward-projection's numeric path, not a backtested value). |
| 000827 | 0:13:46 | other | Talking head, "Now with that, I conclude the practical application." — end of chart demo. |
| 000836 | 0:13:55 | other | Talking head / transition into "Limitations" slide title appearing. |
| 000853 | 0:14:12 | other | Talking head. |
| 000862 | 0:14:21 | other | Slide "Limitations" — full bullet list incl. **"Some assets, like Palladium (PA) or Natural Gas (NG), are unreliable due to extreme price movements."** (relevant textual/verbal finding re: which assets the indicator is unreliable for — ties to open question (e) indirectly, re: limitations of use, not scale). |
| 000870 | 0:14:29 | other | Same "Limitations" slide, repeated content. |
| 000886 | 0:14:45 | other | Talking head. |
| 000892 | 0:14:51 | other | Same "Limitations" slide again (no new bullets). |
| 000900 | 0:14:59 | other | Talking head. |
| 000913 | 0:15:12 | other | Same "Limitations" slide again. |
| 000938 | 0:15:37 | other | Talking head. |
| 000951 | 0:15:50 | other | Same "Limitations" slide (final repeat). |
| 000963 | 0:16:02 | other | Talking head. |
| 000987 | 0:16:26 | other | Slide "Summary" — 4 bullets, generic recap, no indicator numbers. |
| 001014 | 0:16:53 | other | Talking head. |
| 001021 | 0:17:00 | other | Slide "Summary" repeated. |
| 001048 | 0:17:27 | other | Talking head. |
| 001055 | 0:17:34 | other | Split-screen: talking head + course-navigation UI showing 3 tabs "COT / Valuation / Seasonality" (Seasonality highlighted), text "*Practical Application classes are not available to all Campus tiers." — platform UI chrome, not indicator content. |
| 001070 | 0:17:49 | other | Talking head, closing remarks re: weekly live sessions. |

**All 68 frames accounted for.** Only two frames (000384, 000538) show a settings dialog; only one symbol (SB1! Sugar No. 11 Futures, 1D, ICEUS) ever carries the indicator; frames 000307/000316/000324 show a pre-indicator/pre-symbol-switch context (US30 chart) with no Seasonality pane.

---

## Settings dialogs (full detail)

### Dialog #1 — frame_000384.jpg (timestamp 0:06:23) — initial/default state
**Title: "Seasonality Index - v4"**, tabs: Inputs | Style | Visibility (Inputs tab active)

| Field | Value |
|---|---|
| Average Years | **5** |
| Project # Bars into Future | **45** |
| Align First Future Bar with Close | **unchecked** |
| Start Future Projection 1 Year Before End | **unchecked** |
| Show Debug Info | **unchecked** |

Bottom controls: "Defaults" dropdown, Cancel, Ok. Pane title in background reads "Seasonality Index - v4 5 45" with last-value badge "164.59" visible at the right edge.

*(Exactly matches the prior sampled pass's finding for this frame — confirmed.)*

### Dialog #2 — frame_000538.jpg (timestamp 0:08:57) — Average Years changed live
Same dialog fields as above are implied to still be open/being edited (this frame captures the moment the "Average Years" field was changed on-screen). Confirmed value change: **Average Years: 5 → 10**. Project # Bars into Future remains **45** (unchanged). No new screenshot of the checkboxes' state was needed since only Average Years was edited per the transcript ("Let me just change ten now and then just click on OK").

*(Matches the prior sampled pass's finding — confirmed, no new fields revealed.)*

**No other dialog views exist in this lesson's 68 frames.** The Style and Visibility tabs are never shown.

---

## Scale and projection findings (open questions)

### Question 1: What SCALE is the seasonality line plotted in?

**Answer: The line is NOT plotted on a fixed/bounded/normalized scale** (not 0–100, not ±100, not a percentage). Direct evidence from y-axis tick labels read across the lesson:

- With **Average Years = 5** (frames 000349, 000384, 000538 initial state): y-axis ticks run **148.00 → 172.00** (last value 164.59).
- With **Average Years = 10** (frames 000562 onward, all subsequent chart frames): y-axis ticks run **≈54.00/55.00 → 68.00–72.50** depending on zoom (e.g. 000562: 55.00–72.50; 000640: ~54–68; 000687/688/689/701 etc.: ~54.00–68.00-ish ranges with visible ticks like 56.00, 58.00, 60.00, 62.00, 64.00, 66.00, 68.00).

Changing only the **Average Years** parameter (5→10) collapsed the visible range from ~148–172 down to ~54–72 — roughly a 3x contraction with no overlap in absolute level. This is inconsistent with any bounded oscillator (RSI-style 0–100, or a ±100 sentiment index) and is consistent with the line being an **arbitrary/relative cumulative value** (e.g., a running sum of average historical daily returns over N years, whose absolute magnitude is a function of the lookback length and possibly the cumulation's starting anchor point) rather than a normalized percentage or price level. **The shape of the curve (peaks, troughs, slope direction) carries the meaning; the absolute y-value is not independently interpretable / not comparable across different Average-Years settings.** This corroborates and strengthens the prior sampled pass's tentative note ("arbitrary/cumulative scale, NOT price or a bounded index").

No percentage sign, "%", or explicit unit label was seen anywhere on the indicator pane's axis in any of the 68 frames.

### Question 2: Does the forward projection start at the last real bar, or one bar after?

**Answer: At the same bar as the last real candle (confirmed a second time).** In frame_000737 (date box "Thu 02 Jan '25"), the color transition from gray (historical) to orange (projected) occurs exactly at the crosshair/date-box position — the orange segment's leftmost point is at that same x-coordinate, not one bar to its right. This is consistent with the prior sampled pass's finding from frame_000384/000538 region. No frame in this exhaustive pass contradicts this; no frame showed a visible one-bar gap between the last gray point and the first orange point.

The "Align First Future Bar with Close" input (unchecked in the dialog) did not appear to need to be enabled for this overlap behavior — the default (unchecked) state already produces projection starting at the last bar.

---

## Per-symbol configuration

**Only one symbol carries the Seasonality Index in this lesson: SB1! — Sugar No. 11 Futures · 1D · ICEUS.**

- Settings applied to it: Average Years 5 (initial) → changed to 10 (final, used for the rest of the demo); Project # Bars into Future = 45 (never changed); both checkboxes ("Align First Future Bar with Close", "Start Future Projection 1 Year Before End") left unchecked; "Show Debug Info" left unchecked.
- A different symbol, **US 30 Cash (Dow/US30) · 1W**, appears at the very start (frames 000307, 000316) but **without** the Seasonality indicator loaded — it's shown only as generic platform/account context before Bernd switches to the actual demo symbol. Not a second "seasonality-configured" symbol.
- No other tickers (no Gold, no EURUSD, no ES/NQ, no other commodities) ever appear with this indicator in this lesson's frames.

---

## Verification anchors (full table, deduplicated)

Format: Symbol / Timeframe · Date (crosshair) · Seasonality Index value (top-left pane legend) · Confidence · Source frame(s)

| # | Symbol/TF | Date | Value | Confidence | Frame(s) |
|---|---|---|---|---|---|
| 1 | SB1!/1D | Thu 02 Jan '25 | 68.45 | High (matches prior pass) | 000737 |
| 2 | SB1!/1D | Mon 31 Oct '22 | 65.99 | High (matches prior pass) | 000687 |
| 3 | SB1!/1D | Fri 13 Mar '20 | 59.43 | High (matches prior pass) | 000719 |
| 4 | SB1!/1D | Wed 10 May '23 | 62.18 | High (matches prior pass) | 000660 |
| 5 | SB1!/1D | Wed 23 Feb '22 | 60.39 | High (single unambiguous date box) | 000688 |
| 6 | SB1!/1D | Tue 22 Feb '22 | 65.64 | High (single unambiguous date box) | 000689 |
| 7 | SB1!/1D | Wed 22 Feb '23 | 62.24 | Moderate (2 date boxes present) | 000666 |
| 8 | SB1!/1D | Tue 21 Feb '23 | 66.36 | Moderate | 000667 |
| 9 | SB1!/1D | Mon 12 Sep '22 | 57.94 | Moderate (2 date boxes, cursor-proximity pairing) | 000734 |
| 10 | SB1!/1D | Fri 19 Jan '24 | 67.01 | Moderate | 000736 |
| 11 | SB1!/1D | Wed 29 Jan '25 | 69.03 | High, but **inside forward-projection (future), not historical** | 000765 |
| 12 | SB1!/1D | Tue 22 Jun '21 | 57.37 | Moderate (2 date boxes, cursor-proximity pairing) | 000701 |
| 13 | SB1!/1D | Fri 26 Mar '21 | 58.99 | Moderate | 000704 |
| 14 | SB1!/1D | Tue 04 Feb '20 | 62.33 | Moderate (cursor roughly between 2 boxes) | 000716 |
| 15 | SB1!/1D | ~Jun 2020 (exact day not legible) | 58.04 | Low — date estimated from axis position only | 000730 |
| 16 | SB1!/1D | Thu 23 Feb '23 *(disputed — see notes)* | 69.12 | Low — possible last-value artifact | 000669 |
| 17 | SB1!/1D | Wed 24 Feb '21 *(disputed — see notes)* | 69.12 | Low — possible last-value artifact, cursor was not on crosshair mode | 000702 |
| 18 | SB1!/1D | Tue 04 Mar '25 | 162.11 | Low/informational — this is a **right-axis Y-coordinate-under-cursor badge**, not the top-left legend value, captured **during** the Average-Years 5→10 transition (stale 148–172 scale still showing) | 000538 |

**Right-axis "last value" badges seen (current/live, NOT verifiable retroactively, listed separately per task instructions):**
- "164.59" — Seasonality Index last value at Average Years=5, seen persistently in frames 000349, 000384, 000538 (pre-transition).
- "69.12" — recurs as a persistent-looking value in frames 000562, 000669, 000702, 000675 area — most likely this is effectively the "current/default" last-bar value once Average Years=10 stabilized on the originally-loaded default zoom window, rather than a genuine distinct per-date read each time it appears. Treat any single occurrence of exactly "69.12" with caution unless independently corroborated by a clearly single, unambiguous date box.

---

## Confidence notes / ambiguous reads

1. **Two-box-color heuristic used for pairing dates to values**: Across frames with multiple highlighted date boxes at the bottom time axis, one box is consistently rendered in a **solid/bright blue** fill and the other(s) in a **lighter gray** fill. Empirically, the bright-blue boxes align with Bernd's manually **drawn vertical trend-line markers** (persistent annotations at recurring seasonal dates, e.g. "same week of February across 5 years"), while the gray box tends to sit directly under the live "+" crosshair cursor and is the one that should pair with the top-left pane legend's trailing value. This heuristic was used for anchors #7, #8, #9, #10, #12, #13, #14 above and is **moderate, not certain**, confidence — I could not fully verify TradingView's exact internal legend-update behavior pixel-by-pixel in every case, and I did not have a ground-truth video to scrub. Treat these as best-effort.

2. **Frames 000669 and 000702 both show the value "69.12" attached to two different dates** ("Thu 23 Feb '23" and "Wed 24 Feb '21" respectively). Frame 000702 additionally shows a non-crosshair cursor icon (pane-divider resize handle) and a static/unscrubbed OHLC legend matching the symbol's live quote — strong evidence that in at least frame 000702, "69.12" is the indicator's **current/last value**, not a value specific to "Wed 24 Feb '21". Frame 000669 is less clear (drawing toolbar open, could be either). Both are flagged low-confidence as dated anchors; I recommend NOT relying on either for Pine Script backtesting verification without independent confirmation.

3. **Frame 000538's "162.11"** is read from a small floating badge on the indicator pane's own right-axis at the crosshair's Y-height, captured in the same frame where Average Years was being changed from 5→10 live — the pane's underlying series was mid-recalculation (y-axis ticks still showed the old 148–172 range from the Average-Years=5 state). This value should be treated as **low confidence / transitional-state artifact**, not a clean verification anchor for either the 5-year or 10-year configuration.

4. **Frame 000730's date could not be pinned down precisely** — the crosshair sits between two of Bernd's drawn markers with no distinct date box of its own visible in the frame at the resolution read. Estimated as "around June 2020" purely from proportional axis position between the "May" and "Jul" tick labels; do not treat as an exact-date anchor.

5. **Frames 000640 and 000562** each show multiple (4–5) drawn vertical marker lines simultaneously (illustrating "same pattern recurs every February for 5 years running") with pane legend/axis values (63.38/63.94 and 69.12 respectively) that could not be confidently attributed to any single one of the multiple dates shown. These are recorded as pattern-illustration frames rather than clean anchors.

6. **No frame in this lesson shows any symbol other than SB1! (Sugar) with the Seasonality Index applied**, and no frame shows the Style or Visibility settings tabs — only Inputs was ever opened, confirming the prior pass did not miss a second dialog state elsewhere in the folder.

7. **Indicator naming discrepancy** (informational, not really an ambiguity but worth flagging): the TradingView indicator-browser library entry is titled **"OTC True Seasonality v4"** (frame_000326, Personal tab), while the actual on-chart pane/legend title once applied reads **"Seasonality Index - v4"** (all subsequent frames). These are the same script; the discrepancy is simply between the script's browse-library display name and its Pine `indicator()` title string.
