# Phase 28 Audit - Zone Detection and Qualifiers

Code reviewed: `D:\Azalyst Bernd Skorupinski\Propfirm Trading Dashboard\BP_zone_detector.py`
Methodology reviewed: `methodology/01_zone_detection.md`, `methodology/02_zone_qualifiers.md`
Corpus chapters cited: 9, 10, 20, 21, 22, 34, 64, 65, 68.

12 findings: 3 P1, 6 P2, 3 P3.

---

### [P1] Q1 Departure scores only the FINAL leg-out candle, not the average across all leg-out candles
- **Methodology claim**: `02_zone_qualifiers.md:62-100`. `score_departure(legout_candles, avg_range_20)` walks every candle in the leg-out, computes `avg_body_pct = sum(body_pcts) / len(body_pcts)` and `size_ratio` from the average range.
- **Code reality**: `BP_zone_detector.py:339, 352-361`. `leg_out_candle = df.iloc[zone['leg_out_end']]` then `leg_out_body_pct = leg_out_candle['body'] / leg_out_candle['range']`. Only the single final candle of the leg-out is scored.
- **Source (Bernd verbatim)**: Chapter 022 "the size of explosive candles, no opposing zones created and a clean arrival" (plural) and Chapter 034 "one two three four five six green candles this one is exposed to find abnormally bigger followed for one it is a clear rally". Bernd grades the full leg-out as a sequence of multiple candles, not the last one.
- **Discrepancy**: A two-candle leg-out where the first is explosive (body 90%) and the second is just decisive (body 55%) would be scored as 5/10 by the code despite being a strong departure by Bernd's standard.
- **Recommended action**: Iterate over `df.iloc[zone['leg_out_start']:zone['leg_out_end']+1]`, take the mean body_pct, and score against the same 0.70 / 0.60 / 0.50 thresholds. Also compute the average leg-out candle range against `avg_range_20` for the size-ratio band (currently absent from Q1 score).

---

### [P1] Q5 Profit Margin gate fires at margin_ratio < 2.0, methodology says < 1.0
- **Methodology claim**: `02_zone_qualifiers.md:323-329`. Score 5 at `>= 2x`, score 3 at `>= 1.5x`, score 0 (fail) at `< 1x`. Counter-trend MUST PASS gate fires only at "less than 1x zone height".
- **Code reality**: `BP_zone_detector.py:420-430`. Chain is `>=5 -> 10`, `>=3 -> 7`, `>=2 -> 5`, `else -> 0`. The 1.5x tier (score=3) and the 1x-2x range (score>0) are missing. Any margin between 1.0 and 2.0 returns 0, then `q5_failed_gate` at line 436 hard-rejects on counter-trend.
- **Source (Bernd verbatim)**: Chapter 022 "you would measure that on the preferred version and the conservative rule is that price must travel a minimum of 1 to 3 away from the zone before price comes back regardless of trend". Bernd's minimum is 1:3 R:R distance (a soft conservative rule), and elsewhere "needs to be at least profit margin of bigger than 1 to 2". Minimum 1:2. Neither chapter says counter-trend dies at <2x.
- **Discrepancy**: Counter-trend setups with margin between 1.0 and 2.0 are silently rejected when methodology says they should still trade (with reduced score). Real impact: under-trading of counter-trend / sideways setups that Bernd would take.
- **Recommended action**: Insert the missing tier: `elif margin_ratio >= 1.5: profit_score = 3.0`, `elif margin_ratio >= 1.0: profit_score = 1.0`, `else: profit_score = 0.0`. Q5 hard fail then correctly fires only when margin_ratio < 1.0.

---

