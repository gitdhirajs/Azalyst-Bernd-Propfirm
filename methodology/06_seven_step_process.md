# The Seven-Step Decision Process — Complete Workflow

> Bernd Skorupinski Blueprint Trading System — File 6 of 7

---

This is the **EXACT sequence** every trade must follow. No steps can be skipped. Each step acts as a gate — if the criteria are not met, the trade is rejected and you move on.

---

## STEP 1: Market Selection

Select the instrument to analyze from your watchlist of liquid, tradeable markets.

### Requirements

- Must be a liquid instrument with tight spreads
- Must have **COT data available** (futures-based instruments)
- Must be on your pre-defined watchlist (no random picks)

### Asset Classes

| Asset Class | Examples |
|-------------|----------|
| Forex Pairs | EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CAD, USD/CHF, NZD/USD |
| Commodities | Gold (XAU/USD), Silver (XAG/USD), Oil (WTI), Natural Gas |
| Equity Indices | S&P 500, Nasdaq 100, Dow Jones, Russell 2000 |

### Futures-to-Funded Cheat Sheet

Cross-check the futures symbol (used for COT data) against the funded/spot symbol (used for chart analysis and execution).

| Futures | Funded/Spot | Asset Class |
|---------|-------------|-------------|
| 6E | EUR/USD | Forex |
| 6B | GBP/USD | Forex |
| 6J | USD/JPY (inverted) | Forex |
| 6A | AUD/USD | Forex |
| 6C | USD/CAD (inverted) | Forex |
| 6S | USD/CHF (inverted) | Forex |
| 6N | NZD/USD | Forex |
| GC | XAU/USD (Gold) | Commodity |
| SI | XAG/USD (Silver) | Commodity |
| CL | WTI Crude Oil | Commodity |
| NG | Natural Gas | Commodity |
| ES | S&P 500 / SPX | Equity Index |
| NQ | Nasdaq 100 / NDX | Equity Index |
| YM | Dow Jones / DJI | Equity Index |

> **Note on Inverted Pairs**: 6J, 6C, and 6S are quoted inversely to their spot equivalents. When COT shows 6J bullish, USD/JPY goes DOWN (JPY is strengthening).

---

## STEP 2: HTF Technical Analysis

Perform the higher-timeframe structural analysis. This establishes **Location** and **Trend**.

### Location Analysis

Draw a Fibonacci retracement from the HTF demand zone distal to the HTF supply zone distal.

| Fib Level | Location Label | Bias |
|-----------|---------------|------|
| Below 33% | Very Cheap | STRONG BUY |
| 33% - 50% | Cheap | BUY bias |
| ~50% | Equilibrium | NO TRADE (beginners must skip) |
| 50% - 66% | Expensive | SELL bias |
| Above 66% | Very Expensive | STRONG SELL |

**Rule**: If price is at equilibrium (~50%), beginners must skip the trade entirely. Advanced traders may trade equilibrium only with strong fundamental confluence.

### Trend Analysis

Count **6 pivots** (3 swing highs + 3 swing lows), reading **RIGHT to LEFT** on the HTF chart.

| Pattern | Trend | Action |
|---------|-------|--------|
| Higher lows (higher highs NOT required) | Uptrend | Trade WITH trend (buy dips) |
| Lower highs (lower lows NOT required) | Downtrend | Trade WITH trend (sell rallies) |
| Neither | Sideways | Can still trade, but adjust targets to max 1:2 |

The rule is **asymmetric** (OTC M2 L3/L4 "Required: 2× HL … HH not necessarily required"; code
`BP_rules_engine._determine_trend`, verified 2026-09-14). Higher lows are checked first, so
rising lows under falling highs (a contracting triangle) read as **uptrend**. Earlier versions of
this table said "all HH + HL", which the code has not done since the OTC Lesson 4 fix.

#### Pivot-Break = Explicit Trend-Reversal Trigger (Phase 6, Ch 174)

The 6-pivot pattern only labels the current state. The **trend FLIPS** when price closes **beyond the most recent opposing pivot** — the operational reversal trigger. Bernd: *"we broke this pivot… we broke that line… we would not be in a confirmed downtrend"* (until that break occurs).

