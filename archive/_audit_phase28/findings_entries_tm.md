# Phase 28 audit findings: Entries, Trade Management, Cheatsheet, 20 Rules

Scope: methodology files 04_entry_triggers.md, 05_trade_management.md, 07_asset_class_cheatsheet.md and the 20 Non-Negotiable Rules block in CLAUDE.md against live code in `Propfirm Trading Dashboard/`. Sources cross-referenced against `Blueprint - Cheatsheet.xlsx`, chapters 022, 026, 027, 033, 035-046, 061 in `D:\Trading\Output\Trading Doc`.

Conventions: P1 = correctness or live-trading safety. P2 = methodology fidelity. P3 = polish.

---

### [P1] Counter-trend HARD CEILING at T2 is unenforced in the paper trader
- **Methodology claim**: `methodology/05_trade_management.md:202` and `methodology/07_asset_class_cheatsheet.md:256` plus the rule that counter-trend trades close FULL at T2, no trailing.
- **Code reality**: `BP_paper_trader.py:333-346` treats every T2 hit identically (50% partial + start trailing). There is no branch on `trade_context`. Search of `BP_paper_trader.py` finds zero occurrences of `counter_trend`, `anticipatory`, or `trade_context`.
- **Source (Bernd verbatim)**: CW43-Idx and the May LIVE session referenced in `05_trade_management.md`, plus the Phase 4+5 audit log in CLAUDE.md: "counter-trend HARD CEILING at T2... no moon-shooting".
- **Discrepancy**: `RulesEngine.run_seven_step_process` emits `trade_context: 'counter_trend'` on the signal dict (`BP_rules_engine.py:516`) but the paper trader never reads it. Counter-trend trades trail past T2 like with-trend trades. Direct prop-firm DD risk.
- **Recommended action**: Add a `trade_context` field to `Position`, populate it in `submit_signal`, and at T2 (`i == 1`) when `pos.trade_context == 'counter_trend'`, close 100% instead of the 50% partial. Add a regression case to goldtest.

---

### [P1] Equity-basket 3% total budget is documented but not in code
- **Methodology claim**: `methodology/05_trade_management.md:328-348` `calculate_basket_position_sizes()` (3% TOTAL across NQ+ES+YM aligned, capped 1% each). `07_asset_class_cheatsheet.md:247` lists the basket exception in the universal-rules table.
- **Code reality**: `_calculate_position_size` in `BP_rules_engine.py:2137-2160` is symbol-blind. Risk per trade is always 1% (or 0.5% reduced). Search across the codebase for `basket`, `3%`, `0.03` returns no matches in any sizing path.
- **Source (Bernd verbatim)**: CLAUDE.md Phase 4+5 P2 list: "Equity basket 3% total risk budget for correlated NQ+ES+YM basket".
- **Discrepancy**: If the live scanner fires LONG on all three indices the system opens 3 positions at 1% each on a correlated direction with no cap.
- **Recommended action**: In `RulesEngine` (or `run_scanner.py` after consensus), detect when NQ=F/ES=F/YM=F all return the same `direction` and reduce per-position risk so total never exceeds 3%. Tag the signals with `equity_basket: true`.

---

### [P1] `build_entry_options` always uses a -33% Fib stop; HTF-weekly distal-only mode is missing
- **Methodology claim**: `methodology/04_entry_triggers.md:755-797`, `05_trade_management.md:24-36`, 20-rules block "rule #8 EXCEPTION HTF weekly income trades use the DISTAL LINE ONLY". CLAUDE.md Phase 4+5 P1 #3 "HTF weekly stop = DISTAL ONLY".
- **Code reality**: `BP_rules_engine.py:1864-1912` `build_entry_options`. Line 1869: `stop = distal - sign * 0.33 * zone_height` is computed once and used for every option (E1/E2/E3). Docstring at lines 1859-1860 explicitly says "ALL three use the same -33% Fibonacci stop measured from the zone distal" which contradicts methodology. No `stop_method` field is emitted. No code path routes by income_strategy to a distal-only stop.
- **Source (Bernd verbatim)**: CW43-Idx (referenced in `05_trade_management.md:34`): "weekly income trades achieve 4:1 R:R using the distal-only stop".
- **Discrepancy**: Weekly-income trades at the weekly proximal are shown a stop 33% below the weekly distal, collapsing R:R well below 1:2 and either skipping trades that should fire or sizing them too small.
- **Recommended action**: Add `stop_method` parameter to `build_entry_options`. When `income_strategy=='weekly'` and the entry is E1 at the weekly proximal (no LTF refinement), use `stop = zone.distal`. Emit `stop_method` on each option so the dashboard can show "distal-only" vs "-33% Fib".

---

