# Phase 28 — COT Audit Findings

Domain: Fundamentals — Commitment of Traders (COT)
Scope: COT methodology in 03_fundamentals.md / 07_asset_class_cheatsheet.md vs Python live engine vs Bernd's canonical chapters.
Already-fixed phases are NOT relitigated. Only new gaps or drift are reported.

### [P2] NG=F COT lookback in code (52w) drifts from methodology (26w) and corpus ("5yr extremes")
- **Methodology claim**: `methodology/03_fundamentals.md:284`, `methodology/07_asset_class_cheatsheet.md:124` — NG=F lookback is "26 weeks". `methodology/07_asset_class_cheatsheet.md:74-75` says "Historical retailer extremes (5year or historical)".
- **Code reality**: `BP_rules_engine.py:37` — `'nat_gas': 52` (matches neither the methodology table 26w nor the cheatsheet narrative 260w).
- **Source (Bernd verbatim)**: Ch.015 (COT PART 2 - RETAILERS): "What are some really big extremes maybe it's five year extremes right maybe if we change the indicator to a five year extreme... We would then get that but these are the things that we have to manually track."
- **Discrepancy**: Code value 52w matches neither the methodology table (26w) nor the cheatsheet narrative (5yr / 260w). 26w would not capture multi-year retailer-positioning regime shifts that drive Bernd's contrarian NG calls; 260w would.
- **Recommended action**: Set `'nat_gas': 26` to match methodology, OR `'nat_gas': 260` to match cheatsheet plus Ch.015. Verify against a Funded Trader NG=F session before committing.

### [P2] COT-is-king block in rules engine excludes nat_gas and soft_commodities; inconsistent with indicator-layer 156w trigger class set
- **Methodology claim**: `methodology/07_asset_class_cheatsheet.md:336` — "COT contrarian primary" for NG; cheatsheet treats COT as the primary driver for NG.
- **Code reality**:
  - `BP_indicators.py:373-374` — `_COT_KING_CLASSES_156W = ('commodities', 'energies', 'precious_metals', 'nat_gas', 'soft_commodities')` (5 classes).
  - `BP_rules_engine.py:1686` — `COT_KING_CLASSES = ('commodities', 'precious_metals', 'energies')` (3 classes, drops nat_gas and soft_commodities).
- **Source (Bernd verbatim)**: Ch.015 NG section: "for some markets they really do matter now natural gas is just one of those markets where this would matter."
- **Discrepancy**: NG=F retailer extremes can fire `bias=bullish/bearish strength=strong` from the indicator layer (and 156w secondary trigger fires for nat_gas), but the rules-engine override block will not lift that signal over a contradicting Location. Same drop for soft_commodities (CC/SB/OJ) which can fire a Non-Commercials divergence at the indicator layer that the engine cannot promote.
- **Recommended action**: Align `COT_KING_CLASSES` in `BP_rules_engine.py:1686` with the indicator's 5-class set. Re-run goldtest to measure regression before committing.

### [P2] DeepSeek Gap 4 COT momentum threshold uses 25% of [20-80] range, not 25% of full -20/+120 scale per methodology
- **Methodology claim**: `methodology/03_fundamentals.md:295` — "if the 5-week trend shows >=25% of the full -20/+120 scale in movement".
- **Code reality**: `BP_indicators.py:397` — `delta = (self.upper_extreme - self.lower_extreme) * 0.25` = `(80-20)*0.25` = **15.0 points**. Methodology spec implies `140 * 0.25` = **35.0 points**.
- **Discrepancy**: Code fires the momentum trigger at less than half the magnitude documented. With 15-point threshold, normal weekly noise can trigger; with 35-point threshold, only genuine institutional regime shifts trigger.
- **Recommended action**: Either fix code to use full -20/+120 scale (e.g. `delta = 35.0`) OR update methodology to reflect the threshold-range basis. Sensitivity-check via goldtest before committing.

### [P2] Fresh-extreme flag ("Short Term CUT") documented in methodology but not implemented in code
- **Methodology claim**: `methodology/03_fundamentals.md:293` — "When COT index crosses the 80/20 threshold in the current week's report... flag it as `fresh_extreme = True`. A fresh extreme carries HIGHER conviction than a sustained one." Also CLAUDE.md Phase 4+5 P2.
- **Code reality**: No grep match for `fresh_extreme`, `Short Term CUT`, or `just_crossed` anywhere under `Propfirm Trading Dashboard/`. The `get_bias` and `cross_category_signal` methods return current-state bias only.
- **Source (Bernd verbatim)**: CW25 "Short Term CUT" (Phase 4+5 audit citation).
- **Discrepancy**: A fresh weekly cross of 80 (institutional accumulation just started) is treated identically to a sustained reading of 80 (institutional accumulation in place for weeks). Bernd's stated higher-conviction signal is invisible to the engine.
- **Recommended action**: Add `is_fresh_extreme` field to `get_bias` return: compare `cot_df[primary_col].iloc[-2]` against threshold versus `iloc[-1]`. Wire into rules engine as a conviction boost (e.g. promote `cot_strength='normal'` → `'strong'` when fresh).