### [P1] Leg-in detector uses 70% direction-majority instead of "all candles decisive"
- **Methodology claim**: `01_zone_detection.md:42-46`. "Minimum 3 consecutive candles moving in the same direction. Candle quality: Each candle must be decisive (`body_pct > 0.50`). Direction: All candles must share the same directional bias."
- **Code reality**: `BP_zone_detector.py:166-168` (and mirrors in `_detect_rbr`, `_detect_rbd`, `_detect_dbd`). `bearish_pct = (leg_in_slice['direction'] == -1).mean(); if bearish_pct < 0.70: return None`. Only direction is checked (against a 70% majority threshold), NOT decisive body. A leg-in containing indecisive doji candles in the right direction will pass.
- **Source (Bernd verbatim)**: Chapter 064 "By contrast, a decisive candle has a body that exceeds 50% of the total range. This is where either buyers or sellers have taken charge"; Chapter 029 "because the leg in is not a clear significant drop".
- **Discrepancy**: Zones can be detected from doji-heavy leg-ins that Bernd would reject as "not a clear significant drop/rally". Inflates the candidate pool.
- **Recommended action**: For each candle in the leg-in slice, require both `direction == expected` AND `body / range > 0.50`. Drop the 70% majority and require all 3 to qualify (matching the methodology's "all must share the same directional bias" + "each must be decisive").

---

### [P2] Q3 Freshness scoring table inconsistent between the two methodology files
- **Methodology claim 1**: `01_zone_detection.md:436-442`. "1 (wider only) = 7.0; 2 (preferred) = 3.0; 3+ = 0.0"
- **Methodology claim 2**: `02_zone_qualifiers.md:248-256`. "1 (wick only) = 7.0; 1 (body test) = 5.0; 2 = 3.3 (formula `10/(retests+1)`); 3 = 2.5; 4+ < 2.0"
- **Code reality**: `BP_zone_detector.py:389-396`. Never tested = 10; wider only = 7; first preferred = 3; second preferred onwards = 0. Matches `01_zone_detection.md` and OTC 2025 Lesson 6 (Bernd's quoted source in code comment), NOT the `02_zone_qualifiers.md` formula table.
- **Source (Bernd verbatim)**: Chapter 068 "Of course, when price has tested the wider version of the zone, but not the preferred version… price has touched the edges of the zone, but hasn't penetrated deeply enough to test the core." Supports the binary wider-vs-preferred split (matching `01_zone_detection.md` + code).
- **Discrepancy**: Code agrees with one document and disagrees with the other. Documentation conflict; the `02_zone_qualifiers.md` table includes a phantom "body test scores 5.0" tier that the code never produces.
- **Recommended action**: Update `02_zone_qualifiers.md:248-256` to match `01_zone_detection.md` and code: never=10, wider=7, preferred (first body test)=3, consumed=0. Remove the `10/(retests+1)` continuous formula and the "body test scores 5.0" row.

---

### [P2] DBR leg-in scan window length doesn't match other formations
- **Methodology claim**: All four formations require `>= 3` consecutive decisive leg-in candles per `01_zone_detection.md:43-44` and `_aligns()` symmetry.
- **Code reality**: `BP_zone_detector.py:160` `leg_in_start = start - self.leg_in_min` and `leg_in_end = start`, so DBR scans exactly `leg_in_min + 1 = 4` candles. The other three formations (`_detect_rbr/rbd/dbd` at lines 195, 217, 239) use `leg_in_start = max(0, start - self.leg_in_min)` and `leg_in_slice = df.iloc[leg_in_start:start + 1]`. Also 4 candles but with the `max(0, ...)` floor that DBR is missing.
- **Source (Bernd verbatim)**: Chapter 064 zoning rule is symmetric across all four formations.
- **Discrepancy**: DBR with `start < self.leg_in_min` produces `leg_in_start < 0` and `return None` early (line 163), silently dropping otherwise-valid demand zones near the start of the data window. The other three formations gracefully clamp to index 0.
- **Recommended action**: Replace `leg_in_start = start - self.leg_in_min` with `leg_in_start = max(0, start - self.leg_in_min)` and drop the `if leg_in_start < 0: return None` guard. Use the same `leg_in_slice = df.iloc[leg_in_start:start + 1]` convention as the other detectors.

---

### [P2] Q6 Arrival scoring uses "bars to return" instead of opposing-zone path obstacles
- **Methodology claim**: `02_zone_qualifiers.md:398-470`. Q6 scores the arrival by checking for opposing zones in the return path, classifying as "fast clean impulse" (no opposing zones), "stair-stepping" (some opposing zones), or "blocked" (adjacent opposing zone). The pseudocode at lines 414-470 walks `all_active_zones`, builds `opposing_zones_in_path`, then checks adjacency and consolidation count.
- **Code reality**: `BP_zone_detector.py:440-456`. Counts `bars_to_return` (how many candles until price first touches the proximal), then scores: `<=5 -> 10`, `<=15 -> 7`, `<=30 -> 5`, else `3`. No path-obstacle / speed-bump check; no opposing-zone scan. Speed bump detection exists separately in `detect_speed_bumps()` (line 636) but is never called from `_score_zone`.
- **Source (Bernd verbatim)**: Chapter 068 "When price moves slowly or stair steps into the zone, it often leaves behind opposing… if these zones are in high quality, they can still act as obstacles, making it harder"; Chapter 022 "a clean arrival is important for ensuring profit margin of one to two".
- **Discrepancy**: Q6 currently rewards/penalises by speed-of-return only. A 3-bar return that crosses a major opposing zone scores 10 even though Bernd would mark it as a speed-bumped arrival (score 5 or 0). The information needed (the opposing zones) is computed elsewhere in the same class.
- **Recommended action**: Wire `detect_speed_bumps(zones, target_zone, current_price)` into `_score_zone` (need to pass `all_active_zones` as a parameter). Score 10 when no opposing zones in path, 5 when 1-2 are present but none adjacent (centered within 0.5 zone-heights of target proximal), 0 when an adjacent opposing zone blocks. Optionally combine with bars-to-return as a secondary tiebreaker.

---

### [P2] Q4 originality uses a fixed map but methodology hints at "flip + non-original" composite
- **Methodology claim**: `02_zone_qualifiers.md:281-308` and `01_zone_detection.md:91-95`. RBR/DBD = 10, DBR/RBD = 5, FLIP = 12.
- **Code reality**: `BP_zone_detector.py:401-407` matches the simple map. `_flag_flip_zones` at line 35-70 only flips zones where `z.get('is_original')`. Flip detection is gated to RBR/DBD only.
- **Source (Bernd verbatim)**: Chapter 021 "those original flip zones tend to be extremely strong" and "the textbook understanding would be that flip zones can only be original, right? That's the easy understanding... the more advanced understanding of what a flip zone is". Bernd explicitly says the strict "flip-must-be-original" rule is the textbook simplification and that DBR/RBD can also flip in his more advanced reading.
- **Discrepancy**: Code implements only the strict version. Non-original-but-flipped zones (DBR after a prior RBR) silently score 5 instead of being upgraded.
- **Recommended action**: Either drop the `if not z.get('is_original'): continue` guard in `_flag_flip_zones` (line 45) and score all flips at 12, or expose a config flag (`strict_flip_originality: True`) to make the behaviour explicit. Document the choice in the methodology file.

---

### [P2] Gap-as-leg-out doesn't apply Q1 score-10 even though methodology says treat as body_pct = 1.0
- **Methodology claim**: `01_zone_detection.md:76`. "When a gap is present, treat the gap-out candle as `body_pct = 1.0` for zone validity even if its actual body is smaller. The gap itself is the institutional signature."
- **Code reality**: `BP_zone_detector.py:321-328`. `_find_leg_out` accepts a gap as the leg-out marker (returns `i` early), but `_score_zone` at line 353 then computes `leg_out_body_pct = leg_out_candle['body'] / leg_out_candle['range']` from the actual gap-up candle. A gap-up candle with body 40% (common: open-near-high gap, then small body) gets Q1 = 0 and the zone is rejected.
- **Source (Bernd verbatim)**: Phase 6 / Ch 171 ("a gap, you can usually a gap") already imported into the methodology doc.
- **Discrepancy**: `_find_leg_out` opens the door (accepts gaps as valid leg-outs) but `_score_zone` then slams it shut (gives them Q1 = 0 if the candle's own body is small).
- **Recommended action**: When `_find_leg_out` returns via the gap branch, set a flag on the zone dict (e.g. `'leg_out_is_gap': True`) and in `_score_zone` use `leg_out_body_pct = 1.0` when that flag is set, so Q1 scores 10 as documented.

---

### [P2] `_count_retests_split` 25% deep-test heuristic is custom, not in the documented binary spec
- **Methodology claim**: `02_zone_qualifiers.md:158-163` defines preferred test as "bodies broke into the zone but price ultimately held". A binary body-vs-wick check.
- **Code reality**: `BP_zone_detector.py:603-617`. A touch is classified as "preferred" if `close < preferred` OR `low < preferred - 0.25 * abs(preferred - wider)`. The second clause is a heuristic invented to upgrade deep wick tests into preferred tests; it is not in the docs.
- **Source (Bernd verbatim)**: Chapter 068 only describes "preferred version touched" as bodies crossing the proximal; no quantitative "25% deeper wick" upgrade rule.
- **Discrepancy**: A pure wick test that pokes >25% into the zone body but closes above proximal is silently counted as a preferred (body) test, scoring Q3 = 3.0 instead of Q3 = 7.0.
- **Recommended action**: Either document the 25% wick-promotion rule in `02_zone_qualifiers.md` as an audit-derived refinement (with citation), or simplify to the pure body-close check `after['close'] < preferred` only. The 25% Penetration Invalidation Rule (Phase 6) is a separate hard gate and not affected by this fix.

---

### [P3] Composite recompute on flip zones omits the LOL weighting weight name typo path
- **Methodology claim**: Composite weighting per `02_zone_qualifiers.md:8-17` uses `level_on_top * 0.10`.
- **Code reality**: `BP_zone_detector.py:59`. `lol_w = self.weights.get('level_on_top', 0.10)` (fallback to 0.10 if key missing). The default weights dict at line 29-33 spells it `'level_on_top'` consistently. The fallback is sound. However the same recompute at lines 60-69 uses `self.weights['departure']` etc. with direct key access (no `.get()` fallback). If a partial config dict were ever passed, the recompute would KeyError while the original scoring at lines 462-470 also uses direct access.
- **Source (Bernd verbatim)**: N/A (internal consistency issue).
- **Discrepancy**: Inconsistent fallback handling within the same function. Minor.
- **Recommended action**: Either use `.get()` for all weight lookups in `_flag_flip_zones` and `_score_zone`, or remove the special-case `.get()` for `level_on_top` since the config defaults always populate it. Tighten with a one-line assertion at `__init__` validating that all 7 expected keys are present in `self.weights`.

---

### [P3] HTF location zones - leg-out doesn't need to be explosive per Bernd, no code path for this
- **Methodology claim**: `01_zone_detection.md` requires every detected zone to have an explosive leg-out (Q1 hard gate). The methodology never mentions an HTF-relaxation.
- **Code reality**: `_find_leg_out` requires `body_pct >= 0.70 AND body >= 2 * avg_body` for every detection regardless of timeframe.
- **Source (Bernd verbatim)**: Chapter 065 (HAI Module 2 Lesson 3 MTF). "We will rely on the preferred version of zone placement, discussed earlier. **Where the leg out doesn't need to be explosive, just the size**." Bernd is talking about drawing HTF zones for location (Fib placement) where the bar is relaxed.
- **Discrepancy**: For monthly/weekly LOCATION-only zones (where the zone is used to anchor the Fib 33/66 range, not as a tradeable setup), Bernd accepts a non-explosive but abnormally-large leg-out. The system currently requires the same strict Q1 across all timeframes, which can drop too many HTF anchor zones.
- **Recommended action**: Add an optional `relaxed_legout` parameter (default `False`) to `detect_zones` and `_find_leg_out`. When `True`, accept `body_pct > 0.50 AND body >= 1.5 * avg_body` (size matters more than body fraction). Wire from `_analyze_htf` in `BP_rules_engine.py` so location zone detection uses the relaxed mode while trade-trigger zone detection uses strict. Document the asymmetry in `01_zone_detection.md`.

---

### [P3] RTH-only intraday claim has no Bernd citation in the audited chapters
- **Methodology claim**: `CLAUDE.md` Phase 4+5 P1 item 12. "RTH-only zone drawing for intraday equity index zones."
- **Code reality**: No filtering present in `BP_zone_detector.py`. All candles in the supplied DataFrame are scanned. The decision is delegated to the caller.
- **Source (Bernd verbatim)**: Not found in any of chapters 9-12, 20-22, 23-25, 28-34, 63-71 (the Phase 28 scope). Phase 4+5 attributed this to FT outlooks audit; the OTC/HAI/Practical-Application corpus audited here does not contain it.
- **Discrepancy**: Either (a) the corpus pass missed it and it lives only in FT outlooks (acceptable; not a code bug), or (b) the rule was over-extrapolated from a single source. Worth flagging because the data fetcher's intraday endpoint returns 24-hour electronic-session data for futures. If Bernd's screen shows RTH only, our zone detection on the same symbol can produce different zones.
- **Recommended action**: Either add a corpus citation to the methodology doc, or relax the claim to "where intraday equity index analysis is being performed, prefer RTH-filtered data when available". A pure documentation P3, not a code fix unless RTH filtering is added in `BP_data_fetcher.py`.

---

**Summary count:** 3 P1 (live-trade-affecting), 6 P2 (drift / accuracy loss), 3 P3 (doc polish). All P1 fixes are localised to `BP_zone_detector.py` and would not regress the goldtest because they expand acceptance (Q5 1.5x tier, leg-out averaging) or tighten an over-permissive detector (leg-in decisiveness). Expect minor positive movement in commodity/PM Stage-1 cases where current 70%-direction leg-in admits weak candidates.
