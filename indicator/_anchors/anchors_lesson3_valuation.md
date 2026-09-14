# Lesson 3 (Valuation) — Verification Anchors for CampusValuationTool

Source: `D:\Trading\Output\Bernd_Skorupinski Campus Blueprint OTC\Bernd Skorupinski - Campus Blueprint - OTC - 2025 Course\5. Module 3 Market Analysis and Forecasting Fundamentals\Lesson 3. Valuation`
94 frame files, 20 inspected with the Read tool (plus zoomed crops of the same 20 for exact-pixel legend/date reading). All numbers below were read directly off the images; nothing was inferred from formulas.

## Legend layout (discovered, applies to every frame in this lesson)

The indicator's pane legend always renders four tokens after the title string, in this fixed order:
`<zero-line: always "0.00000", dimmed grey>  <Reference Symbol 1 value, BLUE>  <Reference Symbol 2 value, YELLOW>  <Reference Symbol 3 value, MAGENTA/PURPLE>`

When a reference's "Show Reference Symbol N" box is unchecked, its slot in the legend shows a "Ø" (circle-slash / hidden) icon instead of a number, and its line is not drawn in the pane. This mapping (position 2=Ref1=blue, position 3=Ref2=yellow, position 4=Ref3=magenta) is directly confirmed by **frame_000786** (see Settings dialogs / Verification anchors below), where all three references are checked simultaneously and all three colors + values appear at once, in title order (ZB1!, GC1!, DXY).

## Settings dialogs

| Frame | Symbol | Ref 1 | Ref 2 | Ref 3 | Show1 | Show2 | Show3 | ROC | Rescale Len | Rescale Max | Rescale Min | Upper Thr | Lower Thr |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| frame_000808 | AUDUSD 1D (FXCM) | CBOT_DL:ZB1! | COMEX_DL:GC1! | TVC:DXY | ✅ | ✅ | ✅ | 10 | 100 | 100 | -100 | 75 | -75 |
| frame_001240 | AAPL 1D (NASDAQ) | CBOT_DL:ZB1! | COMEX_DL:GC1! | TVC:DXY | ☐ (unchecked) | ☐ (unchecked) | ✅ (still checked at this moment) | 10 | 100 | 100 | -100 | 75 | -75 |

Notes on frame_001240: this is the dialog as opened, BEFORE Bernd's edit. It shows the settings carried over from the prior AUDUSD session (only Ref3/DXY checked). Transcript at this timestamp (20:39): *"I go back into the settings. We're going to unselect reference symbol three, which is the dollar."* No frame exists between 001240 and 001253 (checked file listing — the next file on disk is 001253), so the moment he also (necessarily) re-checks Ref 1 is not directly captured. See "AAPL toggle answer" below for how this was resolved from the resulting chart.

## Per-symbol configuration

| Symbol | Timeframe | Refs shown (confirmed from legend/chart, not just dialog) | ROC | Rescale Len/Max/Min | Thresholds | Source frames |
|---|---|---|---|---|---|---|
| AUDUSD (FXCM) | 1D | Ref1(ZB1!)+Ref2(GC1!)+Ref3(DXY) all three, simultaneously | 10 | 100 / 100 / -100 | 75 / -75 | frame_000786 (all 3 lines+values), frame_000808 (dialog, all 3 checked) |
| AUDUSD (FXCM) | 1D | Ref3 (DXY) ONLY — Ref1 and Ref2 unchecked | 10 | 100 / 100 / -100 | 75 / -75 | frame_000980 onward through frame_001146 (single magenta line, legend value always in the 4th/last slot) |
| AAPL (NASDAQ) | 1D | Ref3 (DXY) ONLY, still carried over from AUDUSD, immediately BEFORE Bernd edits settings | 10 | 100 / 100 / -100 | 75 / -75 | frame_001220 (single magenta line, ROC still 10 in title) |
| AAPL (NASDAQ) | 1D | **Ref1 (ZB1!, Bonds) ONLY** — this is the config Bernd actually analyzes AAPL with | **13** | 100 / 100 / -100 | 75 / -75 | frame_001253 through frame_001375 (single BLUE line; title reads "...DXY 13 100 100 -100 75 -75"; legend value consistently sits in the Ref-1/2nd slot, Ref2 and Ref3 slots show "Ø") |

### AAPL toggle answer (Task item 1)

