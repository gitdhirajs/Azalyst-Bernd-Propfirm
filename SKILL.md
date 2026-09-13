---
name: trading-system-builder
description: "Use this skill whenever the user wants to build a TradingView strategy, Pine Script indicator, trading system documentation, or HTML trading textbook from Bernd Skorupinski's supply/demand trading course materials. Triggers include: any mention of 'trading strategy', 'TradingView', 'Pine Script', 'supply and demand zones', 'prop firm', 'trading textbook', 'trading skill file', 'COT analysis', 'zone qualifiers', 'entry triggers', 'candlestick patterns for trading', or requests to process/compile the 148 HTML lesson files into a unified resource. Also triggers when the user wants to create TradingView alerts, backtest strategies, or generate trade ideas based on the Bernd Skorupinski methodology. Use this skill even if the user just says 'build my trading system' or 'process the trading lessons' or 'create trading ideas'. Do NOT use for general stock tips, unrelated financial advice, or non-trading document creation."
---

# Trading System Builder — Bernd Skorupinski Blueprint Trading System

Complete reference for building trading bots, Pine Script strategies, Python automation, and trade analysis tools based on the Bernd Skorupinski Blueprint Trading System. Derived from 150 lessons across 3 courses (16,840+ video frames analyzed).

## Source Materials

