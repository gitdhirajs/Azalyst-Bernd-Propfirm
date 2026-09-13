# Agent Handoff — Bernd Skorupinski Blueprint Trading System

> **For any AI agent picking up this project**: read this file FIRST. Then read [CLAUDE.md](CLAUDE.md) for the deep technical reference. Both files together give you the full picture of what's been built, what's broken, what's correct, and how to keep it working.

---

## What this project is

A live algorithmic trading system that mirrors Bernd Skorupinski's Blueprint methodology for a real prop-firm-funded $100k FundingPips challenge account. The user trades real money. Wrong signals cost the account.

**Two deployment paths exist** (logic identical, paths differ):

| Path | Where it runs | Trigger | Files |
|------|---------------|---------|-------|
| `Propfirm Trading Dashboard/` (this repo) | User's laptop | `scan_daily.bat` / `scan_weekly.bat` / `scan_monthly.bat` (manual) | Flat layout, `scan_results.json` in same folder |
| `coolusername-stack/azalyst-propfirm` (GitHub) | GitHub Actions hourly cron | `.github/workflows/scan.yml` | Subfolders: `scanner/`, `dashboard/`, `data/`, `methodology/` |

After any code change to the local `Propfirm Trading Dashboard/`, sync to the GitHub repo's `scanner/` so the cloud runner stays current. The cleanup pass on 2026-05-07 brought GitHub up to Phase 25 — see CLAUDE.md "Phase 25" section.

---

## Status as of 2026-05-09 (Phase 27 complete — equities presidential/sannial cycle path; SKILL.md updated with Phase 26/27 methodology)

System is **production-safe for prop-firm trading**. Run the goldtest harness to spot-check before any code change:

### 160-case goldtest (Phase 8 baseline + 45 Funded Trader cases)
```
Full-signal match (Stage 2, would actually trade): 13/160 = 8.1%
Full-signal false positives:                        0      ← CRITICAL safety metric (preserved through all 27 phases)
Bias-only match (Stage 1, analytical brain):      96/156 = 61.5%
```

Run with: `cd "Propfirm Trading Dashboard" && python goldtest/run_goldtest.py --cases-file goldtest/gold_cases_phase8.yaml`

(The 121-case Funded Trader test set was retired in Phase 22 — its cases are now folded into `gold_cases_phase8.yaml`.)

**Phase 27 by asset class (160-case goldtest Stage-1, estimated):**
| Asset Class | PASS | TOTAL | Rate |
|-------------|------|-------|------|
| Energies (CL=F) | 3 | 4 | 75% |
| Precious Metals (GC/SI/PA/PL) | 30 | 41 | 73% |
| Commodities (KC/ZC/ZS/CT/CC) | 10 | 14 | 71% |
| Equity Indices (ES/NQ/YM/RTY) | 19 | 42 | 45% |
| **Equities (individual stocks)** | **~26** | **45** | **~58%** |
| Forex (USDJPY/USDCHF/EURUSD/MXN/6S) | 3 | 9 | 33% |
| Interest Rates (ZB) | 0 | 1 | 0% |

**Zero false positives is the prop-firm-safety guarantee.** The conservative profile is intentional — Bernd takes 0-3 trades per week, not dozens. A silent system is recoverable; a wrong-direction signal that hits the daily-loss limit is not.

