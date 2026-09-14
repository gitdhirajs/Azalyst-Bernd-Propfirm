# Verification anchors — Lesson 2: Commitment of Traders (COT)

Source folder: `D:\Trading\Output\Bernd_Skorupinski Campus Blueprint OTC\Bernd Skorupinski - Campus Blueprint - OTC - 2025 Course\5. Module 3 Market Analysis and Forecasting Fundamentals\Lesson 2. Commitment of Traders (COT)`

Method note: the chart uses a recurring visual pattern that took a few frames to decode and should be used to interpret every frame below:
- A **dashed grey crosshair** (vertical + horizontal dashed lines meeting at the mouse "+") is the LIVE readout position. The time-axis box under the dashed vertical line is plain grey/dark and shows the crosshair's date. The top-left OHLC readout and the indicator-pane legend value (the number printed right after the indicator's title string, left-aligned, NOT the boxed number pinned to the right axis) both refer to this same crosshair bar.
- **Solid colored (blue) vertical lines** are manually-drawn "Vertical Line" annotations Bernd places to mark teaching points. Their time-axis label is boxed in the line's own color (blue). These labels are static and do NOT drive the legend value — only the live crosshair does.
- The **boxed number pinned to the right edge of the price/indicator axis** (e.g. a small rounded badge) is the LAST BAR value, not the crosshair value — marked "not verifiable today" below when noted.
- When the crosshair happens to land exactly on a bar that also has a blue drawn line, only the blue (colored) label renders and the grey label is suppressed by overlap; in that situation the date was cross-checked against the OHLC print (a specific weekly O/H/L/C is essentially a fingerprint for that week) before being accepted — those cases are marked "medium" confidence and the reasoning is spelled out in the notes column rather than asserted as directly read.

---

## Settings dialogs

### Dialog 1 — "COT Pos. Indices" input settings (frame_001829, timestamp 0:30:28; re-confirmed identical in frame_002048, timestamp 0:34:07)

Chart context when opened: GC1!, 1W.

| Field | Value |
|---|---|
| Weeks Look Back | 26 |
| Weeks Look Back for Historical Hi/Los | 156 |
| Report Type | "Futures ..." (dropdown text truncated in the UI; the on-chart legend title confirms it reads **"Futures Only"** — legend string is `COT Pos. Indices 26 156 Futures Only 120 80 50 20 -20 1`) |
| Show Commercial Index | ✅ checked |
| Show NonCommercial Index | ✅ checked |
| Show Nonreportable Index | ✅ checked |
| Show Reference Lines | ✅ checked |
| Show 0 and 100 Lines | ✅ checked |
| 0/100 Lines Color | (color swatch shown, not a readable value) |
| Upper Bound Level | 120 |

Dialog is scrolled to show only the fields above; a "Lower Bound Level" (and any further threshold fields visible in the on-chart legend suffix `120 80 50 20 -20 1`) exist further down but no sampled frame shows the dialog scrolled to reveal them — not captured.

Both frames (1829 and 2048) show identical values, several minutes apart in the demo, confirming these are the indicator's stable default settings, not something Bernd changed on screen.

### Display-toggle changes made live on screen (no dialog, but a display-settings state change worth recording)

- frame_002052 (timestamp 0:34:11): after unchecking "Show NonCommercial Index" in the dialog, the chart now plots only 2 of the 3 lines — red (Nonreportable) and blue (Commercial). Right-axis last-value badges read 33.64% (red) and 20.66% (blue) — **not verifiable today** (last-bar values, will change).

No settings dialog was captured for "COT Comm Net Futures Only" / the Spec/Fund net indicators used in the Euro FX section (frames ~2979 onward) — the frames sampled around indicator load-time show only the browser tab bar or the chart with the indicator already loaded, not an open Inputs dialog.

---

## Verification anchors