### [P1] Entry options E3b, E3c, E4 are documented but not produced
- **Methodology claim**: `methodology/04_entry_triggers.md:403-732` plus the summary table at lines 946-953 list six sanctioned options. CLAUDE.md "Phase 1-27 audit-driven features" #4: "Six explicit entry options (E1/E2/E3a/E3b/E3c/E4) - `BP_rules_engine.build_entry_options()` emits all sanctioned entries on every signal". Phase 4+5 P2 list reaffirms E3b/E3c/E4 as adopted.
- **Code reality**: `grep` on `BP_rules_engine.py` and `BP_patterns.py` for `E3a|E3b|E3c|E4|Throwback|throwback|trendline|stop_buy` returns zero hits. `build_entry_options` at `BP_rules_engine.py:1877-1912` only constructs labels `'E1'`, `'E2'`, and `'E3'` (named "Confirmation").
- **Source (Bernd verbatim)**: OTC L7 (E1/E2/E3a); funded-trader corpus for E3b "stop-buy above hammer high", E3c "Throwback Strap", E4 "trendline break for stock reversals".
- **Discrepancy**: CLAUDE.md asserts E3b/E3c/E4 are implemented; the live code emits only E1/E2/E3. The dashboard cannot show the user a stop-buy entry or trendline-break entry. Phase 23 T4 zone-arrival hook (`_hq_zone_arrival` flag) presupposes these options exist.
- **Recommended action**: Either implement the three additional options in `build_entry_options` per the function signatures in `methodology/04_entry_triggers.md:602-732`, or remove the "implemented" claim from CLAUDE.md and mark them as deferred.

---

### [P1] Natural Gas COT lookback is 52 weeks in code, 26 weeks in methodology
- **Methodology claim**: `methodology/07_asset_class_cheatsheet.md:124` `COT Lookback | 26 weeks (retail positioning cycle shorter than commercial hedging)`. Quick-lookup row at line 329 also shows `26 weeks`.
- **Code reality**: `BP_rules_engine.py:37` `'nat_gas': 52`.
- **Source (Bernd verbatim)**: Blueprint Cheatsheet xlsx row 10 (Natural Gas) additional-notes column reads "historical retailer extremes (5year or historical)". Ambiguous between 26w default + 156w extreme overlay vs a true 5-year (260w) primary lookback. Methodology committed to 26w; the Phase 12 audit log in CLAUDE.md did not specify the value.
- **Discrepancy**: Methodology and code disagree numerically. 52w dampens index movement on the COT V2 scale and suppresses retailer-extreme signals the cheatsheet specifically calls out.
- **Recommended action**: Pick one. If methodology is correct, change `COT_LOOKBACK_BY_CLASS['nat_gas'] = 26`. If 52w (or 260w "five year") is correct, update methodology + quick-lookup. Add a source-cited comment either way.

---

### [P1] Discord secrets loader does not strip surrounding quotes from values
- **Code reality**: Commit 43b3004 `send_discord.py` `_load_secrets_from_bat` (and its mirror in `run_scanner.py`) parses `.secrets.bat` via `key, _, value = kv.partition("=")` then `.strip()`s only whitespace. A standard Windows `.secrets.bat` line like `set DISCORD_WEBHOOK_URL="https://discord.com/..."` yields `os.environ['DISCORD_WEBHOOK_URL'] = '"https://discord.com/..."'` (quotes preserved). Webhook returns 400.
- **Discrepancy**: The fix message says "DISCORD_WEBHOOK_URL... picked up automatically" but only works if the user wrote unquoted values. Even more failure-prone with the `set "VAR=value"` form where the leading quote ends up in the variable name.
- **Recommended action**: After `value = value.strip()` add `value = value.strip('"').strip("'")`. Also handle the `set "VAR=value"` form (split on first `=` after stripping outer quotes).

---

### [P2] Equity-index refinement ladder does not include 720m/960m/40m
- **Methodology claim**: `07_asset_class_cheatsheet.md:187` "Additional LTF | 720-min (12H) and 960-min (16H) also valid for equity indices". CLAUDE.md Phase 4+5 P1 #9.
- **Code reality**: `BP_rules_engine.py:1927-1932` `REFINE_LADDER` only lists `1mo, 1wk, 1d, 4h, 60m, 30m, 15m`. No equity-index overlay.
- **Discrepancy**: For equity-index weekly trades the system cannot refine to the 12H/16H Bernd shows in live sessions. Refinement stops at 60m which is too granular for index-futures swing setups.
- **Recommended action**: Add an `equity_indices` overlay ladder (e.g. `'weekly_equity_indices': ['1wk', '1d', '720m', '960m', '4h', '60m']`) and consult `asset_class` in `refine_zone` when picking the chain.

---

