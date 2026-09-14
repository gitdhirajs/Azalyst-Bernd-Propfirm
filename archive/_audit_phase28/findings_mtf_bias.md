# Phase 28 Audit — MTF Framework and Bias Hierarchy / Consensus

Domain: MTF, Location/Trend determination, _bias_consensus hierarchy, cycle overrides.

Methodology files audited:
- methodology/06_seven_step_process.md
- methodology/03_fundamentals.md (Bias Synthesis section)
- CLAUDE.md Phase 11 and Phase 23-27 sections

Python audited:
- Propfirm Trading Dashboard/BP_rules_engine.py (run_seven_step_process, _analyze_htf, _determine_trend, _zigzag_pivots, _constituent_proxy_bias, _bias_consensus, EQUITY_INDEX_CONSTITUENTS)
- Propfirm Trading Dashboard/BP_roadmap.py (PRESIDENTIAL_CYCLE_BIAS, SANNIAL_CYCLE_BIAS, cycle_year_in_pres_cycle)

Findings below.

---

### [P1] constituent bias not wired into _bias_consensus from run_seven_step_process — live scanner dead code
- **Methodology claim**: CLAUDE.md Phase 24. Constituent route says bullish constituent stocks alone are enough to override loc=bearish when cycles agree. Bernd Ch.157 verbatim: "if these two [AAPL + MSFT] are undervalued, you can buy NQ / ES."
- **Code reality**: BP_rules_engine.py:292-299 — the `biases` dict assembled in `run_seven_step_process` contains only location, trend, cot, cot_strength, valuation, seasonality. It does NOT include `constituent`, even though `_analyze_fundamentals` correctly computes it and returns it in `fund_bias` (BP_rules_engine.py:1358). Inside `_bias_consensus` the Phase 23/24 cycle-override path reads `_const_n = normalized.get('constituent', 'neutral')` at line 1512 — so in the live pipeline `_const_n` is ALWAYS neutral and `_constituent_overrides` (line 1529) can never be True. The goldtest bias_only path correctly adds the key (goldtest/run_goldtest.py:459), so this divergence is visible only at Stage 2 (live trading).
- **Source (Bernd verbatim)**: Chapter 157 — "the two most important stocks is Apple and is Microsoft that they are not overbellied... if these two are undervalued, you can buy NQ / ES."
- **Discrepancy**: The constituent-routing path that CLAUDE.md credits with Phase 24 +5 cases (and that goldtest measures) is inert when the live scanner is the caller. Goldtest score overstates live-scanner behavior on equity-index ATH cases.
- **Recommended action**: In BP_rules_engine.py:292-299 add `'constituent': fund_bias.get('constituent', 'neutral'),` to the `biases` dict so the live scanner mirrors the goldtest harness.

### [P2] NG=F weekly ZigZag override (15%) missing from _determine_trend
- **Methodology claim**: CLAUDE.md Phase 4+5 P1 fixes. ZigZag % = 15 for @NG weekly (default 3.0 for daily). The Seasonality 10y+5y NG override IS implemented (line 1322); the ZigZag 15% override is NOT.
- **Code reality**: BP_rules_engine.py:701-708 — `TF_ZIGZAG` is a flat per-timeframe dict with no per-symbol override. NG=F on `'1wk'` gets 6 percent like every other instrument. No `NAT_GAS_SYMBOLS`-aware branch in `_determine_trend`.
- **Source**: CLAUDE.md Phase 4+5 from FT CW corpus audit.
- **Discrepancy**: NG weekly trend label may flip too often, undermining counter-trend gate decisions for NG trades.
- **Recommended action**: Add per-symbol override in `_determine_trend`: `if symbol in NAT_GAS_SYMBOLS and htf == '1wk': zz_pct = 0.15`. Forward `symbol` from `_analyze_htf` to `_determine_trend`.

### [P2] _determine_trend ZigZag percent for 4H vs 1H mislabelled / missing
- **Methodology claim**: CLAUDE.md MTF table — ZigZag % per TF: weekly=6, daily=3, 4H=2, 1H=1.
- **Code reality**: BP_rules_engine.py:701-708 — `TF_ZIGZAG = {'1mo': 0.10, '1wk': 0.06, '1d': cfg, '60m': 0.02, '30m': 0.015, '15m': 0.01}`. There is NO `'4h'` or `'240m'` key. `'60m'` (=1H) is set to 2 percent — but per the methodology, 1H should be 1 percent and 4H should be 2 percent. run_scanner.py:168 confirms intraday htf = `'60m'`, so the live engine uses the 4H ZigZag value for 1H bars.
- **Source**: CLAUDE.md spec.
- **Discrepancy**: Intraday strategy uses an under-tight ZigZag, suppressing genuine 1H pivots.
- **Recommended action**: Either add `'4h': 0.02` AND change `'60m': 0.01`, or remap intraday strategy htf from `'60m'` to `'4h'`.