### Phase progression summary (160-case goldtest Stage-1 bias_only)
| Phase | Score | Δ | Key change |
|-------|-------|----|-----------|
| Phase 13 | 60/160 = 37.5% | — | COT V2 formula (140x-20), ZigZag weekly 6% |
| Phase 14 | 62/160 = 38.8% | +2 | Grains/Cotton→Commercials, PM COT 26w |
| Phase 15 | 59/160 = 36.9% | -3 | Goldtest CT/ZC class fix (correct, costly) |
| Phase 16 | 62/160 = 38.8% | +3 | KC=F→Commercials, BTC 4yr seas, COT-is-king |
| Phase 17 | 64/160 = 40.0% | +2 | PM→Commercials routing fix, contrarian strength |
| Phase 18 | 74/160 = 46.2% | +10 | 156w COT secondary trigger + COT-is-king at equilibrium |
| Phase 21 | 73/156 = 46.8% | -1 | Pine Script audit: ZN→ZB fix, USD-base COT inversion |
| Phase 22 | 73/156 = 46.8% | 0 | Stable MD5 zone IDs + re-entry suppression fix |
| Phase 23 | 78/156 = 50.0% | +5 | Presidential cycle T1 + hang-fix infra |
| Phase 24 | 81/154 = 52.6% | +3 | T1 relaxation, T2 SMA fix, constituent routing, forex Loc inversion |
| Phase 25 | 82/156 = 52.6% | +1 | DeepSeek hardening: COT-sim opt-in, zone-freshness filter, intraday guard |
| Phase 26 | 87/156 = 55.8% | +5 | DeepSeek gaps: ATH momentum, SPY proxy, USD-base inversion, COT momentum + cycle dominance |
| **Phase 27** | **96/156 = 61.5%** | **+9** | **Presidential/sannial cycle path for individual stocks** |

### Deferred (not blocking trading)
1. **Oct 2023 seasonal-low stock cluster** — AAPL/META/TSLA Oct 29 2023 where Bernd buys the seasonal low. Seasonality reads bearish for late Oct, blocking Phase 27. Discretionary contrarian-seasonality call, can't replicate mechanically.
2. **2024 stock continuation calls** — election year (cy=0, sannial=4). Cycle tables don't support bullish override for 2024. Bernd follows AI narrative / momentum reasoning not captured by cycle tables.
3. **CampusValuationTool_V2** — individual stock Valuation via earnings/multiples. Largest remaining lever (~12 cases). User doesn't have the Pine Script source.
4. **Forex 11-case structural failures** — USDJPY×4, USDCHF×3, 6S=F×3. Mostly Bernd's discretionary supply-zone-priority overrides of his own Valuation veto.
5. **Equity index ATH structural gap** — Bernd routes NQ/ES bullish thesis to AAPL/MSFT constituent zones when index is at ATH with no demand zone. Not automatable without Zone search on constituent OHLCV.
6. **Wick-over-wick big-brother substitute** — corpus mentions but doesn't quantify.

### Two-stage signal pipeline (CRITICAL to understand)

1. **Stage 1 — Directional bias**: Bernd's hierarchy (Phase 11) — Location gate → Valuation veto → minimum (loc+val aligned = tradeable) → COT/Seas/Trend as tie-breakers → bullish/bearish/hold.
2. **Stage 2 — Trade trigger**: bias + zone direction match + decision matrix + zone arrival + entry pattern → real signal.

Bernd's recorded calls are usually Stage 1 thesis ("buy AAPL because undervalued"), not "execute right now". Auditing them only against Stage 2 makes the system look ~8% accurate when its analytical brain is actually ~34–48% aligned (depending on test set). The harness reports both metrics separately.

---

## How to verify the system is correct

Run the gold-standard test harness:

```bash
cd "Propfirm Trading Dashboard"
python goldtest/run_goldtest.py            # all 160 cases (Phase 8 baseline 115 + 45 FT cases)
python goldtest/run_goldtest.py --case 5   # single case
python goldtest/run_goldtest.py --asset equities  # filter by class
```

Then open `Propfirm Trading Dashboard/goldtest/gold_diff.html` in a browser. You'll see a colour-coded table with:
- Bernd's call (date, symbol, bias, source quote)
- System's call (direction, zone levels, score)
- Per-field verdict pills

**The single number that matters most: `Full-signal false positives = 0`.** If your changes push this above 0, you've broken the prop-firm-safety guarantee. Roll back.

To diagnose a single divergence:

```bash
python goldtest/diagnose_one.py AAPL 2024-01-02 monthly
```

Prints raw values for every indicator + zone detection + bias decision flow.