**The single line plotted for AAPL is Reference Symbol 1 (CBOT_DL:ZB1!, the 30-year T-Bond), not DXY.** This is not a guess — it is read directly from two independent signals across frames 001253–001375:
1. **Line color = blue.** Frame_000786 (AUDUSD, all 3 refs on at once) unambiguously establishes blue = Ref1/ZB1!, yellow = Ref2/GC1!, magenta = Ref3/DXY, by matching each color to its numeric value in title-symbol order.
2. **Legend slot position.** In every AAPL frame after the settings edit, the visible number sits in the *second* legend slot (immediately after the dimmed "0.0000" zero-line token), with "Ø" hidden-icons in slots 3 and 4. That second slot is the Ref-1 slot per the same frame_000786 mapping.

So: the transcript's "we're going to unselect reference symbol three, which is the dollar" is confirmed (DXY got turned off), but the dialog frame (001240) only captured him unchecking Ref3 — it must ALSO have been the moment he checked Ref1, since going from "only Ref3 checked" to "nothing checked" would leave zero lines, and the resulting frames clearly show one blue line. No frame captures the intermediate click, but the resulting chart is unambiguous about which reference ends up visible: **Ref 1 (Bonds/ZB1!)**, not Ref3(DXY) and not Ref2(Gold). If a README currently assumes the AAPL example is showing DXY, that is incorrect — it is showing Bonds (ZB1!).

Also note: the ROC Length was changed from 10 to 13 for AAPL in the same settings visit (confirmed by title string change, frame_001253 onward: `...DXY 13 100 100 -100 75 -75`).

## Verification anchors