### [P2] _analyze_htf does not forward symbol to _determine_trend
- **Methodology claim**: Per-symbol ZigZag overrides require `_determine_trend` to know the symbol.
- **Code reality**: BP_rules_engine.py:644 — `trend = self._determine_trend(highs, lows, htf=htf)`. Symbol is not passed. `_determine_trend` signature at line 676 does not accept `symbol`.
- **Discrepancy**: Blocks any future per-symbol ZigZag tuning (NG=F 15%, Bitcoin, etc.).
- **Recommended action**: Add `symbol: Optional[str] = None` to `_determine_trend` signature and forward from `_analyze_htf` (which already receives `symbol` parameter at line 558-562).

### [P2] LOOKBACK dict in _determine_trend has no 4h entry
- **Methodology claim**: Phase 9 — lookback shortened from 200 to 100 bars for weekly data because 200 bars = 4 years contains the 2022 bear-market lows. Same logic implies 4H needs its own lookback.
- **Code reality**: BP_rules_engine.py:714 — `LOOKBACK = {'1mo': 60, '1wk': 100, '1d': 200, '60m': 200, '15m': 200}`. No `'4h'`. If 4H ever passed, falls through to default 200 = ~33 days of 4H bars = ~6 weeks — too short for trend characterization.
- **Source**: CLAUDE.md Phase 9.
- **Discrepancy**: System currently consistent because no strategy uses `'4h'` as htf; future 4H strategy will be miscalibrated.
- **Recommended action**: Add explicit `'4h': 200` (or 300+) when 4H strategy is added.

### [P3] BP_roadmap.PRESIDENTIAL_CYCLE_BIAS header docstring INVERTED relative to actual key mapping
- **Methodology claim**: BP_roadmap.py:38 header comment says: "Index 0 = post-election (year 1), 1 = mid-term, 2 = pre-election, 3 = election."
- **Code reality**: The dict actually uses 0=election, 1=post-election, 2=mid-term, 3=pre-election (matches inline per-key comments at lines 42-45 AND `cycle_year_in_pres_cycle` math: `(2024 - 1992) % 4 = 0`; 2024 IS an election year). Verified empirically: 2023 yields cy=3 with the all-bullish row (correct for pre-election year).
- **Source (Bernd verbatim)**: Chapter 109 / 112 / 156 (Funded Trader monthly roadmaps; 2023 = pre-election year).
- **Discrepancy**: Header docstring contradicts the data. Any new agent reading the file will mis-identify the cycle phases.
- **Recommended action**: Replace line 38 with "Index 0 = election year, 1 = post-election, 2 = mid-term, 3 = pre-election."

### [P3] cycle_year_in_pres_cycle anchor docstring invites unsafe edits
- **Methodology claim**: BP_roadmap.py:88 — "Adjust the anchor if needed -- the textbook uses 1992 as a known election year."
- **Code reality**: Anchor 1992 IS the canonical anchor (Clinton election year). `PRESIDENTIAL_CYCLE_BIAS` rows are keyed off it.
- **Discrepancy**: Wording invites editing without realising the cycle table rows would need re-alignment.
- **Recommended action**: Strengthen wording: "1992 is the canonical anchor (Clinton election year). DO NOT change — the PRESIDENTIAL_CYCLE_BIAS table is keyed off it."

### [P2] Methodology has no discrete MTF section in 03_fundamentals.md
- **Methodology claim**: User prompt directed audit to MTF and Bias Synthesis sections of 03_fundamentals.md. Bias Synthesis exists (line 779+). MTF as a discrete section does NOT exist.
- **Code reality**: `_analyze_htf` is the MTF code anchor. The canonical MTF table (Fib 33/66, ZigZag pcts, asset-class HTF/LTF pairs) lives in CLAUDE.md only.
- **Discrepancy**: MTF rules (Fib drawing, equilibrium skip, asset-class lookbacks, ZigZag pcts per TF, 6-pivot vs ZigZag relationship) are not collected anywhere in the methodology folder.
- **Recommended action**: Add `## MTF Framework` section to 03_fundamentals.md (or split into a new 08_mtf.md).