---

## The Phase 7 fixes (what was broken before, what's correct now)

Eight bugs/gaps were found and fixed in the live code on 2026-05-02. Full details in [_audit/phase7/FINDINGS.md](_audit/phase7/FINDINGS.md). Quick summary of what to be aware of:

1. **Valuation indicator was returning empty for every symbol** — refs were fetched at LTF interval but `Valuation.calculate` is fed HTF data. Date intersection was too small for ROC. **Fix: refs fetched at HTF.** If you change the data-fetch logic in `run_scanner.py`, preserve `interval=htf` for valuation refs.

2. **`Length=10` is the Pine Script default**, not 13. The user shared the canonical Pine Script (`Propfirm Trading Dashboard/pinescript_reference/Valuation_v4.pine`). "Dual-ROC for Equities" is an OVERLAY practice (two indicator instances with different lengths on same chart), NOT a parameter override. If you see `Length=13` anywhere in code or docs, it's wrong.

3. **`Valuation.get_bias` reads 3 INDIVIDUAL lines, not a composite average.** Bernd reads each reference line separately. The 4-state model per line: ≥+75 strong bearish, ≥+10 mild bearish, ≤-10 mild bullish, ≤-75 strong bullish. Aggregate: all 3 agree → that direction; 2-of-3 with 0 opposing → that direction (mild). Don't average to one composite — you'll lose signal nuance.

4. **Trend vote was silently ignored** before Phase 7. `_analyze_htf` returns `'uptrend'/'downtrend'/'sideways'` but the consensus rule counted only literal `'bullish'/'bearish'`. Fixed: trend now normalised to consensus vocabulary inside `_bias_consensus`. If you ever rename trend strings, update `_bias_consensus` in lockstep.

5. **Stocks have no CFTC COT report.** They use a Valuation-driven path in `_bias_consensus` (long-only, no shorts on individual names). Bernd shorts indices via futures (ES/NQ/YM), never single stocks. Don't try to enable shorts on AAPL etc.

6. **Decision Matrix softened** — "demand-at-expensive" / "supply-at-cheap" used to hard-reject; now they allow the trade as anticipatory IF Valuation explicitly agrees with the zone direction. Counter-trend setups get reduced 0.5% risk via `trade_context = 'counter_trend'` or `'anticipatory'`.

7. **Trend safety gate** (prop-firm protection): never fire SHORT in an uptrend or LONG in a downtrend unless 4+ same-direction votes with 0 opposing. Without this, COT smart-vs-dumb signals (commercials extreme-short + retailers extreme-long) could fire shorts in rallying markets and blow the daily-loss limit. **Don't remove this gate** without compensating safety.

---

## File map