### [P2] Multi-target hierarchy (T4/T5 price-action zones, gap-fill targets) is not produced
- **Methodology claim**: `05_trade_management.md:89-116` `expand_targets_with_price_action()` plus the table row `T5 | Price-action zone | Take remainder at next opposing supply/demand zone (Phase 6, Ch 169)`. Gap-fill `T1.5/T2.5` documented at lines 135-139.
- **Code reality**: `BP_rules_engine._calculate_targets` (line 1836-1841) returns exactly `[1R, 2R, 3R]` and no consumer extends it. No references to T4/T5 targets or gap fills as discrete partials.
- **Source (Bernd verbatim)**: Ch 169 quoted in `05_trade_management.md:93`: "we have number one, we have number two, and now we have three targets. Number four is price action".
- **Discrepancy**: With-trend setups exit at 3R rather than continuing to the next opposing zone; gap-fill price magnets (NQ/ES/YM) are not flagged as interim partials.
- **Recommended action**: Implement `_expand_targets_with_price_action(entry, stop, opposing_zones, direction)` per the methodology snippet and wire it after `_calculate_targets` for with-trend signals. Gap-fill detection can be added in `run_scanner.py` using the daily OHLCV already fetched.

---

### [P2] `at_swing_low` / `at_swing_high` guard uses a 10-bar rolling extreme, not a true swing
- **Methodology claim**: `04_entry_triggers.md` plus chapter 035 (Hammer): "we are in a low a low in a downtrend" and chapter 041 (Hanging Man): "we are in the high high". The intent is a confirmed higher-low / lower-high relative to surrounding swing structure.
- **Code reality**: `BP_patterns.py:79-80` `recent_low = df['low'].iloc[max(0, idx-10):idx].min(); at_swing_low = candle['low'] <= recent_low`. A strict-or-equal rolling-min over 10 bars. A continuation candle that pushes to a new local low and prints a hammer-shaped wick passes.
- **Discrepancy**: Continuation breakdown candles will pass the guard and trigger long entries against the trend, which is the opposite of what Bernd wants (a higher-low forming after price has already started a new swing up).
- **Recommended action**: Replace with the existing ZigZag pivot detector (`BP_rules_engine._zigzag_pivots`) or a 3-bar local-min check (`lows[i-1] > lows[i] AND lows[i+1] > lows[i]`).

---

### [P2] Hammer upper-wick cap loosened in config to 0.20 (methodology says 0.10)
- **Methodology claim**: `04_entry_triggers.md:88` "upper_wick <= 0.10 * range_size". Summary table at line 938 echoes "tiny or no upper wick".
- **Code reality**: `BP_config.yaml:180` `upper_wick_max_pct: 0.20    # Loosened from 0.10 -- Bernd doesn't enforce a hard cap`. Same loosening for shooting_star (line 186) and hanging_man (line 190).
- **Discrepancy**: Methodology and CLAUDE.md show 0.10 as the canonical threshold; live system uses 0.20.
- **Recommended action**: Pick one. Either lift methodology numbers to 0.20 (with the YAML comment explanation) or tighten the config back to 0.10. Add a one-line audit-log entry on the chosen value.

---

### [P2] Silver Valuation uses generic ZB=F; methodology specifies `@VD`
- **Methodology claim**: `07_asset_class_cheatsheet.md:70` `Valuation References | DXY + @VD (Bonds use @VD ticker, NOT @US) + GC (Gold)`. CLAUDE.md Phase 4+5 P1 #6: "Silver bonds ref = @VD (not @US)".
- **Code reality**: `run_scanner.py:189` `precious_metals: ["DX-Y.NYB", "GC=F", "ZB=F"]`. No per-symbol override for Silver in `VALUATION_REFS_PER_SYMBOL` (line 194). All PMs use ZB=F.
- **Discrepancy**: Silver uses the same bond series as Gold. `@VD` is a different bond/vol reference. ZB=F may give different Valuation readings than Bernd sees.
- **Recommended action**: Confirm what `@VD` resolves to in TradingView. Add `VALUATION_REFS_PER_SYMBOL['SI=F'] = ['DX-Y.NYB', '<vd-equivalent>', 'GC=F']`. If no clean Yahoo-fetchable equivalent exists, document the gap.

---

### [P2] `slide_entry_for_rrr`, `buffered_entry_and_stop`, `consecutive_reversal_strength`, `liquidity_aware_stop` documented but absent
- **Methodology claim**: `04_entry_triggers.md:457-526` and `05_trade_management.md:50-66` define four named helpers. CLAUDE.md Phase 6 P2 list mentions order-placement asymmetry, multi-bar pattern repetition, ATH-aware stop, entry sliding to midpoint.
- **Code reality**: `grep` across the dashboard returns zero hits for any of these helpers.
- **Discrepancy**: Methodology presents these as code-ready; they exist only as docstrings. `slide_entry_for_rrr` is particularly load-bearing because Bernd uses it to recover sub-2:1 entries before refining.
- **Recommended action**: Implement the four helpers (in `BP_entry_helpers.py` or in `RulesEngine`). Wire `slide_entry_for_rrr` into `build_entry_options` before falling back to `refine_zone`. Wire `liquidity_aware_stop` for any short within X% of the recent N-day high (mirror for longs near lows).

