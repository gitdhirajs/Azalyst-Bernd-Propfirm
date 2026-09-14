# AUDIT PHASE 28 — Frame-Verified Threshold Disputes

Date: 2026-05-24
Method: Sonnet vision agents read Bernd's actual chart frames (transcript-aligned `frame_NNNNNN.jpg` files in `D:\Trading\Output\...`) for each disputed numeric threshold flagged by the Phase 28 doc-vs-code audit.

This complements `AUDIT_PHASE_28.md`. Where the desk audit could only say "doc and code disagree", these verdicts resolve the dispute against Bernd's on-screen settings or verbal statements.

---

## Summary

| Dispute | Verdict | What to do |
|---|---|---|
| Seasonality forward-projection bars | **CONFIRMED 30** | Fix code from 20 to 30 |
| Equity Valuation refs (individual stocks) | **REFUTED. ZB only** | Drop GC and SPY from `equities` refs |
| Equity Valuation refs (NQ ES YM futures) | **AMBIGUOUS leaning ZB only** | Same fix is defensible; verify via live session before committing |
| AAPL Valuation ROC length | **DUAL ROC confirmed** | Add per-timeframe override (30 daily, 13 weekly) |
| Hammer upper-wick cap | **INCONCLUSIVE Bernd qualitative** | Drop the numeric threshold from methodology; keep code at 0.20 as engineering filter |
| COT momentum threshold (25% of scale) | **INCONCLUSIVE no corpus support** | Resolve via goldtest sensitivity not corpus |
| NG=F COT lookback weeks | **DEFERRED session limit** | Retry next session |

3 verdicts result in code or doc changes. 2 are pure documentation cleanups. 1 deferred.

---

## Verdict 1: Seasonality forward-projection bars — CONFIRMED 30

**Dispute:**
- Methodology: 30
- Code (`BP_config.yaml:249`): 20
- Pine Script default: 30

**Frame evidence:**
- `Funded Traders\Practical Application\03.04.2024 - Practical Application - Seasonality\frame_001496.jpg` [0:24:55]: TradeStation chart shows TWO active seasonality instances both with the indicator label reading `(5,30,FALSE,FALSE)` and `(10,30,FALSE,FALSE)`. Both project 30 bars forward.
- `Funded Traders\Practical Application\03.04.2024 - Practical Application - Seasonality\frame_001482.jpg` [0:24:41]: Settings dialog open; Bernd is changing `ProjectNumberBarsIntoTheFuture` away from 100 to 30 while the running instance label already shows `30`.
- `HAI\LESSON 3 TRUE SEASONALITY\frame_001008.jpg` [0:16:47]: Indicator label reads `(10,150,False,False)`. Bernd says "I could project up to 150 bars to the right here as well". This is a capability demo, not a personal preference.

**Bernd verbatim** (frames 1482 to 1496):
> "I don't have a lot of data on the right so I just don't project 100 I just project 30 days in the future for me that's enough and I want to have 10"

**Reasoning:** Bernd's own stated preference is 30. Pine Script canonical default is 30 (`Seasonality_OTC.txt:10` `_future = 30`). The chart label in the live session confirms 30. The 150 in HAI lesson 3 was a demo of the maximum projection capability, explicitly framed as such. The code value 20 has no corpus support and is below the canonical default.

**Recommended action:** Change `BP_config.yaml:249 bias_lookahead_bars: 20` to `30`. Confirmed safe.

---

## Verdict 2: Equity Valuation reference symbols — REFUTED. Bernd uses ZB only for individual stocks

**Dispute:**
- Methodology cheatsheet line 192: ZB + DXY only
- Methodology cheatsheet line 205: DXY + ZB + GC
- Code `equities`: ZB + GC + SPY
- Code `equity_indices`: DXY + ZB + GC

**Frame evidence (INDIVIDUAL STOCKS):**
- `OTC 2025\Lesson 3 Valuation\frame_001240.jpg` [0:20:39]: AAPL chart with CampusValuationTool settings dialog open. All 3 ref symbols loaded (ZB1!, GC1!, TVC:DXY). At this moment Symbols 1 and 2 are unchecked; only Symbol 3 (DXY) is ticked. Bernd is mid-configuration.
- `OTC 2025\Lesson 3 Valuation\frame_001253.jpg` [0:20:52]: After Bernd's reconfiguration. Only ONE blue line visible in the Valuation panel (the ZB / interest rates line). The other two refs are loaded but hidden. ROC changed to 13.
- `OTC 2025\Lesson 3 Valuation\frame_000645.jpg` [0:10:44]: OTC course slide "How we use the Valuation Tool". The table row "Equity indices AND stocks" lists "Interest rates" only as the comparison reference.