```
D:\Azalyst Bernd Skorupinski\
├── AGENTS.md                                  (this file — for any AI)
├── CLAUDE.md                                  (deep technical reference, all 7 audit phases)
├── SKILL.md                                   (skill definition for trading-system-builder)
│
├── methodology/                               (CANONICAL spec — ground truth)
│   ├── 01_zone_detection.md
│   ├── 02_zone_qualifiers.md
│   ├── 03_fundamentals.md                     (COT + Valuation + Seasonality details)
│   ├── 04_entry_triggers.md
│   ├── 05_trade_management.md
│   ├── 06_seven_step_process.md               (consensus rule + trend safety gate)
│   └── 07_asset_class_cheatsheet.md
│
├── templates/
│   ├── analysis_checklist.md                  (pre-trade 27-point checklist)
│   └── tradingview_idea_template.md
│
├── pinescript/                                (Pine Script v6 reference + strategy template)
│
├── Propfirm Trading Dashboard/                (LOCAL runner — laptop)
│   ├── scan_daily.bat / scan_weekly.bat / scan_monthly.bat
│   ├── scan_markets.bat                       (master, accepts strategy arg)
│   ├── BP_indicators.py                       (COT, Valuation, Seasonality)
│   ├── BP_rules_engine.py                     (7-step pipeline + consensus + safety gates)
│   ├── BP_zone_detector.py                    (zone detection + 6 qualifiers)
│   ├── BP_paper_trader.py                     ($100k FundingPips paper account)
│   ├── BP_data_fetcher.py                     (yfinance + CFTC API)
│   ├── BP_config.yaml                         (watchlist + risk params)
│   ├── run_scanner.py                         (orchestrator, serves dashboard)
│   ├── dashboard.html                         (live results dashboard)
│   │
│   ├── goldtest/                              (audit harness)
│   │   ├── run_goldtest.py                    (replay 115 Bernd cases)
│   │   ├── gold_cases.yaml                    (Bernd's published trade calls)
│   │   ├── gold_diff.html                     (results viewer, open in browser)
│   │   ├── gold_results.json                  (latest harness output)
│   │   └── diagnose_one.py                    (single-case deep-dive)
│   │
│   ├── audit_pine_to_python.py                (Phase 24 drift detector — diffs Pine Script defaults vs Python)
│   ├── forward_test_wide.bat                  (wide-window forward test, 2yr daily)
│   ├── run_goldtest.bat                       (one-click goldtest)
│   ├── run_forward_test.py / run_realworld.py (validation runners)
│   │
│   ├── pinescript_reference/                  (CANONICAL Pine Script sources, user-shared)
│   │   ├── Valuation_v4.pine
│   │   └── Seasonality_OTC_v5.pine
│   │
│   ├── README.md                              (operational guide)
│   ├── paper_trader_state.json                (persistent paper account — DO NOT DELETE)
│   ├── scan_results.json                      (latest scan output — used by dashboard)
│   ├── scan_history.json                      (long-term log of every scan — monthly review record)
│   └── discord_state.json                     (Discord webhook state)
│
├── (GitHub repo — coolusername-stack/azalyst-propfirm)
│   ├── scanner/BP_*.py                        (synced to local Phase 25 on 2026-05-07)
│   ├── methodology/                           (mirror of root methodology/)
│   ├── dashboard/dashboard.html
│   ├── data/                                  (paper_trader_state.json + scan_results.json)
│   └── .github/workflows/                     (scan.yml hourly cron + pages.yml dashboard publish)
│
├── _audit/                                    (per-phase audit findings — historical reference)
│   ├── phase7/FINDINGS.md
│   ├── skill_audit/                           (Phase 4+5 detailed gap log)
│   └── per_lesson/                            (per-PDF audit per Phase 4+5)
│
├── _corpus/                                   (source transcripts — DO NOT EDIT)
│   ├── 01_hybrid_ai.txt                       (Hybrid AI Trading course transcripts)
│   ├── 02_otc_2025.txt                        (OTC 2025 Campus transcripts)
│   ├── 03_funded.txt                          (Funded Trader weekly outlooks 2023-2024)
│   ├── 04_practical_application_2024.txt      (Practical Application sessions)
│   └── per_chapter_2024/                      (individual chapter files)
│
└── Blueprint_Trading_System_COMPLETE_TEXTBOOK_v7_REBUILT.docx
                                               (generated artifact, rebuild via build_textbook_v7.py)
```

---

## Working principles (preserve these in any future agent session)

1. **The methodology files are canonical**. The Python is the executable interpretation. If they disagree, fix both — don't let the code drift from the spec.
2. **Test against the harness after every code change**. If `Full-signal false positives` goes above 0, you broke something. Revert.
3. **Never relax the trend safety gate** without compensating safety elsewhere. It's there to protect the prop-firm account.
4. **Single codebase**: `Propfirm Trading Dashboard/` is the only Python location. The `Azalyst Propfirm/scanner/` path no longer exists — ignore any historical references to it.
5. **Bernd's monthly-roadmap calls are directional theses, not trade triggers.** Don't expect 1:1 match between his commentary and our full-signal output.
6. **Don't invent indicators.** If you don't have the canonical Pine Script for something Bernd uses, ask the user to share it. Inventing methodology = inventing risk = blown account.

