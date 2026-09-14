# Phase 28 Audit — Fundamentals: Valuation and Seasonality

Scope: Compared `methodology/03_fundamentals.md`, `methodology/07_asset_class_cheatsheet.md`, CLAUDE.md Phases 1-27, the live Python in `Propfirm Trading Dashboard/`, the canonical Pine Script in `04_Pine_Script_Indicators/`, and Bernd transcripts (Ch 17, 18, 19, 25, 74, 75, 122, 131, 141, 147, 151, 157, 169).

13 findings: 4 P1, 7 P2, 2 P3.

---

### [P1] Seasonality fed daily OHLCV into weekly-binning code path

- **Methodology claim**: `methodology/03_fundamentals.md:622` "Chart timeframe: DAILY only"; CLAUDE.md: "Seasonality is daily-data-only ... code always fetches `interval='1d'`".
- **Code reality**: `BP_data_fetcher.py:410` fetches daily bars, but `BP_rules_engine.py:1321, 1329, 1332` always call `calculate_multi(seasonal_df, timeframe='weekly')` and `get_current_bin(price_df, 'weekly')`. `BP_indicators.py:901-903` `weekly` branch bins by `df.index.isocalendar().week - 1` into 52 bins. Daily bars become ~5 samples per weekly bucket per year instead of 252 daily TDOY bins.
- **Source (Bernd)**: Ch.019 "We can use seasonality on a daily as well as on a weekly timeframe ... I'm going to show true seasonality on a weekly chart now". Pine Script `Seasonality_OTC.txt:35-44`: bin scheme depends on chart timeframe, not data input. Daily uses `_tdoy` 252 bins, weekly uses `_twoy` 52 bins.
- **Discrepancy**: Code mixes daily data with weekly binning. The 252-bin TDOY pattern Bernd reads on a daily chart is never computed by the live system. Phase 10 fixed the TDOY math in the daily branch but no caller reaches it.
- **Recommended action**: Pass timeframe through `_analyze_fundamentals` so weekly price_df uses weekly bars (resampled), daily price_df uses daily bars. Simpler option: hard-route to `timeframe='daily'` in `_analyze_fundamentals` since seasonality input is always daily.

---

### [P1] Seasonality `get_bias` ignores the "slope must actively TURN" rule

- **Methodology claim**: `methodology/03_fundamentals.md:638-702` and CLAUDE.md Phase 4+5 P1: "slope must actively TURN positive/negative ... a slope that has been positive for many weeks but is flattening or topping does NOT count as a fresh bullish signal".
- **Code reality**: `BP_indicators.py:956-975` `get_bias` computes `slope = end_val - start_val` only. No prior-slope comparison, no turn detection.
- **Source (Bernd)**: Phase 4+5 audit codified this from FT sessions. Methodology lines 630-693 spell out the contract.
- **Discrepancy**: Documented P1 fix never landed in code. System fires bullish on sustained-flat-positive curves that have already crested.
- **Recommended action**: Extend `get_bias` to take prior slope and tag `TURNED_BULLISH` vs `SUSTAINED_BULLISH`. Use the reference signature already in `03_fundamentals.md:630-693`.

---

### [P1] Stock SPY relative-strength proxy uses 10-bar ROC, not the documented 52-week threshold