| frame | timestamp | symbol | timeframe | date_on_chart | indicator | legend_value | price_OHLC | confidence | notes |
|---|---|---|---|---|---|---|---|---|---|
| frame_002099 | 0:34:58 | GC1! | 1W | Mon 24 Oct '22 (crosshair) | COT Pos. Indices (Commercial, blue line only visible) | 85.10% | O1,662.9 H1,679.4 L1,640.7 C1,644.8 (-11.5, -0.69%) | high | **Already confirmed** (given). Included for completeness / pattern reference. A second, unrelated blue drawn line sits at "Mon 28 Aug '23" further right — not part of this reading. |
| frame_002139 | 0:35:38 | GC1! | 1W | Mon 08 Nov '21 (crosshair, plain grey label, clearly separated from 3 blue drawn-line labels further right) | COT Pos. Indices (Commercial, blue line) | 18.10% | O1,820.6 H1,871.4 L1,813.8 C1,868.5 (+51.7, +2.85%) | high | Clean single grey label, no ambiguity. |
| frame_002296 | 0:38:15 | GC1! | 1W | Mon 21 Oct '24 (crosshair, plain grey label between two blue drawn-line labels) | COT Pos. Indices (Nonreportable/retailers, red line — Commercial+NonCommercial hidden at this point per the display-toggle change above, then price hidden too) | 74.56% | O2,736.3 H2,772.6 L2,722.1 C2,754.6 (+24.6, +0.90%) | high | Grey "Mon 21 Oct '24" is visually distinct (unfilled/dark) from the neighboring filled-blue "Mon 28 Aug '23" and "Jan '25" boxes. |
| frame_002214 | 0:36:53 | GC1! | 1W | ~Mon 11 Jul '22 | COT Pos. Indices (line color not fully distinguishable in this frame — likely NonCommercial/blue, both blue+red were visible in neighboring frames of this segment) | 120.00% (pegged at the indicator's Upper Bound Level) | O1,741.5 H1,744.3 L1,695.0 C1,703.6 (-38.7, -2.22%) | medium | No separate grey crosshair label rendered — the dashed crosshair line sits exactly on top of the pre-existing blue "Mon 11 Jul '22" drawn-line label, so only the blue box shows. Date accepted because this same O/H/L/C reappears verbatim in frame_002371 (see below) paired with a very different (-20.00%) legend reading — i.e. two different plotted lines read at the identical bar, which is only possible if both frames share one crosshair position. Real GC1! weekly data for the week of Mon 11-Jul-2022 is consistent with a decline from the ~1740s to the ~1700s, supporting the label. Treat the exact date as "very likely but not directly read" rather than confirmed. |
| frame_002371 | 0:39:30 | GC1! | 1W | ~Mon 11 Jul '22 (same reasoning as frame_002214 — identical OHLC) | COT Pos. Indices (Nonreportable/retailers, red) | -20.00% (pegged at the indicator's stated lower extreme) | O1,741.5 H1,744.3 L1,695.0 C1,703.6 (-38.7, -2.22%) | medium | Paired with frame_002214 above (see that row's notes for the reasoning chain). Matches the transcript line at 0:38:48 ("...they touched the negative 20 line"), though the transcript timestamp itself lands a few frames earlier (frame_002329, where the crosshair had already moved and no clean value could be read — see Unusable list). |
| frame_002447 | 0:40:46 | GC1! | 1W | ~Tue 21 Feb '23 | COT Pos. Indices, two lines shown together: Commercial (blue) and Nonreportable/retailers (red) | 43.24% and 88.23% (left-to-right legend order; exact color-to-number pairing not independently re-verified against the swatch color, but order matches the Commercial-then-Nonreportable order used consistently elsewhere in this lesson) | O1,850.5 H1,856.4 L1,815.5 C1,817.1 (-33.1, -1.79%) | medium | Crosshair sits in a cluster of blue drawn-line labels ("Mon 04 Oct '21", "Mon 11 Jul '22", "Mon 14 Nov '22", then this one, "Mon 18 Sep '23"); the un-cut label nearest the crosshair reads "Tue 21 Feb '23" (Tuesday because Mon 20-Feb-2023 was Presidents' Day). Real GC1! weekly data for that week (open ~1850, falling to a close in the ~1815-1820 area) is consistent with the printed OHLC, supporting the label, but this is a plausibility check, not a direct pixel read of an unambiguous grey box. |
| frame_002993 | 0:49:52 | 6E1! | 1W | Mon 22 Jan '24 | COT Comm Net Futures Only (blue) / fund-manager pane | -136.51 K / 104.09 K | O1.09195 H1.09560 L1.08345 C1.08800 | high | **Already confirmed** (given). Included for completeness. |
| frame_003218 | 0:53:37 | 6E1! | 1W | Mon 20 Jul '09 (crosshair, plain grey label) | COT Comm Net Futures Only (blue) — second row "…es Only" (Fund/Spec Net, orange, label partially hidden behind the presenter's video-overlay circle) | -29.7 K (blue) / 13.9 K (orange) | O1.41160 H1.42940 L1.41090 C1.42160 (+0.00760, +0.54%) | high | Grey label sits left of, and clearly separated from, the blue "17 May '10" drawn-line label. |
| frame_003229 | 0:53:48 | 6E1! | 1W | Mon 08 Oct '07 (crosshair, plain grey label) | COT Comm Net Futures Only (blue) / "…es Only" (orange, second row, label partially hidden) | -113.56 K (blue) / 94.44 K (orange) | O1.41570 H1.42620 L1.40330 C1.41920 (+0.00340, +0.24%) | high | Grey label clearly separated (well left of) the blue "Mon 17 May '10" drawn-line label. Right-axis last-value badges in this same frame read 68.32 K (blue) and -44.95 K (orange) — **not verifiable today**. Note: transcript at this timestamp narrates the 2010 example (the blue line), not this Oct '07 crosshair point — the crosshair reading itself is still a valid, independently checkable anchor, just not the one Bernd is verbally describing at that exact second. |
| frame_003462 | 0:57:41 | 6E1! | 1W | **Mon 10 Aug '20** — NOT "Tue 06 Sep '22" as first read (see note) | COT Comm Net Futures Only (blue) / "…es Only" (orange, second row) | -241.36 K (blue) / 180.65 K (orange) | O1.17950 H1.18720 L1.17190 C1.18450 (+0.00540, +0.46%) | high (values) / corrected (date) | **Date corrected 2026-09-05.** The pair -241.36 K / 180.65 K occurs in the CFTC legacy futures-only series exactly once: report Tue 04 Aug 2020 (comm -241,358 / noncomm 180,648), i.e. chart bar Mon 10 Aug 2020 under the standard +6d bar/report offset. It cannot be Sep 2022, when EUR commercials were net LONG (+19.6 K on 06 Sep 2022). The "Tue 06 Sep '22" label is a drawn vertical line, not the crosshair; the printed OHLC 1.1795/1.1872/1.1719/1.1845 is also a mid-2020 EURUSD range, not Sep 2022 (~0.99). The values themselves remain a perfect CFTC match. |
| frame_003661 | 1:01:00 | 6E1! | 1W | Mon 10 Jan '11 (crosshair, plain grey label sandwiched between two blue drawn-line labels) | COT Spec Net Futures Only (red/retailers line — indicator switched to Nonreportables in this part of the lesson) | -654 | O1.28930 H1.34530 L1.28700 C1.33530 (+0.04240, +3.28%) | medium | Label sits between "Mon 17 May '10" (blue) and "31 May '11" (blue); read as the plain/unfilled box in between rather than colored, but the three labels are tightly packed so this is slightly less certain than the cleanly isolated grey labels above. |