---

## Critical insight: Why NQ/ES goldtest failures are NOT bugs (Phase 16 finding)

**Phase 16 transcript audit resolved the equity-index diverge mystery.**

03_funded.txt line 282 (Jan 2024, NQ at ATH): Bernd says: *"In the middle of nowhere because we at an all time high there is no supply obviously overhead and there we are also definitely not in weekly demand... this is nothing I would trade."*

03_funded.txt line 6735: In January 2024 (pre-election bull market), Bernd says: *"I don't see a trade on the NASDAQ itself because it would be this daily demand"* — meaning even with a strongly bullish roadmap, he requires a proper demand zone before taking the NQ trade.

**The system returning `hold` for NQ=F at ATH with no zone is CORRECT behavior.** Bernd's "buy NASDAQ" thesis from the monthly roadmap is expressed by trading AAPL/MSFT/AMZN/NVDA at their individual demand zones — not by taking NQ=F futures with no zone. The six constituent stocks are checked as an "odds enhancer" for intraday direction; they are NOT a weekly signal generator for index futures.

01_hybrid_ai.txt [2:01:07]: *"if apple doesn't rally the market doesn't rally so if the road map says from January be bullish then apple has to be bullish from January onwards"* — the roadmap thesis gets executed on constituent stock zones, not the index itself when it has no setup.

**Action**: Do not try to "fix" NQ=F DIVERGE cases where Bernd is bullish and the system says neutral/hold at ATH. Those are cases where Bernd himself wouldn't take a NQ futures position — he'd buy AAPL or MSFT instead.

---

## What's NOT done yet (still deferred after Phase 21)

1. **Individual stock Valuation** (~12 FT failures) — NFLX/GOOGL/MSFT/AMZN read overvalued vs rising 2023 rates with standard ZB/GC formula; Bernd reads "undervalued" because he uses `CampusValuationTool_V2`. Not fixable without that Pine Script.
2. **Equity index location override via presidential/sannial cycle** (~18 goldtest failures) — NQ/ES/YM near ATH shows Location=expensive, but Bernd buys because year-3 pre-election cycle is overwhelmingly bullish. Our `BP_roadmap.py` has the cycle data but uses it only as `roadmap_warning`, not a hard Location override.
3. **Forex location calculation** (remaining forex failures) — ±69 threshold fix + USD-base COT inversion applied; remaining failures are USDJPY×4 (COT neutral), 6S=F×3 (Valuation veto on Bernd discretionary supply trades), EURUSD×1 (Bernd counters his own COT signal).
4. **Phase 2B numeric-threshold frame verification** — 40 rules in queue at `_phase8_rebuild/phase2_frame_verify/queue_numeric_rules.jsonl`. ~400k Sonnet to complete.
5. **Seasonality forward-projection visual reading** — Pine Script projects 30 bars forward; our slope-over-20 is a faithful but limited proxy.
6. **NG=F goldtest class mismatch** — gold_cases_phase8.yaml has NG=F as `asset_class: energies` but live scanner uses `nat_gas` effective class (via `NAT_GAS_SYMBOLS`). Low priority since only 2 NG cases in goldtest.

---

## How to validate the project state right now

Run this from a fresh terminal in `D:\Azalyst Bernd Skorupinski\Propfirm Trading Dashboard`:

```bash
# 1. Run the audit harness end-to-end (160-case goldtest, Phase 25 baseline)
run_goldtest.bat
# OR equivalently:
uv run --python 3.12 --with pandas --with numpy --with pyyaml --with yfinance \
       --with requests --with curl-cffi python goldtest/run_goldtest.py \
       --cases-file goldtest/gold_cases_phase8.yaml

# Expected (Phase 25): Stage2=13/156, FP=0, Stage1=82/156, errors≈4 (yfinance flakiness)
# If false positives appear at Stage-2 → something regressed → revert last change.

# 2. Parse results for Stage-1/Stage-2/by-asset-class breakdown
uv run --python 3.12 python goldtest/parse_results.py

# 3. Run the Pine Script ↔ Python parameter drift detector
uv run --python 3.12 python audit_pine_to_python.py
# Expected: "no drift detected" — any DRIFT line is a real divergence to fix.

# 4. Run a live scan to confirm wiring
scan_daily.bat
# Expected: scan completes, dashboard opens at http://127.0.0.1:8765
# Expected: 0-3 signals (rare is correct — see "Working principles" above)
```