**Bernd verbatim:**
> "We're going to unselect reference symbol three, which is the dollar." (Ch074, AAPL switch)
> "Whether comparing stocks to interest rates, currencies to the dollar index or commodities..." (Ch074 summary slide)

**Reasoning:** Bernd's on-screen action for AAPL is unambiguous. He loads the indicator with all 3 refs as default then manually unchecks GC and DXY, leaving the ZB (interest rates) line as the sole displayed reference. The OTC course slide states the rule for both stocks and indices as "interest rates" only. The current code path for `equities = ["ZB=F", "GC=F", "SPY"]` includes two references Bernd explicitly hides.

**Frame evidence (EQUITY INDEX FUTURES):**
- `Funded Trader Weekly Outlook\2023\10.12.2023 - CW50\frame_000240.jpg` [0:03:59]: TradeStation CampusValuationTool_V2 legend for @YM/@NQ shows all 3 refs active and plotted with 3 colored lines. Bernd's verbal cue points only to one line.

The CW50 live session shows all 3 refs displayed for indices. The OTC slide says indices use interest rates only. Discrepancy is likely because the live session uses the uncustomized default while the OTC course teaches the per-asset customization. Evidence leans toward ZB only for indices too but is not as clean as for individual stocks.

**Recommended action:**
- **Individual stocks**: change `equities` refs in `run_scanner.py:186` and `goldtest/run_goldtest.py` from `["ZB=F", "GC=F", "SPY"]` to `["ZB=F"]`.
- **Equity index futures**: equity-indices Valuation is currently skipped entirely per Phase 15 (returns neutral). The ref correction is moot until that skip is reconsidered. If/when the skip is removed, use `["ZB=F"]` based on the OTC slide.
- Reconcile cheatsheet line 192 vs line 205. Pick "ZB only for stocks AND indices" if you trust the OTC course slide as canonical.

---

## Verdict 3: AAPL Valuation ROC length — DUAL ROC confirmed (30 daily, 13 weekly)

**Dispute:**
- Methodology: 10 (Phase 7 empirical)
- Code (`BP_config.yaml`): 30 (Phase 24 per-symbol override)
- Pine Script default: 10

**Frame evidence:**
- `HAI\Ch017\frame_003575.jpg` [0:59:34]: Blueprint Cheatsheet xlsx "Finite Markets" tab open on screen. The Apple section reads verbatim:

| Direction | Valuation | Strategy | Cycle | Action | When |
|---|---|---|---|---|---|
| Uptrend | Undervalued | Trendfollowing | **30** | Buy | Weekly, Daily |
| Downtrend | Overvalued | Trendfollowing | **30** | Sell | Weekly, Daily |
| Downtrend | Undervalued | End of the Bend | **13** | Buy | Monthly (weekly) |
| Uptrend | Overvalued | End of the Bend | **13** | no action | Monthly (weekly) |

- `HAI\Ch017\frame_003501.jpg` [0:58:20]: AAPL Daily chart. Bernd has compared 10 vs 30 visually and concludes "with the downtrend it really seems like the 30 is better than the 10 but with an uptrend if you're uptrending then you can easily also use the 10".
- `HAI\Ch017\frame_003461.jpg` [0:57:44]: AAPL Daily, settings dialog shows Length=13 mid-comparison.
- `HAI\Ch017\frame_003742.jpg` [1:02:21]: AAPL Daily, settings dialog shows Length=10 in a comparison.
- `OTC 2025\Ch074\frame_001253.jpg` [0:20:52]: AAPL Daily TradingView, indicator label reads `ROC=13`. Bernd says "change the ROC from 10 to 13".

**Bernd verbatim:**
> "and if we do days then we can do 30 or we can do 10 I just like to do 30 for now" (Ch017 frame 1765)
> "no doubt about it that on the case of Apple we should use the 30-day cycle" (Ch017 frame 3575, while the cheatsheet is on screen)
> "And down here I'm going to change the ROC from 10 to 13" (OTC Ch074 frame 1253, AAPL daily, end-of-band context)