All "legend_value" entries below are **crosshair legend values** (the number shown in the indicator pane's top-left legend line, next to the title, at the crosshair position), NOT the right-axis "last value" badge. Right-axis badges are noted separately as unverifiable-today where visible.

| frame | timestamp | symbol | timeframe | date_on_chart (crosshair tooltip) | line (colour / ref) | legend_value | confidence | notes |
|---|---|---|---|---|---|---|---|---|
| frame_000786 | 0:13:05 | AUDUSD (FXCM) | 1D | Fri 17 Jan '25 | Ref1 ZB1! (blue) | **-1.44193** | high | all 3 refs shown simultaneously — this is the frame that establishes the color/slot mapping |
| frame_000786 | 0:13:05 | AUDUSD (FXCM) | 1D | Fri 17 Jan '25 | Ref2 GC1! (yellow) | **-67.84738** | high | same frame as above |
| frame_000786 | 0:13:05 | AUDUSD (FXCM) | 1D | Fri 17 Jan '25 | Ref3 DXY (magenta) | **5.70231** | high | same frame as above |
| frame_001017 | 0:16:56 | AUDUSD (FXCM) | 1D | Wed 15 May '24 | Ref3 DXY only (magenta) | **72.67503** | high | Ref1/Ref2 legend slots show "Ø" (hidden) |
| frame_001028 | 0:17:07 | AUDUSD (FXCM) | 1D | Thu 23 Nov '23 | Ref3 DXY only (magenta) | **69.38354** | high | |
| frame_001047 | 0:17:26 | AUDUSD (FXCM) | 1D | Thu 12 Sep '24 | Ref3 DXY only (magenta) | **?2.83218** (first digit obscured) | low — AMBIGUOUS | the on-screen mouse-cursor crosshair icon sits directly over the leading digit/sign; only "2.83218" with something before the "2" is legible. Could plausibly be "72.83218" (consistent with neighboring readings) but the leading character is genuinely not readable — flagging rather than guessing. |
| frame_001066 | 0:17:45 | AUDUSD (FXCM) | 1D | Thu 24 Oct '24 | Ref3 DXY only (magenta) | **-58.05168** | high | |
| frame_001092 | 0:18:11 | AUDUSD (FXCM) | 1D | Tue 27 Aug '24 | Ref3 DXY only (magenta) | **86.07036** | high | |
| frame_001128 | 0:18:47 | AUDUSD (FXCM) | 1D | Wed 26 Jun '24 | Ref3 DXY only (magenta) | **-7.92290** | high | |
| frame_001146 | 0:19:05 | AUDUSD (FXCM) | 1D | Fri 14 Jun '24 | Ref3 DXY only (magenta) | **-19.42793** | high | |
| frame_001268 | 0:21:07 | AAPL (NASDAQ) | 1D | Fri 10 Jan '25 | Ref1 ZB1! only (blue) | **-54.05** | high | title/ROC=13 config |
| frame_001302 | 0:21:41 | AAPL (NASDAQ) | 1D | Wed 31 Jul '24 | Ref1 ZB1! only (blue) | **-54.26** | high | |
| frame_001316 | 0:21:54 | AAPL (NASDAQ) | 1D | Thu 07 Mar '24 | Ref1 ZB1! only (blue) | **-90.95** | high | note: transcript at this timestamp says "Silver here, we were in a very long downtrend" but the on-screen chart title still reads "Apple Inc · 1D · NASDAQ" — see Frames inspected but unusable / discrepancy note below |
| frame_001326 | 0:22:05 | AAPL (NASDAQ) | 1D | Mon 04 Dec '23 | Ref1 ZB1! only (blue) | **-46.90** | high | |
| frame_001330 | 0:22:09 | AAPL (NASDAQ) | 1D | Wed 08 Nov '23 | Ref1 ZB1! only (blue) | **-5.14** | high | |
| frame_001343 | 0:22:22 | AAPL (NASDAQ) | 1D | Wed 25 Oct '23 | Ref1 ZB1! only (blue) | **-35.64** | high | |
| frame_001375 | 0:22:54 | AAPL (NASDAQ) | 1D | Fri 03 Nov '23 | Ref1 ZB1! only (blue) | **-22.97** | high | |

### Right-axis "last value" badges seen in passing (NOT verifiable today — for reference only)

- frame_001017: right-axis badge shows 34.92446 (magenta) — this is the indicator's current/last-bar value on the AUDUSD chart at the time of recording, not tied to the crosshair date.
- frame_001066: right-axis badge shows 35.58420 (magenta).
- frame_001092: right-axis badge shows 35.23047 (magenta) plus a second badge 92.80061 (grey, appears to be a price-scale artifact, not the indicator).
- frame_001253 (AAPL): right-axis badges 0.0000 and -7.97 (blue) — last value of Ref1 at the time of recording.
- frame_001330 (AAPL): right-axis badges 18.84 (grey) and 31.54/36.15 (blue) appear across nearby frames — last-bar value drifting as chart is panned; not a fixed data point.

## Frames inspected but unusable

- frame_000980, frame_000990: show the AUDUSD chart with only the DXY (Ref3, magenta) line after Bernd unselects Ref1/Ref2, but no crosshair/date tooltip is active in these frames — useful for confirming the single-line-remaining state and legend layout, not as a dated data point.
- frame_001220, frame_001222: AAPL chart just before the settings edit (still showing the carried-over "Ref3/DXY only, ROC=10" config from AUDUSD) — useful for the "before" state in the AAPL toggle analysis, no usable crosshair date.
- frame_001240: settings dialog open for AAPL — captured mid-edit (Ref3 still checked in this specific frame, Ref1/Ref2 still unchecked) — this is the "before" moment of the edit, not the final state. No frame captures the "after" checkbox state directly (see AAPL toggle answer discussion).
- frame_001253: shows the resulting AAPL chart with Ref1/blue line and ROC=13 title, but the legend row in this specific frame is in its "hover toolbar" state (eye/target/braces/trash icons) rather than showing crosshair values, because the mouse is hovering over the legend itself, not the chart.
- frame_000753/754/763/772/782: AUDUSD intro / loading indicator sequence — no numeric legend data yet (indicator still loading or dialog not yet open).
- frame_001204/1213/1218/1221: transition frames from AUDUSD to AAPL (symbol search box, chart still loading) — no usable legend data.

## Discrepancy note: "Silver" transcript mention (timestamp 0:21:54, frame_001316)

Transcript text at frame_001316 reads: *"But we became undervalued and then we got this massive rally out of it. Silver here, we were in a very long downtrend."* However, the on-screen chart at this exact frame — and at every frame checked before and after it through frame_001392 ("With that, I want to close this practical application") — is still titled "Apple Inc · 1D · NASDAQ". No symbol switch to a Silver instrument (SI1!, XAGUSD, etc.) was observed anywhere in the 94 frames of this lesson. This is likely a Whisper transcription artifact (misheard word) rather than an actual on-screen symbol change — flagging so the anchors aren't mis-attributed to a Silver chart that was never shown.