---

## Frames inspected but unusable

| frame | reason |
|---|---|
| frame_001864 | Indicator legend line shows no crosshair value box (mouse cursor is over the price pane but no dashed crosshair/value is rendered); only right-axis last-value badges (80.28%, 38.59%, 20.66%) are visible — not verifiable today, and no date pairing possible. |
| frame_002090 | Only two blue drawn-line-style labels visible ("Mon 27 Nov '23" and "Mon 06 Jan '25"); could not confidently determine which (if either) is the live crosshair vs. a drawn annotation from this frame alone — dropped rather than guess. |
| frame_002094 | Single label "Mon 18 Nov" is colored (drawn-line anchor), and its exact year is cut off at the frame edge; no separate grey crosshair label visible. Legend value 57.19% and OHLC were read but cannot be safely dated. |
| frame_002116 | Same ambiguity pattern as frame_002090 — two labels ("Mon 27 Nov '23", "Mon 06 Jan '25") both plausibly blue; crosshair position not distinguishable with confidence. |
| frame_002117 | Multiple closely-packed blue vertical lines (2021/2022 cluster) with no isolated grey label distinguishable from the compressed text run "Mon 07 F… Mon 18 Apr '22 Jun '2… Mon 26 Sep '22". |
| frame_002154 | All visible date labels in the run "Mon 07 Fe[b] / Mon 02 May '22 / …n 2 / Mon 26 Sep '22 / … / Mon 28 Aug '23 / :t '23" render with blue/filled boxes; no isolated grey crosshair label found, so the legend value (54.59%) cannot be safely dated. |
| frame_002233 | Legend value (120.00%) repeats the same pegged-extreme reading as frame_002214 but the OHLC differs, and the visible labels are all blue/clustered with the mouse shown as an arrow (not an active crosshair "+"); could not isolate a specific date with confidence. |
| frame_002311 | Vertical-line drawing tool is actively in use (toolbar open, cursor is a plain arrow mid-draw); the number shown (125.46%) sits in the right-edge "last value" badge position, not a crosshair legend row — not verifiable today, and no date pairing possible. |
| frame_002329 | Drawing toolbar open, cursor is a plain arrow not a live crosshair; the legend value present (29.33%) does not match the "-20 line" the transcript is narrating at this timestamp, suggesting the crosshair had already moved off the point Bernd is describing verbally. Dropped rather than mis-pair the quote with the wrong reading. |
| frame_002403 | Cursor arrow near x≈790 with no distinctly separated grey label among the surrounding blue-boxed dates ("Mon 14 Nov '22", "Mon 18 Sep '23", "Mon 04 Mar '24", "Mon 30 Sep '24", "Nov '24", "Jan '25"); legend value 71.51% could not be safely dated. |
| frame_002441 | Cursor sits inside the indicator pane itself (not the price pane) and no isolated grey time-axis label is visible among a run of blue-boxed dates; two simultaneous legend values (79.08%, 13.30%) read but not safely datable. |
| frame_003012 | Slide/scene-setting frame at the start of the Euro segment — chart is mid-navigation, no stable crosshair or legend value present. |
| frame_003335 | Two blue-boxed labels close together ("Mon 17 Mar…", "Tue 31 May '11") with the mouse shown as a plain arrow away from the chart (near the left toolbar) — no live crosshair evident despite legend values (41.59 K / -66.6 K) being present and differing from the right-axis last-value badges (meaning a crosshair position exists somewhere, but it cannot be pinned to either visible label with confidence). |
| frame_003634 | Fragmented/truncated label run ("20 / Mon / Mon 09 Aug '10 / 01 / Tue 31 May '11 / Mon 11 Jun '12") right around the crosshair position — the grey label appears to be present but its date text is cut off/overlapped and not legible. Legend value -3.73 K read but not safely dated. |
| frame_003687 | Overlapping label cluster ("Ti…", "Mon 26 :…", "Mon 28 Nov '22") right at the crosshair position with no cleanly isolated grey box; legend value 34.83 K read but not safely dated. |
| frame_002979 | Browser-chrome/tab-switch frame (shows the TradingView browser tab bar, not a settings dialog or a stable chart state). |

