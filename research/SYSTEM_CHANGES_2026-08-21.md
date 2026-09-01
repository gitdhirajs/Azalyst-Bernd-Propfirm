# EVERY CHANGE MADE TO THE LIVE SYSTEM — 2026-08-21

Live code lives at `D:\Trading\Azalyst Bernd Skorupinski\Propfirm Trading Dashboard\`.
`python_snapshot/` in THIS folder is a byte-for-byte copy taken after all changes below.
`python_snapshot/backups/` holds the pre-change backup of every file that was edited.

Everything is revertible. Nothing was changed without being measured first.

---

## 1. BEHAVIOUR CHANGES — four flags, all in `BP_config.yaml`

The file previously had **no `rules:` section at all**; both pre-existing flags were reading their
code-level `False` default. The section was added and now reads:

```yaml
rules:
  cot_blocks_zone_arrival:        true
  xcat_skip_equity_indices:       true
  allow_prelection_index_shorts:  true
  cot_proposes_short:             true
```

| flag | finding | what it does | measured effect |
|---|---|---|---|
| `cot_blocks_zone_arrival` | C-58 / C-69 | zone-arrival may not fire a direction COT directly opposes | Bernd opposites 6 -> 4; goldtest 0 regression |
| `xcat_skip_equity_indices` | C-61 -> C-76 | excludes equity indices from the commercials-vs-retail override | Clemens 2/7 -> 5/7; opposites 12 -> 9 |
| `allow_prelection_index_shorts` | C-72 | lets equity indices be called DOWN in pre-election years | +2 Bernd MATCH, 0 new opposites |
| `cot_proposes_short` | C-83 | a MODERATE bearish COT proposes the short instead of location | shorts 21% -> 33%, **0 losses, 0 new opposites** |

Revert any one by setting it to `false`, or restore a backup:
`BP_config.yaml.bak-2026-08-21` (before flag 1) through `.bak4-2026-08-21` (before flag 4).

## 2. CODE CHANGES — `BP_rules_engine.py`

Backup: `python_snapshot/backups/BP_rules_engine.py.bak-2026-08-21`

| change | finding | default |
|---|---|---|
| `allow_prelection_index_shorts` gate added around the Phase 42 Fix-2 index-short block | C-72 | **ON** (approved) |
| `cot_proposes_short` path: moderate bearish COT proposes the short and bypasses the per-class short suppressions | C-83 | **ON** (approved) |
| `allow_precious_metals_shorts` gate added around the Phase 42 Fix-1 PM-short block | C-79 | **OFF — tested, rejected** (+3 match but +6 wrong-direction) |
| `momentum_unfreezes_location` — extends the ATH momentum override to all classes | C-80 | **OFF — tested, rejected** (-4 match) |
| `location_requires_zone_touch` — location per the literal course definition | C-81 | **OFF — tested, rejected** (+7 match but +4 wrong-direction) |
| `outside_range_is_no_setup` — price beyond the zone range = no setup | C-84 | **OFF — tested, rejected in both symmetric and asymmetric forms** |
| **diagnostics** `location_pct` and `location_source` exposed on `_last_htf_analysis` | C-80 | read-only, no behaviour change |

## 3. CODE CHANGES — `BP_zone_detector.py`

Backup: `python_snapshot/backups/BP_zone_detector.py.bak-2026-08-21`

| change | finding | default |
|---|---|---|
| `self.config` stored on the instance (was not kept) | — | harmless |
| `fair_zone_scan` — evaluates all four zone patterns per bar instead of a demand-first cascade | C-82 | **OFF — tested, rejected** (-6 match, despite fixing a real bug) |

**Note on C-82:** the cascade bug is REAL — the shipped loop hides **73% of all supply zones**
(151 demand : 45 supply, vs 186 : 171 when fixed). Fixing it still made the scoreboard worse,
because downstream logic had been compensating for it. Left off deliberately, not overlooked.

## 4. HARNESS CHANGE — `validate_against_lectures.py`

Records the two new diagnostic columns (`loc_pct`, `loc_source`) per row. No scoring change.

---

## WHAT WAS **NOT** CHANGED

- No indicator maths. `BP_indicators.py` is untouched this session.
- No zone-detection parameters — C-86 confirmed them correct against the course verbatim.
- No consensus rebalancing. `_bias_consensus` still has 17 bullish exits vs 4 bearish (C-70).
  Deliberate: C-79 demonstrated that opening short paths before fixing their INPUT adds
  wrong-direction calls.
- `BP_data_fetcher.py`, `run_scanner.py` unchanged this session.

## HOW TO VERIFY THE LIVE SYSTEM MATCHES THIS SNAPSHOT

```
cd "D:\Trading\Azalyst Bernd Skorupinski\Propfirm Trading Dashboard"
python -c "import yaml; print(yaml.safe_load(open('BP_config.yaml'))['rules'])"
```
Expect all four flags `True`.

```
cd "D:\Trading\Azalyst Bernd Skorupinski\_audit_ftw_vision\validation"
python validate_against_lectures.py --verdicts all_traders_ground_truth.csv --min-confidence low
```
Expect **MATCH 77 (58%), hold 46, OPPOSITE 10; longs 66/100; shorts 11/33**.

If those numbers differ, something drifted — diff `python_snapshot/` against the live folder.