- **Methodology claim**: `methodology/03_fundamentals.md:410` "SPY RS proxy (Phase 26) for individual stocks: underperformed SPY >10% over 52w = undervalued; outperformed >15% = overvalued".
- **Code reality**: `BP_rules_engine.py:1287-1295` instantiates generic `Valuation(length=10, rescale_length=100, overvalued=75.0, undervalued=-75.0)` against SPY. 10-bar lookback = ~2 weeks on daily data, not 52. The ±75 trigger is on the rescaled spread, not raw percentage outperformance.
- **Source (Bernd)**: No verbatim cite for 10%/15% / 52w in CLAUDE.md Phase 26 description. Only the methodology doc.
- **Discrepancy**: Doc describes 52w mean-reversion proxy; code implements 10-bar momentum-spread. Qualitatively different signals. A stock that crashed last year but rallied last month reads "undervalued" per doc but "overvalued" per code.
- **Recommended action**: Decide which is correct (52w mean-reversion matches Bernd's "AAPL undervalued long-term" per Ch.157 / Ch.74). Either rewrite the equities branch with the documented 52w threshold, or rewrite methodology to describe what the code does.

---

### [P1] AAPL ROC override (length=30) contradicts the Phase 7 production decision

- **Methodology claim**: `methodology/03_fundamentals.md:418` "Pine Script default Length=10 across ALL asset classes. AMZN/META/NVDA give wildly different (incorrect-vs-Bernd) readings with Length=13; Length=10 matches." CLAUDE.md Phase 7: `VALUATION_LENGTH_BY_CLASS reset to 10 across all asset classes`.
- **Code reality**: `BP_config.yaml:213-223` `cycle_per_symbol` overrides mega-caps to length=30: `AAPL: 30, MSFT: 30, GOOG: 30, GOOGL: 30, META: 30, AMZN: 30, NFLX: 30, NVDA: 30, TSLA: 30`. `BP_rules_engine.py:834-841` applies them. The exact symbols Phase 7 validated at 10 now run at 30.
- **Source (Bernd)**: Ch.017 "the 30-day cycle that I used on Apple" supports 30 for AAPL daily trend-following. Ch.074 says "change the ROC from 10 to 13" as the back-test step. Mixed evidence. Phase 7 empirically picked 10 for mega-caps.
- **Discrepancy**: Phase 24 reintroduced the per-symbol overrides "per cheatsheet + transcripts" but didn't reconcile Phase 7's empirical finding. Now undocumented config silently overrides validated code.
- **Recommended action**: Run a regression on the Ch.141 CW39 narrated readings (AAPL not undervalued, AMZN undervalued, META neutral, GOOG slowly undervalued, MSFT undervalued, NFLX undervalued) at length=10 vs 30. Keep the length that matches more cases. Document the call.

---

### [P2] Equity-index Valuation refs include GC=F but methodology says ZB + DXY only

- **Methodology claim**: `methodology/03_fundamentals.md:410` and `methodology/07_asset_class_cheatsheet.md:192`: "Stocks / Equity Indices Refs = ZB + DXY only".
- **Code reality**: `run_scanner.py:185` `equity_indices: ["DX-Y.NYB", "ZB=F", "GC=F"]`. Includes Gold. `_analyze_fundamentals:1274-1277` skips Valuation for equity_indices entirely (so refs are moot for the index itself) but they ARE consumed by `_constituent_valuation_bias`.
- **Source (Bernd)**: Pine Script `Valuation_OTC.txt:8-10` defaults are DXY, GC1!, ZB1!. Gold IS canonical. Cheatsheet line 205 contradicts line 192: "Equity indices DO use DXY ... @BUS (bonds) + @GC (Gold) + @$XY (DXY)".
- **Discrepancy**: Three sources disagree. Code matches Pine Script (DXY+ZB+GC); methodology line 410 says ZB+DXY; line 205 (same file) says DXY+ZB+GC.
- **Recommended action**: Update methodology lines 410 and 192 to "DXY + ZB + GC" matching code and Pine Script.

---

### [P2] Individual-stock Valuation refs contradict cheatsheet (no DXY)

- **Methodology claim**: `methodology/07_asset_class_cheatsheet.md:192` says "Stocks/Equity Indices = ZB + DXY only". CLAUDE.md Phase 16: stocks use "ZB + GC (no DXY)".
- **Code reality**: `run_scanner.py:186` `equities: ["ZB=F", "GC=F", "SPY"]`. No DXY; SPY added Phase 26.
- **Source (Bernd)**: OTC 2025 Module 3 L3 (cited in Phase 16): "We're going to unselect reference symbol three, which is the dollar" for Apple. DXY OFF for individual stocks.
- **Discrepancy**: Code matches Phase 16 for stocks (no DXY); cheatsheet line 192 lumps indices and stocks together with DXY for both. Also: equities branch never actually uses these macro refs. It routes through SPY proxy (P1 #3) or 3yr-SMA proxy. The macro refs for `equities` are largely dead code.
- **Recommended action**: Split the cheatsheet row into "equity indices" (DXY + ZB + GC) and "individual stocks" (ZB + GC, no DXY, plus SPY relative proxy). Document explicitly that the equities branch uses SPY proxy not macro refs.

---

### [P2] Forex Valuation runs at length=10 per Pine Script default but cycle_per_symbol re-asserts it

- **Methodology claim**: `methodology/07_asset_class_cheatsheet.md:22-23`: "Valuation ROC | 10. Refs | DXY only".
- **Code reality**: `BP_rules_engine.py:138` `VALUATION_LENGTH_BY_CLASS['forex'] = 10` AND `BP_config.yaml:230-237` overrides `6E=F: 10, 6B=F: 10, 6J=F: 10, 6S=F: 10, EURUSD=X: 10, ...`. All 10, duplicating the class default.
- **Source (Bernd)**: Ch.018 "the length on the cycles we're going to put a 10 right there".
- **Discrepancy**: Not a bug. Dead config. Misleading to a contributor who thinks forex needs explicit per-symbol entries.
- **Recommended action**: Remove forex entries from `cycle_per_symbol`, or add a comment that they exist purely for documentation.

---

### [P2] Valuation-as-EXIT signal documented but not implemented

- **Methodology claim**: `methodology/03_fundamentals.md:598-608` "Daily Valuation as EXIT Signal on Weekly Trades (Phase 6, Ch 173) ... tighten stop to breakeven and/or take partial profit". CLAUDE.md Phase 4+5: "Valuation as EXIT signal: 'I run away from this trade' (Ch.147)".
- **Code reality**: No grep hit for valuation-as-exit / val_exit / exit_signal across `BP_paper_trader.py`, `BP_rules_engine.py`, `run_scanner.py`. `_analyze_fundamentals` returns a static snapshot; nothing consumes a mid-trade Valuation flip.
- **Source (Bernd)**: Ch.147 verbatim: "my exit point look at the dollar valuation ... once we are overvalued I run away from this trade regardless where we are".
- **Discrepancy**: Methodology promises an exit rule; code has zero hooks. Documented across multiple audit cycles.
- **Recommended action**: Either implement in `BP_paper_trader.py` (per-position recompute Valuation on each scan; if direction flips against position AND price covered at least half target, BE stop), or demote the methodology section to a manual checklist.

---

### [P2] `bias_lookahead_bars=20` vs Pine Script `_future=30` and Bernd's stated 30

- **Methodology claim**: `methodology/03_fundamentals.md:624` "Forward projection 30 to 150 bars (per-trader preference; Bernd: 'I just project 30 days in the future for me that's enough')".
- **Code reality**: `BP_indicators.py:872` and `BP_config.yaml:249` `bias_lookahead_bars: 20`. Pine Script `Seasonality_OTC.txt:10` `_future = 30` (default).
- **Source (Bernd)**: Methodology cites Bernd's 30-day standard projection. Pine Script default matches.
- **Discrepancy**: Bias slope is computed over 20 bins. Compounds with P1 #1: 20 weekly bins is ~5 months. Even after P1 #1 fix, 20 daily bins (~1 month) is shorter than Bernd's 30.
- **Recommended action**: Change default `bias_lookahead_bars` to 30 to match Pine Script and Bernd's stated preference.

---

### [P2] BTC seasonality 4yr-only inherits the weekly-binning defect

- **Methodology claim**: CLAUDE.md Phase 16 "Bitcoin only has ~4 years of history ... 4yr-only lookback".
- **Code reality**: `BP_rules_engine.py:1319-1321` `Seasonality(multi_lookbacks=(4,)).calculate_multi(seasonal_df, timeframe='weekly')`. Same weekly binning as P1 #1.
- **Discrepancy**: 4yr times 52 weekly buckets times ~5 daily samples/week = ~20 samples per bucket. Below statistical resolution.
- **Recommended action**: Once P1 #1 is fixed and seasonality runs on daily TDOY bins, BTC at 4yr lookback becomes 4 times 252 ≈ 1008 daily samples per bucket across years. Retest BTC post-fix.

---

### [P2] NG=F seasonality 10y+5y correctly excludes 15y but uses weekly binning

- **Methodology claim**: `methodology/07_asset_class_cheatsheet.md:127` "NG Seasonality: 10yr + 5yr only".
- **Code reality**: `BP_rules_engine.py:1327-1329` `Seasonality(multi_lookbacks=(5, 10)).calculate_multi(seasonal_df, timeframe='weekly')`. The 15yr exclusion (Phase 25) is correct. Weekly binning is same as P1 #1.
- **Source (Bernd)**: Ch.025 "natural gas, it's a technical blind demand game in combination with the true seasonals". Seasonality is the PRIMARY signal for NG.
- **Discrepancy**: Phase 25 fix is correct, but NG's PRIMARY signal is computed at the wrong resolution due to P1 #1.
- **Recommended action**: Same as P1 #1.

---

### [P3] `valuation_composite` column still computed despite being unused

- **Methodology claim**: `methodology/03_fundamentals.md:426` "Read 3 INDIVIDUAL LINES, never a composite average".
- **Code reality**: `BP_indicators.py:736-739` still computes `results['valuation_composite'] = results[val_cols].mean(axis=1)`. `get_bias` correctly excludes it. Dashboard or downstream consumers may still consume it.
- **Recommended action**: Remove the composite column entirely, or rename `valuation_visual_mean` and document as diagnostic-only.

---

### [P3] Cheatsheet internal contradiction on equity-index GC reference

- **Cheatsheet line 192** says "ZB + DXY only" for stocks/indices.
- **Cheatsheet line 205** (same file) says "Equity indices DO use DXY ... @BUS + @GC + @$XY ... Previous documentation stating 'NO Dollar' was incorrect".
- **Code reality** at `run_scanner.py:185` matches line 205 + Pine Script defaults: `DX-Y.NYB + ZB=F + GC=F`.
- **Recommended action**: Reconcile to "DXY + ZB + GC" matching code and Pine Script. The Phase 21 ZN removal stays; GC inclusion was already documented at line 205 but not propagated to the canonical row at line 192.

---

## Cross-cutting observation

The single largest defect is **P1 finding #1**: Seasonality fed daily data into weekly binning. It silently degrades the primary signal for natural gas, bitcoin, soft commodities, energies. Every market where seasonality dominates. Phase 10 fixed the TDOY math in the daily branch but no caller routes through it.

**P1 #2** (slope-turn detection missing) is the second largest. Bernd treats "slope rolling over" as exit-grade information; system reads it as a fresh bullish signal.

**P1 #3 and #4** are silent drift. SPY proxy doesn't match documentation; mega-cap length=30 contradicts Phase 7's empirical lesson. Both likely produce wrong-direction stock bias that gets masked by Phase 27's cycle override.

The P2/P3 items are mostly documentation incoherence (three files disagree on equity Valuation refs) and undocumented divergence between methodology and code. None individually produce wrong signals, but the contradictions would mislead any new contributor.
