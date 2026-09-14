# Fundamental Analysis — COT, Valuation, Seasonality

## Overview

Fundamental analysis in the Blueprint system provides **directional bias** — it tells you which side of the market to trade. It does NOT provide timing or entries. Fundamentals filter which zones to trade and which to skip. Always combine with technical zone analysis for actual trade execution.

---

## COT (Commitment of Traders)

### Data Source

- **Publisher**: CFTC (Commodity Futures Trading Commission)
- **Release**: Friday afternoon (U.S. Eastern time)
- **Data date**: Prior Tuesday (3-day reporting lag)
- **Chart timeframe**: WEEKLY only
- **Report type**: Legacy report (sufficient for this system)

### COT Index Formula — 0-100 (C-57 correction, supersedes Phase 13)

⚠️ **2026-08 C-57 correction** (`research/audit/CODE_FINDINGS.md`): the Phase 13 switch to the
V2 form (`140 × … − 20`, scale −20..+120) was wrong for the current course. On CFTC data,
Bernd's on-screen gold commercials reading of **34.43** (chart bar Mon 07 Aug 2023) is reproduced
by the 0-100 form to 0.002; the V2 form gives 28.21 and matches no lecture value in 40 years of
data. `BP_indicators.COTIndex` defaults to **0/100** since C-57. The real indicator exposes the
bounds as inputs, so V2 is one argument away: `COTIndex(lower_bound=-20, upper_bound=120)`.

Why it matters: with 80/20 thresholds, V2 flags "extreme" at 71.4% / 28.6% of the range instead of
80% / 20%, which produced 26.9% more extreme calls than Bernd makes.

```python
def cot_index(net_position, net_position_history, lookback, lower=0.0, upper=100.0):
    """0-100 by default (COTIndex_OTC.txt, 2025 course). lower=-20, upper=120 gives V2."""
    history_window = net_position_history[-lookback:]
    lowest = min(history_window)
    highest = max(history_window)

    if highest == lowest:
        return None  # Pine: na

    return lower + (upper - lower) * (net_position - lowest) / (highest - lowest)
```

### Raw Formula (0-100 — canonical)

```
cot_index = 100 * (net_position - lowest(net_position, lookback)) /
            (highest(net_position, lookback) - lowest(net_position, lookback))
```

**Thresholds**: ≥80 = extreme bullish | ≤20 = extreme bearish | 0 to 100 full range

### Three Trader Groups

Each group provides a different type of signal, and the **primary group varies by asset class**.

---

### COMMERCIALS (Hedgers)

**Rule: TRADE WITH them.**

Commercials are producers and consumers who hedge their business exposure. They have the deepest pockets and the best understanding of their market's fundamentals.

| COT Index | Signal | Interpretation |
|-----------|--------|----------------|
| >= 80 | **BULLISH** | Heavy hedging against price rise — they expect prices to increase |
| <= 20 | **BEARISH** | Minimal hedging — they expect prices to stay low or decline |
| 20-80 | Neutral | No clear signal |

**156-Week (3-Year) Extreme Line**: When the COT index reaches a level not seen in 156 weeks, this is the **STRONGEST** signal. Mark it clearly in analysis.

**Best for**: Commodities (Gold GC, Silver SI, Crude Oil CL, Natural Gas NG, agricultural products)

```python
def commercial_signal(cot_index_value, lookback_156_high, lookback_156_low):
    """
    Generate commercial hedger signal.
    
    Returns:
        dict with signal direction and strength
    """
    # 156-week extreme check (strongest signal)
    if cot_index_value >= lookback_156_high:
        return {"signal": "BULLISH", "strength": "EXTREME_156W"}
    elif cot_index_value <= lookback_156_low:
        return {"signal": "BEARISH", "strength": "EXTREME_156W"}
    
    # Standard thresholds
    if cot_index_value >= 80:
        return {"signal": "BULLISH", "strength": "STRONG"}
    elif cot_index_value <= 20:
        return {"signal": "BEARISH", "strength": "STRONG"}
    else:
        return {"signal": "NEUTRAL", "strength": "NONE"}
```

---

### Cross-Category COT Relationships (smart vs dumb money)

The single-category extreme is weaker than the **relational** pattern between categories. Bernd's strongest signals come from comparing two categories at the same time:

#### Producer vs Retailer (Commercials vs Small-Specs)

The "smart money vs dumb money" gauge. Commercials are physical-industry hedgers (almost always right at extremes); retailers are small accounts (almost always wrong at extremes).

| Commercials | Retailers | Signal | Interpretation |
|-------------|-----------|--------|----------------|
| Extreme LONG (≥80) | Extreme SHORT (≤20) | **STRONG BULLISH** | Smart money buying, dumb money selling — highest conviction long |
| Extreme SHORT (≤20) | Extreme LONG (≥80) | **STRONG BEARISH** | Smart money selling, dumb money buying — highest conviction short |
| Both extreme LONG | — | Aligned (no edge) | Retailers happen to be right by accident — single signal degraded |
| Both extreme SHORT | — | Aligned (no edge) | Same — no smart-money asymmetry |

When this confluence triggers, it **overrides** any contradicting single-category bias and promotes `cot_strength = 'strong'`.

#### Hedge Fund vs Producer (Non-Commercials vs Commercials)

The "trend-confirmation vs turning-point" gauge. Non-commercials are trend followers; they're right during trends but wrong at major turning points.

| Commercials | Non-Commercials | Signal | Interpretation |
|-------------|-----------------|--------|----------------|
| Extreme LONG | Extreme LONG | `bullish_aligned` | Both smart money and hedge funds long — trend confirmation |
| Extreme SHORT | Extreme SHORT | `bearish_aligned` | Both bearish — trend confirmation |
| Extreme LONG | Extreme SHORT | `bullish_divergence` | **Commercials accumulating BEFORE hedge funds follow** — early-phase bullish |
| Extreme SHORT | Extreme LONG | `bearish_divergence` | Commercials distributing while funds still long — top forming |

Divergence patterns are leading signals (smart money is early); aligned patterns are confirming (trend is mature).

Implementation: `COTIndex.cross_category_signal(cot_calculated)` returns a dict `{smart_vs_dumb, funds_vs_commercials, extreme_confluence}`. The rules engine wires `extreme_confluence=True` to elevate `cot_strength` to `strong`, and tags every signal with `fund_bias.cot_cross` so the dashboard can show the relational pattern.

---

### COT Report (raw positions)

The textbook ships **two COT indicators**: the normalized 0-100 **COT Index** (rolling lookback) and the raw-positions **COT Report**. They are complementary:

| Indicator | What it shows | When to consult |
|-----------|---------------|-----------------|
| **COT Index** | Normalized **0 to 100** ranking vs configured lookback (26w / 52w + 156w extreme). Formula: `100*(net-min)/(max-min)` (C-57; the Phase 13 V2 form `140*(net-min)/(max-min)-20` is superseded). Thresholds: ≥80 bullish extreme, ≤20 bearish extreme. | Bias decision: at/near extreme = trade signal |
| **COT Report** | Raw contract counts. Longs as positive numbers, shorts as negative, with the per-trader-category net plotted as a thicker line | Confirm the *direction* and *momentum* of positioning over time. The Index can hit 80 even when actual positions are still climbing — the Report reveals that |

In the dashboard the two appear as side-by-side panels under "INDICATORS". Implementation: `COTIndex.calculate()` and `COTReport.calculate()` in `BP_indicators.py`. The Report is purely diagnostic — bias decisions still come from the Index.