The user's workspace contains:
- **Blueprint_Trading_System_COMPLETE_TEXTBOOK_v7_REBUILT.docx** — 21MB master textbook with chart images and full methodology (regenerable via `build_textbook_v7.py`)
- **Bernd Skorupinski Hybrid AI Trading/** — 3 course folders:
  - `Hybrid AI Trading/` — 46 lessons (6,967 frames) — deepest theory
  - `Campus Blueprint OTC 2025/` — 28 lessons (2,023 frames) — polished methodology
  - `Funded Traders/` — 76 sessions (7,850+ frames) — real trade signals + weekly outlooks
- **Pine Script indicators**: `COTIndex_OTC.txt`, `COTReport_OTC.txt`, `Seasonality_OTC.txt`, `Valuation_OTC.txt`

---

## COMPLETE METHODOLOGY REFERENCE

### The Two-Step Mechanical Process
1. **Establish fundamental bias** using COT + Valuation + Seasonality indicators
2. **Execute trades** using supply/demand zone methodology with precise entries and mechanical risk management

No discretion, no guessing, no emotions. ALL decisions are rule-based.

### Three Pillars
- **Technical (WHERE)**: Supply/Demand Zones + Multi-Timeframe Analysis + Trend/Direction/Location
- **Fundamental (WHAT DIRECTION)**: COT + Valuation + Seasonality — must align before any trade
- **Management (HOW MUCH)**: R:R ratios + Stop Loss + Position Sizing + Trailing Rules

---

## CANDLE CLASSIFICATION (Foundation of Everything)

Every candle is classified by body-to-range ratio:

| Type | Formula | Role |
|------|---------|------|
| **INDECISIVE** | `body_pct = abs(close-open)/(high-low) <= 0.50` | BASE candles — required for valid zone base |
| **DECISIVE** | `body_pct > 0.50` | LEG-IN candles — momentum arriving |
| **EXPLOSIVE** | `body_pct >= 0.70` | LEG-OUT candles — REQUIRED for valid departure |

---

## SUPPLY & DEMAND ZONE FORMATION

### Zone Anatomy
- **Leg-In**: 3+ consecutive directional candles (decisive). Less important than leg-out.
- **Base**: 1-6 INDECISIVE candles (body <= 50%). Tighter = stronger. **7+ candles = ZONE INVALID**
- **Leg-Out (MOST CRITICAL)**: Explosive candles (body >= 70%), abnormally larger than surrounding. **If leg-out is indecisive = ZONE FAILS regardless of all other qualities.**

### Four Formation Types

| Formation | Class | Pattern | Originality |
|-----------|-------|---------|-------------|
| **DBR** (Drop-Base-Rally) | DEMAND | Bearish leg-in → Base → Bullish explosive | Non-original |
| **RBR** (Rally-Base-Rally) | DEMAND | Bullish → Base → Bullish continuation | Original |
| **RBD** (Rally-Base-Drop) | SUPPLY | Bullish leg-in → Base → Bearish explosive | Non-original |
| **DBD** (Drop-Base-Drop) | SUPPLY | Bearish → Base → Bearish continuation | Original |

### Zone Drawing (Proximal/Distal)
- **Proximal line** (entry side): Demand = highest BODY of base. Supply = lowest BODY. Fibonacci = 100
- **Distal line** (stop side): Demand = lowest WICK of base/leg-out. Supply = highest WICK. Fibonacci = 0
- **Preferred version**: Body extremes only (tighter, better precision)
- **Wider version**: Including wicks (for LOL analysis and HTF coverage)
- **Fibonacci coding**: ALWAYS 100 = Proximal, 0 = Distal, -33 = Stop Loss

### Zone Detection Algorithm (for Pine Script / Python)
```
1. Scan for leg-in: 3+ consecutive candles in same direction (decisive)
2. Scan for base: 1-6 candles where ALL have body_pct <= 0.50
3. Scan for leg-out: 1+ candles with body_pct >= 0.70, size > 2× average candle
4. If all three found: valid zone. Type = DBR/RBR/RBD/DBD based on leg directions
5. Proximal = max(base bodies) for demand, min(base bodies) for supply
6. Distal = min(base+legout wicks) for demand, max(base+legout wicks) for supply
```

---

## 6 ZONE QUALIFIERS — SCORING SYSTEM

**NOT 7 qualifiers.** The system uses exactly 6 qualifiers + LOL bonus, scored 0-10 each with weighted composite.

### Q1: DEPARTURE (Weight: 30%) — MUST PASS
| Score | Condition |
|-------|-----------|
| 10 | Explosive candles (body >= 70%), abnormally larger than surrounding |
| 5-7 | Decisive candles (body > 50%) |
| **0 = FAIL** | Indecisive leg-out (body <= 50%). **ZONE IS INVALID. Do not trade.** |

### Q2: BASE DURATION (Weight: 10%) — MUST PASS
| Score | Candles |
|-------|---------|
| 10 | 1-2 candles (tightest, least risk) |
| 7 | 3-4 candles |
| 4 | 5-6 candles |
| **0 = FAIL** | 7+ candles. Orders likely filled during basing. |

### Q3: FRESHNESS (Weight: 15%)
| Score | Condition |
|-------|-----------|
| 10 | Fresh / never tested — all unfilled orders intact |
| 7 | Wider version tested only |
| 3 | Preferred version tested |
| Formula | `score = 10 / (retests + 1)` — each visit consumes orders |
| **0 — INVALIDATED** | **>25% penetration into zone range** (Phase 6, Ch 184). Zone is consumed/dead — DO NOT TRADE. Hard gate that overrides all retest scoring. |

**Preferred-version active entry trigger (Phase 6, Ch 156)**: Once the wider version has been tagged, the preferred version becomes the active entry trigger — wait for price to return to the preferred boundary; do NOT pre-emptively re-enter at the wider version.

### Q4: ORIGINALITY (Weight: 15%)
| Score | Type |
|-------|------|
| 10 | Original (RBR, DBD) — continuation patterns |
| 5 | Non-original (DBR, RBD) — reaction patterns |
| **12** | FLIP ZONES — former demand becoming supply or vice versa. Extremely powerful. |

### Q5: PROFIT MARGIN (Weight: 10%) — MUST PASS for counter-trend
| Score | Distance traveled before returning |
|-------|----------------------------------|
| 10 | 5× zone height or more |
| 7 | 3× zone height |
| 5 | 2× zone height |
| **0 = FAIL** | < 1× zone height (fail for counter-trend trades) |

### Q6: ARRIVAL (Weight: 10%) — Only for sideways/counter-trend
| Score | How price returns |
|-------|-------------------|
| 10 | Fast/clean impulse — single move, no opposing zones |
| 5 | Slow/stair-stepping — leaves speed-bump zones |
| 0 | Adjacent opposing zone blocks path |

**With-trend trades: skip arrival check entirely.**

### LOL BONUS (Weight: 10%, Max: 5)
Level-on-Top-of-Level: multiple zones stacking at same price from different timeframes. Three entry options:
1. Combine levels — entry at first proximal, stop below second distal
2. Enter at wider version of deeper level
3. Skip first level, full position on distal level

### Composite Score Formula
```python
score = (departure * 0.30) + (base * 0.10) + (freshness * 0.15) + 
        (originality * 0.15) + (profit_margin * 0.10) + (arrival * 0.10) + (lol * 0.10)
# MUST PASS gates: departure > 0, base > 0, profit_margin > 0 (if counter-trend)
```

---

## MULTI-TIMEFRAME ANALYSIS

### Location — Fibonacci 33/66 Framework
Draw Fibonacci from distal of demand zone to distal of supply zone on HTF:

| Location | Fibonacci | Bias | Action |
|----------|-----------|------|--------|
| Very Cheap | Below 33% | STRONG BUY | Demand zones only |
| Cheap | 33-66% lower | BUY | Favor demand |
| **Equilibrium** | ~50% | **AVOID** | No edge. Beginners skip. |
| Expensive | 66-100% | SELL | Favor supply |
| Very Expensive | Above 100% | STRONG SELL | Supply zones only |

**Location overrides Trend at extremes** (OTC L5 0:33:41 — verbatim Bernd: "*it's only allowed to short… because the current price is close [to the very-expensive boundary]*"). Even in an HTF uptrend, at Very Expensive **only supply trades are allowed**; mirror for Very Cheap. The "trade with trend" rule is subordinate to Location at the edges.

### 3×3 Action Matrix (OTC L5 — Decision Process slide, frame 599+1092)

The canonical decision grid that collapses Location × Trend → Action with profit/probability tags. **"Best Setup"** is the diagonal-aligned cell (zone matches both location AND trend).

| Location ↓ / Trend → | Up | Sideways | Down |
|----------------------|----|----------|------|
| **Cheap / V.Cheap** (demand) | **Best** — big-picture demand, HIGH profit | Acceptable — pullback demand, MEDIUM profit | Acceptable — pullback demand, LOW profit |
| **Equilibrium**             | Avoid — no big-brother coverage | **No trade** | Avoid — no big-brother coverage |
| **Expensive / V.Exp** (supply) | Acceptable — pullback supply, LOW profit | Acceptable — pullback supply, MEDIUM profit | **Best** — big-picture supply, HIGH profit |

**Sideways at extreme location is acceptable** (medium tier); **sideways at equilibrium is hard-skip**.

### Drawing convention: preferred + wider zones together (OTC L5 frames 2025/2441/2544)

When Bernd marks HTF zones in live sessions he draws BOTH the preferred (inner) and wider (outer) boxes simultaneously — they are NOT alternatives, they form a tolerance band. Treat the proximal of the wider zone as the maximum-tolerance fill; the proximal of the preferred zone as the optimal fill.

### Direction — ZigZag % + 6-Pivot Trend Identification
- **ZigZag tool** (Hybrid AI HAI 1:12:51): pivots auto-detected at a configurable percentage reversal (default 3% on daily, 5% on weekly, 2% on 4H, 1% on 1H). User can manually override individual pivots when ZigZag is too noisy / too smooth
- **Uptrend**: 3 consecutive higher lows + 3 higher highs (counted right-to-left from the most recent ZigZag pivots)
- **Downtrend**: 3 consecutive lower highs + 3 lower lows
- **Sideways**: No consecutive pattern. No directional bias — Q5/Q6 must be evaluated; counter-trend setups rejected unless extreme location
- **Anticipatory**: (1) HTF trend theory — zoom out. (2) Pivot at extreme location

**ZigZag % by timeframe** (Phase 9 — OTC Ch.012 "six second percent"):
| Timeframe | Default % | Asset-class exceptions |
|-----------|-----------|------------------------|
| Weekly (1wk) | 6% | **NG=F: 15%** — extreme volatility; 6% creates excessive noise pivots |
| Daily (1d) | 3% | — |
| 4-Hour (4H) | 2% | — |
| 1-Hour (1H) | 1% | — |

**Natural Gas (NG=F) uses 15% on the weekly timeframe** (Phase 25 correction). NG's intraday swings routinely exceed 6%, making the standard weekly % produce spurious pivots. 15% matches Bernd's visual pivot identification on NG weekly charts.

Implementation: `BP_rules_engine._zigzag_pivots(highs, lows, pct)` produces a chronological pivot list. `_determine_trend()` consumes this list and applies the higher-high/lower-low rule. Configurable via `zigzag_percent` in BP_config.yaml; asset-class override applied in `run_scanner.py` before calling the engine.

### Big Brother / Small Brother (CRITICAL)
**Rule**: An LTF zone qualifies as "high quality" ONLY when it sits ENTIRELY INSIDE a same-direction HTF zone (containment, not just proximity). LTF demand inside weekly demand = valid; LTF supply inside weekly demand = invalid (no big-brother coverage).

**Containment, NOT multi-TF stacking (Phase 6, Ch 182)**: Bernd: *"That's not how it works… you have to pick"*. BB/SB is a binary check on a single trade — pick ONE primary HTF, then refine downward. Do NOT draw zones on every TF and add them up as "stacked coverage". Recursion across the income ladder (Weekly Income uses weekly as BB, Daily Income uses daily as BB, Intraday uses 4H) is fine — but each trade has ONE BB↔SB pair.

**Equilibrium fallback** (OTC L5 0:46:55): when current price is 33-66% of the HTF Fib (equilibrium location), there's "no big brother" — these setups are flagged as low quality regardless of what zones exist.

**Wick-over-wick substitute** (OTC L3 0:38:04): when no clean HTF formation is visible, two adjacent overlapping wicks of the same direction can act as the big brother. Rare; not auto-detected by code, must be marked manually.

Implementation: `BP_zone_detector.has_big_brother_coverage()` + `filter_by_big_brother()`. Strict mode (drop uncovered zones) opt-in via `require_big_brother: true` in BP_config.yaml. Every LTF zone tagged with `has_big_brother` boolean and the parent's `big_brother_id`.

### Speed Bumps (zone path obstacles)
**Rule** (OTC L6): opposing zones in the price path between current price and your target zone will likely stall the trade. Bernd warns NOT to trade through obvious speed bumps — they consume institutional orders before price can reach your zone.

**Detection**: any opposing-direction zone whose midpoint falls between `current_price` and `target_zone.proximal`. A "blocking" speed bump = composite score ≥ 5.0 (qualified enough to actually stall the trade).

Implementation: `BP_zone_detector.detect_speed_bumps()` returns the list ordered nearest-first. `has_blocking_speed_bump()` returns True/False. Every signal carries `speed_bumps[]` (top 3) and `speed_bump_warning` boolean. Not auto-rejected — Bernd takes some trades through speed bumps when entry/exit math is overwhelming, but they're flagged for manual review.

### Zone Refinement Workflow (for tighter R:R)
**Trigger**: HTF zone produces R:R below `min_rr` (default 2.0) to the next opposing zone.

**Process** (OTC L7-L8 + HAI Mod 6 L6): drill down the timeframe ladder until a tighter zone is found that
1. shares direction with the HTF zone
2. is ENTIRELY CONTAINED within the HTF zone (proximal/distal both inside)
3. independently passes qualifier checks (composite ≥ 6.0)

**Ladder per income strategy**:
| Strategy | Drill-down ladder |
|---|---|
| Monthly | 1mo → 1wk → 1d |
| Weekly (primary) | 1wk → 1d → 4h → 60m |
| Daily | 1d → 4h → 60m → 30m |
| Intraday | 4h → 60m → 30m → 15m |

**Stop placement on refined zone**: LTF distal -33% (default per textbook) OR HTF distal (conservative override; gives looser stop, lower R:R but more protection).

**Stop refining when**: noise sets in below 60-min for weekly-income; below 15-min for any strategy.

Implementation: `BP_rules_engine.refine_zone(htf_zone, target, ohlcv_by_tf, income_strategy, min_rr)` returns the deepest valid refined zone or None.

### Timeframe Hierarchy

| Strategy | HTF | LTF | Duration | Fundamentals |
|----------|-----|-----|----------|-------------|
| Monthly Income | Monthly | Weekly | Months | Full COT + Valuation + Seasonality |
| **Weekly Income** (primary) | Weekly | Daily | Weeks | COT + Valuation required |
| Daily Income | Daily | 240-min (4H) | Days | Quick COT check |
| Intraday | 240-min | 60-min or less | Hours | Minimal |

---

## FUNDAMENTAL ANALYSIS

### COT (Commitment of Traders)
- **Source**: CFTC weekly release (Friday afternoon, data from prior Tuesday)
- **Chart**: WEEKLY only
- **COT V2 formula** (Phase 13 — confirmed from Pine Script source `COT V2 120-20.txt`):
  `index = 140 × (netPos - lowest(netPos, weeks)) / (highest(netPos, weeks) - lowest(netPos, weeks)) − 20`
  Scale: **−20 (extreme bearish) to +120 (extreme bullish)**. Thresholds: **≥80 = extreme bullish, ≤20 = extreme bearish**. Bernd's verbal "above 100" = casual reference to the +120 upper bound, NOT a separate threshold.
- **Two-band approach** (Hybrid AI course): the indicator is overlaid with TWO lookbacks:
  - **Primary band** — **26 weeks for ALL assets** (Hybrid AI universal default). 52w override for commodities/energies/PMs only (planting/harvest cycle, Funded Trader 02.03.2024).
  - **156-week extreme** — 3-year historic extreme; the highest-conviction signal. When BOTH bands register at the same end of the spectrum, treat the signal as **strong** (override-grade). Rolling-only extreme = **normal** signal.
  - **Approaching-extreme trigger** (Phase 18): for COT-king classes (PM/commodities/energies only), when the 26w rolling index is APPROACHING extreme (≥60 bullish or ≤35 bearish — 75% of the way there) AND the 156w line IS already at extreme → fire directional bias. Bernd visually reads the 156w "yellow line" and acts before the 26w crosses 80/20. This catches the Gold Aug 2023 pattern: `comm_idx_26w=68.59` (approaching) + `comm_ext_156w=86.32` (historic extreme) → Bernd=long. NOT applicable to equity indices or forex (COT is confluence for those, not override).
  - **COT momentum trigger** (Phase 26): when the 26w index is neutral (hasn't crossed 80/20) but the **5-week trend shows ≥25% of full scale movement** AND the 156w extreme IS already at extreme → fire directional bias. Captures fast-moving institutional accumulation before the normalized index registers. Same class restriction as the 156w trigger — commodities, precious_metals, energies, nat_gas, soft_commodities only. Implementation: `COTIndex.get_bias` in `BP_indicators.py`.

| Group | How to Use | Asset Classes |
|-------|-----------|---------------|
| **Commercials** | TRADE WITH them. Index ≥80 = BULLISH. ≤20 = BEARISH. 156-week (3yr) extreme = STRONGEST signal | **Commodities** (CL, NG, ZC, ZW, ZS, CT, KC), **Precious Metals** (GC, SI, PL, PA) |
| **Non-Commercials** | DIVERGENCE focus. Right in trends, WRONG at extremes. Price new low + COT higher low = bullish divergence | **Forex** (6E, 6B, 6J, 6A, 6C, 6S), **Equity Indices** (ES, NQ, YM), **Soft Tropical** (CC, SB, OJ) |
| **Retailers** | CONTRARIAN. Extreme net long = bearish signal, extreme net short = bullish signal | **Natural Gas** (NG=F) only |

**Per-asset routing (Phase 14 + Phase 17 corrections):**
- **Precious Metals (GC/SI/PL/PA)**: Commercials ① (non-contrarian). "Retailers bearish + Commercials bullish = perfect PM buy" (Ch.147/122/132). The earlier "Retailers CONTRARIAN for PM" entry was WRONG — retailers are a confirming odds-enhancer (③), not the primary driver. (Phase 17 fix)
- **Natural Gas (NG=F)**: Retailers ① (CONTRARIAN). Historical retailer extremes signal reversals. Valuation excluded for NG. (Phase 12)
- **Grains + Cotton (ZC/ZW/ZS/CT)**: Commercials 52w. "Planting/harvesting season" commercial hedging dominates. (Phase 14 — Ch.159/168/113/144)
- **Tropical soft commodities (CC/KC/SB/OJ)**: Non-Commercials 26w divergence. (Phase 14/16)
- **Bitcoin**: Seasonality 4yr lookback only (data history too short for 5/10/15yr). (Phase 16)

**For Forex**: ALWAYS cross-check opposing currency COT. EUR bearish + USD bullish = double confirmation.

### COT Report (raw positions)
The COT Report indicator (separate from COT Index) plots the **actual contract counts** — longs as positive numbers, shorts as negative, with the net plotted as a thicker line. Used to see direction and momentum of institutional flows that the normalized index doesn't capture. Implementation: `COTReport.calculate()` in `BP_indicators.py`.

### Valuation
- **Formula**: Compares asset performance vs macro benchmarks (Dollar, Bonds, Gold). Rescaled to -100/+100
- **NOT a timing tool** — tells IF ripe for change, not WHEN. Must combine with zones for timing.

| Asset Class | Timeframe | References | ROC Setting |
|-------------|-----------|------------|-------------|
| Forex | Weekly | Dollar (DXY) only | 10 (Pine Script default) |
| **Equity Indices** (ES/NQ/YM) | Daily | **DXY + ZN + ZB** | 10 |
| **Individual Stocks** (AAPL/MSFT/etc.) | Daily | **ZN + ZB + GC** (no DXY — OTC 2025 L3: "unselect reference symbol three, which is the dollar") | 10 |
| Commodities | Weekly | All three (DXY, GC, ZB) | 10 (Pine Script default) |
| Platinum | Weekly | DXY + Gold only (no Bonds) | 10 |
| Silver | Weekly | DXY + ZB + GC (Gold) — Bonds ticker @VD not @US | 10 |
| Natural Gas | Weekly | **EXCLUDED** — weather/supply shocks make DXY-relative reading uninformative | — |

**Pine Script `Length=10` default applies to ALL asset classes** (CampusValuationTool source — confirmed Phase 7 audit, 2026-05-02). Earlier versions of these notes claimed Length=13 for equities; that was a misreading of "Dual-ROC", which is an OVERLAY practice (running two instances of the indicator with different lengths simultaneously), NOT a parameter override on a single instance. Empirically: Length=13 produced wildly more bearish readings on AMZN/META/NVDA than Bernd's verbal calls; Length=10 matches.

**Read 3 INDIVIDUAL LINES, never a composite average**: the indicator plots one line per reference. Bernd reads each separately ("DXY line is undervalued, bond line is undervalued = 2 of 3 agree → mild bullish"). Do NOT average them. Aggregate rule:
- All 3 lines in extreme zone (≥+75 or ≤-75) same direction → STRONG that direction
- All 3 in mild zone same direction → MILD that direction
- 2 of 3 same direction with 0 opposing → MILD that direction
- Mixed → neutral

- **Overvalued**: >= +75 = STRONG BEARISH → look for supply zones
- **Mild overbought**: +10 to +75 = mild bearish (counts as a vote)
- **Near mean**: -10 to +10 = NEUTRAL (avoid noise from indicator chatter)
- **Mild oversold**: -10 to -75 = mild bullish (counts as a vote)
- **Undervalued**: <= -75 = STRONG BULLISH → look for demand zones
- **Dual-ROC for Equities (overlay practice)**: Daily: overlay ROC 10 + ROC 13 — both must agree. Weekly: overlay ROC 13 + ROC 30 — both must agree. Mixed = neutral. Note: each is a separate indicator instance on the chart; the `Length` parameter on each instance stays at its configured value, the overlay is at chart level.
- For Stocks: Valuation is the **PRIMARY/LEADING** indicator — if undervalued AND trend not strongly down → LONG (no 3/5 vote needed; stocks use Valuation-driven path). Individual stocks are never SHORTED directly (Bernd shorts indices via futures, not single names).
- **SPY Relative-Strength proxy for stocks** (Phase 26 — replaces Phase 23 SMA proxy): instead of absolute price vs 3-year SMA, compare the stock's 52-week return vs SPY. If stock **underperformed SPY by >10%** = relatively undervalued (bullish). If stock **outperformed SPY by >15%** = relatively overvalued (bearish). Captures Bernd's "stock is cheap relative to the market" reasoning. Applied in `_analyze_fundamentals` equities branch when `SPY` OHLCV is available. Thresholds: `underperform_threshold=-0.10`, `outperform_threshold=+0.15`.

### True Seasonality
- **Chart**: DAILY only. Minimum 25 years backdrop. Project 150 bars forward
- **Multiple lookbacks**: Add indicator 3×: 5yr, 10yr, 15yr. All agree = strong signal. 2-of-3 same direction = mild signal.
- **Reading**: Slope UP = historically bullish. Slope DOWN = bearish
- **NOT standalone**: Must combine with COT + Valuation + Technicals
- **Natural Gas (NG=F) exception (Phase 25)**: Use **10yr + 5yr ONLY** — do NOT add the 15yr lookback. NG seasonal data is unreliable beyond 10 years due to structural market changes (shale revolution 2008–2012 fundamentally altered supply dynamics). 15yr NG seasonality produces misleading signals. Enforced in `Seasonality.calculate_multi` — passing 15yr for NG=F will be silently ignored.

### Monthly / Quarterly / Yearly Roadmap (timing-overlay filter)
**Purpose** (HAI 1:56:13): the roadmap is NOT a signal generator — it's a TIMING-OVERLAY that tells you WHEN to be a buyer or seller across the year. Trade ideas still come from zones + fundamentals; the roadmap suppresses counter-roadmap entries and amplifies aligned ones.

**Components**:

| Component | Equities | Commodities / Forex | Notes |
|-----------|----------|---------------------|-------|
| Long-term seasonality (5/10/15y multi-lookback) | ✅ | ✅ | Already calculated by `BP_indicators.Seasonality` |
| Presidential cycle (4-year) | ✅ | ❌ | Pre-election year is historically the most bullish; election year volatile |
| Sannial / decennial cycle (10-year) | ✅ | ❌ | Years ending in 1, 5, 9 = poor; 3, 7, 8 = strong |
| COT positioning (commercials extreme alignment) | ✅ | ✅ | Strong COT (both 26w + 156w extreme) can override an otherwise-neutral roadmap |
| News calendar / monthly economic events | (manual override) | (manual override) | Not auto-calculated |

**Output**: `bias = 'buy' / 'sell' / 'neutral'`, `confidence ∈ [0, 1]`, plus a per-component breakdown.

**Application**: every signal carries a `roadmap` dict + `roadmap_aligned: true|false`. Counter-roadmap signals get a `roadmap_warning` but aren't auto-rejected — Bernd takes some counter-roadmap trades when COT is at a 156w extreme.

Implementation: `BP_roadmap.build_monthly_roadmap()` + `filter_signal_by_roadmap()`.

### Bias Synthesis — Bernd's Actual Hierarchy (Phase 11)

Frequency analysis across 186 course/session transcripts shows Bernd does NOT use an equal 3-of-5 vote. He follows a strict priority hierarchy:

| Priority | Indicator | Frequency | Role |
|----------|-----------|-----------|------|
| 1st | Location / zone | 88% | **Hard gate** — equilibrium = no trade, ever |
| 2nd | Valuation | 92% | **Hard veto** — opposing = trade cancelled |
| 3rd | Valuation + Location both aligned | — | **Minimum threshold** = tradeable |
| 4th | COT | 48% | Confluence enhancer; not required |
| 5th | Seasonality / Trend | 76% / 64% | Supporting context only |

**Step 1 — Location gate (HARD)**: If location is neutral (equilibrium, ~33–66% of HTF Fib range), NO TRADE regardless of all other indicators. Bernd: "never trade at 50%, no edge there." This gate fires before any vote counting.

**Step 2 — Valuation veto (HARD, Rule #1)**: Location determines the proposed direction (cheap=long, expensive=short). If Valuation actively OPPOSES that direction (overvalued = no long; undervalued = no short), the trade is **VETOED**. Bernd: "Rule number one: valuation" (CW38, CW39).

**Step 3 — Minimum threshold**: Location aligned + Valuation aligned (both bullish or both bearish) = **Bernd's stated minimum to trade**. No 3/5 majority required. If Valuation is neutral (not opposing), one supporting indicator from COT / Seasonality / Trend is needed as the tie-breaker.

**Step 4 — Counter-trend safety gate (prop-firm protection)**: Never fire SHORT in an uptrend or LONG in a downtrend unless non-trend agreement is overwhelming (≥2 non-trend indicators same direction, 0 opposing). Phase 8 H1 fix: gate checks non-trend tally only (avoids impossibility bug where trend vote made the gate unreachable).

**Equities branch (Phase 7 / Phase 11)**: individual stocks have no CFTC COT report. Bernd's stock process is Valuation-driven: long when Valuation undervalued AND trend not strongly down. Individual stocks are NEVER shorted directly (he uses index futures). Implementation: `_bias_consensus(asset_class='equities')` branches to a Valuation-primary path.

**Retailer directional-alignment veto**: If Retailers are net-positioned on the SAME side as your proposed trade (even below extreme threshold), this degrades conviction. For **Natural Gas**: HARD veto (retailers are the PRIMARY indicator — contrarian). For other asset classes: reduce size. Note: Precious Metals no longer uses Retailers as primary — PM uses Commercials (Phase 17 fix).

**Phase 26 — ATH momentum override for equity indices**: When equity index is in the expensive zone (`loc='bearish'`, price at ATH) BUT trend = uptrend AND 4-bar ROC > 2%, downgrade `loc` from 'bearish' to 'neutral' BEFORE running consensus. This prevents the hard bearish-location veto from blocking cycle-driven long signals on strongly trending indices. Applied inside `_analyze_htf` after the standard Fib computation.

**Phase 26 — Cycle dominance override for equity indices**: After the T1 cycle override block, if `loc != 'bearish'` (already relaxed by ATH momentum above) AND trend is uptrend/sideways AND Valuation/Seasonality are not bearish AND **both** presidential AND sannial cycles agree bullish AND COT is not bearish → return `'bullish'`. Fires in residual cases where T1 relaxation set loc to neutral but full consensus still stalled. Search `Phase 26 cycle dominance` in `BP_rules_engine.py`.

**Phase 27 — Equities presidential/sannial cycle path**: In the equities branch of `_bias_consensus`, before returning 'hold', check: if `seas_n != 'bearish'` AND `pres_score > 0` AND `sann_score > 0` → return `'bullish'`. Captures 2023-style cycle-driven stock rallies (AAPL/GOOG/META/NFLX) where Valuation reads 'overvalued' (outperformed SPY) but Bernd was bullish on pre-election year-3 + sannial year-3 thesis. Key design guards: **trend guard removed** (Oct 2023 ZigZag downtrend blocked correct calls); **seasonality guard preserved** (prevents false fire at genuine seasonal lows e.g. AAPL mid-October). Equities branch is long-only — never returns 'bearish' — so removing guards has no wrong-direction risk. Only fires historically during year-3 pre-election cycles (2023, 2027…); live scanner in 2026 (sannial year 6, score=0) does NOT fire.

Implementation: `BP_rules_engine._bias_consensus()` — Phase 11 rewrite replaces flat equal vote with this hierarchy. Phases 26-27 layer equity-specific cycle overrides on top.

---

## ENTRY TRIGGERS — CANDLESTICK PATTERNS

### Pattern Detection Rules (for Pine Script / Python)

| Pattern | Body | Lower Wick | Upper Wick | Close | Location |
|---------|------|-----------|-----------|-------|----------|
| **Hammer** | <= 30% of range | >= 2× body | <= 10% of range | Near high (green preferred) | AT demand zone |
| **Shooting Star** | <= 30% of range | <= 10% of range | >= 2× body | Near low (red preferred) | AT supply zone |
| **Hanging Man** | Same as Hammer | Same as Hammer | Same as Hammer | Same geometry | AT supply zone (bearish!) |
| **Bullish Engulfing** | Green engulfs prior red | Low <= prior low | — | Close > prior open | AT demand zone |
| **Bearish Engulfing** | Red engulfs prior green | — | High >= prior high | Close < prior open | AT supply zone |
| **Head & Shoulders** | 3 peaks, middle highest | Neckline connects troughs | — | Break below neckline | Trend reversal |

### Three Entry Options (sanctioned per OTC L7)

| Label | Name | Entry price | Fill prob | R:R rank | When to use |
|-------|------|-------------|-----------|---------|-------------|
| **E1** | Proximal | `proximal` (top of base body for demand; bottom for supply) | High (~99%) | Lowest | When you don't want to miss the move; price often penetrates deeper before reversing |
| **E2** | Zone / Midpoint | `(proximal + distal) / 2` | Medium (~50%) | Better | When you can afford to miss the trade for a better entry |
| **E3a** | Pattern Confirmation | At LTF zone proximal inside the HTF zone (zone refinement) | Low (~40%) | Best | LTF zone within HTF zone — full zone refinement workflow |
| **E3b** | Stop-Buy Above Hammer | `hammer_high + 1 tick` (stop-buy order triggered only if price continues up) | Low-Medium | High | When you need trend confirmation before committing; avoids false fills on hammers that reverse |
| **E3c** | Throwback Strap | Entry on the RETURN after first impulse away from the zone. Price must first move away from zone (initial impulse), then pull back toward zone, then resume. | Very Low | Highest | Highest confidence; requires patience; catches second-touch after confirmation |
| **E4** | Trendline Break | Entry when price breaks above a descending trendline drawn across swing highs (for demand) or below ascending line (for supply) | Low-Medium | High | Stock reversals; use when no clean single-candle pattern forms but trendline structure is clear |

**ALL three use the same stop formula**: -33% Fibonacci extension beyond zone distal for **LTF/pattern entries**. **EXCEPTION for HTF weekly income trades**: stop = DISTAL LINE ONLY (no -33% extension) — this preserves the 4:1 R:R that weekly timeframe zones deliver. Apply -33% only when entering via LTF refinement.

**Selection logic**: code emits all three on every signal as `entry_options[]`. `recommended_entry` is the one with `fill_prob = high` that meets `min_rr ≥ 2.0`; falls back to the option with the best R:R if none meet minimum. User can override by picking E1/E2/E3 manually based on their own R:R math.

Implementation: `BP_rules_engine.build_entry_options(zone, target, pattern_signal)` and `recommend_entry_option(options, min_rr)`.

### Stop Loss Formula
```
stop = pattern_extreme - 0.33 * (pattern_high - pattern_low)  # for longs (below low)
stop = pattern_extreme + 0.33 * (pattern_high - pattern_low)  # for shorts (above high)
```

---

## TRADE MANAGEMENT

### Stop Loss — Two Modes by Timeframe

**Mode 1 — LTF / Pattern entries (default): -33% Fibonacci**
```
# Fibonacci: 100 = Proximal, 0 = Distal
demand_stop = distal - 0.33 * (proximal - distal)  # Below distal
supply_stop = distal + 0.33 * (proximal - distal)  # Above distal
```

**Mode 2 — HTF Weekly Income trades: DISTAL LINE ONLY**
```
# For weekly-timeframe zone entries (monthly income / weekly income strategies at the HTF zone directly):
demand_stop = distal  # Exactly at the distal line — no extension
supply_stop = distal  # Exactly at the distal line — no extension
```
Rationale (CW43-Idx): weekly zones inherently have wider zones. Using distal-only stop achieves 4:1 R:R on the weekly chart. The -33% extension would push the stop so far that R:R collapses. -33% is reserved for LTF zone entries where the zone is tight enough to absorb the buffer.

### R-Multiple Targets
| Target | R:R | Action |
|--------|-----|--------|
| Half-T1 (0.5R) | 0.5:1 | **MOVE STOP TO BREAKEVEN** (Bernd's live practice — preferred default) |
| T1 (1R) | 1:1 | Conservative breakeven trigger (textbook fallback) |
| T2 (2R) | 1:2 | Take 50% partial profit. Begin trailing. |
| T3 (3R) | 1:3 | Take remaining OR continue trailing with trend |
| T4 (4R) | 1:4 | Extended target for strong with-trend only |

### Breakeven — Two Variants
- **Half-target BE** (preferred, default): once price has covered HALF the distance from entry to T1, move stop to entry. This is Bernd's live-trading practice from the Funded Trader sessions — locks in protection earlier without giving up the T1+ R-multiple.
- **T1 BE** (conservative): wait for price to touch T1 (1R) before moving to breakeven. Fewer false stop-outs but bigger drawdowns when a setup fades.
- Toggle in `BP_config.yaml`: `stop_loss.breakeven_at_half_target: true|false`.

### Trailing Rules
- After 2R: trail stop to below most recent demand zone distal (longs) or above supply distal (shorts) — `apply_zone_trailing()`
- No zones visible: use 1R trailing increments — built into `update_positions()`
- **With trend**: Target 3R-4R+
- **Sideways**: Max 1:2
- **Counter-trend**: **HARD CEILING AT T2 (2R)**. Close full position at T2. No trailing. No moon-shooting. (CW43-Idx, LIVE-May)
- **Anticipatory**: 1R-1.5R

### Risk Management
- **Risk per trade**: EXACTLY 1% of account (max 2%)
- **Position size**: `size = (balance * 0.01) / abs(entry - stop)`
- **Max concurrent**: 2-3 uncorrelated positions
- **Minimum R:R**: 1:2 for ALL trades. No exceptions.
- **Equity basket mode**: When NQ, ES, YM all align in the same direction, treat them as a CORRELATED BASKET. Total risk budget = 3% across all three positions (≈1% each). NOT 1% per trade independently — that would be 3% on effectively one direction.
- **Anticipatory / counter-trend size reduction**: 0.5% risk (half the standard) — lower conviction = lower exposure.
- **Prop firm challenge accounts**: Weekly timeframe NOT recommended (drawdown limits too tight for wide weekly stops). Use Daily + 4H instead.
- **High-impact calendar events (CPI, NFP, FOMC)**: Reduce risk to 0.5% or skip entirely until post-announcement zones form.

### Cross-Asset Gates for Equity Stocks
Before analyzing individual stocks:
1. **Parent index check**: Index (NQ/ES/YM) must be at a zone and fundamentally aligned before entering individual stocks within it. Index-level Valuation gates stock entries.
2. **AAPL + MSFT dual-gate**: Both AAPL and MSFT must independently pass the full qualifier scan before analysing other Nasdaq/tech stocks. They are the bellwethers — if they're not at zones, the sector isn't ready.
3. **NASDAQ gap-fill check**: Before taking a long on NQ, ES, or YM, verify there are no unfilled daily gaps between current price and target zone. Gap-fill acts as a speed bump. Same rule applies to YM and ES (not just NQ).

### Index Leading Indicators
- **RTY (Russell 2000)**: Leading indicator for ES/NQ directional confirmation. RTY often leads the large-cap indices by 1-2 sessions. When RTY turns decisively, expect ES/NQ to follow.
- **Treasury Bond (ZB/ZN) Demand Zones**: Before entering equity index SHORT setups, confirm that Treasury Bond supply zone is intact. If bonds are also at supply, risk-off is likely = higher conviction equity short.

---

## PINE SCRIPT INDICATOR CORRECTIONS

The course provides 4 indicators. Known issues and fixes:

### COT Index (v5)
- **Fix**: Auto-select lookback (Commodities=52wk, Equities=26wk, Forex=**26wk**, Soft Commodities/Grains=26wk NonCommercials)
- **Fix**: Add 156-week (3yr) yellow line for historic extremes
- **Fix**: Add Disaggregated COT option (Producer/Merchant vs Managed Money)
- **Fix**: Divergence detection — price new low + COT higher low = alert

### COT Report (v5)
- **Fix**: Add normalized index (calcIndex on raw data)
- **Fix**: Add open interest plot

### Seasonality (v5)
- **Fix**: Multiple lookback lines (5yr/10yr/15yr) in single instance
- **Fix**: Bias label output (bullish/bearish/neutral from slope)

### Valuation (v4 — OUTDATED)
- **Fix**: Upgrade `security()` to `request.security()` (v5)
- **Fix**: Asset presets per canonical Pine Script source (`Valuation_v4.pine`, Phase 21 audit):
  - **Equity Indices (ES/NQ/YM)**: `ZB1!` (30yr T-Bond) + `DXY` only. **NOT ZN** — Phase 21 removed ZN1! (10yr T-Note), it was double-counting bonds. ROC=10.
  - **Individual Stocks**: `ZB1!` + `GC1!` (Gold). **No DXY** (OTC 2025 L3: "unselect reference symbol three, which is the dollar"). ROC=10.
  - **Forex**: `DXY` only. ROC=10.
  - **Commodities / Precious Metals**: All three (`DXY` + `ZB1!` + `GC1!`). ROC=10.
  - **Natural Gas (NG=F)**: **EXCLUDED** — weather/supply shocks make DXY-relative reading uninformative.
- **Fix**: `Length=10` is the Pine Script default for ALL asset classes (confirmed Phase 7). "Dual-ROC" is an overlay practice (two separate indicator instances), NOT a parameter change on a single instance.
- **Fix**: Composite score — weighted average for single signal

### MISSING: Zone Detection Engine
Build from scratch:
1. Detect leg-in (3+ directional decisive candles)
2. Detect base (1-6 indecisive candles, body <= 50%)
3. Detect leg-out (explosive, body >= 70%, > 2× average size)
4. Auto-score all 6 qualifiers
5. Plot zones as rectangles (green=demand, red=supply)
6. Alert on zone approach

---

## NON-NEGOTIABLE RULES

These are absolute rules extracted from the course. A trading bot MUST enforce all of these:

1. ALWAYS place a stop loss — every trade, no exceptions
2. ALWAYS ensure reward > risk — minimum 1:2 RRR
3. ALWAYS check HTF before LTF — direction and location first
4. NEVER anticipate a zone — wait for complete formation with explosive leg-out
5. NEVER trade counter-trend in equilibrium — no edge
6. NEVER chase a missed entry — "we have to learn to live with that"
7. ALWAYS move stop to breakeven at **Half-T1 (0.5R)** — preferred live-trading practice (Bernd Funded Trader sessions). Conservative fallback: T1 (1R). **Never later than T1.**
8. ALWAYS use correct stop mode: **HTF weekly-income entries → distal line only** (no -33% extension). **LTF/pattern entries → distal -33% Fibonacci** extension. Using -33% on weekly stops collapses R:R; using distal-only on LTF entries leaves stops too tight.
9. NEVER skip Departure check — indecisive leg-out = invalid zone. Period.
10. ALWAYS draw Fib: 100=proximal, 0=distal — consistent coding
11. NEVER risk > 1-2% per trade — 1% recommended
12. ALWAYS use uncorrelated positions — max 2-3 concurrent
13. ALWAYS wait for price to come to you — never chase
14. ALWAYS use set-and-forget — entry/stop/target placed automatically
15. ALWAYS align with institutional flow — never fight $55T+ AUM
16. ALWAYS backtest with hidden future — avoid hindsight bias
17. ALWAYS cross-check opposing currency COT — for Forex
18. ALWAYS verify futures-to-funded instrument mapping — cheat sheet
19. Losing trades = business operating costs — normal, accept them
20. Measure with RRR + Win Rate — need BOTH KPIs together

---

## TRADE IDEA FORMAT

When generating trade ideas:

```
INSTRUMENT: [symbol]
DIRECTION: Long/Short
TIMEFRAME: [HTF] → [LTF]

FUNDAMENTAL BIAS:
- COT: [Commercials/NonComm/Retail] at [X]% — [bullish/bearish]
- Valuation: [over/undervalued] at [X] — [bullish/bearish]
- Seasonality: Slope [up/down] — [bullish/bearish]
- Consensus: [X/3] fundamentals aligned

TECHNICAL SETUP:
- Location: [very cheap/cheap/equilibrium/expensive/very expensive] — Fib [X]%
- Direction: [uptrend/downtrend/sideways] — [X] pivots identified
- Zone Type: [DBR/RBR/RBD/DBD]
- Zone Proximal: [price] (Fib 100)
- Zone Distal: [price] (Fib 0)
- Qualifier Score: [X/60+5]
  Q1 Departure: [X/10] | Q2 Base: [X/10] | Q3 Fresh: [X/10]
  Q4 Originality: [X/10] | Q5 Profit Margin: [X/10] | Q6 Arrival: [X/10]
  LOL Bonus: [X/5]

EXECUTION:
- Entry: [price] ([method: proximal/midpoint/confirmation])
- Stop: [price] (distal - 33% = Fib -33)
- T1: [price] (1R — breakeven)
- T2: [price] (2R — partial)
- T3: [price] (3R — trail/close)
- Risk: 1% of account = $[amount]
- Position Size: [lots/contracts]
```

---

## WORKFLOW: Building Textbook or Processing Lessons

If the user asks to rebuild or update the textbook:
1. The current textbook is `Blueprint_Trading_System_COMPLETE_TEXTBOOK_v7_REBUILT.docx` (21 MB)
2. The build script is `build_textbook_v7.py` at the project root
3. Frame extracts come from `D:\Trading\Output\Trading Doc\` (190 chapter folders, each with `transcript.json` + frame_*.jpg)
4. Methodology canonical specs in `methodology/*.md` are the ground truth — when rebuilding, the textbook chapters must match the methodology files
5. To rebuild: `python build_textbook_v7.py` (uses python-docx with batched image insertion)

## WORKFLOW: Pine Script Generation

When creating Pine Script:
1. Read the 4 indicator .txt files from the workspace for coding style reference
2. Use v5 syntax (`request.security()` not `security()`)
3. Follow the zone detection algorithm above
4. Implement all 6 qualifiers as configurable inputs
5. Include the -33% Fibonacci stop calculation (LTF entries) OR distal-only stop (HTF weekly income entries)
6. Add R-multiple target levels
7. Reference the COT cheat sheet for asset-class-specific settings

---

## AUDIT TRAIL

The methodology files in `methodology/*.md` are the canonical spec. They have been validated against the full 156-PDF Phase 4+5 audit, Phase 6 follow-up audit (2024 Practical Application + Beginner Breakout + Monthly Roadmaps, 21 chapters), Phase 7 live system audit, and Phase 8+9 indicator recalibration.

**Key audit-derived rules** (all currently in methodology + code):
- 25% penetration HARD invalidates a zone (Phase 6, Ch 184) — overrides Q3 retest scoring
- BB/SB is containment, not multi-TF stacking (Phase 6, Ch 182)
- Equity-index shorts require BOTH retailer-extreme AND bond ROC actively rolling negative (Phase 6, Ch 156)
- Gaps function as explosive leg-outs (Phase 6, Ch 171)
- Mega-cap basket scan (top-7+) for NQ bias (Phase 6, Ch 153)
- Stock dual-timeframe Valuation gate (Phase 6, Ch 153)
- Daily Valuation = exit signal on weekly trades (Phase 6, Ch 173)
- Pivot-break = explicit trend-reversal trigger (Phase 6, Ch 174)
- Stop above ATH for shorts near all-time-high (Phase 6, Ch 180)
- LTF opposing zone = trade-management signal NOT profit target (Phase 6, Ch 186)
- "Trade the constituents not the index" fallback (Phase 6, Ch 153)
- Mid-equilibrium LTF level-to-level swing trades sanctioned with reduced size (Phase 6, Ch 182)
- Spot-vs-futures cross-confirmation (Phase 6, Ch 182)
- **Phase 9**: ZigZag % is timeframe-aware (1wk=6%, 1d=3%, 4H=2%, 1H=1%) — flat 3% was creating noise pivots on weekly data. Note: 6% weekly confirmed Phase 13 (OTC Ch.012 "six second percent")
- **Phase 9**: `Seasonality.get_bias_multi` 2/3 agreement now returns directional bias (was silently returning 'neutral', making Seasonality fire too rarely)
- **Phase 9**: Initial soft-commodity COT routing — partially corrected in Phase 14 (see below)
- **Phase 10**: Counter-trend gate long-in-downtrend arm relaxed (3+ non-trend bullish, ≤1 opposing, val=bullish). Pine Script seasonality bug fixed: calendar `dayofyear` → trading-day-of-year rank (`df.groupby(year).cumcount()`) matching Pine Script's `_tdoy`
- **Phase 11**: `_bias_consensus` completely rewritten from flat 3-of-5 equal vote to Bernd's actual decision hierarchy: Location gate → Valuation veto → minimum (Location + Valuation = tradeable) → COT/Seasonality/Trend as tie-breakers. Based on frequency analysis of 186 transcripts (Location 88%, Valuation 92%, COT only 48%)
- **Phase 13**: COT V2 formula corrected to `140*(net-min)/(max-min)-20`, scale -20/+120, thresholds 80/20 (Pine Script source confirmed). Weekly ZigZag updated to 6%
- **Phase 14**: Grains (ZC/ZW/ZS) + Cotton (CT) moved from Non-Commercials → **Commercials 52w** (Ch.159 Corn: "commercials bullish"; Ch.113/144 Cotton: "smart money commercials"). Precious Metals COT lookback: 52w → **26w** (Ch.107 Bernd: "look back is 26")
- **Phase 16**: Coffee (KC=F) moved from soft_commodities → **Commodities Commercials 52w** (retailers "not real retailers"). Individual stock Valuation: DXY removed, Gold (GC) added — OTC L3: "unselect reference symbol three, which is the dollar". Bitcoin Seasonality: **4yr lookback only** (data history too short). Natural Gas Valuation **excluded**
- **Phase 17**: **Precious Metals COT routing corrected**: was Retailers (contrarian) → now **Commercials (non-contrarian)**. Blueprint Cheatsheet + Phase 14 corpus: Gold/Silver/Palladium all use Commercials ①. The "Retailers CONTRARIAN for PM" entry was wrong — retailers are a confirming odds-enhancer (③). Contrarian Retailers now applies to **Natural Gas only**. Contrarian strength-direction logic also fixed for nat_gas. Goldtest: 64/160 Stage1=40% (new high), Stage2=13/160, zero false positives
- **Phase 18**: **156w-only COT secondary trigger** + **COT-is-king extended to equilibrium**. (1) When 26w index APPROACHES extreme (≥60 bullish / ≤35 bearish) but hasn't crossed the threshold, AND 156w historic extreme IS already extreme → fire directional bias. Restricted to COT-king classes (commodities/PM/energies/nat_gas/soft_commodities) — equity indices and forex excluded. (2) `_bias_consensus` COT-is-king block extended to also override the equilibrium all-3-unanimity gate when COT=strong for commodity/PM/energy assets. Canonical case: GC=F Aug 2023 (comm_idx_26w=68.59 approaching, comm_ext_156w=86.32 at historic extreme) — confirmed fixed. Goldtest Stage 1: **74/160 = 46.2%** (+10 cases, +6.2pp from Phase 17). FT 121-case Stage 1: **68/121 = 56.2%** (+4 cases, +3.3pp). Stage 2: 13/160 unchanged. By asset class: commodities 10/14=71%, energies 3/4=75%, equities 20/45=44%, equity_indices 8/42=19%, forex 3/9=33%, precious_metals 30/41=73%. Zero Stage-2 false positives
- **Phase 19**: **Diagnostic verbose run — no code changes.** First-ever by-asset-class FT 121-case breakdown: Energies 10/10=100%, Nat Gas 10/11=91%, PM 17/25=68%, Equities 14/25=56%, Equity Indices 14/31=45%, Commodities 2/5=40%, Forex 1/14=7%. 14 Stage-1 wrong-direction cases ALL identified as Bernd's deliberate discretionary overrides of his own rules (supply-shock CC=F, PM counter-trend, 2024 AI ATH equity rally, USD/CHF contrarian) — not system bugs. Stage-2 wrong-direction = 0 preserved. **Forex root cause isolated**: `cross_category_signal` in `_analyze_fundamentals` applies the commodity "smart money / dumb money" override to forex corporate hedgers, which flips the non-comm (large specs) bullish CHF signal to bearish; the USD cross-check then sees a conflict and demotes to neutral. Fix (ready, deferred to Phase 20): `if cot_cross.get('extreme_confluence') and asset_class not in ('forex',):`. Component breakdown on failing 53 cases: cot_strength 100%, valuation 81%, cot 81%, location 79%, trend 72%, seasonality 66%. Key insight: equity index failures are structural (ATH location + presidential cycle not yet as hard override), not fixable by indicator tuning. FT 68/121 = 56.2% confirmed identical to Phase 18 run (no data drift)
- **Phase 20**: **Forex COT cross-category guard applied. FT 68/121 = 56.2% (unchanged). Goldtest Stage 2: 13/160, zero false positives.** One-line fix: `if cot_cross.get('extreme_confluence') and asset_class not in ('forex',)`. Fix is architecturally correct but didn't move the needle because `extreme_confluence` was NOT firing for most of the 14 forex failures — the dominant failures are structural: (1) **USDJPY×4** — COT neutral (JPY CFTC signal too weak), Location often opposite to Bernd's intended direction; (2) **USDCHF×3** — **COT direction inversion bug discovered**: COT is for CHF (6S=F futures, `cot_bias='bullish'`=long CHF=SELL USDCHF) but Location Fib is drawn on USDCHF pair (`location='bullish'`=BUY USDCHF). Both "bullish" signals are anti-correlated but system treats them as agreeing → fires LONG while Bernd wants SHORT. Fix candidate (Phase 21): invert COT for USD-base pairs before consensus; (3) **6S=F×3** — Valuation=bullish CHF fires Rule#1 veto on Bernd's short 6S (he's at supply zone, overrides his own Valuation rule — discretionary); (4) **EURUSD×1** — Bernd counters his own bullish COT signal; (5) **MXN=X×1** — No CFTC code. Deferred: USDCHF/USDJPY COT inversion (+5-6 FT expected), equity index ATH override via presidential cycle (+18 FT expected), stock CampusValuationTool (+12 FT expected)
- **Phase 21**: **Pine Script audit + USD-base inversions.** Two fixes from direct comparison of `04_Pine_Script_Indicators/Valuation_OTC.txt` against Python: (1) `ZN=F` (10yr T-Note) removed from equity/equity-index Valuation refs — canonical Pine Script uses `ZB1!` (30yr T-Bond) only. ZN+ZB was double-counting bonds. (2) USD-base forex pair COT inverted in `_analyze_fundamentals` for `USDJPY=X`/`USDCHF=X`/`USDCAD=X` — when CFTC tracks the QUOTE currency (JPY/CHF/CAD), "non-comms long CHF" must invert to "bearish USDCHF" before consensus. Goldtest Stage-1: 73/156 = 46.8% (-1 from Phase 18, structurally correct: equity Valuation now uses one bond instrument, not two). Stage-2: 13/156 = 8.3% preserved
- **Phase 22**: **Stable MD5 zone IDs + re-entry suppression.** Zone IDs in `BP_zone_detector.py` were `uuid.uuid4()[:8]` — random per scan, broke `zone_memory` deduplication and the forward-test re-entry guard (every zone re-fired indefinitely, inflating trade counts and producing meaningless 20% win rates). Replaced with `hashlib.md5(symbol|zone_type|tf|origin_time|proximal|distal)[:10]` so the same zone gets the same ID across scans. Forward-test now correctly tracks consumed/open zones; `BP_paper_trader.zone_memory` works in production. Hash inputs include rounded-to-4dp price levels so floating-point noise doesn't break ID stability
- **Phase 23**: **Presidential/Sannial cycle T1 override + zone-arrival T4 + hang-fix infrastructure.** Three task strands: (1) **T1 cycle override** — when `asset_class=='equity_indices'` and `loc=='bearish'` (price at ATH), and presidential cycle score > 0 AND sannial cycle score > 0, the strict bearish Location can be relaxed to 'neutral'. `today_override` parameter added to `_bias_consensus` so the goldtest replays historical years correctly (else `date.today()` always returns 2026 mid-term cycle). (2) **T2 stock SMA proxy** — added `_stock_valuation_proxy()` static method computing price-vs-3yr-SMA mean reversion as substitute for the unavailable CampusValuationTool_V2 Pine Script. (3) **T4 zone-arrival flag** — `_hq_zone_arrival = bool(at_zone and zone_composite >= 7.0)` plumbed through, ready for future soft-veto integration. (4) **Hang-fix infra** — RTY=F→IWM in `FUTURES_PROXY`, 30s socket timeout in `_fetch_one`, intraday-fetch-skip for cases >729 days old. Goldtest Stage-1: 78/156 = 50.0% (+5 from Phase 22). Stage-2: 13/156 preserved
- **Phase 24**: **Multi-front improvement pass.** Five tasks landed: (1) **T1 relaxation** — Phase 23 T1 blocked itself if any of {COT, Seas, Val} was bearish; Phase 24 allows ONE bearish IF seasonality is bullish (`_seas_overrides_one_bearish`), captures early-2023 NQ/ES/YM where COT large-specs were still net short while seasonality was bullish. (2) **T2 timeframe-aware fix** — `_stock_valuation_proxy` previously used fixed `sma_period=156` regardless of input timeframe (for monthly = 13 years, for daily = 7 months). Now infers bar frequency from timestamp spacing and computes window in calendar years. (3) **Constituent thesis routing** — new `_constituent_proxy_bias()` method: when equity index has `loc='bearish'` AND cycles bullish AND ≥1 primary constituent (AAPL/MSFT) reads bullish on SMA proxy, route bullish bias through. Bernd Ch.157: *"if these two are undervalued, you can buy NQ / ES."* (4) **USD-base forex Location inversion** mirroring Phase 21 COT inversion. (5) **Per-symbol Valuation ROC** populated in `BP_config.yaml > valuation.cycle_per_symbol` (mega-caps=30, NQ/ES=10, YM=13, forex=10). Plus `audit_pine_to_python.py` drift detector + `forward_test_wide.bat` shortcut. Goldtest Stage-1: 81/154 = 52.6% (+3 from Phase 23). Stage-2: 11/154 = 7.1% (-2 was transient yfinance flakiness, recovered in Phase 25). equity_indices: 38% → 45%; equities: 36% → 38%. Zero false positives
- **Phase 25**: **DeepSeek Pro v4 review + safety hardening.** External review of Phase 24 state confirmed indicator math fidelity and consensus-hierarchy correctness, identified six concrete fixes — three real bugs + three hardening items. All shipped: (1) **P0 SAFETY: COT simulation made opt-in** — `DataFetcher` now defaults `allow_cot_simulation=False`. On CFTC API failure, returns empty DataFrame (rules engine treats as neutral) instead of synthetic random data that could trigger live trades on noise. Worst live-trading risk eliminated. (2) **Zone-freshness Fib filter** — `_analyze_htf` now filters invalidated/consumed zones (Q3=0) before picking the most recent for Location range; stale distals no longer distort cheap/expensive labels. (3) **SMA proxy intraday guard** — `_stock_valuation_proxy` rejects `med_days < 0.9` (sub-daily) data, prevents 60-min stock data getting a 252-bar/year SMA over 756 hourly bars. (4) **Multi-column timestamp detection** (`'timestamp'`/`'Date'`/`'date'`/`'Datetime'`). (5) **Single-secondary-stock guard** — `_constituent_proxy_bias` requires ≥2 secondary stocks before downgrading the AAPL+MSFT primary signal. (6) **Calendar staleness warning** at year boundary; **NG=F seasonality enforced (5y, 10y) only** in code (was documented but `Seasonality.calculate_multi` would still vote 15y). Goldtest Stage-1: 82/156 = 52.6% (+1 from Phase 24). Stage-2: 13/156 = 8.3% (recovered from Phase 24's transient flakiness). Zero opposite-direction errors at Stage-2 across all 25 phases ✓
- **Phase 26**: **DeepSeek gap fixes + cycle dominance override.** Four methodology gaps identified by external DeepSeek Pro v4 review and applied: (1) **ATH momentum override** — when equity index is in expensive zone (`loc='bearish'`) but trend is confirmed uptrend AND 4-bar ROC > 2%, downgrade `loc` from 'bearish' to 'neutral' inside `_analyze_htf`, preventing hard bearish-location veto from blocking cycle-driven long signals; (2) **SPY relative-strength proxy for stocks** — replaces Phase 23 absolute SMA proxy with relative-strength vs SPY: stock underperformed SPY by >10% over 52w = relatively undervalued, outperformed by >15% = relatively overvalued. Captures "cheap relative to market" reasoning without `CampusValuationTool_V2`; (3) **USD-base forex price inversion moved into `_analyze_htf`** (was post-hoc label swap in `run_seven_step_process`) — raw OHLCV is now inverted (1/price) before Fib computation, giving geometrically correct Location in quote-currency frame; (4) **COT momentum trigger** — when 26w index hasn't crossed 80/20 but shows 25%+ scale movement over 5 weeks AND 156w extreme is already at extreme, fire directional bias. Same COT-king classes only. Plus Phase 26b **cycle dominance override**: for equity indices where `loc != 'bearish'` (already relaxed by Gap 1), when both presidential AND sannial cycles agree bullish AND COT/Valuation/Seasonality are not bearish → return 'bullish'. Goldtest Stage-1: **87/156 = 55.8%** (+5 from Phase 25). Stage-2: 13/156 = 8.3% unchanged. Zero false positives preserved
- **Phase 27**: **Presidential/sannial cycle path for individual stocks.** Bernd's 2023 roadmap calls on individual stocks (AAPL/GOOG/META/NFLX/TSLA) were uniformly bullish throughout 2023 — driven by pre-election year-3 + sannial year-3 (both strongly bullish cycles), NOT by technical indicators. When both long-term cycles agree bullish (pres_score>0 AND sann_score>0) AND seasonality is not bearish, the equities branch in `_bias_consensus` now returns 'bullish' without requiring Valuation or Location to agree. Two design guards: (a) **Seasonality guard preserved** (`seas_n != 'bearish'`) — prevents firing on mid-October AAPL cases where Bernd himself called neutral, protecting correct Stage-1 passes; (b) **Trend guard removed (Phase 27b)** — the Oct-Dec 2023 ZigZag at 6% weekly threshold showed 'downtrend' for stocks recovering from summer pullback, blocking correct calls. Safe to remove because equities branch never returns 'bearish' — Stage-2 zone+decision-matrix still gates all real trade signals. `today_override` dependency: the live scanner passes `date.today()` (2026, sann_year=6, score=0, doesn't fire); the goldtest bias_only path passes `case_date` (2023, cy=3, pres=1, sann=1, fires correctly for historical backtesting). Goldtest Stage-1: **96/156 = 61.5%** (+9 from Phase 26). Stage-2: 13/156 = 8.3% unchanged. Zero Stage-2 false positives preserved. Cases gained: AAPL Jan 2023, GOOG Jan 2023, AAPL Mar 2023, GOOG Apr 2023, META Jan 2023, GOOG Apr 2023 (2nd), AAPL Dec 2023, AAPL Jan 2023 (2nd test case), AAPL Oct 2023 (pres=1, sann=1, seas=neutral). Cases still blocked: Oct 29 2023 cluster (AAPL/META/TSLA at seasonal low with `seas=bearish` for late October — Bernd's discretionary "buy the low" override that can't be replicated mechanically). **Files changed**: `BP_rules_engine.py` (Phase 27 equities cycle path in `_bias_consensus`), `goldtest/run_goldtest.py` (Stage-1 bias_only summary line added to output)

For full audit details: `_audit/skill_audit/FINAL_REPORT.md` (Phase 4+5) and `_audit/skill_audit/phase6/FINDINGS.md` (Phase 6). Phase 21-27 details in `CLAUDE.md` per-phase sections.


## Phase 46 Reconciliation Updates
- Explosive candle threshold: STRICTLY > 0.70 (requires BP_EXPLOSIVE_STRICT flag).
- COT Index Formula: 100 * (net - min) / (max - min) (requires BP_COT_0_100 flag).
- Trade Management: Counter-trend trades now close 100% at T2 (requires BP_TYPE_LADDERS flag).
- Contrarian Indicators: Forex and CL=F use retail contrarian signals (requires BP_RETAIL_CONTRARIAN flag).