```python
def detect_trend_reversal(candles, current_trend_label, recent_opposing_pivot):
    """
    Returns ('FLIP_TO_DOWN' | 'FLIP_TO_UP' | None).
    A confirmed close beyond the most recent opposing pivot flips the label.
    """
    last_close = candles[-1].close
    if current_trend_label == "UP" and last_close < recent_opposing_pivot.low:
        return "FLIP_TO_DOWN"
    if current_trend_label == "DOWN" and last_close > recent_opposing_pivot.high:
        return "FLIP_TO_UP"
    return None
```

Until a confirmed close beyond the opposing pivot, the prior trend label persists. This prevents whipsaws from over-counting pivot patterns.

### Action Matrix — Location × Trend → Action

This is the **canonical decision grid** Bernd walks through in OTC 2025 Module 2 Lesson 5 (Decision Process). It collapses Location and Trend into a single per-cell action with explicit profit-potential and probability tags.

#### Cheap / Very Cheap location row (look for DEMAND zones)

| Trend     | Action                                                                  | Tier         |
|-----------|-------------------------------------------------------------------------|--------------|
| Uptrend   | Look for **big-picture** Demand Zones — **High profit potential**       | Best Setup   |
| Sideways  | Look for **pullbacks** into Demand Zones — Medium profit potential      | Acceptable   |
| Downtrend | Look for **pullbacks** into Demand Zones — Low profit potential         | Acceptable   |

#### Expensive / Very Expensive location row (look for SUPPLY zones — mirror of above)

| Trend     | Action                                                                  | Tier         |
|-----------|-------------------------------------------------------------------------|--------------|
| Downtrend | Look for **big-picture** Supply Zones — **High profit potential**       | Best Setup   |
| Sideways  | Look for **pullbacks** into Supply Zones — Medium profit potential      | Acceptable   |
| Uptrend   | Look for **pullbacks** into Supply Zones — Low profit potential         | Acceptable   |

#### Equilibrium location row (avoid)

| Trend     | Action                                                                                                                |
|-----------|-----------------------------------------------------------------------------------------------------------------------|
| Uptrend   | Reduced profit & probability — **big brother / small brother is not given** — better to avoid                         |
| Sideways  | **No trades**                                                                                                          |
| Downtrend | Reduced profit & probability — **big brother / small brother is not given** — better to avoid                         |

#### Critical rules from the slide

- **Location overrides Trend at extremes**: at Very Cheap / Very Expensive, Location categorically overrides Trend. Even if the HTF trend is up, at Very Expensive only **supply** trades are allowed. Bernd: "*it's only allowed to short the asset… because the current price is close [to the very-expensive boundary]*".
- **"Best Setup"** is reserved terminology — applies when zone direction is **aligned with trend** AND **aligned with location** (the diagonal cells of the matrix).
- **Equilibrium-skip is mechanical, not discretionary**: at equilibrium the HTF Big-Brother / LTF Small-Brother nesting cannot form because price is mid-range. There is no clean HTF zone to anchor on, so the LTF zone has no parent. This is why equilibrium is a hard skip.
- **Sideways at extreme location is acceptable** (medium profit/probability) but **sideways at equilibrium is not**.

#### Mid-Equilibrium LTF Level-to-Level Trades (Phase 6, Ch 182)

The HTF equilibrium skip rule applies to **directional** HTF-anchored trades. It does NOT forbid **LTF level-to-level swing trades** between intermediate LTF levels while HTF is mid-range. Bernd, asked: *"if we have exactly the situation that we are between those location zones, can I trade in the lower timeframe independent from the location zones"* — he answered yes, with caveats.

**Allowed**:
- LTF (60m / 4H) ranges with clean LTF supply at the top + LTF demand at the bottom
- Short-hold (intraday to a few sessions) trades
- Position size **reduced** (≤50% of standard) — HTF equilibrium = no parent zone = lower conviction
- T2 hard cap; no trailing into a multi-leg trade

**Still forbidden**:
- HTF-anchored directional trades at equilibrium (the original rule stands)
- Trying to ride the LTF trade through the equilibrium zone into the next HTF leg (treat as scalp only)

### The 3-Column Framework (canonical lesson framing)

Every Step-2 analysis answers three questions in this fixed order:

1. **Location (HTF)** — Understand the location of the entry levels.
2. **Trend (HTF)** — Understand the direction of the trend.
3. **Zone (LTF)** — Identify high-quality zones.

Skip any one and the trade is invalid.

