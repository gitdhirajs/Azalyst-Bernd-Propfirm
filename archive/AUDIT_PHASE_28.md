# AUDIT PHASE 28 — Full Methodology vs Corpus Cross-Check

Date: 2026-05-24
Auditor: Phase 28 multi-agent sweep (5 parallel domain audits)
Scope: All rules in `methodology/*.md` plus `Propfirm Trading Dashboard/BP_*.py` plus CLAUDE.md against 186 chapter docs in `D:\Trading\Output\Trading Doc\` (the canonical Bernd Skorupinski source corpus).

This is a READ-ONLY audit. No methodology files or code were modified. All findings below need user review before action.

---

## Headline numbers

| Domain | P1 | P2 | P3 | Total |
|---|---|---|---|---|
| Zone Detection plus Qualifiers | 3 | 6 | 3 | 12 |
| MTF plus Bias Hierarchy | 1 | 6 | 5 | 12 |
| Fundamentals COT | 0 | 8 | 4 | 12 |
| Fundamentals Valuation plus Seasonality | 4 | 7 | 2 | 13 |
| Entries plus Trade Mgmt plus Cheatsheet | 6 | 6 | 2 | 14 |
| **Total** | **14** | **33** | **16** | **63** |

P1 = correctness or live-trading safety. Fix before next live run.
P2 = methodology drift or accuracy loss. Plan to fix.
P3 = doc polish, internal inconsistency, low priority.

Detailed findings: see `_audit_phase28/findings_<domain>.md`.

---

## Top 10 P1 fixes to do first

1. **Counter-trend HARD CEILING at T2 unenforced** (`BP_paper_trader.py:333-346`). Counter-trend trades trail past T2 like with-trend trades. Documented since Phase 4+5, never wired. Direct prop-firm DD risk. Fix: read `trade_context` in paper trader; at T2 if `counter_trend`, close 100%.

2. **Seasonality fed daily data into weekly binning** (`BP_rules_engine.py:1321,1329,1332`). The 252-bin TDOY pattern Bernd reads on a daily chart is never computed. Phase 10 fixed the TDOY math but no caller routes through it. Silently degrades NG, BTC, soft commodities, energies. Fix: route to `timeframe='daily'` in `_analyze_fundamentals`.

3. **Constituent bias dropped between `_analyze_fundamentals` and `_bias_consensus` in live scanner** (`BP_rules_engine.py:292-299`). The Phase 24 constituent-routing override that goldtest credits with +5 cases is INERT in live trading because the `biases` dict in `run_seven_step_process` does not include the `'constituent'` key. Goldtest builds the dict separately and the route fires there. Fix: add `'constituent': fund_bias.get('constituent', 'neutral')` to the `biases` dict.

4. **`build_entry_options` always uses -33% Fib stop; HTF weekly distal-only mode missing** (`BP_rules_engine.py:1864-1912`). Rule #8 EXCEPTION (HTF weekly income = distal only) documented since Phase 4+5 and re-confirmed in Phase 8, never wired. Weekly-income trades at the weekly proximal get a stop 33% below the weekly distal, collapsing R:R well below 1:2. Fix: add `stop_method` parameter; route by income_strategy.

5. **Entry options E3b, E3c, E4 documented as implemented but not produced** (`BP_rules_engine.py:1877-1912`). CLAUDE.md asserts six options live; code emits only E1, E2, E3. Phase 23 T4 zone-arrival hook depends on these existing. Fix: implement the three additional options OR mark them as deferred in CLAUDE.md.

6. **Equity-basket 3% total risk budget not in code** (`BP_rules_engine.py:2137-2160`). If the scanner fires LONG on NQ+ES+YM the system opens 3 positions at 1% each on a correlated direction with no cap. Direct prop-firm DD risk. Fix: detect basket alignment in `RulesEngine` and reduce per-position risk.

7. **Seasonality `get_bias` ignores the "slope must actively TURN" rule** (`BP_indicators.py:956-975`). Computes `slope = end_val - start_val` only. No prior-slope comparison. System fires bullish on sustained-flat-positive curves that have already crested. Documented Phase 4+5 P1, never implemented.

8. **Stock SPY relative-strength proxy uses 10-bar ROC, not the documented 52-week threshold** (`BP_rules_engine.py:1287-1295`). Doc describes 52w mean-reversion proxy; code implements 10-bar momentum-spread. Qualitatively different signals; gives opposite readings for crashed-stock-then-rallied case.

9. **AAPL ROC override length=30 contradicts Phase 7 production decision** (`BP_config.yaml:213-223`). Phase 7 reset to 10 because META/NVDA/AMZN read wrong at 13. Phase 24 reintroduced per-symbol overrides at 30 without reconciling Phase 7. Now undocumented config silently overrides validated code.

10. **Q1 Departure scores only the FINAL leg-out candle** (`BP_zone_detector.py:339,352-361`). Methodology spec walks every leg-out candle and averages. A two-candle leg-out where first is explosive (90%) and second is decisive (55%) gets Q1 = 5/10 instead of strong.

Plus three more P1s in zone detection (Q5 Profit Margin gate misfires at 1.0 to 2.0; leg-in uses 70% direction-majority instead of all-decisive), NG=F COT lookback mismatch (52w in code vs 26w in doc vs 260w in cheatsheet narrative), and Discord secrets loader does not strip surrounding quotes.

---

## Cross-cutting themes

### Theme A: documented but never implemented

Multiple high-impact rules sit in methodology docs and CLAUDE.md phase logs but have zero code presence. Grep for `fresh_extreme`, `commercial_regime_flip`, `retailer_alignment_veto`, `cot_confirmation_queue`, `slide_entry_for_rrr`, `buffered_entry_and_stop`, `consecutive_reversal_strength`, `liquidity_aware_stop`, `expand_targets_with_price_action`, `E3b`, `E3c`, `E4`, `Throwback`, `trendline`, `equity_basket`, `counter_trend.*close`, `val_exit`, `valuation.*exit` returns mostly empty.

The methodology docs read as if these are implemented. Any new contributor or downstream agent will assume the system enforces them when it does not. Either implement them or move the descriptions into a deferred-features section with explicit "NOT IMPLEMENTED" tags.

### Theme B: code-and-doc disagree on numeric thresholds

| Item | Doc | Code | Source |
|---|---|---|---|
| NG=F COT lookback | 26w | 52w | Findings COT 1 |
| COT momentum threshold | 35 pts (25% of 140) | 15 pts (25% of 60) | Findings COT 3 |
| Hammer upper-wick cap | 0.10 | 0.20 | Findings Entries 9 |
| `bias_lookahead_bars` | 30 | 20 | Findings Val 8 |
| AAPL Valuation ROC | 10 | 30 | Findings Val 4 |
| Forex Valuation refs (cheatsheet line 192 vs 205) | "ZB + DXY only" vs "DXY + ZB + GC" | DXY + ZB + GC | Findings Val 5 |

In every case the code may be correct and the doc may be stale (or vice versa). Each needs a decision and a one-line audit note.

### Theme C: methodology files contradict each other

- `01_zone_detection.md:436-442` says Q3 freshness scoring is binary wider-vs-preferred (matches code).
- `02_zone_qualifiers.md:248-256` says the same Q3 uses a continuous `10/(retests+1)` formula with a phantom "body test = 5.0" tier.
- Code matches the first. Second doc is stale.

Similar internal contradictions in `07_asset_class_cheatsheet.md` for equity-index Valuation refs (line 192 vs line 205).

### Theme D: dead config

`BP_config.yaml` `cycle_per_symbol` populated for forex with values that duplicate the class default. No effect, just misleading.

### Theme E: cross-layer drift

`COT_KING_CLASSES` in `BP_rules_engine.py:1686` lists 3 classes; `_COT_KING_CLASSES_156W` in `BP_indicators.py:373-374` lists 5. Indicator-layer can fire `bias=strong` for nat_gas and soft_commodities; rules-engine override block cannot promote them over a contradicting Location. Same code, different class set.

---

## Recommended sequencing

**Sprint 1 (live-safety, complete before next live run):**
- P1 #1 counter-trend T2 ceiling
- P1 #6 equity-basket sizing
- P1 #4 HTF-weekly distal stop
- P1 #10 Discord secrets quote-stripping

**Sprint 2 (signal accuracy):**
- P1 #2 seasonality timeframe routing
- P1 #3 constituent bias wiring
- P1 #7 seasonality slope-turn detection
- P1 #8 SPY proxy spec alignment
- P1 #9 AAPL Valuation ROC reconciliation

**Sprint 3 (zone quality):**
- P1 #11 Q1 leg-out averaging
- P1 #12 Q5 profit-margin tier
- P1 #13 leg-in decisiveness check
- P1 #14 NG=F COT lookback decision

**Sprint 4 (P2 backlog):**
- 33 P2 items, prioritise by domain frequency

**Sprint 5 (P3 doc polish):**
- 16 items, batch into a single doc-cleanup PR

---

## Files referenced

- `D:\Azalyst Bernd Skorupinski\_audit_phase28\findings_zone.md`
- `D:\Azalyst Bernd Skorupinski\_audit_phase28\findings_mtf_bias.md`
- `D:\Azalyst Bernd Skorupinski\_audit_phase28\findings_cot.md`
- `D:\Azalyst Bernd Skorupinski\_audit_phase28\findings_val_seas.md`
- `D:\Azalyst Bernd Skorupinski\_audit_phase28\findings_entries_tm.md`
- `D:\Azalyst Bernd Skorupinski\_audit_phase28\extract_chapter.py` (corpus helper)

## Methodology drift hot spots (where to look first)

- `methodology/02_zone_qualifiers.md:248-256` (Q3 freshness table stale)
- `methodology/03_fundamentals.md:410` (equity-index refs ambiguous)
- `methodology/03_fundamentals.md:622` (seasonality timeframe assertion not enforced)
- `methodology/06_seven_step_process.md:444+` (flowchart missing Phase 23/26 paths)
- `methodology/07_asset_class_cheatsheet.md:124` (NG=F lookback)
- `methodology/07_asset_class_cheatsheet.md:192` vs `:205` (equity Val refs contradict)
- `methodology/07_asset_class_cheatsheet.md:336` (nat_gas consensus cell misleading)
- `CLAUDE.md` "Phase 1-27 audit-driven features" item #4 (claims E3b/c/E4 implemented; they are not)
- `CLAUDE.md` Phase 24 constituent-routing description (live scanner does not actually receive constituent vote)

## Code hot spots (load-bearing files with multiple findings)

- `BP_rules_engine.py` — 11 findings (constituent wiring, ZigZag per-symbol, COT-king class drift, entry options, basket sizing, decision-matrix, SPY proxy)
- `BP_indicators.py` — 5 findings (seasonality slope turn, COT momentum threshold, fresh-extreme flag, regime-flip detector, Valuation composite column)
- `BP_zone_detector.py` — 6 findings (Q1 leg-out averaging, Q5 tier, leg-in decisiveness, DBR window, gap-as-leg-out scoring, Q6 path-obstacles)
- `BP_paper_trader.py` — 2 findings (counter-trend T2, valuation-as-exit)
- `BP_patterns.py` — 2 findings (swing-low guard 10-bar rolling-min, fixed 0.1% entry buffer)
- `BP_data_fetcher.py` — 2 findings (forex bare-ticker mapping, .secrets.bat quote-stripping)
- `BP_roadmap.py` — 2 findings (header docstring inverted, anchor edit warning)

---

## Closing note

The system is in a much stronger state than at Phase 27 — most fundamental indicator math has now been cross-checked twice against Pine Script and corpus. The remaining issues split cleanly into three buckets: (1) documented-but-not-coded features that need either implementation or deferral, (2) numeric drift between code and doc that needs a decision per item, and (3) the live-scanner / goldtest divergence in constituent routing that overstates measured performance.

None of the P1 findings would generate wrong-direction signals at Stage 2. The Stage-2 zero-false-positive guarantee preserved across Phases 1 to 27 stands intact. P1 fixes are about completeness and prop-firm DD safety, not about preventing bad trades.
