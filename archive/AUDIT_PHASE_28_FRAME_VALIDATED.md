# AUDIT PHASE 28 — Frame-Validated Engine vs Bernd Validation Report

Date: 2026-05-24
Method: combine Phase 28 desk audit findings (doc vs code), frame verification (Bernd's actual screen), and the 160-case goldtest mismatch diagnostic to answer the question:

> Where does our Python engine disagree with Bernd, and for each disagreement is the cause (a) an indicator bug, (b) a methodology rule we are not enforcing, or (c) a structural gap or Bernd discretionary override?

This report consumes:
- `AUDIT_PHASE_28.md` (63 doc vs code findings)
- `AUDIT_PHASE_28_FRAME_VERIFIED.md` (6 frame-verified threshold verdicts)
- `_audit_phase28/mismatch_diagnostic.md` (160 goldtest case-by-case)

---

## Headline numbers

| Category | Cases | Pct |
|---|---|---|
| STAGE1_MATCH (system agrees with Bernd direction) | 93 | 58.1% |
| STAGE1_NEUTRAL (Bernd had direction, system said hold) | 31 | 19.4% |
| STAGE1_OPPOSITE (system fired wrong direction; ALL filtered at Stage 2) | 20 | 12.5% |
| BERND_NEUTRAL (Bernd said no trade) | 12 | 7.5% |
| ERROR (yfinance fetch failure) | 4 | 2.5% |
| **Total** | **160** | **100%** |

**Stage 2 false-positive count: 0.** Every STAGE1_OPPOSITE case was correctly blocked by the Stage 2 zone-direction match plus decision matrix gates before any trade fired. Production safety preserved.

The 51 non-matching directional cases (31 NEUTRAL + 20 OPPOSITE) are what this report dissects.

---

## Per-asset-class match rates

| Asset Class | n | Match | Match% | Neutral | Opposite | Bernd-neutral | Error |
|---|---|---|---|---|---|---|---|
| precious_metals | 41 | 29 | **78%** | 4 | 4 | 4 | 0 |
| commodities | 14 | 10 | **71%** | 0 | 4 | 0 | 0 |
| energies | 4 | 3 | **75%** | 1 | 0 | 0 | 0 |
| equities | 47 | 29 | **66%** | 13 | 2 | 1 | 2 |
| equity_indices | 44 | 20 | **57%** | 8 | 7 | 7 | 2 |
| forex | 9 | 2 | **22%** | 4 | 3 | 0 | 0 |
| interest_rates | 1 | 0 | **0%** | 1 | 0 | 0 | 0 |

Forex remains the structural bottleneck (Phase 19 / 20 isolated). Equity indices second weakest due to 2024 ATH rally cases that Bernd took on cycle thesis with no demand zone present.

---

## Failed-indicator tallies on the 31 STAGE1_NEUTRAL cases

For each NEUTRAL case (Bernd had a direction, system said hold), we count how many cases had each indicator either OPPOSING Bernd's direction or returning NEUTRAL.

| Indicator | Opposing | Neutral | Total disagree |
|---|---|---|---|
| **cot_strength** | 0 | 31 | 31 |
| **constituent** | 1 | 29 | 30 |
| **seasonality** | 16 | 13 | 29 |
| **cot** | 4 | 23 | 27 |
| **valuation** | 6 | 20 | 26 |
| **location** | 11 | 10 | 21 |
| **trend** | 9 | 12 | 21 |

`cot_strength` is structurally neutral when COT is not at extreme so its 31/31 is expected. `constituent` 30/31 is **directly explained by Phase 28 MTF P1 finding** — the constituent vote is built in `_analyze_fundamentals` but never copied into the `biases` dict in `run_seven_step_process` so it always reads as neutral in live `_bias_consensus`. One-line fix.

---

## Root-cause classification of the 51 directional mismatches

### Bucket A: Confirmed code bug, fix already in Phase 28 finding

#### A1. Constituent vote not wired into live `_bias_consensus` (Phase 28 MTF P1)
**Affects: ~30 of 31 NEUTRAL cases. Largest single bug.**

`_analyze_fundamentals` computes constituent bias for equity indices via `_constituent_proxy_bias`. The result is returned in `fund_bias` but `run_seven_step_process` at `BP_rules_engine.py:292-299` builds the `biases` dict WITHOUT `'constituent'`. Inside `_bias_consensus` the Phase 23/24 cycle override path reads `_const_n = normalized.get('constituent', 'neutral')` and the override therefore never fires in the live pipeline.

The goldtest harness builds the dict separately (`goldtest/run_goldtest.py:459`) which is why the goldtest can show Stage-1 results that the live scanner cannot reproduce.

**Cases where this likely caused the NEUTRAL outcome:**
- Cases 1 (NQ=F 2024-01-02), 21 (YM=F 2023-01-08), 34 (RTY=F 2023-03-18), 49 (RTY=F 2023-06-03), 51 (YM=F 2023-08-26) — equity indices where constituent should override loc=neutral/bearish

**Action:** Add `'constituent': fund_bias.get('constituent', 'neutral')` to the `biases` dict at `BP_rules_engine.py:292-299`. Estimated +3 to +5 cases.

#### A2. Equities Valuation refs include GC and SPY — frame-verified to be ZB only (Phase 28 frame Verdict 2)
**Affects: up to 13 of 13 NEUTRAL equities cases plus 2 OPPOSITE equities cases.**

Frame verification (`OTC 2025 Lesson 3 Valuation frame_001253.jpg`) showed Bernd explicitly unselects GC and DXY for AAPL leaving ONLY the ZB (interest rates) line. The current code uses `equities: ["ZB=F", "GC=F", "SPY"]`. The wrong basket produces wrong Valuation readings.

**Cases this likely affects** (Bernd=bullish, system=neutral, Valuation=neutral or opposing):
- Case 3 AMZN 2024-01-02, Case 5 NFLX 2024-01-02, Case 10 MSFT 2024-02-03, Case 13 NVDA 2024-02-03

**Action:** Change `equities` Valuation refs in `run_scanner.py:186` and `goldtest/run_goldtest.py` from `["ZB=F", "GC=F", "SPY"]` to `["ZB=F"]`. Estimated swing on equities is uncertain because the SPY-relative proxy added in Phase 26 also affects equities; need to re-run goldtest after the change.

#### A3. Seasonality fed daily data into weekly-binning branch (Phase 28 Val Seas P1 #1)
**Affects: up to 29 of 31 NEUTRAL cases plus several OPPOSITE cases.**

`_analyze_fundamentals` always calls `Seasonality.calculate_multi(seasonal_df, timeframe='weekly')` regardless of input timeframe. Daily bars then get grouped into 52 weekly buckets producing ~5 samples per bucket per year instead of the 252-bin TDOY pattern Bernd reads. Most affected: NG, BTC, soft commodities, energies — markets where seasonality dominates.

**Cases this likely affects:**
- 16 cases where `seasonality=opposing` Bernd's direction
- 13 cases where `seasonality=neutral`

**Action:** Route `timeframe='daily'` in `_analyze_fundamentals` since the input data IS daily. Estimated +5 to +10 cases after fix.

#### A4. Seasonality `get_bias` ignores the "slope must actively TURN" rule (Phase 28 Val Seas P1 #2)
**Affects: a subset of the 16 OPPOSING seasonality cases.**

Bernd treats "slope rolling over" as exit-grade information; system reads a flat-or-flattening positive slope as fresh bullish. Compounds with A3.

**Action:** Implement turn detection per `methodology/03_fundamentals.md:638-702`.

#### A5. Seasonality `bias_lookahead_bars=20` should be 30 (Phase 28 frame Verdict 1)
**Affects: marginal but uniform across all seasonality reads.**

Frame `Practical Application 03.04.2024 Seasonality frame_001496.jpg` shows Bernd's running instance with the indicator label literally reading `(5,30,FALSE,FALSE)`. Bernd verbatim: "I just project 30 days in the future for me that's enough". Code uses 20.

**Action:** `BP_config.yaml:249 bias_lookahead_bars: 30`. Safe pure config change.

---

### Bucket B: Bernd discretionary overrides of his own rules

These cases are not engine bugs. Bernd took the trade despite his own indicators contradicting because of higher-order context. Stage 2 correctly blocks them all.

#### B1. NQ=F 2024 ATH rally cycle calls
**Cases: 14, 26, 78, 122, 151, 152, 153 (7 cases).**

All NQ=F with location=bearish (at ATH, no demand zone). Bernd's bullish thesis comes from "constituents undervalued long-term" (AAPL/MSFT cheap) plus presidential cycle (2023=pre-election year 3 bullish). The Phase 23/24 cycle override path was designed for exactly this but does not fire because (a) constituent vote not wired (A1) and (b) the strict guard "no bearish fundamentals" blocks T1 in some cases.

CLAUDE.md `01_hybrid_ai.txt [2:01:07]` quote: "if apple doesn't rally the market doesn't rally". Bernd routes the bullish thesis to constituent stock trades, not the NQ futures themselves. He himself says "I don't see a trade on the NASDAQ itself because it would be this daily demand" while saying "buy Nasdaq" in monthly outlook. Direction-only validation overstates the failure here.

**Fix path:** A1 (constituent wiring) unlocks 3-5 of these. Remaining are genuine "no zone, route to stocks" cases that need constituent-level zone search to convert.

#### B2. GC=F 2023 counter-trend demand calls
**Cases: 19, 56, 90, 127 (4 cases).**

All GC=F where system reads location=bearish + COT/Val also bearish, but Bernd was bullish on the macro view ("end of year rally", "demand cluster area"). Phase 18 156w-extreme secondary trigger should catch these but the COT 156w wasn't yet at extreme on these specific dates.

**Fix path:** Cannot be cleanly fixed by indicator tweak; these are pure Bernd-discretion. Accept as residual.

#### B3. CT=F / ZC=F bearish-on-retailer-bullish calls
**Cases: 106, 125, 126, 154 (4 cases).**

System reads Commercials bullish for Cotton/Corn (Phase 14 routed these to `commodities` Commercials 52w). Bernd reads "retailers getting super bullish = top of the market" and goes short. The Phase 14 commodities Commercials routing is the **wrong primary group** for these specific cotton/corn trades — Bernd reads retailer extremes here, not commercial positioning.

**Conflict with Phase 14:** Phase 14 audit (Ch.113/144/159/168) found Bernd using Commercials primary for Cotton+Corn in OTHER sessions. So the rule depends on context: when retailers are extreme, retailers win; when commercials are extreme, commercials win.

**Fix path:** Implement Phase 28 COT finding #2 (`COT_KING_CLASSES` 5-class set) which would let retailer extremes promote to strong on soft commodities. Even simpler: implement Phase 28 COT P2 #1 (cross-category smart-vs-dumb override). Either way the engine reads the retailer extreme correctly.

#### B4. USDCHF/USDCAD/6S=F structural forex limits
**Cases: 43, 46, 113, 114, 118, 119, 143 (7 cases).**

Same root cause as Phase 19/20 isolated:
- USD-base pairs need both COT inversion (Phase 21) AND Location inversion (Phase 24 Gap 3)
- Bernd treats supply-zone arrival as priority over Valuation veto on CHF shorts
- Bare tickers (EUR=X without USD suffix) silently fail COT lookup (Phase 28 COT P2 finding 8)

**Fix path:** Add bare-forex tickers to `get_cftc_code` mapping. The other forex failures are Bernd discretionary supply-zone-over-Val.

---

### Bucket C: Indicator data gaps / external factors

#### C1. yfinance fetch errors
**Cases: 4 (yfinance returned empty or wrong data on the test date).**

Not a methodology issue. Transient. Re-running the goldtest typically recovers 2-3 of these.

#### C2. Bare-ticker forex COT silently neutral (Phase 28 COT finding 8)
**Affects: any forex case using `EUR=X` instead of `EURUSD=X`.**

`get_cftc_code('EUR=X')` returns empty so COT becomes neutral by default. The goldtest cases use `6E=F` and `=X` long-form so this does not affect the current goldtest, but the live scanner could miss signals if configured with bare tickers.

**Fix path:** Add bare forex tickers to the mapping dict per Phase 28 COT finding 8.

---

### Bucket D: Asymmetric rule design (intentional but limiting)

#### D1. Counter-trend short-in-uptrend gate is intentionally strict
**Cases: subset of equity-index OPPOSITE cases where Bernd took counter-trend longs.**

Phase 10 added a long-in-downtrend relaxed path but the short-in-uptrend mirror was deliberately NOT added (tested and caused CC=F 2024-02 wrong-direction on supply-shock parabolic trade). This is by-design but limits coverage on legitimate counter-trend setups.

**Fix path:** Documented as intentional. Could revisit per-asset if specific OPPOSITE cases warrant.

#### D2. Phase 23 T1 cycle override is bullish-only (intentional)
**Cases: 0 in this dataset. Documented to prevent demand-zone longs being blocked by election-year seasonality.**

**Fix path:** No action needed; document explicitly per Phase 28 MTF P3 finding.

---

## Expected Stage-1 score improvement per Phase 28 fix

Approximate effect sizes if each Phase 28 fix is applied individually (cannot be combined linearly because some cases would be fixed by multiple paths):

| Fix | Estimated cases unlocked | Risk |
|---|---|---|
| A1 constituent wiring (one-line) | +3 to +5 | Very low. Goldtest already simulates the wire. |
| A3 seasonality timeframe routing | +5 to +10 | Medium. Affects all seasonality consumers. Should re-run goldtest. |
| A2 equities refs ZB only | +2 to +6 | Medium. Removes false bearish vetoes in 2023 bull market. Re-run goldtest. |
| A5 lookahead bars 30 | +0 to +2 | Very low. Pure config change. |
| A4 seasonality slope-turn | +1 to +3 | Low to medium. Need careful threshold tuning. |
| Add E=X / J=X / etc. forex tickers (COT #8) | 0 in goldtest; live impact varies | None. Mapping additions. |

Aggregate estimate: applying A1 + A2 + A3 + A5 in sequence + retest could lift Stage-1 from 58% to roughly 65-70%. Stage 2 false-positive count should remain 0 because the gates are unchanged.

The remaining ~30% gap is mostly Bucket B (Bernd discretionary overrides). Closing it would require either:
- `CampusValuationTool_V2` Pine Script (for stock-relative-to-earnings valuation)
- Constituent-level zone search routed from index thesis (for "no zone at ATH, route to stocks" case)
- Supply-zone-overrides-Valuation rule for CHF shorts
- Retailer-extreme-overrides-Commercials rule for cotton/corn

---

## Top 5 actions ranked by impact-per-effort

1. **Wire constituent vote into `_bias_consensus`** (A1). One line. Estimated +3 to +5 cases. Zero regression risk because the goldtest already simulates the wire. **Do first.**

2. **Switch equities Valuation refs to ZB only** (A2). Two-line config change in `run_scanner.py` and `goldtest/run_goldtest.py`. Frame-verified evidence. Estimated +2 to +6. **Do second.**

3. **Bump `bias_lookahead_bars` from 20 to 30** (A5). One-character config change. Frame-verified. Zero risk. **Do third (trivial).**

4. **Route seasonality to `timeframe='daily'`** (A3). Single-method change in `_analyze_fundamentals`. Affects the biggest disagreement bucket (29/31 NEUTRAL cases). Re-run goldtest before declaring done. **Do fourth, with regression check.**

5. **Add bare forex tickers to `get_cftc_code`** (Phase 28 COT #8). Mapping additions. No regression risk because new keys do not change existing behavior. **Do anytime; affects live scanner more than goldtest.**

These five together are about 15 lines of code change. The combined effect should be a measurable Stage 1 improvement without touching the consensus rule, decision matrix, or any of the load-bearing gates.

---

## What remains genuinely hard

These would be Phase 29+ structural work:

- **`CampusValuationTool_V2` Pine Script** for stocks (compares stock vs earnings/multiples not vs macro refs). 12 stock cases blocked by absent tool.
- **Constituent-level zone search routed from index thesis** to convert "buy Nasdaq" macro thesis into actionable AAPL/MSFT zone trade. 5+ equity-index cases.
- **Soft-commodity retailer-extreme override** for cotton/corn. 4 cases.
- **Forex location frame inversion + supply-zone-overrides-Val for CHF**. 3-5 forex cases.
- **NG=F COT lookback verdict** (deferred from Phase 28 frame verification due to session limit). Could be 26w, 52w, or 260w. Awaiting retry.

---

## Files referenced

- `D:\Azalyst Bernd Skorupinski\AUDIT_PHASE_28.md`
- `D:\Azalyst Bernd Skorupinski\AUDIT_PHASE_28_FRAME_VERIFIED.md`
- `D:\Azalyst Bernd Skorupinski\_audit_phase28\mismatch_diagnostic.md`
- `D:\Azalyst Bernd Skorupinski\_audit_phase28\analyze_goldtest_mismatches.py`
- `D:\Azalyst Bernd Skorupinski\Propfirm Trading Dashboard\goldtest\gold_results.json`