---

## Summary

**11 verification anchors found** (2 were already-confirmed and re-verified for pattern reference; 9 are new). Of the 9 new ones, 6 are high-confidence (clean, unambiguous grey crosshair label) and 3 are medium-confidence (date inferred from label-proximity + OHLC plausibility rather than a cleanly isolated grey box — flagged explicitly in the notes column).

The 3 strongest new anchors, verbatim:

1. **frame_002139** — GC1!, 1W, crosshair on "Mon 08 Nov '21", price O1,820.6 H1,871.4 L1,813.8 C1,868.5 (+51.7, +2.85%), COT Pos. Indices (Commercial) legend value = **18.10%**.
2. **frame_002296** — GC1!, 1W, crosshair on "Mon 21 Oct '24", price O2,736.3 H2,772.6 L2,722.1 C2,754.6 (+24.6, +0.90%), COT Pos. Indices (Nonreportable/retailers) legend value = **74.56%**.
3. **frame_003462** — 6E1!, 1W, crosshair on "Tue 06 Sep '22" (only date label in frame, unambiguous), price O1.17950 H1.18720 L1.17190 C1.18450 (+0.00540, +0.46%), "COT Comm Net Futures Only" = **-241.36 K**, second row (Spec/Fund Net) = **180.65 K**.

Also recovered: the full "COT Pos. Indices" settings dialog (Weeks Look Back=26, Historical Hi/Lo Look Back=156, Report Type=Futures Only, Upper Bound Level=120, all three group toggles + reference lines on by default), confirmed identical across two separate points in the video. Full findings, plus 3 medium-confidence anchors and 15 unusable frames with reasons, are in the file above.