### [P2] Commercial regime-flip detector documented in methodology but not implemented in code
- **Methodology claim**: `methodology/03_fundamentals.md:178-191` — `commercial_regime_flip()` with `swing_threshold=40` over 3 weeks; "fires INDEPENDENT of the static 80/20 thresholds — a flip from 75 to 30 in 3 weeks is more significant than a sustained 78 reading."
- **Code reality**: No function `commercial_regime_flip` or `regime_flip` under `Propfirm Trading Dashboard/`.
- **Source (Bernd verbatim)**: Phase 6 / Ch.155: "super bullish to all of a sudden, super bearish... really indicative to something bigger happening" the following month.
- **Discrepancy**: A 40-point COT swing in 3 weeks (turning-point leading signal) is invisible to the engine — only the absolute level matters.
- **Recommended action**: Add `detect_regime_flip(cot_df, lookback=3, threshold=40)` to `COTIndex` returning 'bullish_flip' / 'bearish_flip' / 'none'. Wire into rules engine as an early-warning override (separate from the 156w extreme path).

### [P2] Retailer directional-alignment veto documented as HARD VETO for NG=F but not implemented
- **Methodology claim**: `methodology/03_fundamentals.md:297-300` — "Natural Gas (NG=F): HARD VETO — Retailers are the PRIMARY indicator; being on the same side as proposed trade kills the contrarian thesis." `methodology/07_asset_class_cheatsheet.md:94` — same rule (soft warning for PMs post Phase 17).
- **Code reality**: No grep match for `retailer_alignment`, `retailer.*veto`, or equivalent in any Python file. Only mentioned in `README.md`. The existing NG=F contrarian logic produces the inverted signal at extremes only — Bernd's rule extends to SUB-extreme retailer positioning that aligns with the proposed direction.
- **Source (Bernd verbatim)**: Implied by Ch.025: "the retailers are buying, which is kind of troublesome to see because it may mean that price is going to [drop]."
- **Discrepancy**: A demand-zone long on NG=F with retailers net-long (even at 55, not yet extreme) should be vetoed. Current code passes such a setup.
- **Recommended action**: In `_analyze_fundamentals` for NG=F (and as soft-warning for PMs), compare `sspec_idx` direction vs proposed trade direction; if aligned and `sspec_idx` is above 50 (long bias) or below 50 (short bias), emit `retailer_alignment_warning` and HARD VETO for NG=F.

### [P2] `cross_category_signal` "smart-vs-dumb" override applied to nat_gas where primary IS retailers
- **Code reality**: `BP_rules_engine.py:1201` — `if cot_cross.get('extreme_confluence') and asset_class not in ('forex',)` — the override fires for `nat_gas` because the guard only excludes `forex`.
- **Discrepancy**: For nat_gas, the primary trader category IS retailers (contrarian). The single-category `get_bias` already produces the correct contrarian-from-retailer signal. Adding the `smart_vs_dumb` override (which treats commercials as smart money) on top of an already-contrarian primary signal is conceptually redundant for nat_gas: usually both rules agree, but in edge cases (e.g. both groups extreme-long simultaneously the override returns `aligned` and demotes) it can silently override nat_gas's contrarian primary.
- **Source (Bernd verbatim)**: Ch.025: "for natural gas... we don't really have one [a specific rule]" — Bernd treats nat_gas COT idiosyncratically.
- **Recommended action**: Extend the guard to `asset_class not in ('forex', 'nat_gas')`. Or condition the override on the asset class using commercials as primary in `get_bias` (commodities / PMs / energies / grains+cotton).

### [P3] Methodology cheatsheet NQ CFTC code "20974A" vs code "209742"
- **Methodology claim**: `methodology/03_fundamentals.md:353` — `| Nasdaq | NQ | 20974A |`.
- **Code reality**: `BP_data_fetcher.py:434,484` — `'NQ=F': '209742'`. The `A`-suffixed code refers to the futures+options combined report; the all-digit code is the futures-only Legacy code. Ch.013 explicitly endorses the Legacy futures-only report: "the legacy reports because the legacy reports will spit out our three different groups."
- **Discrepancy**: Methodology cites a non-Legacy code; code is correct but the doc misleads.
- **Recommended action**: Update `methodology/03_fundamentals.md:353` to `209742`. Also confirm ES=F entry (`13874A` in both code and methodology — both may be non-Legacy and should be checked).