### [P3] _constituent_proxy_bias candidate logic permits 1 bullish + 1 neutral = bullish — methodology says BOTH primaries required
- **Methodology claim**: CLAUDE.md Phase 6/15 — Primary gate: if BOTH primaries are NOT strongly overvalued -> constituent = bullish.
- **Code reality**: BP_rules_engine.py:1007-1016 — sets `bearish` if `primary_bear >= 1`; sets `bullish` if `primary_bull == len(primary_available)`; falls through to `elif primary_bull >= 1: candidate = 'bullish'`. The fall-through fires for 1 bullish + 1 neutral (since `primary_bear == 0` already passed).
- **Discrepancy**: A single bullish primary (with the other neutral) is enough to vote bullish — more permissive than "both required".
- **Recommended action**: Either tighten code to require `primary_bull == len(primary_available) and primary_bear == 0`, OR loosen methodology language to match code.

### [P2] Methodology 06_seven_step_process.md ASCII flowchart does not mention Phase 23/26 cycle overrides
- **Methodology claim**: The Bias Synthesis prose section (lines 222-247) covers Phase 23/26/27 overrides clearly. The ASCII flowchart at line 444+ does not.
- **Code reality**: `_bias_consensus` runs Phase 23 cycle override at line 1497 — BEFORE the Step-1 location gate prose described in the flowchart.
- **Discrepancy**: A reader following the flowchart alone will not see the equity-indices cycle paths that fire BEFORE the documented consensus.
- **Recommended action**: Add a flowchart line for equity_indices: `[IF equity_indices AND loc=bearish: presidential/sannial cycle may pre-empt — Phase 23/26]` before the CONSENSUS box at line 444.

### [P2] _analyze_htf Phase 25 zone-usability fallback may keep stale zones
- **Methodology claim**: Phase 25 hardening — filter out invalidated/consumed zones before selecting the most recent for the Location Fib.
- **Code reality**: BP_rules_engine.py:601-614 — `_zone_is_usable()` checks `qualifier_scores.Q3` (or aliases). Falls back to `not z.get('invalidated', False)` when scores missing. Zones from older detector runs or zones built without qualifier scoring will pass via the fallback.
- **Source**: CLAUDE.md Phase 25.
- **Discrepancy**: Hardening is best-effort. Any zone without `qualifier_scores` is treated as usable.
- **Recommended action**: Force-compute qualifier scores on every zone before the Fib filter, OR log a warning in `_zone_is_usable` when `qualifier_scores` is missing.

### [P3] _bias_consensus STOCKS branch — Phase 23 T2 (line 1637) cannot fire because earlier paths catch first
- **Methodology claim**: CLAUDE.md Phase 23 T2 — buy-the-crash setups for crashed stocks even in downtrend, when val=bullish AND seas=bullish.
- **Code reality**: BP_rules_engine.py:1620-1670 — equities branch order: (1) val=bullish and trend != downtrend; (2) seas == loc == bullish; (3) seas=bullish and val != bearish and trend != downtrend; (4) Phase 23 T2 val=bullish and seas=bullish; (5) Phase 27 cycle. T2 only fires when val=bullish AND trend == downtrend AND seas=bullish AND cycles not all bullish — extremely narrow window.
- **Discrepancy**: None at runtime; CLAUDE.md is honest about T2 being scaffolding.
- **Recommended action**: NONE. Flagging only to confirm the documented "T2 does not fire" observation is structurally inherent.

### [P3] Phase 23 cycle override is asymmetric (loc=bearish only) — by design but undocumented
- **Methodology claim**: CLAUDE.md Phase 23 — cycle override designed for ATH/expensive Location at year-3 pre-election. Asymmetry (bullish-only override) is not called out explicitly.
- **Code reality**: BP_rules_engine.py:1497 — `if asset_class == 'equity_indices' and loc == 'bearish'`. There is no `loc == 'bullish'` mirror. Phase 26b cycle dominance (1587) checks `loc != 'bearish'` and produces `bullish` only — also asymmetric.
- **Discrepancy**: For election years (cy=0) the presidential cycle has BEARISH months (Jul/Aug/Sep). If loc=bullish (price at demand zone) AND cycle is bearish AND val is bearish, no symmetric override fires. This IS the design but easy to mistake for a bug.
- **Recommended action**: Add a one-line note in CLAUDE.md Phase 23 description: "NOTE: only bullish-direction override is implemented; the bearish mirror (demand-zone long blocked by cycle bearish) is intentionally absent — Bernd does not override demand-zone longs with election-year seasonality."