### Anticipatory Bias (Advanced)

Anticipatory setups are counter-trend trades taken at extreme locations. These are advanced and carry lower conviction.

1. **HTF Trend Theory**: Zoom out to an even higher timeframe. If the overarching trend on the ultra-HTF contradicts the current HTF trend, an anticipatory reversal may be forming.
2. **Pivot at Extreme Location**: A reversal pivot forming at Very Cheap or Very Expensive on the Fibonacci = an anticipatory signal.

Anticipatory trades use reduced targets (1R to 1.5R max) and tighter management.

---

## STEP 3: Fundamental Confirmation

Check **ALL THREE** fundamental indicators to build the consensus.

### 1. COT (Commitment of Traders)

- Select the correct COT group for the asset class:
  - **Forex**: Non-Commercials (Large Speculators)
  - **Commodities**: Commercials (primary) + Retailers (contrarian)
  - **Equities**: Non-Commercials
- Check the COT index level (**0 to 100 scale**, `100*(net-min)/(max-min)`. Thresholds: ≥80 bullish, ≤20 bearish. C-57 reverted Phase 13's −20..+120 V2 scale — see `03_fundamentals.md`.)
- Check for divergences between price and COT positioning
- 156-week extreme levels are the strongest signals (especially for commodities)

### 2. Valuation

- Use the correct Rate of Change (ROC) period per asset class (frame-verified Phase 41):
  - **Forex**: ROC 10, reference DXY only
  - **General Commodities**: ROC 10, reference DXY + Bonds (ZB) + Gold (GC)
  - **Agricultural commodities (ZC / ZW / ZS)**: ROC **30** (Phase 41 chunk 5: CW07 Corn + CW05 Soybeans confirm ROC=30 in label), references DXY + ZB + GC
  - **Equities / Equity Indices**: ROC 10 with DXY + ZB + GC. **Dual-ROC chart overlay** for stock-level analysis: run two indicator instances at different lengths (daily: 10+13; weekly: 13+30) and require both to agree direction; this is a chart practice not a parameter override.
  - **Natural Gas (NG=F)**: **EXCLUDED** — do not use Valuation. Phase 16/25 correction.
  - **Gold (GC=F)**: ROC **13** (Phase 41 chunk 5: CW45 frame_000644), references DXY + ZB + GC
  - **Silver (SI=F)**: ROC **30** (Phase 41 chunk 5: CW11 frame_000841), references DXY + ZB (@VD ticker) + GC
  - **Platinum (PL=F) and Palladium (PA=F)**: ROC 10, references **DXY + Gold (GC) + Bonds (ZB)** — all three active. Phase 41 chunk 3 correction (5 frames across 2 sessions confirmed all 3 refs on CampusValuationTool_V2). The earlier "DXY + Gold only" claim was incorrect.
  - **Crude Oil (CL=F)**: ROC 10, references DXY + GC + ZB (standard 3 refs; Phase 33's earlier "Gold only" reverted in Phase 41 after 4 independent frames confirmed all 3 active). Daily ZigZag = **5%** override (Phase 41 chunk 1: frame_004397 status bar).
- Use the **4-state model**: STRONG BULLISH (≤-75) / MILD BULLISH (0 to -75) / MILD BEARISH (0 to +75) / STRONG BEARISH (≥+75)
- For equities, valuation is the **PRIMARY/LEADING** fundamental indicator AND a **HARD PREREQUISITE GATE**

### 3. Seasonality

- Check the slope direction across all three lookback periods: **5yr, 10yr, 15yr**
- All three agree on direction = strong seasonal signal
- Two of three agree = moderate signal
- Conflicting slopes = weak/no seasonal signal

### Consensus Rule — Two-Step Process

**Step 1: Valuation Hard Gate (MANDATORY — "Rule Number One")**

Before counting votes, check the Valuation reading against the proposed trade direction:
- **STRONG opposition** (e.g. Valuation is STRONG BEARISH and you want to go LONG) → **STOP. NO TRADE.** This is a veto, regardless of all other factors.
- **Mild opposition** → WARNING. Reduce size to 0.5%; only proceed if COT is at 156-week extreme.
- **Aligned or neutral** → Proceed to Step 2.

**Step 2: Bernd's Hierarchy (Phase 11 — replaces "3/5 Vote")**

Transcript analysis across 186 sessions shows Bernd uses a PRIORITY HIERARCHY, not an equal vote.

**2a — Location gate (HARD):**
- Location = cheap/very cheap → proposed direction = LONG
- Location = expensive/very expensive → proposed direction = SHORT
- Location = equilibrium (neutral) → **NO TRADE** unless ALL 3 fundamentals (Val + COT + Seas) unanimously override

**2b — Valuation veto (HARD — "Rule Number One", CW38/CW39):**
- Valuation STRONGLY opposes proposed direction → **NO TRADE**
- Valuation mildly opposes → WARNING, reduce size; may proceed with strong COT (156w extreme)
- Valuation neutral or aligned → PASS

**2c — Minimum threshold:**
- Location aligned + Valuation aligned → **TRADEABLE** (Bernd's stated minimum)
- Location aligned + Valuation neutral + 1 of (COT / Seasonality / Trend) → **TRADEABLE**
- Location aligned + Valuation neutral + nothing else → NO TRADE

**2d — Counter-trend safety gate (prop-firm protection):**
Never fire SHORT in an uptrend or LONG in a downtrend unless non-trend agreement is overwhelming (≥2 non-trend indicators same direction, 0 opposing). Phase 8 H1 fix: gate checks non-trend tally only — the trend vote is excluded to avoid the impossibility bug where `bullish == 0` was unreachable in any uptrend.

**2e — Presidential/Sannial cycle override for equity indices (Phase 23):**
For equity indices (NQ/ES/YM/RTY) only: when Location reads "bearish" (price at ATH / expensive zone), the system checks the presidential cycle (4-year) and sannial decennial cycle before applying the bearish Location verdict. If both cycles are in a bullish phase AND no fundamental is bearish, Location is promoted to 'bullish' (full override) or 'neutral' (partial relax). This covers Bernd's pre-election-year behaviour where the bullish seasonal regime takes priority over technical ATH location. Any bearish fundamental blocks the override entirely.

**2f — ATH momentum override for equity indices (Phase 26):**
When equity index is in the expensive zone (loc='bearish') BUT trend = uptrend AND 4-bar ROC > 2% → downgrade loc to 'neutral' inside `_analyze_htf` BEFORE the consensus runs. Prevents hard bearish-location veto from blocking cycle-driven long signals on strongly trending indices.

**2g — Cycle dominance override for equity indices (Phase 26):**
After the T1 cycle-override block (Phase 23), if loc is not bearish AND trend is uptrend/sideways AND Valuation/Seasonality not bearish AND both presidential+sannial cycles bullish AND COT not bearish → return 'bullish'. Fires when Phase 23 relaxed loc to neutral but full consensus stalled.

**2h — Equities presidential/sannial cycle path for individual stocks (Phase 27):**
In the equities branch, before returning 'hold': if `seas_n != 'bearish'` AND `pres_score > 0` AND `sann_score > 0` → return 'bullish'. Captures cycle-driven stock rallies (2023 AAPL/GOOG/META). Trend+Valuation guards removed (safe — equities branch never returns 'bearish'). Seasonality guard kept. Only activates during year-3 pre-election cycles (2023, 2027…); 2026 does not fire.

> **Implementation**: `BP_rules_engine._bias_consensus()` — Phase 11 rewrite with Phase 23–27 additions. Full hierarchy: Location gate (with Phase 23/26 cycle overrides for equity indices) → Valuation veto → Minimum threshold → Counter-trend gate → Phase 27 equities cycle path. See CLAUDE.md Phase 11, 23, 26, 27 for full details.

**Asset-class-specific consensus for individual stocks**: stocks have NO CFTC COT report. Per Phase 6 audit + monthly-roadmap analysis, Bernd's stock process is **Valuation-driven**: if Valuation is undervalued AND trend ≠ strongly down → take long. **Individual stocks are NEVER shorted directly** — Bernd shorts indices via futures. Implementation: `_bias_consensus(asset_class='equities')` branches to a Valuation-primary path.

### Special Gates for Equity Stocks (beyond indices)

When trading individual STOCKS (not indices themselves):
1. **Parent index check first**: The parent index (NQ for Nasdaq stocks, ES for S&P stocks) must INDEPENDENTLY pass the 7-step process and be at a valid zone before any constituent stock is analysed.
2. **AAPL + MSFT dual-gate** (for Nasdaq/tech stocks): BOTH Apple and Microsoft must independently show valid zone setups. If neither is at a zone, the Nasdaq sector is not ready.
3. **Index-level Valuation gates individual stocks**: Even if a stock's own Valuation looks favourable, if the parent index Valuation is strongly bearish, individual stock longs within that index are down-graded.
4. **Mega-cap basket Valuation scan (Phase 6, Ch 153)**: For an NQ-direction call, scan the full top-7+ mega-cap basket (AAPL, MSFT, GOOG, META, AMZN, NFLX, TSLA, NVDA) — require ≥4/8 aligned with the proposed bias direction in addition to the AAPL+MSFT gate. See [03_fundamentals.md](03_fundamentals.md) "Mega-Cap Basket Scan".
5. **Stock-level dual-timeframe Valuation gate**: For individual stock entries, BOTH long-term (weekly) AND short-term (daily) Valuation must be aligned with trade direction. See [03_fundamentals.md](03_fundamentals.md) "Stock-Level Dual-Timeframe Valuation Gate".
6. **"Trade the constituents not the index" fallback (Phase 6, Ch 153)**: When the parent index has NO tradable zone but the mega-cap constituents are aligned and at their own zones, **trade the constituent stocks directly**, skip the index. Bernd: *"I don't see a trade on the NASDAQ itself because it would be this daily demand [too far away]"* — but the constituent stocks each had clean zones.

### US Holiday and Calendar Gates

Before executing a new trade, check:
- **US Federal Holiday within 2 sessions**: Apply the two-session gate — avoid entering on the Friday before AND the Monday of any US federal holiday (low liquidity = unreliable zone behaviour).
- **Thanksgiving or Christmas week**: COT data freshness is suppressed. Treat COT from the prior week as stale. Skip new entries during these weeks.
- **High-impact events (CPI, NFP, FOMC) same day**: Reduce risk to 0.5% or wait until post-announcement zone forms.

---

## STEP 4: LTF Zone Identification

Switch to the LTF chart and identify tradeable supply/demand zones.

### Zone Detection Sequence

1. **Scan** for leg-in → base → leg-out formations
2. **Score** all 6 qualifiers for each zone found:
   - Departure (leg-out strength)
   - Basing (number of candles in base, max 6)
   - Arrival (leg-in characteristics)
   - Freshness (has zone been tested?)
   - Trend alignment
   - Location alignment
3. **Check** for HTF alignment — Big Brother / Small Brother nesting
   - Does the LTF zone sit inside or near an HTF zone of the same type?
   - Nested zones receive a scoring bonus
4. **Rank** all zones by composite score
5. **Select** the highest-scoring zone that matches the consensus direction

### Direction Matching

| Consensus | Zone Type to Trade | Action if Opposite |
|-----------|-------------------|-------------------|
| Bullish | DEMAND zones only | SKIP supply zones |
| Bearish | SUPPLY zones only | SKIP demand zones |

**If no qualifying zone exists in the consensus direction, there is no trade.** Wait for one to form.

---

## STEP 5: Entry Trigger

Wait for price to reach the selected zone and provide a candlestick confirmation pattern.

### Entry Conditions

1. Price must **touch** the zone's proximal-to-distal range
2. Look for confirmation candlestick patterns:

| At Demand (Long) | At Supply (Short) |
|-------------------|-------------------|
| Hammer | Shooting Star |
| Bullish Engulfing | Bearish Engulfing |
| Morning Star | Evening Star |
| Dragonfly Doji | Gravestone Doji |

### Entry Options

| Option | Method | R:R Quality | Description |
|--------|--------|-------------|-------------|
| Option 1 | Limit order beyond the extreme candle | Good | Place limit above the high of the confirmation candle (demand) or below the low (supply) |
| Option 2 | Limit order within the zone range | Better | Place limit within the proximal-to-distal range |
| Option 3 | LTF zone within the pattern | **BEST R:R** | Drop to an even lower TF, find a micro zone within the confirmation pattern |

### If No Confirmation Pattern Forms

Place a **limit order at the proximal line** with a stop at the **-33% Fibonacci extension** beyond the distal line. This is a blind entry — acceptable when zone quality is high and consensus is strong.

---

## STEP 6: Trade Execution & Management

Execute the trade and manage it according to the fixed rules.

### Execution Checklist

1. **Calculate position size**:
   ```
   position_size = risk_amount / stop_distance
   ```
2. **Verify R:R >= 1:2** — if the nearest obstacle (opposing zone, major level) makes 1:2 unreachable, **SKIP the trade**
3. **Place all orders simultaneously**:
   - Entry limit order
   - Stop loss at -33% Fibonacci
   - T1 take-profit (1R)
   - T2 take-profit (2R)
   - T3 take-profit (3R)
4. **At T1 hit**: Move stop to breakeven — **NON-NEGOTIABLE**
5. **At T2 hit**: Close 50% of position, begin trailing stop
6. **At T3 hit**: Close the remaining position OR continue trailing if with-trend

### Management by Direction Context

| Direction | T1 Action | T2 Action | Beyond T2 |
|-----------|-----------|-----------|-----------|
| With trend | BE move | 50% partial + trail | Let it run to T3/T4 |
| Sideways | BE move | Close full position | No trailing |
| Counter-trend | BE move | Close full position | No trailing |
| Anticipatory | Close 50% at 1R | Close remainder | No trailing |

---

## STEP 7: Review & Refine

After every trade closes (whether win or loss), complete a structured review.

### Post-Trade Review Questions

1. **Was the zone valid?** (Did it pass departure and base qualifiers?)
2. **Did fundamentals align?** (Did Location gate pass + Valuation not oppose + minimum threshold met?)
3. **Was entry at the zone?** (Or did I chase price?)
4. **Was stop at -33% Fib?** (Proper placement, not arbitrary?)
5. **Did I follow management rules?** (BE at 1R, partial at 2R?)
6. **What is the R-multiple outcome?** (e.g., +2.3R, -1R, +0.5R)
7. **Update statistics**: win rate, average R, expectancy

### Expectancy Formula

```
expectancy = (win_rate * avg_win_R) - ((1 - win_rate) * avg_loss_R)

# Positive expectancy = profitable system over time

# Example with 50% win rate and 1:2 average R:R:
# (0.50 * 2) - (0.50 * 1) = 0.50R per trade
# Over 100 trades: 100 * 0.50R = 50R profit
```

### Statistics to Track

| Metric | Formula | Target |
|--------|---------|--------|
| Win Rate | wins / total_trades | 40-60% |
| Average Win (R) | sum(winning_R) / wins | > 2.0R |
| Average Loss (R) | sum(losing_R) / losses | ~1.0R |
| Expectancy | (WR * avg_win) - ((1-WR) * avg_loss) | > 0.3R |
| Profit Factor | gross_profit / gross_loss | > 1.5 |
| Max Consecutive Losses | longest losing streak | Track for psychology |

---

## Complete Flowchart (Text Version)

```
START
  │
  ▼
SELECT MARKET (Step 1)
  │ Must have COT data, must be liquid
  │ Is today a US holiday or within 2 sessions of one? → SKIP or reduce size
  ▼
HTF: LOCATION CHECK (Step 2)
  │ Draw Fib from demand distal to supply distal
  │ Is price at equilibrium (~50%)?
  │   YES → SKIP TRADE
  │   NO  → Continue
  ▼
HTF: TREND CHECK (Step 2)
  │ ZigZag pivots + 6-pivot method (right to left)
  │ Determine: Uptrend / Downtrend / Sideways
  ▼
  [IF EQUITY STOCK: verify parent index at zone + AAPL/MSFT gate first]
  ▼
VALUATION: HARD GATE (Step 3 — RULE #1)
  │ Use correct ROC and references (stocks: ZB + DXY; NG=F: EXCLUDED; forex: DXY; commodities: DXY+GC+ZB)
  │ 4-state reading: STRONG/MILD BULLISH or BEARISH
  │ Does Valuation STRONGLY oppose the proposed direction?
  │   YES → VETO TRADE ──────────────────→ Return to Step 1
  │   MILD opposition → WARNING (reduce to 0.5%) → Continue
  │   NO opposition  → Continue normally
  ▼
COT: CHECK INDEX + DIVERGENCE (Step 3)
  │ Use correct group for asset class (Forex/Equities: Non-Comm 26w; Commodities: Comm 52w)
  │ Check for fresh extreme (just crossed 80/20 this week = higher conviction)
  │ Check retailer directional-alignment veto for PMs
  │ Note bias: Bullish / Bearish / Neutral
  ▼
SEASONALITY: SLOPE DIRECTION + TURN? (Step 3)
  │ Check 5yr / 10yr / 15yr (NG: 10yr+5yr only)
  │ MUST ACTIVELY TURN positive/negative — sustained flat slope = neutral
  │ Note bias: Bullish / Bearish / Neutral
  ▼
CONSENSUS: BERND'S HIERARCHY (Step 3)
  │  1. Location gate: neutral = SKIP (unless 3/3 fundamentals override)
  │  2. Valuation veto: strongly opposing = SKIP
  │  3. Minimum: loc + val aligned = GO; loc + val-neutral + 1 other = GO
  │  4. Counter-trend: needs ≥2 non-trend agreeing, 0 opposing
  │   NO  → SKIP TRADE ──────────────────→ Return to Step 1
  │   YES → Continue
  ▼
CALENDAR + NASDAQ GAP CHECK
  │ Thanksgiving/Christmas week + stale COT? → SKIP
  │ CPI/NFP/FOMC today? → Reduce to 0.5% or skip
  │ NASDAQ (or YM/ES) gap between price and target zone? → Flag as speed bump
  ▼
LTF: FIND QUALIFIED ZONE (Step 4)
  │ Scan for leg-in → base → leg-out
  │ Score all 6 qualifiers
  ▼
ZONE MATCHES CONSENSUS DIRECTION?
  │   NO  → SKIP ─────────────────────────→ Return to Step 1
  │   YES → Continue
  ▼
COMPOSITE SCORE >= 4.0?
  │   NO  → SKIP ─────────────────────────→ Return to Step 1
  │   YES → Continue
  ▼
SPEED BUMPS CHECK
  │ Opposing zones between price and target zone?
  │   Blocking? → Reduce conviction; consider skipping
  │   Minor? → Flag and continue
  ▼
WAIT FOR ENTRY PATTERN (Step 5)
  │ Price must reach zone
  │ Look for confirmation candle (E1/E2/E3a/E3b/E3c/E4)
  │ Determine stop mode: LTF entry (-33% Fib) OR HTF weekly (distal only)
  ▼
R:R >= 1:2?
  │   NO  → SKIP ─────────────────────────→ Return to Step 1
  │   YES → Continue
  ▼
EXECUTE TRADE (Step 6)
  │ Position size = risk% (0.5% if counter-trend/anticipatory/calendar event)
  │ Place entry, stop, and TP orders
  │
  ├── At half-T1: Move stop to breakeven (preferred) OR wait for T1 (conservative)
  ├── At T2 (2R): Close 50% (or 100% if counter-trend); begin trailing if with-trend
  └── At T3 (3R): Close remainder or continue trail (with-trend only)
  │
  ▼
TRADE CLOSES
  │
  ▼
REVIEW (Step 7)
  │ Answer all 7 review questions
  │ Update statistics
  │ Calculate expectancy
  ▼
REPEAT → Return to Step 1
```

---

## Quick Reference: The 7 Steps at a Glance

| Step | Name | Key Question | Gate Condition |
|------|------|-------------|----------------|
| 1 | Market Selection | Is this tradeable? | Liquid + COT available + not holiday week |
| 2 | HTF Technical | Where is price? What's the trend? | Not at equilibrium; ZigZag trend confirmed |
| 3a | Valuation Gate | Does Valuation allow this direction? | **VETO if strongly opposed — Rule #1** |
| 3b | COT + Seasonality | Do COT + Seasonality confirm? | Check fresh extreme, retailer veto |
| 3c | Consensus | Location gate + Valuation veto + minimum met? | Loc gate → Val veto → loc+val aligned OR loc+val-neutral+1 other |
| 4 | LTF Zone | Is there a quality zone in the right direction? | Composite score >= 4.0; speed bumps checked |
| 5 | Entry Trigger | Is there a confirmation pattern with good R:R? | R:R >= 1:2; stop mode selected (LTF vs HTF) |
| 6 | Execution | Am I managing by the rules? | BE at half-T1 (preferred); partial at T2; counter-trend FULL close at T2 (paper trader: only with `BP_TYPE_LADDERS=1` — see `05_trade_management.md`) |
| 7 | Review | Did I follow the system? | Honest self-assessment; expectancy updated |