### [P3] PMs cross_category_signal still uses retailers in smart-vs-dumb override despite Phase 17 demoting them to ③
- **Code reality**: `BP_indicators.py:541-548` — `smart_vs_dumb` checks `comm_long_ext and sspec_short_ext → 'bullish'`. Rules engine uses this for PMs via `extreme_confluence` (Phase 17 changed PMs to commercials-primary; the smart-vs-dumb still implicitly uses retailers).
- **Methodology claim**: `methodology/03_fundamentals.md:283`, `methodology/07_asset_class_cheatsheet.md:49,66,79` — "Retailers are confirming odds-enhancer (③) — NOT primary" for PMs.
- **Discrepancy**: When PMs trigger `smart_vs_dumb='bullish'`, the engine elevates `cot_strength='strong'` AND can override single-category neutral. For PMs that means a 'normal' commercials-bullish signal gets promoted to 'strong' specifically because retailers are at the opposite extreme. This is plausibly correct per "perfect PM buy = Commercials bullish + Retailers bearish" (Ch.147/122/132), but the methodology table calling retailers "③ confirming" implies they should ONLY confirm — not promote `normal` → `strong`. Currently undocumented elevation.
- **Recommended action**: Document this elevation explicitly in `methodology/03_fundamentals.md` as the implementation of the "Retailers ③ confirming = strength boost" rule.

### [P2] Forex bare ticker (EUR=X, GBP=X, JPY=X) not mapped in get_cftc_code; COT silently returns neutral
- **Code reality**: `BP_data_fetcher.py:458` — `'EURUSD=X': '099741'` mapped. But the bare `'EUR=X'` (the default Yahoo Finance ticker for EUR/USD) is NOT in the mapping. `get_cftc_code('EUR=X')` returns empty → `fetch_cot_data('')` returns empty → COT silently neutral.
- **Methodology claim**: `methodology/03_fundamentals.md:288` — Forex uses Non-Commercials 26w with cross-currency check.
- **Discrepancy**: Any scanner configured with `EUR=X` (Yahoo default) gets neutral COT silently. The `EURUSD=X` form works but is non-standard.
- **Recommended action**: Add `'EUR=X': '099741'`, `'GBP=X': '096742'`, `'JPY=X': '097741'`, `'AUD=X': '232741'`, `'CAD=X': '090741'`, `'CHF=X': '092741'`, `'NZD=X': '112741'` to the mapping dict in `get_cftc_code`. Or add a normalization step that converts bare `XXX=X` to `XXXUSD=X` or `USDXXX=X` before lookup.

### [P3] `cot_confirmation_queue` (wait-for-N-releases) documented in methodology but not implemented
- **Methodology claim**: `methodology/03_fundamentals.md:160-176` — `cot_confirmation_queue(current_index, threshold, weekly_delta, releases_remaining=2)` defers entry up to 2 releases when threshold is close.
- **Code reality**: No grep match for `cot_queue`, `cot_confirmation_queue`, or `releases_remaining`.
- **Source (Bernd verbatim)**: Ch.155: "most likely in a third week of February. So we get two more updates on COT data."
- **Discrepancy**: When COT index is at 75 with strong upward momentum, Bernd defers entry 1-2 weeks waiting for 80 confirmation. Engine fires immediately. Partially subsumed by the Phase 18 156w-secondary trigger and Phase 26 momentum trigger (both fire EARLY rather than DEFERRING) — but the explicit defer-and-wait behaviour is missing.
- **Recommended action**: Add `cot_trajectory` or `wait_for_confirmation` output flag in `_analyze_fundamentals` when index is within 5 of threshold. Low-priority.

### [P3] Logged "smart-vs-dumb overrides single-category" misleading on nat_gas
- **Code reality**: `BP_rules_engine.py:1208-1213` — when `cot_cross.smart_vs_dumb` overrides `cot_bias`, log shows `"COT smart-vs-dumb (X) overrides single-category (Y)"`. For nat_gas the "single-category" was already retailer-contrarian — replacing it with the commercials-driven smart-vs-dumb breaks the audit trail when a setup is later reviewed.
- **Discrepancy**: No real-trade impact when readings agree, but failure post-mortems for NG=F can't tell which trader group drove the signal.
- **Recommended action**: Combine with the nat_gas guard fix above — skipping the override removes the misleading log entirely.