### Workflow Sequencing — Report BEFORE Index (Phase 6, Ch 155)

Bernd's roadmap-session workflow is explicit: *"let's look at the normal CUT data… I want you to learn the normal CUT data to understand how our index basically works"*. The correct order:

1. **First** open the COT **Report** (raw counts) and visually compare the current week's net position to prior similar drops/rallies. This builds intuition for whether the Index reading is "real" or distorted by the lookback window.
2. **Then** consult the COT **Index** for the normalized signal.

Skipping straight to the Index loses the calibration step — you may act on an extreme reading whose absolute level is actually middling versus the multi-year backdrop.

### COT Update Queue — Wait for N Future Releases (Phase 6, Ch 155)

When a setup is forming pre-extreme and the COT Index trajectory is fast but has not yet crossed the 80/20 threshold, Bernd defers entry: *"most likely in a third week of February. So we get two more updates on COT data."*

```python
def cot_confirmation_queue(current_index, threshold, weekly_delta, releases_remaining=2):
    """
    Defer entry by up to N COT releases when threshold is close but not yet reached.
    Returns (action, reason).
    """
    projected = current_index + weekly_delta * releases_remaining
    if abs(current_index - threshold) <= 5:
        return "WAIT", f"COT {current_index:.0f} near threshold {threshold} — waiting up to {releases_remaining} releases"
    if (weekly_delta > 0 and projected >= threshold) or (weekly_delta < 0 and projected <= threshold):
        return "WAIT", f"COT trajectory ({weekly_delta:+.1f}/wk) projects to cross threshold within {releases_remaining} releases"
    return "PROCEED", "extreme already reached or trajectory too slow to project"
```

### Commercial Regime-Flip Detector (Phase 6, Ch 155)

A commercial COT swing of **≥40 index points within ≤3 weekly releases** ("super bullish to all of a sudden, super bearish") is a leading reversal signal — *"really indicative to something bigger happening"* in the following month.

```python
def commercial_regime_flip(cot_index_history, lookback_weeks=3, swing_threshold=40):
    """Detect whether commercials have flipped regime in the recent window."""
    if len(cot_index_history) < lookback_weeks + 1:
        return False, 0
    swing = cot_index_history[-1] - cot_index_history[-1 - lookback_weeks]
    return abs(swing) >= swing_threshold, swing
```

When detected, this fires **independent** of the static 80/20 thresholds — a flip from 75 to 30 in 3 weeks is more significant than a sustained 78 reading.

---

### NON-COMMERCIALS (Large Speculators / Funds)

**Rule: Focus on DIVERGENCE.**

Large speculators (hedge funds, CTAs) are trend followers. They are right during trends but consistently **wrong at turning points**. The key signal is divergence between their positioning and price.

| Pattern | Signal |
|---------|--------|
| Price makes new LOW + COT index makes HIGHER low | **BULLISH divergence** (turning point) |
| Price makes new HIGH + COT index makes LOWER high | **BEARISH divergence** (turning point) |
| No divergence | Follow their direction during trends |

**Best for**: Forex (6E Euro, 6B Pound, 6J Yen, 6A Aussie, 6C Canadian, 6S Swiss), Equity Indices (ES, NQ, YM)

```python
def non_commercial_divergence(price_data, cot_index_data, lookback=52):
    """
    Detect divergence between price and non-commercial positioning.
    
    Args:
        price_data: weekly price series (close prices)
        cot_index_data: weekly COT index series for non-commercials
        lookback: number of weeks to scan
    
    Returns:
        dict with divergence type or None
    """
    recent_prices = price_data[-lookback:]
    recent_cot = cot_index_data[-lookback:]
    
    # Find price lows and COT lows
    price_lows = find_swing_lows(recent_prices)
    cot_lows = find_swing_lows(recent_cot)
    
    # Bullish divergence: price lower low + COT higher low
    if len(price_lows) >= 2 and len(cot_lows) >= 2:
        if (price_lows[-1]["value"] < price_lows[-2]["value"] and
            cot_lows[-1]["value"] > cot_lows[-2]["value"]):
            return {"divergence": "BULLISH", "type": "price_lower_low_cot_higher_low"}
    
    # Find price highs and COT highs
    price_highs = find_swing_highs(recent_prices)
    cot_highs = find_swing_highs(recent_cot)
    
    # Bearish divergence: price higher high + COT lower high
    if len(price_highs) >= 2 and len(cot_highs) >= 2:
        if (price_highs[-1]["value"] > price_highs[-2]["value"] and
            cot_highs[-1]["value"] < cot_highs[-2]["value"]):
            return {"divergence": "BEARISH", "type": "price_higher_high_cot_lower_high"}
    
    return {"divergence": "NONE"}
```

---

### RETAILERS (Small Speculators)

**Rule: CONTRARIAN — fade the crowd.**

Small speculators are consistently wrong at extremes. When the crowd is overwhelmingly positioned one way, the opposite move is likely.

| Retail Positioning | Signal |
|-------------------|--------|
| Extreme net LONG | **BEARISH** (crowd usually wrong at extremes) |
| Extreme net SHORT | **BULLISH** (crowd usually wrong at extremes) |

**Best for**: **Natural Gas (NG=F) ONLY** as PRIMARY signal (contrarian). For Precious Metals, Retailers are a confirming odds-enhancer ③ — NOT primary. Phase 17 correction.

```python
def retailer_contrarian_signal(retail_cot_index):
    """
    Generate contrarian signal from retail positioning.
    """
    if retail_cot_index >= 80:
        return {"signal": "BEARISH", "note": "Retailers extreme long — fade"}
    elif retail_cot_index <= 20:
        return {"signal": "BULLISH", "note": "Retailers extreme short — fade"}
    else:
        return {"signal": "NEUTRAL"}
```

---

### Asset-Class Lookback Periods

| Asset Class | Lookback Period | Primary Group | Usage |
|-------------|----------------|---------------|-------|
| **Crude Oil** (CL=F) | **26 weeks** + 156w extreme | Commercials | Trade WITH hedgers. Reverted from 52w (full-corpus indicator audit, 2026-07) — two independent settings-dialog frames confirm `WeeklyLookBack=26` for @CL specifically. |
| **Other Energies** (BZ etc.) | 52 weeks + 156w extreme | Commercials | Trade WITH hedgers. No frame evidence yet to change these from the general commodity default. |
| **Precious Metals** (GC/SI/PL/PA) | **26 weeks** + 156w extreme | **Commercials ① (non-contrarian)** | Trade WITH Commercials. Phase 14 (26w) + Phase 17 (Commercials primary) corrections. |
| **Natural Gas** (NG=F) | 26 weeks | **Retailers ① CONTRARIAN** | FADE the crowd. Extreme retail SHORT = bullish; extreme retail LONG = bearish. Phase 12 correction. |
| **Grains + Cotton** (ZC/ZW/ZS/CT) | 52 weeks | Commercials | Trade with hedgers (planting/harvest cycle). Phase 14 correction from Non-Commercials. |
| **Cocoa** (CC=F) | **52 weeks** | **Commercials, Non-Commercials disabled** | Moved out of the tropical-softs Non-Commercials grouping (full-corpus indicator audit, 2026-07) — two independent settings-dialog frames both show `DisplayNonCommercialTradersIndex=false` + `WeeksLookBack=52`. |
| **Tropical Soft Commodities** (SB/OJ) | 26 weeks | Non-Commercials | Divergence focus |
| **Coffee** (KC=F) | 52 weeks | Commercials | Trade WITH Commercials. Phase 16 correction. |
| **Forex** | 26 weeks | Non-Commercials | Divergence focus |
| **Equities / Equity Indices** | 26 weeks | Non-Commercials | Divergence focus |