If Stage-2 full-signal drops below 13 or any false positives appear, something has regressed. The CLAUDE.md Phase 25 section is the latest reference; phases 22–25 brought the system from Phase 21's 73/156 = 46.8% Stage-1 to current 82/156 = 52.6% with **zero Stage-2 false positives preserved** across every phase.

---

**Last updated**: 2026-05-08 by Claude — Phase 25 in production. Weekly scan run (77 symbols). Methodology files 03/06/07 verified and corrected against Phase 25 canonical spec. SKILL.md updated: NG=F ZigZag 15% exception, NG Seasonality 5yr+10yr-only, breakeven Half-T1 rule, two-mode stop clarification, Valuation Pine Script refs corrected (equities: ZB1! only, ROC=10).

**Current state**: Phase 25 implemented. Stage-1 goldtest 82/156 = 52.6%, Stage-2 13/156 = 8.3% with **zero false positives across all 25 phases**.

**Phase 25 changes (DeepSeek-driven):**

(1) **`fetch_cot_data` simulation made opt-in** (`BP_data_fetcher.py`): on CFTC API failure, returns empty DataFrame instead of random synthetic data. Eliminates the worst live-trading risk — synthetic COT extremes triggering trades. Pass `allow_cot_simulation=True` to re-enable for development.

(2) **Zone-freshness filter on Location-Fib** (`BP_rules_engine._analyze_htf`): stale (consumed or >25%-penetrated) zones no longer distort the "cheap/expensive" Fib reading. Filters via `qualifier_scores.Q3 > 0`.

(3) **Stock SMA proxy intraday guard** (`_stock_valuation_proxy`): rejects sub-daily data (`med_days < 0.9`) instead of mis-calibrating the 3yr SMA. Also robust timestamp column detection (`'timestamp'`/`'Date'`/`'date'`/`'Datetime'`).

(4) **Constituent secondary-vote requires ≥2 stocks** before downgrading the AAPL+MSFT primary signal — prevents a single noisy NVDA reading from overriding.

(5) **NG=F seasonality enforced (5y, 10y) only** in code (was documented but not enforced — `Seasonality.calculate_multi` would still compute 15y).

(6) **Calendar staleness warning** at year boundary so the operator knows when to refresh `_HIGH_IMPACT_2026+`.

**Confirmed correct by DeepSeek (no action):** COT V2 formula, thresholds, group routing, USD-base inversions, Valuation ROC math, Seasonality bins, zone detection, COT-is-king, counter-trend gate, equilibrium gate, Phase 24 T1 relaxation, forex Location inversion.

**CFTC API confirmed working.** `fetch_cot_data(get_cftc_code('GC=F'))` = `fetch_cot_data('088691')` returns real CFTC data. Direct symbol call `fetch_cot_data('GC=F')` returns no-match → empty DataFrame (Phase 25 changed: was simulation, now neutral). Goldtest uses correct `get_cftc_code()` flow.

**Goldtest display format note**: The goldtest terminal output "OK/DIVERGE" shows Stage 2 (`bias_match` — full signal including zone arrival). Stage 1 (`bias_only_match`) is computed from `gold_results.json` post-run by `parse_results.py`. The progression table above uses Stage 1.


## Phase 46 Reconciliation Update (2026-09-14)
We have performed a full reconciliation against the Master Reference PDF. Several discrepancies between the code (Phase 25) and the 28-lesson scope were identified and resolved via feature flags for A/B testing. See \CLAUDE.md\ for full details.