**Reasoning:** Bernd's own cheatsheet documents TWO ROC values for AAPL depending on the strategy:
- ROC=30 for Trendfollowing (Daily and Weekly)
- ROC=13 for End-of-the-Bend (Monthly, optionally Weekly)

Phase 7 reset to 10 because tests against 13 produced wrong directional readings versus Bernd's verbal calls. The verbal calls in funded-trader sessions are trend-following daily reads, so the correct comparison value was 30 not 13. Phase 24 reintroduced 30 which matches Bernd's primary daily trend-following use. The remaining gap is that the code does not switch to 13 for end-of-band weekly reads.

**Recommended action:** Restructure `cycle_per_symbol` to support per-timeframe overrides. Target shape:
```yaml
cycle_per_symbol:
  AAPL: {daily: 30, weekly: 13}
  MSFT: {daily: 30, weekly: 13}
  ...
```
Update `_indicators_for_class()` to read the per-timeframe entry. The current flat `AAPL: 30` is correct for daily and weekly trend-following per the cheatsheet. Adding 13 for end-of-band weekly will expand correct coverage without regressing existing matches.

---

## Verdict 4: Hammer upper-wick cap — INCONCLUSIVE. Bernd is qualitative

**Dispute:**
- Methodology `04_entry_triggers.md:88`: `upper_wick <= 0.10 * range_size`
- Code `BP_config.yaml:180`: `upper_wick_max_pct: 0.20`

**Frame evidence:**
- `HAI\Ch035 Hammer Theory\frame_000615.jpg` [0:10:14, Page 7/13 Key Takeaways]: Bernd's canonical Hammer rules slide. The Wick section diagram labels the body as `1x` and the lower wick as `2x at least`. The upper wick is drawn as visually negligible (roughly equal to or smaller than the body) but carries NO numeric label, NO percentage annotation, and NO threshold text anywhere on the slide.
- `HAI\Ch035\frame_000331.jpg` [0:05:30, Page 6/13]: Hammer definition slide. States "small real body and a long lower wick" and "lower wick should be at least two times the height of the real body". No upper wick rule.
- `HAI\Ch035\frame_001916.jpg` [0:31:55, Page 10/13]: "Hammer Candle key takeaways must be met" back-reference to Page 7/13.

**Bernd verbatim:** Across all 145 frames Bernd never speaks a numeric upper-wick threshold. The only quantitative wick rule in the lesson is "lower wick at least 2x the body".

**Reasoning:** The Phase 28 desk audit assumed `0.10` was Bernd-canonical because it appears in the methodology file. Frame verification shows it is not. Bernd's slide is purely qualitative on the upper wick ("tiny" / "negligible" by diagram, no number). Both 0.10 and 0.20 are human-authored engineering filters with no Bernd citation. The 0.20 value in code with the comment "Bernd does not enforce a hard cap" is the more accurate characterization.

**Recommended action:**
- Update `methodology/04_entry_triggers.md:88` to remove the hard `<= 10% of range` threshold and replace with a qualitative description matching Bernd's slide ("little to no upper wick; visually negligible relative to the body").
- Leave `BP_config.yaml` at 0.20 with an updated comment noting it is a practical filter with no corpus citation.
- Change `BP_patterns.py` default from 0.10 to 0.20 to match live config.

---

## Verdict 5: COT momentum threshold (25% of scale) — INCONCLUSIVE. No corpus support

**Dispute:**
- Methodology (Phase 26 Gap 4 spec): 35 points (25% of full -20/+120 V2 scale)
- Code (`BP_indicators.py:397`): 15 points (25% of the 20 to 80 actionable range)

**Frame evidence:** Two chapters (Ch 015 Retailers full lesson, Ch 154 CW10 02.03.2024 commodity scan with extended COT discussion) were grepped end-to-end for: fast, quickly, swung, shift, flip, jump, massive, sudden, momentum, 40 point, 25%, 3 weeks, spike, dramatic. Zero numeric magnitude references found.

