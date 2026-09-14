# Reconciliation report — lecture reference vs Azalyst engine (2026-09-14)

> **This file replaces the 50eeb05 version of the same name.** That version described the reconciliation flags as resolved; `BP_RETAIL_CONTRARIAN` was undefined and silenced COT on 8 live symbols (see section 2). The A/B numbers and local-folder file:line citations below refer to the `fp-5k-config` engine, not this repo's `main`.

Inputs: `D:\Trading\New folder\` (master reference, Field Map, Claude diff PDF, DeepSeek diff),
the OTC 2025 course (`D:\Trading\Output\All PDFs\Book 2 - Campus Blueprint OTC 2025\` and the
matching frame folders), this folder (local `fp-5k-config`), and the GitHub repo
`gitdhirajs/Azalyst-Bernd-Propfirm` (the only repo whose scan workflow is live; the
`gitdhirajsv` copy's scans stopped 2026-07-07).

Nothing in `D:\Trading\New folder\` was modified. The lecture-side corrections live in
`docs/LECTURE_SCOPE.md` (both trees).

---

## 1. Repo vs this folder

They are **not** the same code.

| | `gitdhirajs/main` (live, daily 00:17 UTC) | this folder (`fp-5k-config`, `gitdhirajsv`) |
|---|---|---|
| Split point | 8806da6 (Phase 46) | 8806da6 (Phase 46) |
| Since then | ~40 scan-state commits, 50eeb05 "Phase 46 reconciliation", daily cron, mplfinance charts | Phase 46–48, portfolio risk gates, constituent zones, composite gate removal, C-series audit fixes, E-01..E-05, measurement tooling, research/ (693 commits incl. state) |
| `BP_rules_engine.py` | 2,972 lines | 3,675 lines |
| COT scale default | 140×−20 (`BP_COT_0_100` flag) | 0–100 (C-57) |
| Forex / CL=F COT | Non-Comm / Commercials (`BP_RETAIL_CONTRARIAN` flag) | Retail contrarian (C-22 / C-44) |
| `goldtest/` | no `ab_paired.py`, no pinned OOS set | pinned 510-case OOS set, `ab_paired.py`, `score_by_presenter.py` |

`D:\Trading\Azalyst-repo` already existed (HEAD 4b9a078) with untracked `fix.py`, `patch.py` and a chart PNG
from another session; those were left untouched.

## 2. Live bug found on the repo (fixed in PR #3)

Commit **50eeb05** referenced `_RETAIL_CONTRARIAN` in `COTIndex.get_bias()` without defining it. The rules
engine wraps the call in try/except, so the scan did not crash: it logged
`COT calculation failed: name '_RETAIL_CONTRARIAN' is not defined` and used COT = neutral.

- Production run 34808243626 (2026-09-14 05:04 UTC, head 4b9a078): 8 warnings — EURUSD, GBPUSD, AUDUSD,
  NZDUSD, USDJPY, USDCHF, USDCAD, CL=F. That run opened a USDJPY paper trade (a9450ef2) with COT forced neutral.
- 50eeb05 also dropped CL=F from the 156w approaching-extreme trigger (new `crude_oil` class), and its
  `BP_TYPE_LADDERS` counter-trend close covered longs only.

PR: https://github.com/gitdhirajs/Azalyst-Bernd-Propfirm/pull/3 (branch `reconcile/fix-2026-09-14`, **not merged**)

| Commit | Change | Verification |
|---|---|---|
| eee0c9d | define `BP_RETAIL_CONTRARIAN` (default OFF); `crude_oil` parity | 1,600 synthetic COT series: 50eeb05 NameError 1,600/1,600; fix matches pre-50eeb05 (2ac0790) 1,600/1,600 |
| 30435e4 | counter-trend T2 close for shorts | smoke test: flag OFF unchanged; ON closes long and short at +2.0R |
| 19ab130 | stale comments in `scan.yml` / `run_scanner.py` | comments only |
| dc237bc, + | `docs/LECTURE_SCOPE.md`, CLAUDE.md correction, control characters written by 50eeb05 | docs only |

## 3. Verification table (code claims from the diffs)

Citations are to this folder unless marked *repo*. CONFIRMED = the diff describes the code correctly.

| Claim | Source | File:line | Verdict | What the code does |
|---|---|---|---|---|
| Trend = 2×HL / 2×LH, not HH+HL | PDF | `BP_rules_engine.py:1209` | CONFIRMED | `if higher_lows: uptrend; if lower_highs: downtrend`. Field Map was wrong. Lecture M2 L4 `frame_000378` agrees |
| No trade-context exit branch | PDF | `BP_paper_trader.py` update_positions | CONFIRMED | same ladder for every trade; now `BP_TYPE_LADDERS=1` (default OFF) adds counter-trend T2 close (`:627`) |
| `apply_zone_trailing` never called | PDF | `BP_paper_trader.py:910` | CONFIRMED | dead; trail = price ∓ 1R after T2 partial. *Repo*: deleted in 50eeb05 |
| Breakeven 0.5R on every trade | PDF | `BP_paper_trader.py:556`, `BP_config.yaml:404` | CONFIRMED | half-target BE. Not in the 28 lessons (M2 L4 `frame_001472`: 2R trend / 1R others) |
| 50% partial at 2R on every trade | PDF | `BP_paper_trader.py:655` | CONFIRMED | then trail, close rest at T3 |
| Explosive `>= 0.70` | PDF | `BP_zone_detector.py:404`, `:440` | CONFIRMED | lecture slide says > 70%, narration "at least 70%" |
| Leg-in ≥3 candles, 70% direction | PDF | `BP_config.yaml:369`, `BP_zone_detector.py` `_detect_*` | CONFIRMED | 4-candle window, ≥70% in direction, decisiveness unchecked. Rule card: "a decisive / explosive candle" |
| Base max 5 | PDF | `BP_config.yaml:370` | CONFIRMED | lecture table 1–6, cheat sheet "approx. 1–5" |
| Gap as leg-out | PDF | `BP_zone_detector.py` `_find_leg_out` | CONFIRMED | implemented; not in the 28 lessons (only gap mention is a target, L8 `frame_000897`) |
| COT formula | PDF, DeepSeek | `BP_indicators.py:45` | CONFIRMED (code 0–100). Master reference node 14 WRONG | 0–100 default. *Repo*: 140×−20 default. Class docstring was stale (fixed) |
| COT lookback by class | PDF | `BP_rules_engine.py:33`, `:1290–1303` | CONFIRMED with nuance | 26 default; 52 commodities (grains, cotton, cocoa, coffee) and energies; JPY 52; CL 26; SB/OJ 26 |
| Valuation ±75 | PDF | `BP_indicators.py:782` | CONFIRMED | M3 L3 settings dialog `frame_000808`: 75 / −75 |
| Valuation refs per class | PDF | `run_scanner.py:195–220` | CONFIRMED | forex 3-ref; stocks ZB only; indices 3-ref but skipped |
| Index Valuation off | PDF | `BP_rules_engine.py:2038` | CONFIRMED | `BP_INDEX_VALUATION` default OFF (ON measured −12/479, p=0.008 on 2026-09-05). Same on *repo* |
| Retail-contrarian forex + crude | PDF, DeepSeek | `BP_indicators.py:357`, `:395` | CONFIRMED | lecture: retail is one of three reads, commercials primary. *Repo*: flag, broken until PR #3 |
| Silver ROC 30 | PDF | `BP_config.yaml:507` | CONFIRMED | lecture slide `frame_000645` lists 30 "long term" for metals, so master's "no 30 setting" is wrong |
| `--all-strategies` no-op | PDF | `run_scanner.py:1452` | CONFIRMED | scans `active_strategy` only; `scan.yml` comment was stale (fixed, both trees) |
| Discord tiers removed | PDF | `send_discord.py:331` | CONFIRMED | every signal TAKE |
| A zone can fail profit margin and still rank | PDF | `BP_zone_detector.py:553`, `:818` | PARTLY | counter-trend <2× is hard-rejected (`q5_failed_gate`); sideways <2× and counter-trend 2–3× still rank |

### New findings not in either diff

| # | Finding | Where | Action |
|---|---|---|---|
| N1 | Repo: undefined `_RETAIL_CONTRARIAN` silenced COT on 8 symbols live | *repo* `BP_indicators.py` | fixed, PR #3 |
| N2 | DBR alone rejects an explosive first leg-out candle (`leg_out_end <= leg_out_start`) | `BP_zone_detector.py:254` | flag `BP_DBR_LEGOUT_FIX`, measured, not adopted |
| N3 | `_position_from_dict` dropped `close_reason` (E-01b) and `trade_context` on every state reload | `run_scanner.py:437` | fixed (reporting only) |
| N4 | Doji counted as bearish (`np.where(close > open, 1, -1)`) | `BP_zone_detector.py:128` | documented |
| N5 | Lecture departure alternatives missing: LTF decisive+decisive; HTF (location) zones need only a decisive, abnormally bigger candle | `_find_leg_out` | documented; next candidate to measure |
| N6 | Q5 skipped for with-trend zones; lecture cheat sheet says minimum 3:1 "regardless of trend" | `BP_zone_detector.py` Q5 | documented |
| N7 | Hanging man / head & shoulders / inverse H&S are not taught (only 4 patterns) | `BP_patterns.py` | documented |
| N8 | `replay_trades.py` does not pass `trade_context`, so no existing harness can measure an exit-ladder change | `goldtest/replay_trades.py:216` | documented |

## 4. Decisions (the seven items) — evidence now available

| Item | Code now | OTC 2025 course (frame) | Evidence | Status |
|---|---|---|---|---|
| Valuation for index futures | OFF | "Valuation" is the primary tool for infinite markets (M3 L1 `frame_000431`) | ON = −12/479, p=0.008 (2026-09-05) | **keep OFF** (measured) |
| Silver ROC | 30 | slide table: metals 10 short / 30 long (`frame_000645`) | both values are lecture settings | keep 30; open: short/long pair not modelled |
| Gap as leg-out | on | not in the 28 lessons | not measured | **operator decision** |
| Retail-contrarian forex + crude | on (local) / flag (repo) | trade against retail at extremes, commercials primary (`frame_001533`) | C-22 / C-44 frames | **operator decision** for repo |
| Four type-specific ladders | not implemented; counter-trend T2 close behind flag | M2 L4 `frame_001472` | **not measurable** (5 OOS Stage-2 trades; replay lacks trade_context) | flag stays OFF |
| COT formula | local 0–100 / repo 140×−20 | 0–100: Gold legend 20.66 / 80.28 reproduced exactly (`frame_001728`, CFTC 2025-01-28) | frame proof, not A/B | local settled; **operator decision** to switch repo default |
| Weekly distal-only stop | on | lecture uses −33% ("Plus 33 percent … our recommendation", L8 `frame_003171`) and also "just below distal" | not measured | **operator decision** |

## 5. Changes applied

### Tier 1 — docs and comments (this folder)
- `methodology/03_fundamentals.md`, `methodology/06_seven_step_process.md`, `SKILL.md`: COT formula 0–100 (C-57), trend rule asymmetric.
- `methodology/05_trade_management.md`, `SKILL.md`: what the paper trader actually does; lecture ladder with frame citation.
- `methodology/01_zone_detection.md`: table of lecture vs code differences with frame citations and flags.
- `docs/LECTURE_SCOPE.md` (new): scope paragraph, the master reference's contradictions resolved against frames, Price Action and intro-lesson checks.
- `.github/workflows/scan.yml`: `--all-strategies` comment.
- `BP_indicators.py` `COTIndex` docstring (was V2).

### Tier 2 — no behaviour change
- `run_scanner.py` `_position_from_dict`: restores `close_reason` and `trade_context` (N3).
- `BP_paper_trader.py`: positions carry `trade_context`.
- `apply_zone_trailing` left in place (dead, documented) — wiring or deleting it is an exit change and cannot be measured yet.

### Tier 3 — behaviour flags, all default OFF, measured

Pinned 510-case out-of-sample set, six shards, `--cot-snapshot read --ohlcv-snapshot read`,
paired with `goldtest/ab_paired.py` against a fresh baseline (`base0914_?.json`).
Baseline vs the 2026-09-05 baseline: **0 of 479 predictions changed** (flags-off code is identical; data pinned).

| Flag | Lecture basis | Bernd n=339 | Instructors n=140 | Pooled 479 | Decision |
|---|---|---|---|---|---|
| `BP_EXPLOSIVE_STRICT` | slide "> 70%" | 0 changed | 0 changed | +0, p=1.000 | OFF (no Stage-1 impact; lesson inconsistent) |
| `BP_BASE_MAX6` | table 1–6 | 0 changed | 0 changed | +0, p=1.000 | OFF (no Stage-1 impact; cheat sheet says ~1–5) |
| `BP_LEGIN_DECISIVE` | rule card "a decisive candle" | +2 (11 fixed / 9 broke), p=0.824 | −2 (4 / 6), p=0.754 | +0 (15 / 15) | OFF — measured, no edge |
| `BP_DBR_LEGOUT_FIX` | consistency with RBR/RBD/DBD | −3 (0 / 3), p=0.250 | 0 (0 / 0), 1 changed | −3 | OFF — measured, no edge |
| `BP_TYPE_LADDERS` | M2 L4 ladder table | — | — | not measurable (N8) | OFF |

Each flag was also checked at the zone level on 80 pinned price files (40 weekly, 40 daily; 12,683 zones
with flags OFF), to confirm a "0 changed" result is a real null rather than a flag that never switched on:

| Flag | Zones | Files whose zone list changed |
|---|---|---|
| `BP_EXPLOSIVE_STRICT` | 12,683 | 0 — a body of exactly 70% never occurs on these float prices |
| `BP_BASE_MAX6` | 12,648 | 40 — zones do change, but never the ones that set Location/bias |
| `BP_LEGIN_DECISIVE` | 11,989 | 80 |
| `BP_DBR_LEGOUT_FIX` | 12,883 | 48 |

Ship rule applied: adopt only with p < 0.05 or pure spec alignment without signal impact. Nothing met the first;
the two zero-impact flags touch rules on which the lesson contradicts itself, so they stay OFF rather than
picking a side. Arm files: `goldtest/{base0914,strict0914,base6_0914,legin0914,dbrfix0914}_?.json`.

## 6. GitHub

- Branch `reconcile/fix-2026-09-14` on `gitdhirajs/Azalyst-Bernd-Propfirm`, PR #3, not merged.
- No workflow was dispatched: `scan.yml` posts to the live Discord and commits state, so a test dispatch
  needs the operator's go-ahead. The next scheduled run (00:17 UTC) runs `main`, i.e. without the fix,
  unless PR #3 is merged first.
- This folder's changes are uncommitted on `fp-5k-config`.

## 7. Open questions

1. Merge PR #3 before the next scheduled scan?
2. Should `gitdhirajs/main` be brought up to the `fp-5k-config` engine? The live scanner runs code ~40 audit
   fixes behind this folder.
3. Gap leg-out, weekly distal-only stop, repo COT scale, repo forex/crude COT group: keep or change (§4).
4. Build an exit-ladder measurement (pass `trade_context` through `replay_trades.py` and widen Stage-2 signals)
   before touching breakeven / partial / trailing.
5. Next zone candidate: lecture departure alternatives (N5), especially decisive-candle HTF location zones,
   which feed Location on every signal.