---

### [P2] `_make_signal` uses a 0.1% entry buffer (`high * 1.001`) instead of the documented tick-based buffer
- **Methodology claim**: `04_entry_triggers.md:411-432` E1 uses `buffer = 2 * tick_size` (instrument-specific). `04_entry_triggers.md:490-504` "Order Placement Asymmetry" stresses "a few ticks" and symmetric stop shift.
- **Code reality**: `BP_patterns.py:269-273` for LONG sets `entry = candle['high'] * 1.001` (always 10 bps above the high) and `stop = candle['low'] - 0.33 * (high - low)`. No tick_size, no symmetric stop shift, no symbol awareness.
- **Discrepancy**: On a 1.10 EURUSD candle this is +11 pips above the high; on a 5000 ES future it is +5 points (~$250 of slippage). Fill behavior is unpredictable across instruments. The stop is not shifted symmetrically.
- **Recommended action**: Pass `tick_size` into `_make_signal` (from a per-asset-class map). Apply symmetric shift: `entry = high + 2*tick; stop = (low - 0.33*range) + 2*tick`. Default to a per-asset-class fallback when unknown.

---

### [P3] CLAUDE.md "20 Non-Negotiable Rules" #8 wording is ambiguous re: pattern-confirmation entries
- **Methodology claim**: CLAUDE.md Rule #8: "ALWAYS use -33% Fibonacci for stops for LTF/intraday entries and pattern-confirmation entries. EXCEPTION: HTF weekly income trades use the DISTAL LINE ONLY as the stop".
- **Code reality**: `BP_patterns.py:269-273` always uses -33% in `_make_signal`. `build_entry_options` always uses -33% in the option-builder. Neither path branches on income_strategy or "HTF weekly income" tag.
- **Discrepancy**: Rule documented since Phase 4+5 and re-confirmed in Phase 8 but never wired into either of the two entry-construction code paths. Same root issue as the P1 entries-mode item; called out here because Rule #8 is in the 20 non-negotiables and a downstream agent will assume it is enforced.
- **Recommended action**: After the P1 fix above, add a code-function cross-reference next to Rule #8 in CLAUDE.md so the next audit can verify quickly.

---

### [P3] Quick-lookup cell for nat_gas reads "COT contrarian primary"; reality is "Bernd hierarchy with Val skipped"
- **Methodology claim**: `07_asset_class_cheatsheet.md:336` row `Consensus | Bernd hierarchy | Bernd hierarchy | Bernd hierarchy | COT contrarian primary | COT dominant | Phase 26/27 cycle overrides`.
- **Code reality**: NG=F goes through `_bias_consensus` like everything else. "COT contrarian primary" has no analog in code. Live behavior: Valuation = neutral (skipped via `VALUATION_SKIP_SYMBOLS`) + COT routed to retailers-contrarian + standard hierarchy.
- **Recommended action**: Change cell to `Bernd hierarchy (Val skipped, COT contrarian retailers)` to match what the code does.

---

Files referenced (absolute):
- `D:\Azalyst Bernd Skorupinski\methodology\04_entry_triggers.md`
- `D:\Azalyst Bernd Skorupinski\methodology\05_trade_management.md`
- `D:\Azalyst Bernd Skorupinski\methodology\07_asset_class_cheatsheet.md`
- `D:\Azalyst Bernd Skorupinski\CLAUDE.md`
- `D:\Azalyst Bernd Skorupinski\Propfirm Trading Dashboard\BP_patterns.py`
- `D:\Azalyst Bernd Skorupinski\Propfirm Trading Dashboard\BP_paper_trader.py`
- `D:\Azalyst Bernd Skorupinski\Propfirm Trading Dashboard\BP_rules_engine.py`
- `D:\Azalyst Bernd Skorupinski\Propfirm Trading Dashboard\BP_config.yaml`
- `D:\Azalyst Bernd Skorupinski\Propfirm Trading Dashboard\run_scanner.py`
- `D:\Azalyst Bernd Skorupinski\Propfirm Trading Dashboard\send_discord.py`
- `D:\Trading\Output\Trading Doc\Blueprint - Cheatsheet.xlsx`

The five highest-impact findings (P1 #1, #2, #3, #4, #5) sit in code paths the goldtest does not currently exercise (paper trader counter-trend exit, basket sizing, build_entry_options stop mode, missing E3b/c/E4, NG-specific lookback). Adding goldtest cases for each would catch regressions on future fixes.