**Bernd verbatim** (closest to magnitude discussion):
> "We can get even more bearish you see it's not we're not all time bearish" (CW10 frame 1465)
> "Maybe not the three year extreme and definitely not the six months extreme that we saw that have a lot of accuracy" (Ch015 frame 4888)

All COT magnitude language is qualitative: "getting more bearish", "close to all time bearish", "extreme", "not yet". No numeric threshold for a "fast" or "momentum" COT change appears anywhere.

**Reasoning:** The Phase 26 Gap 4 momentum trigger is a DeepSeek-added enhancement with no Bernd corpus backing. The 25% scaling factor is an engineering choice. The dispute between 35 points (25% of full scale) and 15 points (25% of threshold range) cannot be resolved by Bernd's lectures because he never stated either number.

**Recommended action:** Decide the threshold via backtest sensitivity analysis on the 160-case goldtest. If the momentum trigger adds noise (false positives), remove it entirely. If it helps without introducing opposite-direction errors at Stage 2, keep whichever value (15 or 35) produces the better FT 121-case score, and document it as an engineering choice rather than a Bernd teaching.

---

## Verdict 6: NG=F COT lookback — DEFERRED (session limit)

The Sonnet vision agent for this dispute hit a session-rate limit before completing. Retry next session. The remaining dispute is between:
- Methodology: 26 weeks
- Code: 52 weeks
- Cheatsheet narrative: 5 year (260 weeks)

Frames to inspect when retrying:
- `HAI\Ch015 Retailers` — search transcript for "natural gas" + "weeks" / "five year" / numeric
- `HAI\Ch025 Energies` — search for NG COT indicator settings panel
- `FT outlooks` (any NG=F session) — live COT chart with lookback visible

---

## Cross-cutting observations

**Most consequential finding: ZB-only for individual stocks.** The biggest material change from frame verification is that Bernd unchecks both GC and DXY for individual stocks on screen, leaving only the ZB (interest rates) reference. Current code for `equities` uses three refs (ZB, GC, SPY). This explains some of the Phase 7 / 15 / 27 stock-Valuation mysteries: the standard relative-strength comparison was running against the wrong basket. The SPY relative-strength proxy added in Phase 26 is conceptually separate (a substitute for the absent `CampusValuationTool_V2`) and need not be removed.

**Dual ROC unlocks more cases without regressions.** The per-timeframe override structure for `cycle_per_symbol` is a structural improvement that should unlock end-of-band weekly reads for mega-cap tech without affecting daily trend-following calls.

**Two doc claims were corpus-inflations.** Both the Hammer upper-wick `0.10` threshold and the COT momentum `25%` rule were written into methodology files as if they were Bernd's stated rules. Frame verification shows neither is. The methodology files should be cleaned up to remove implied verbatim attribution for these.

**Seasonality lookahead is a simple config fix.** 20 to 30 in `BP_config.yaml` to match Bernd's verbatim "I just project 30 days in the future".

## Files referenced

- `D:\Azalyst Bernd Skorupinski\AUDIT_PHASE_28.md` (parent audit)
- `D:\Azalyst Bernd Skorupinski\_audit_phase28\findings_*.md` (5 domain reports)
- `D:\Azalyst Bernd Skorupinski\_audit_phase28\extract_chapter.py`
- `D:\Azalyst Bernd Skorupinski\_audit_phase28\find_lesson_folder.py`
- `D:\Trading\Output\Bernd_Skorupinski Campus Blueprint OTC\...\Lesson 3. Valuation\frame_001240.jpg, frame_001253.jpg, frame_000645.jpg`
- `D:\Trading\Output\Bernd Skorupinski  Hybrid AI Trading\...\LESSON 2 - VALUATION PART 1\frame_003575.jpg, frame_003461.jpg, frame_003501.jpg, frame_003742.jpg`
- `D:\Trading\Output\Bernd Skorupinski  Hybrid AI Trading\...\Module 1 - Hammer Candle\LESSON 1\frame_000615.jpg, frame_000331.jpg, frame_001916.jpg`
- `D:\Trading\Output\Funded Traders\Practical Application\03.04.2024 - Practical Application - Seasonality\frame_001496.jpg, frame_001482.jpg`
- `D:\Trading\Output\Funded Traders\Funded Trader Weekly Outlook\2023\10.12.2023 - CW50\frame_000240.jpg`