**COT Weighting Hierarchy for Agricultural Commodities**: COT > Seasonality > Valuation. COT positioning carries more weight than the other two for ags because planting/harvest seasons drive commercial hedging so strongly.

**Fresh-Extreme Flag ("Short Term CUT")**: When COT index crosses the 80/20 threshold in the current week's report (i.e., just entered extreme territory), flag it as `fresh_extreme = True`. A fresh extreme carries HIGHER conviction than a sustained one — institutional accumulation/distribution has just begun. Code: check if prior week was below 80 and current week is ≥ 80 (or above 20 → ≤ 20).

**COT Momentum Trigger (Phase 26)**: Even when the 26w index is neutral (hasn't crossed 80/20), if the **5-week trend shows ≥25% of the full -20/+120 scale in movement** AND the 156w historic extreme IS already at extreme → fire directional bias. Captures fast institutional accumulation before the normalized index fully registers. Same class restriction as the 156w approaching-extreme trigger: commodities, precious_metals, energies, nat_gas, soft_commodities only — NOT forex or equity indices. Implementation: `COTIndex.get_bias` in `BP_indicators.py`.

**Retailer Directional-Alignment Veto**: Beyond the contrarian-at-extremes rule, if Retailers are net-positioned on the SAME SIDE as the proposed trade (even below extreme thresholds), this is a dumb-money alignment warning:
- **Natural Gas (NG=F)**: HARD VETO — Retailers are the PRIMARY indicator; being on the same side as proposed trade kills the contrarian thesis. Phase 12 correction.
- Other asset classes: Reduce position size by 50%; emit `retailer_alignment_warning`
- ⚠️ **Note**: Precious Metals (GC/SI/PL) — Retailers are confirming only (③), not primary (Phase 17 correction). A retailer-same-side warning reduces conviction but is no longer a hard veto for PMs.

### Forex Cross-Check Rule

For forex pairs, ALWAYS cross-check both currencies in the pair:

```python
def forex_cot_bias(base_cot_signal, quote_cot_signal):
    """
    Cross-check both currencies for forex pairs.
    
    Example: EURUSD
        base_cot_signal = EUR COT signal
        quote_cot_signal = USD COT signal
    
    EUR bearish + USD bullish = DOUBLE CONFIRMATION for EURUSD short
    EUR bullish + USD bearish = DOUBLE CONFIRMATION for EURUSD long
    """
    if base_cot_signal == "BULLISH" and quote_cot_signal == "BEARISH":
        return {"bias": "BULLISH", "strength": "DOUBLE_CONFIRMED"}
    elif base_cot_signal == "BEARISH" and quote_cot_signal == "BULLISH":
        return {"bias": "BEARISH", "strength": "DOUBLE_CONFIRMED"}
    elif base_cot_signal == "BULLISH" and quote_cot_signal == "BULLISH":
        return {"bias": "NEUTRAL", "strength": "CONFLICTING"}
    elif base_cot_signal == "BEARISH" and quote_cot_signal == "BEARISH":
        return {"bias": "NEUTRAL", "strength": "CONFLICTING"}
    else:
        # One or both neutral
        if base_cot_signal != "NEUTRAL":
            return {"bias": base_cot_signal, "strength": "SINGLE"}
        elif quote_cot_signal != "NEUTRAL":
            # Invert quote signal for pair direction
            inverted = "BULLISH" if quote_cot_signal == "BEARISH" else "BEARISH"
            return {"bias": inverted, "strength": "SINGLE"}
        else:
            return {"bias": "NEUTRAL", "strength": "NONE"}
```

### CME Futures Symbol Mapping for COT

| Forex Pair | Futures Symbol | CFTC Code |
|-----------|---------------|-----------|
| EURUSD | 6E | 099741 |
| GBPUSD | 6B | 096742 |
| USDJPY | 6J | 097741 |
| AUDUSD | 6A | 232741 |
| USDCAD | 6C | 090741 |
| USDCHF | 6S | 092741 |
| Gold | GC | 088691 |
| Silver | SI | 084691 |
| Crude Oil | CL | 067651 |
| Natural Gas | NG | 023651 |
| S&P 500 | ES | 13874A |
| Nasdaq | NQ | 20974A |
| US Dollar Index | DX | 098662 |

---

## Valuation

### Purpose

Compares asset performance vs macro benchmarks using Rate of Change (ROC). Tells you IF conditions are favorable for a directional trade, but NOT when to enter.

**CRITICAL**: Valuation is NOT a timing tool. It establishes bias. Must be combined with zone detection for actual entries.

### Core Formula

```python
def rate_of_change(data, period):
    """
    Calculate Rate of Change.
    
    Args:
        data: price series (close prices)
        period: ROC lookback period
    
    Returns:
        float: percentage change
    """
    if len(data) < period + 1:
        return 0.0
    return ((data[-1] - data[-period - 1]) / data[-period - 1]) * 100


def valuation_score(asset_roc, reference_rocs):
    """
    Compare asset ROC against reference benchmarks.
    Rescale to -100/+100 range.
    
    Args:
        asset_roc: ROC of the asset being analyzed
        reference_rocs: list of ROC values for reference assets
    
    Returns:
        float: -100 to +100 valuation score
    """
    avg_reference_roc = sum(reference_rocs) / len(reference_rocs)
    spread = asset_roc - avg_reference_roc
    
    # Rescale to -100/+100 (normalize based on historical spread range)
    # Implementation depends on historical calibration
    return rescale_to_range(spread, -100, 100)
```

### Settings by Asset Class

| Asset Class | Reference Benchmarks | ROC Period | Special Notes |
|-------------|---------------------|------------|---------------|
| **Forex** | **DXY + Bonds (ZB) + Gold (GC)** | 10 | Reverted from DXY-only (full-corpus indicator audit, 2026-07) — a genuine LIVE session (CW05 FX Edition, Jan 2024) shows CHF and GBP both with all 3 refs simultaneously active; earlier single-ref sightings were teaching-session narrowings. Threshold also reverted from ±69 to the general ±75 — zero on-screen sightings of 69 found anywhere in the corpus. |
| **Stocks / Equity Indices** | **ZB** (Long Bond) + **DXY** only | 10 | **ZN removed (Phase 21 correction)**. Valuation is PRIMARY/LEADING for stocks. SPY RS proxy (Phase 26) for individual stocks: underperformed SPY >10% over 52w = undervalued; outperformed >15% = overvalued. |
| **Commodities** | DXY + Gold (GC) + Bonds (ZB) | 10 | All three references used |
| **Precious Metals (Gold/Silver)** | DXY + ZB (Bonds) + GC (Gold) | Gold: **10** (reverted from 13, full-corpus audit 2026-07 — the 13 value traced to a single Nov 2023 frame; 7 independent chapters spanning the corpus show `Length=10`). Silver: 30. | Silver: Bonds ticker = @VD not @US |
| **Platinum** | ZB (Bonds) + Gold (GC) + DXY | 10 | Phase 41 chunk 3 correction: CW35 Aug 2023 and FT Signals Mar 2023 frames confirm @PL and @PA both use @US+@GC+$DXY (3 refs). Earlier "no Bonds" statement was incorrect. |
| **Energies** | DXY + ZB (Bonds) + GC (Gold) | 10 | Standard commodity triple reference |
| **Natural Gas (NG=F)** | **EXCLUDED — do not use Valuation** | N/A | Phase 16/25 correction. Weather/supply shocks make DXY-relative Valuation uninformative for NG. Valuation vote is omitted from NG=F bias consensus entirely. |
| **Crypto** | **DXY + Bonds (ZB) + Gold (GC)** | 10 | Reverted from DXY-only (full-corpus indicator audit, 2026-07) — 8 independent chapters spanning Apr 2023-Feb 2024 all show the identical 3-reference signature live on BTC charts. |

**Pine Script default `Length=10` across ALL asset classes** (CampusValuationTool source confirmed via Phase 7 audit). A previous version of these docs claimed Length=13 for equities — that was a misreading of "Dual-ROC", which referred to running two instances of the indicator with different lengths simultaneously, NOT changing the parameter on a single instance. Empirically validated: AMZN/META/NVDA give wildly different (and incorrect-vs-Bernd's commentary) readings with Length=13; Length=10 matches.

**Dual-ROC for Equities (overlay practice, NOT a parameter override)**:
- Daily chart: overlay ROC 10 + ROC 13 — BOTH must agree direction for valid signal
- Weekly chart: overlay ROC 13 + ROC 30 — BOTH must agree direction for valid signal
- If mixed (one bullish, one bearish) → treat as NEUTRAL
- Implementation note: each ROC is a separate instance of the Valuation indicator on the chart; the `Length` parameter on each instance stays at the configured value, the overlay is applied at the chart level

**Read 3 INDIVIDUAL LINES, never a composite average** (Pine Script source `Valuation_v4.pine`): the indicator plots one line per reference benchmark. Bernd reads each separately ("DXY line is undervalued, bond line is undervalued, gold line is mild → all 3 agree, strong bullish bias"). Do NOT average them into one composite — that loses the per-reference signal. Aggregate rule:

| Pattern across 3 lines | Bias | Strength |
|------------------------|------|----------|
| All 3 in extreme zone (≥+75 or ≤-75) same direction | direction | strong |
| All 3 in mild zone same direction | direction | mild |
| 2 of 3 same direction, 0 opposing | direction | mild (or strong if any of the 2 is in extreme zone) |
| Mixed / 1 of 3 / lines disagree | neutral | none |

**Valuation is a HARD DIRECTIONAL PREREQUISITE — "Rule Number One"** (verbatim Bernd, CW38 and CW39). Directional trades require Valuation to NOT strongly contradict the trade direction. This is not a vote — it is a prerequisite VETO gate that blocks the trade before any other indicator is checked. If Valuation strongly opposes the location-derived direction, the trade is cancelled regardless of COT, Seasonality, or Trend alignment.

### Interpretation Thresholds — 4-State Model

| Valuation Score | State | Signal | Action |
|----------------|-------|--------|--------|
| >= +75 | **Strong Overvalued** | STRONG BEARISH | Look for SUPPLY zones; short bias |
| 0 to +75 | **Mild Overvalued** | Mild bearish caution | Acceptable long if other factors overwhelm; prefer supply |
| 0 to -75 | **Mild Undervalued** | Mild bullish lean | Acceptable short if other factors overwhelm; prefer demand |
| <= -75 | **Strong Undervalued** | STRONG BULLISH | Look for DEMAND zones; long bias |

```python
def valuation_bias(valuation_score):
    """Convert valuation score to 4-state directional bias."""
    if valuation_score >= 75:
        return "STRONG_BEARISH"    # Strongly overvalued — expect decline
    elif valuation_score > 0:
        return "MILD_BEARISH"      # Mildly overvalued — caution on longs
    elif valuation_score <= -75:
        return "STRONG_BULLISH"    # Strongly undervalued — expect rise
    elif valuation_score < 0:
        return "MILD_BULLISH"      # Mildly undervalued — lean long
    else:
        return "NEUTRAL"           # At zero — no signal

def valuation_passes_gate(valuation_bias, trade_direction):
    """
    Hard gate check: does Valuation allow this trade direction?
    
    Rule: Valuation STRONGLY opposing the trade direction = VETO.
    Mild opposition = warning (reduce size) but not veto.
    Neutral or aligned = pass.
    """
    if trade_direction == "long":
        if valuation_bias == "STRONG_BEARISH":
            return False, "VETO"    # Strongly overvalued — refuse long
        elif valuation_bias == "MILD_BEARISH":
            return True, "WARNING"  # Reduce size
        else:
            return True, "PASS"
    elif trade_direction == "short":
        if valuation_bias == "STRONG_BULLISH":
            return False, "VETO"    # Strongly undervalued — refuse short
        elif valuation_bias == "MILD_BULLISH":
            return True, "WARNING"  # Reduce size
        else:
            return True, "PASS"
```

### Asset-Specific Implementation

```python
def calculate_valuation(asset_class, asset_close_data, reference_data, symbol=None):
    """
    Calculate valuation for a given asset class.
    
    Args:
        asset_class: "forex", "stocks", "commodities", "precious_metals", or "platinum"
        asset_close_data: close price series for the asset
        reference_data: dict of reference close price series
        symbol: optional specific symbol for overrides (e.g. "NG" for natural gas)
    
    Returns:
        dict with valuation score, 4-state bias, and gate_result
    """
    if asset_class == "forex":
        # Reverted to 3-ref (full-corpus indicator audit, 2026-07) — was DXY-only.
        period = 10
        asset_roc = rate_of_change(asset_close_data, period)
        dxy_roc = rate_of_change(reference_data["DXY"], period)
        zb_roc = rate_of_change(reference_data["ZB"], period)
        gc_roc = rate_of_change(reference_data["GC"], period)
        score = valuation_score(asset_roc, [dxy_roc, zb_roc, gc_roc])
    
    elif asset_class in ("stocks", "equities", "equity_indices"):
        # AUDIT CORRECTION (CW42-Idx, CW43-Idx, CW51): DXY IS included for stocks
        # CampusValuationTool_V2 shows three references: @BUS (bonds) + @GC (Gold) + @$XY (DXY)
        period = 13
        asset_roc = rate_of_change(asset_close_data, period)
        zn_roc = rate_of_change(reference_data["ZN"], period)   # 10yr Notes
        zb_roc = rate_of_change(reference_data["ZB"], period)   # 30yr Bonds
        dxy_roc = rate_of_change(reference_data["DXY"], period) # Dollar Index — YES for stocks
        score = valuation_score(asset_roc, [zn_roc, zb_roc, dxy_roc])
    
    elif asset_class == "platinum":
        # Phase 41 chunk 3 correction: Platinum uses ZB + GC + DXY (same as other PMs).
        # CW35 Aug 2023 + FT Signals Mar 2023 frames confirm 3-ref config for @PL and @PA.
        period = 10
        asset_roc = rate_of_change(asset_close_data, period)
        zb_roc  = rate_of_change(reference_data["ZB"],  period)  # 30yr T-Bond
        dxy_roc = rate_of_change(reference_data["DXY"], period)
        gc_roc  = rate_of_change(reference_data["GC"],  period)
        score = valuation_score(asset_roc, [zb_roc, gc_roc, dxy_roc])
    
    elif asset_class == "precious_metals":
        # Silver bonds ticker = @VD, not @US
        period = 10
        asset_roc = rate_of_change(asset_close_data, period)
        dxy_roc = rate_of_change(reference_data["DXY"], period)
        gc_roc = rate_of_change(reference_data.get("GC", reference_data.get("gold")), period)
        bond_roc = rate_of_change(reference_data.get("VD", reference_data.get("ZB")), period)
        score = valuation_score(asset_roc, [dxy_roc, gc_roc, bond_roc])
    
    elif asset_class == "commodities":
        period = 10
        asset_roc = rate_of_change(asset_close_data, period)
        dxy_roc = rate_of_change(reference_data["DXY"], period)
        gc_roc = rate_of_change(reference_data["GC"], period)   # Gold
        zb_roc = rate_of_change(reference_data["ZB"], period)   # 30yr Bonds
        score = valuation_score(asset_roc, [dxy_roc, gc_roc, zb_roc])
    
    else:
        return {"score": 0, "bias": "NEUTRAL", "error": "Unknown asset class"}
    
    bias = valuation_bias(score)
    return {
        "score": round(score, 2),
        "bias": bias,
        "state": bias,   # 4-state: STRONG_BULLISH / MILD_BULLISH / MILD_BEARISH / STRONG_BEARISH
    }
```

### Mega-Cap Basket Scan for NQ Bias (Phase 6, Ch 153)

Bernd's January 2024 roadmap walks through individual Valuation readings on the **top-7 mega-caps** before committing to an NQ direction: *"Apple we discussed… is Amazon doing… Google valuation… Netflix… Tesla"*. The dual AAPL+MSFT gate already documented is the **minimum**; the full mega-cap basket sharpens the bias engine.

**Basket members**: AAPL, MSFT, GOOG, META, AMZN, NFLX, TSLA, NVDA (8 names; weight per index composition).

**Rule**: For an **NQ long** bias, require **≥4/8 mega-caps undervalued** (Valuation score < 0) AND BOTH AAPL + MSFT individually undervalued (the dual-gate). For an NQ short, mirror: ≥4/8 overvalued AND AAPL + MSFT both overvalued.

```python
MEGA_CAP_BASKET = ["AAPL", "MSFT", "GOOG", "META", "AMZN", "NFLX", "TSLA", "NVDA"]

def nq_bias_via_basket(valuation_per_symbol, direction):
    """direction = 'long' or 'short'. valuation_per_symbol: dict[symbol -> score]."""
    aapl, msft = valuation_per_symbol.get("AAPL"), valuation_per_symbol.get("MSFT")
    if aapl is None or msft is None:
        return False, "missing AAPL/MSFT"
    if direction == "long":
        gate = aapl < 0 and msft < 0
        aligned = sum(1 for s in MEGA_CAP_BASKET if valuation_per_symbol.get(s, 0) < 0)
    else:
        gate = aapl > 0 and msft > 0
        aligned = sum(1 for s in MEGA_CAP_BASKET if valuation_per_symbol.get(s, 0) > 0)
    return gate and aligned >= 4, f"AAPL+MSFT gate={gate}; basket aligned={aligned}/8"
```

When the index has no tradable zone but the mega-cap constituents are aligned, **trade the constituents directly** (Phase 6, Ch 153 fallback rule) — *"I don't see a trade on the NASDAQ itself… would be this daily demand [too far away]"* but the constituent stocks each had their own zones.

### Stock-Level Dual-Timeframe Valuation Gate (Phase 6, Ch 153)

Individual stock long entries require **BOTH long-term AND short-term Valuation undervalued** (or aligned), not just one. Bernd: *"close to being undervalued long term and short term"*.

For equities, this maps to:
- **Long-term**: Weekly Valuation (ROC 13 + 30 dual)
- **Short-term**: Daily Valuation (ROC 10 + 13 dual)

Both must be at least mildly undervalued for a stock long; mirror for shorts.

```python
def stock_valuation_dual_timeframe_gate(weekly_val_score, daily_val_score, direction):
    if direction == "long":
        return weekly_val_score < 0 and daily_val_score < 0
    return weekly_val_score > 0 and daily_val_score > 0
```

A stock that is undervalued long-term but overvalued short-term = **wait** — the LTF Valuation will pull back into alignment before the trade triggers.

### Daily Valuation as EXIT Signal on Weekly Trades (Phase 6, Ch 173)

Bernd: *"the daily valuation already would have told you okay we overvalued here you need to get out right but because you traded off a weekly you want to…"* — when a trade was opened on **weekly** Valuation but **daily** Valuation prints overvalued/undervalued **against** the trade direction, treat the daily reading as an **exit warning**.

Operational rule:
1. Weekly trade open in long direction with weekly Valuation undervalued.
2. Price runs in your favour; daily Valuation crosses into **overvalued** territory.
3. The trade has not yet hit T2 — but daily is signalling exhaustion.
4. **Action**: tighten stop to breakeven (if not already) and/or take partial profit; do NOT add to the position.

This makes lower-TF Valuation an active trade-management input, not just a bias filter at entry.

---

## Seasonality (True Seasonality)

### Purpose

Identifies historically recurring price patterns over decades of data. Shows when an asset tends to rise or fall based on time of year.

### Settings

| Parameter | Value |
|-----------|-------|
| **Chart timeframe** | DAILY only |
| **Minimum history** | 25 years |
| **Forward projection** | **30–150 bars** (per-trader preference; Bernd: *"I just project 30 days in the future for me that's enough"*) |
| **Instances** | Add indicator 3 times: 5yr, 10yr, 15yr lookbacks |

### Reading the Indicator

```python
def seasonality_bias(slope_5yr, slope_10yr, slope_15yr,
                     prior_slope_5yr=None, prior_slope_10yr=None, prior_slope_15yr=None):
    """
    Determine seasonality bias from three lookback periods.
    
    CRITICAL AUDIT CORRECTION: The slope must actively TURN positive/negative —
    a slope that has been positive for many weeks but is flattening or topping
    does NOT count as a fresh bullish signal. We require that the slope is
    currently positive AND has recently turned (was negative or flat before).
    
    Args:
        slope_5yr: current slope of 5-year seasonal pattern (positive = up, negative = down)
        slope_10yr: current slope of 10-year seasonal pattern
        slope_15yr: current slope of 15-year seasonal pattern
        prior_slope_*: prior period slopes for turn detection (optional but recommended)
    
    Returns:
        dict with bias, agreement level, and turning flag
    """
    directions = []
    turning = []
    
    for current, prior in [(slope_5yr, prior_slope_5yr), 
                            (slope_10yr, prior_slope_10yr), 
                            (slope_15yr, prior_slope_15yr)]:
        if current > 0:
            directions.append("BULLISH")
            # Detect active turn: slope was flat/negative, now positive
            if prior is not None and prior <= 0:
                turning.append("TURNED_BULLISH")
            else:
                turning.append("SUSTAINED_BULLISH")
        elif current < 0:
            directions.append("BEARISH")
            if prior is not None and prior >= 0:
                turning.append("TURNED_BEARISH")
            else:
                turning.append("SUSTAINED_BEARISH")
        else:
            directions.append("NEUTRAL")
            turning.append("FLAT")
    
    bullish_count = directions.count("BULLISH")
    bearish_count = directions.count("BEARISH")
    
    fresh_turns_bullish = turning.count("TURNED_BULLISH")
    fresh_turns_bearish = turning.count("TURNED_BEARISH")
    
    if bullish_count == 3:
        strength = "STRONG_FRESH" if fresh_turns_bullish >= 2 else "STRONG"
        return {"bias": "BULLISH", "agreement": "ALL_THREE", "strength": strength, 
                "fresh_turn": fresh_turns_bullish > 0}
    elif bearish_count == 3:
        strength = "STRONG_FRESH" if fresh_turns_bearish >= 2 else "STRONG"
        return {"bias": "BEARISH", "agreement": "ALL_THREE", "strength": strength, 
                "fresh_turn": fresh_turns_bearish > 0}
    elif bullish_count == 2:
        return {"bias": "BULLISH", "agreement": "TWO_OF_THREE", "strength": "MODERATE",
                "fresh_turn": fresh_turns_bullish > 0}
    elif bearish_count == 2:
        return {"bias": "BEARISH", "agreement": "TWO_OF_THREE", "strength": "MODERATE",
                "fresh_turn": fresh_turns_bearish > 0}
    else:
        return {"bias": "NEUTRAL", "agreement": "MIXED", "strength": "NONE", "fresh_turn": False}
```

### Interpretation Rules

- **All three slopes UP AND actively turning** = Strongest historically bullish period (STRONG_FRESH)
- **All three slopes UP (sustained)** = Strong historically bullish period (STRONG)
- **All three slopes DOWN AND actively turning** = Strongest historically bearish period
- **Mixed slopes** = No clear seasonal signal
- **SLOPE MUST ACTIVELY TURN**: A slope that has been positive for weeks but is flattening is NOT a fresh bullish signal. Look for the slope to have recently crossed from negative/flat to positive. This prevents entering late into a seasonal move that has already played out.
- **NOT standalone**: Must confirm with COT + Valuation + Technicals. Seasonality alone is never a trade trigger.
- **@NG exception**: Natural Gas uses 10yr + 5yr ONLY (not 15yr — data quality too inconsistent for NG). Both must agree.
- **Crypto note**: Bitcoin uses standard Seasonality alongside COT (not seasonality-only).

---

## Monthly / Quarterly / Yearly Roadmap (Timing Overlay)

The roadmap is a **timing-overlay forecast** that tells you WHEN to be a buyer or seller across the calendar year. It is NOT a signal generator — it filters trade ideas that come from the zone + bias hierarchy process (Location gate → Valuation veto → minimum threshold).

### Three Granularities

| Granularity | Period | Source | Update cadence |
|-------------|--------|--------|----------------|
| **Yearly** | January–December | Long-term seasonality + presidential cycle + Sannial decennial cycle (equities) | Once per year, in January |
| **Quarterly** | 3 months | Monthly aggregation | At the start of each quarter |
| **Monthly** | 1 calendar month | Seasonality + presidential + sannial + COT | At the start of each month (Funded Trader weekly outlook) |

### Components per Asset Class

| Component | Equities | Commodities | Forex |
|-----------|----------|-------------|-------|
| Long-term seasonality (5/10/15y multi-lookback) | ✅ | ✅ | ✅ |
| Presidential cycle (4-year, US) | ✅ | ⚠️ (only USD-correlated) | ⚠️ (only USD pairs) |
| Sannial / decennial cycle | ✅ | ❌ | ❌ |
| COT positioning (commercials extreme alignment) | ✅ | ✅ | ✅ |
| Macro calendar (rate decisions, earnings, etc.) | (manual override) | (manual override) | (manual override) |

### Presidential Cycle Bias (S&P 500 historical, 1950–)

| Year in cycle | January | Q1 (Jan-Mar) | Q2 (Apr-Jun) | Q3 (Jul-Sep) | Q4 (Oct-Dec) |
|---------------|---------|--------------|--------------|--------------|--------------|
| 1 (post-election) | bearish | mixed | bullish | bearish | bullish |
| 2 (mid-term) | neutral | bearish | mixed | bearish | bullish |
| 3 (pre-election) | bullish | bullish | bullish | mixed | **strongly bullish** |
| 4 (election) | neutral | mixed | mixed | bearish | bullish |

### Sannial Decennial Cycle (last digit of year)

| Last digit | Bias | Last digit | Bias |
|------------|------|------------|------|
| 0 | neutral | 5 | bearish |
| 1 | bearish | 6 | neutral |
| 2 | neutral | 7 | bullish |
| 3 | bullish | 8 | bullish |
| 4 | neutral | 9 | bearish |

### Application Rule

```python
def apply_roadmap_filter(signal, roadmap):
    """
    - Same-direction signal: tag aligned, optionally boost confidence
    - Opposite signal (roadmap not neutral): warn but DO NOT auto-reject
      (Bernd takes some counter-roadmap trades when COT is at 156w extreme)
    - Roadmap neutral: signal passes through unchanged
    """
    if roadmap.bias == 'neutral':
        signal['roadmap_aligned'] = None
    elif (signal.direction == 'long' and roadmap.bias == 'buy') or \
         (signal.direction == 'short' and roadmap.bias == 'sell'):
        signal['roadmap_aligned'] = True
    else:
        signal['roadmap_aligned'] = False
        signal['roadmap_warning'] = f"Counter to {roadmap.granularity} roadmap ({roadmap.bias})"
    return signal
```

### Special Case: Strong COT Override

When COT registers at BOTH the 26-week AND 156-week extremes simultaneously (`cot_strength == 'strong'`), it can override an otherwise-neutral roadmap. Per Hybrid AI HAI 0:46:58: "this is a three year extreme... that is a historic level of commercial accumulation."

Implementation: `BP_roadmap.build_monthly_roadmap()` + `filter_signal_by_roadmap()`. Static cycle tables in `BP_roadmap.PRESIDENTIAL_CYCLE_BIAS` and `SANNIAL_CYCLE_BIAS`.

---

## Bias Synthesis Rule

### Per-Asset Seasonality Calibration (Phase 6, Ch 170)

The "all three (5y/10y/15y) must agree" rule is the **strict signal threshold**, but the trader should also empirically test which lookback works best per instrument. Bernd: *"you can change it to 10 years and you can literally do the same thing… is 10 years more accurate than the five one"*.

**Calibration step** (one-time, per instrument):
1. Overlay the 5y, 10y, and 15y seasonality curves on the daily chart.
2. Visually assess which lookback most accurately predicts past turning points for THIS market.
3. Record the preferred lookback in your instrument config (e.g. `seasonality_calibration: {AAPL: 10, GC=F: 15, ...}`).

The strict signal still requires all three to agree, but the calibrated lookback is the **leading** signal — when the calibrated lookback turns first, the other two are expected to follow within 1–2 bars.

### Index–Constituent Seasonality Conflict Resolution (Phase 6, Ch 170)

When the parent equity index seasonality contradicts the constituent stock setups (e.g. NQ seasonality says down but AAPL/GOOG are at demand zones with bullish individual seasonality), treat as **vote-degradation**: *"we will have two things telling us don't short and only one thing telling us to short"*.

Operational rule:
- **Trade the constituents** if their individual stack (zone + bias + Seasonality) is clean.
- **Skip the index trade** entirely.
- **Reduce overall basket size** (the conflict signals lower conviction across the broader equity complex).

### Bullish Seasonality Blocks Valuation-Overvalued Shorts (Phase 6, Ch 173)

When Valuation prints overvalued (suggesting short) BUT Seasonality is strongly bullish, **downgrade or skip** the short. Bernd: *"I still have a very bullish seasonality and I would have also struggled to pinpoint really an [entry to short]"*.

Mirror rule for longs: bearish Seasonality dampens Valuation-undervalued long signals.

This makes Seasonality a **soft override** on Valuation extremes when they conflict — not a full veto, but a confidence reducer in the bias hierarchy. When Seasonality strongly opposes Valuation, treat the trade as lower conviction (reduce size or require a stronger COT reading before proceeding).

### Retailer Disagreement — Soft Warning vs Hard Veto (Phase 6, Ch 176)

Reaffirms class-conditional handling. Bernd: *"I don't want to stop the whole analysis because all the retailers are not aligned"*:

| Asset class | Retailer disagreement (positioned same side as proposed trade) | Action |
|-------------|----------------------------------------------------------------|--------|
| **Precious Metals** | Hard veto (already documented) | **DO NOT TRADE** |
| **All other classes** | Soft warning | Reduce position size 25–50%, proceed with caution |

This codifies that the PM-only hard veto is intentional — for non-PM, retailer-on-the-wrong-side is just one of many inputs.

### Bernd's Actual Hierarchy (Phase 11 — replaces "3/5 vote")

**PHASE 11 CORRECTION**: Transcript frequency analysis of 186 sessions shows Bernd does NOT use an equal 3-of-5 vote. He follows a strict priority hierarchy. The "3/5 vote" was an agent-invented simplification, not Bernd's methodology.

| Priority | Factor | Frequency | Role |
|----------|--------|-----------|------|
| 1st | **Location** | 88% | **Hard gate** — equilibrium = no trade; extreme = proposed direction |
| 2nd | **Valuation** | 92% | **Hard veto** — strongly opposing = trade cancelled ("Rule #1") |
| 3rd | Minimum met | — | Location + Valuation aligned = **tradeable minimum** |
| 4th | **COT** | 48% | Confluence enhancer — not required, not primary gate |
| 5th | **Seasonality / Trend** | 76% / 64% | Supporting context — tie-breakers when val=neutral |

#### Step 1: Location Gate (HARD)

Location determines the **proposed direction** before any fundamental is checked:

| Location | Fib Range | Gate | Proposed Direction |
|----------|-----------|------|--------------------|
| Very Cheap / Cheap | Below 33% | PASS | LONG (bullish) |
| **Equilibrium** | 33–66% | **CONDITIONAL** — see below | — |
| Expensive / Very Expensive | Above 66% | PASS | SHORT (bearish) |

**Equilibrium exception**: if location is neutral, allow the trade ONLY when ALL 3 non-location fundamentals (Valuation + COT + Seasonality) unanimously agree in the same direction with zero opposing. Otherwise → NO TRADE.

#### Step 2: Valuation Hard Gate (Rule #1)

Valuation must NOT actively contradict the proposed direction. Bernd: *"Rule number one — valuation"* (CW38, CW39).

| Proposed Direction | Valuation State | Gate Result |
|-------------------|-----------------|-------------|
| Long | STRONG_BEARISH (≥+75) | **VETOED** — do not proceed |
| Long | MILD_BEARISH | WARNING — reduce size; may proceed with strong COT |
| Long | NEUTRAL / MILD_BULLISH / STRONG_BULLISH | PASS |
| Short | STRONG_BULLISH (≤-75) | **VETOED** — do not proceed |
| Short | MILD_BULLISH | WARNING — reduce size; may proceed with strong COT |
| Short | NEUTRAL / MILD_BEARISH / STRONG_BEARISH | PASS |

**Exception**: A 156-week COT extreme (both bands at extreme) can override MILD Valuation opposition. Cannot override STRONG opposition.

#### Step 3: Minimum Threshold

After both gates pass, the trade is tradeable when:
- **Location aligned + Valuation aligned** = Bernd's stated minimum (no other votes needed)
- **Location aligned + Valuation neutral** = tradeable if 1 of (COT / Seasonality / Trend) also agrees
- **Location aligned + Valuation neutral + nothing else agrees** = HOLD (location alone is not enough)

#### Step 4: Counter-Trend Safety Gate

For prop-firm accounts: never SHORT in an uptrend or LONG in a downtrend unless non-trend indicators overwhelmingly agree (≥2 non-trend same direction, 0 opposing). Counter-trend trades remain valid but require this extra gate.

#### Step 5: Presidential/Sannial Cycle Override for Equity Indices (Phase 23)

Equity indices (NQ=F, ES=F, YM=F, RTY=F) have a dedicated override that can convert a "bearish" Location verdict before the Valuation veto fires. When price is at or near an all-time high, Location reads "expensive" (Fib > 66%) and proposes SHORT — but in pre-election years (presidential cycle year 3, e.g. 2023) most months carry a bullish seasonal regime that Bernd follows even at ATH. Phase 23 adds this check before returning HOLD:

- **Full bullish override**: presidential cycle score > 0 AND sannial cycle score > 0 AND no fundamental is bearish AND ≥1 fundamental (COT / Seas / Val) is bullish → Location is promoted to 'bullish' and the trade proceeds normally through Steps 2–3.
- **Partial relax**: same cycle conditions but all fundamentals neutral → Location is promoted to 'neutral' (equilibrium path), avoiding a hard bearish veto.
- **Blocked**: any fundamental is bearish → no override. The "no bearish fundamentals" guard preserves the zero-false-positive guarantee at Stage 2.

The override only applies to the `asset_class == 'equity_indices'` branch. Individual stocks, forex, and commodities are not affected.

#### Step 6: ATH Momentum Override — Equity Indices (Phase 26)

When equity index is in the expensive zone (`loc='bearish'`, price at ATH) BUT trend = uptrend AND 4-bar ROC > 2%, downgrade `loc` from 'bearish' to 'neutral' BEFORE running consensus. This prevents the hard bearish-location veto from blocking cycle-driven long signals on strongly trending indices. Applied inside `_analyze_htf` after standard Fib computation. Applies to `asset_class == 'equity_indices'` only.

#### Step 7: Cycle Dominance Override — Equity Indices (Phase 26)

After the T1 cycle override block (Phase 23), if `loc != 'bearish'` (already relaxed by Phase 26 ATH momentum) AND trend is uptrend/sideways AND Valuation/Seasonality are not bearish AND **both** presidential AND sannial cycles agree bullish AND COT is not bearish → return `'bullish'`. Fires in residual cases where T1 relaxation set loc to neutral but full consensus still stalled. Search `Phase 26 cycle dominance` in `BP_rules_engine.py`.

#### Step 8: Presidential/Sannial Cycle Path for Individual Stocks (Phase 27)

In the equities branch of `_bias_consensus`, before returning 'hold', check: if `seas_n != 'bearish'` AND `pres_score > 0` AND `sann_score > 0` → return `'bullish'`. Captures 2023-style cycle-driven stock rallies (AAPL/GOOG/META/NFLX) where Valuation reads 'overvalued' (outperformed SPY) but Bernd was bullish on the pre-election year-3 + sannial year-3 thesis.

Design guards:
- **Trend guard REMOVED** — Oct 2023 ZigZag downtrend blocked correct calls even during Bernd's bullish period
- **Valuation guard REMOVED** — SPY RS proxy reads 2023 outperformers as 'overvalued'; cycle thesis trumps relative performance
- **Seasonality guard PRESERVED** — `seas_n != 'bearish'` protects against genuine seasonal lows (e.g. AAPL mid-October) where Bernd is neutral
- **Safe** — equities branch never returns 'bearish', only 'bullish' or 'hold', so removing guards creates no wrong-direction risk
- **Live scanner**: only fires during year-3 cycles (2023, 2027…). 2026 (sannial year 6, score=0) does NOT fire.

### Implementation (Phase 11 hierarchy + Phase 23–27 extensions)

```python
def synthesize_bias(location_bias, trend_bias, cot_bias, valuation_state, seasonality_bias,
                    cot_strength='normal'):
    """
    Synthesize all biases using Bernd's actual hierarchy (Phase 11).
    See BP_rules_engine._bias_consensus() for the live implementation.

    Hierarchy:
      Step 1: Location gate  — neutral = hold (unless 3/3 fundamentals overwhelm)
      Step 2: Valuation veto — opposing = hold
      Step 3: Minimum met   — loc + val aligned = tradeable
                              loc aligned + val neutral + 1 other = tradeable
      Step 4: Counter-trend — requires overwhelming non-trend agreement
    """
    val_bullish = valuation_state in {"STRONG_BULLISH", "MILD_BULLISH"}
    val_bearish = valuation_state in {"STRONG_BEARISH", "MILD_BEARISH"}
    val_str = "BULLISH" if val_bullish else ("BEARISH" if val_bearish else "NEUTRAL")

    # --- STEP 1: Location gate ---
    if location_bias == "NEUTRAL":
        # Allow only if val + cot + seas all agree unanimously
        fund_bull = sum(1 for v in [val_str, cot_bias, seasonality_bias] if v == "BULLISH")
        fund_bear = sum(1 for v in [val_str, cot_bias, seasonality_bias] if v == "BEARISH")
        if fund_bull == 3:   proposed = "BULLISH"
        elif fund_bear == 3: proposed = "BEARISH"
        else:                return {"overall_bias": "NEUTRAL", "action": "NO_TRADE",
                                     "note": "Equilibrium — insufficient fundamental override"}
    else:
        proposed = location_bias  # BULLISH or BEARISH from zone location

    # --- STEP 2: Valuation veto ---
    if proposed == "BULLISH" and val_bearish:
        if valuation_state == "STRONG_BEARISH":
            return {"overall_bias": "NO_TRADE", "action": "NO_TRADE",
                    "note": "Valuation STRONG_BEARISH — long VETOED (Rule #1)"}
        if cot_strength != "strong":
            return {"overall_bias": "NO_TRADE", "action": "REDUCE_SIZE",
                    "note": "Valuation mildly bearish — reduce size or skip"}
    if proposed == "BEARISH" and val_bullish:
        if valuation_state == "STRONG_BULLISH":
            return {"overall_bias": "NO_TRADE", "action": "NO_TRADE",
                    "note": "Valuation STRONG_BULLISH — short VETOED (Rule #1)"}
        if cot_strength != "strong":
            return {"overall_bias": "NO_TRADE", "action": "REDUCE_SIZE",
                    "note": "Valuation mildly bullish — reduce size or skip"}

    # --- STEP 3: Minimum threshold ---
    trend_n = "BULLISH" if trend_bias == "uptrend" else ("BEARISH" if trend_bias == "downtrend" else "NEUTRAL")
    if proposed == "BULLISH":
        if val_str == "BULLISH":
            return {"overall_bias": "BULLISH", "action": "FULL_SIZE",
                    "note": "Location + Valuation aligned = Bernd minimum ✓"}
        if any(v == "BULLISH" for v in [cot_bias, seasonality_bias, trend_n]):
            return {"overall_bias": "BULLISH", "action": "FULL_SIZE",
                    "note": "Location + 1 supporting (val=neutral)"}
        return {"overall_bias": "NEUTRAL", "action": "NO_TRADE",
                "note": "Location only — all else neutral, insufficient"}
    else:  # proposed == "BEARISH"
        if val_str == "BEARISH":
            return {"overall_bias": "BEARISH", "action": "FULL_SIZE",
                    "note": "Location + Valuation aligned = Bernd minimum ✓"}
        if any(v == "BEARISH" for v in [cot_bias, seasonality_bias, trend_n]):
            return {"overall_bias": "BEARISH", "action": "FULL_SIZE",
                    "note": "Location + 1 supporting (val=neutral)"}
        return {"overall_bias": "NEUTRAL", "action": "NO_TRADE",
                "note": "Location only — all else neutral, insufficient"}
```

### Decision Guide

| Scenario | Action |
|----------|--------|
| Location neutral + fundamentals mixed | NO TRADE — equilibrium, no edge |
| Location neutral + val+cot+seas ALL agree | TRADE — overwhelming equilibrium override |
| Location bullish/bearish + Valuation STRONGLY opposes | NO TRADE — Rule #1 veto |
| Location bullish/bearish + Valuation mildly opposes | REDUCE SIZE or skip |
| Location + Valuation both aligned | TRADE — Bernd's stated minimum |
| Location aligned + Valuation neutral + 1 other supports | TRADE — sufficient |
| Location aligned + Valuation neutral + nothing else | NO TRADE — too weak |

---

## Cross-Asset Gates for Equity-Index Shorts

**AUDIT CORRECTION (Phase 6, Ch 156)**: A short setup on @ES / @NQ / @YM requires more than just a supply-zone touch and bearish bias votes. Bernd: *"right now I just don't see the short coming. Retailers are getting more and more bullish on the weekly… we need the help of other Treasury bonds [to roll over]."*

Two cross-asset prerequisites must BOTH be active:

1. **Retailer extreme** — retailers net-bullish on weekly equity COT (the dumb-money side of the trade is on the wrong side).
2. **Treasury Bond ROC actively rolling negative** — not merely net-positioned. The bond reference (@ZB / @ZN) must show an ROC trajectory that has just turned from positive toward zero/negative on the relevant lookback (10 daily / 13 weekly).

```python
def equity_index_short_cross_asset_gate(retailer_pos, retailer_extreme_threshold,
                                         bond_roc_now, bond_roc_prev_n):
    """
    Cross-asset prerequisites for shorting an equity index.
    Returns (allowed, reason).
    """
    # Retailer extreme: retailers loaded long = dumb money on the wrong side
    retailers_extreme = retailer_pos > retailer_extreme_threshold

    # Bond rollover: ROC must be actively turning from positive toward negative
    # (not merely net-long-positioned, which can persist for months)
    bond_rolling = bond_roc_now < 0 and bond_roc_prev_n > 0

    if retailers_extreme and bond_rolling:
        return True, "OK — retailers loaded long AND bonds rolling over"
    if retailers_extreme and not bond_rolling:
        return False, "WAIT — retailers extreme but bonds not yet rolling"
    if not retailers_extreme and bond_rolling:
        return False, "WAIT — bonds rolling but retailers not yet extreme"
    return False, "VETO — neither cross-asset signal active"
```

**Why both are required**: A retailer extreme alone often persists for weeks before the actual top — bonds rolling over signals that the rate environment is finally turning, providing the tailwind for equity weakness. Either signal in isolation is insufficient; their coincidence is what marks the high-conviction equity short window.

**Bond-induced Valuation freeze caveat (Ch 156)**: When equity Valuation reads neutral but bond reference is moving in lockstep with equities, the Valuation reading is uninformative — *"the blue line, which is the Treasury Bond valuation… is not doing anything because they are also moving higher"*. In this regime, weight Valuation reduced and rely more heavily on COT extremes + Seasonality.
| All 5 factors align | Highest conviction trade — consider larger position (max 2%) |
