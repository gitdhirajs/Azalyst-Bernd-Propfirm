# Trade Management — Stops, Targets, Trailing, Position Sizing

> Bernd Skorupinski Blueprint Trading System — File 5 of 7

---

## Stop Loss — Two Modes by Entry Timeframe

**AUDIT CORRECTION (CW43-Idx)**: The stop formula depends on WHERE you are entering — at the LTF zone (default, tight stop) or directly at the HTF weekly zone (wider stop = distal only). Rule #8's "-33% ALWAYS" applies specifically to LTF pattern/zone entries.

### Mode 1: LTF / Pattern Entries — -33% Fibonacci (Standard)

For pattern-confirmation entries and LTF zone refinement entries:

```
# Fibonacci: 100 = Proximal, 0 = Distal
# For DEMAND zones (long trades):
stop = distal - 0.33 * (proximal - distal)  # Below distal by 33% of zone height

# For SUPPLY zones (short trades):
stop = distal + 0.33 * (proximal - distal)  # Above distal by 33% of zone height
```

### Mode 2: HTF Weekly Income Entries — DISTAL LINE ONLY

When entering directly at the **weekly-timeframe zone proximal** without drilling down to LTF:

```
# For DEMAND zones (long trades):
stop = distal  # Exactly at the distal line — NO extension

# For SUPPLY zones (short trades):
stop = distal  # Exactly at the distal line — NO extension
```

**Why**: Weekly zones are inherently wide. Adding -33% to a weekly distal pushes the stop so far that R:R collapses below 1:2. Bernd confirmed (CW43-Idx) that weekly income trades achieve 4:1 R:R using the distal-only stop — the weekly distal already accounts for institutional stop-hunt territory within the wide zone range. The -33% extension is reserved for tight LTF zones where the buffer is genuinely needed.

### Stop Loss Rules (Universal)

- **NEVER** move your stop further from entry. Only tighten (toward entry or breakeven).
- Stop placement is calculated BEFORE entry. If the resulting R:R is less than 1:2, the trade is skipped entirely.
- The stop level applies to the **distal line** in both modes.
- Stop is modified at the half-target breakeven trigger (preferred), or at T1 hit (conservative), and during trailing (tightened further).
- **Set-and-forget discipline (Phase 6, Ch 181)**: do NOT touch the stop until at least half-T1 (or 1R) has been achieved. Bernd: *"I don't touch the stop losses unless it's a one to two to one. Otherwise it's a bad trade."* Pre-emptive tightening = bad trade.

### All-Time-High / All-Time-Low Liquidity-Aware Stop (Phase 6, Ch 180)

When **shorting near an all-time-high** (or **longing near an all-time-low**), place the stop **slightly ABOVE the ATH** (or below the ATL), not merely at the zone distal. Bernd: *"stop losses… above the all-time high, a little bit"* — institutions sweep ATH/ATL liquidity before reversing, so a stop at the zone distal alone often gets stopped out on the sweep.

```python
def liquidity_aware_stop(zone_distal, ath_or_atl, direction, ticks_above=10, tick_size=0.25):
    """
    For shorts near ATH (longs near ATL), use the more conservative of:
      - zone distal stop, or
      - ATH/ATL + buffer.
    """
    buf = ticks_above * tick_size
    if direction == "short":
        liquidity_stop = ath_or_atl + buf
        return max(zone_distal, liquidity_stop)  # the higher (more conservative) stop
    else:  # long near ATL
        liquidity_stop = ath_or_atl - buf
        return min(zone_distal, liquidity_stop)  # the lower (more conservative) stop
```

The R:R math may force a smaller position size, but surviving the liquidity sweep is the priority — a swept-out stop at the actual reversal point is the worst possible outcome.

### Breakeven Trigger — Two Variants

| Variant | Trigger | Used by | When to choose |
|---------|---------|---------|----------------|
| **Half-target BE** (preferred) | Price covers 50% of the distance from entry to T1 | Bernd's live Funded Trader sessions | Default. Locks in protection earlier without giving up T1+ R-multiple. Best for volatile setups where price often pulls back after touching the half-way point |
| **T1 BE** (conservative) | Price reaches T1 (1R) | Textbook OTC 2025 | Lower drawdown protection but cleaner exits. Use when zones are very tight or when expecting a clean 2-3R move |

The Python implementation uses **half-target BE by default** with the toggle `stop_loss.breakeven_at_half_target` in `BP_config.yaml`. Set to `false` to revert to T1 BE.

---

## R-Multiple Target System

All targets are calculated as multiples of the initial risk (R = distance from entry to stop).

| Target | R:R Ratio | Action | Rule Type |
|--------|-----------|--------|-----------|
| T1 | 1:1 (1R) | MOVE STOP TO BREAKEVEN | NON-NEGOTIABLE |
| T2 | 1:2 (2R) | Take 50% partial profit. Begin trailing stop. | NON-NEGOTIABLE |
| T3 | 1:3 (3R) | Take remaining position OR continue trailing | Recommended |
| T4 | 1:4 (4R) | Extended target for strong with-trend trades only | Optional |
| T5 | Price-action zone | Take remainder at next opposing supply/demand zone | Phase 6, Ch 169 |

### Multi-Target Hierarchy — Beyond Fixed R-Multiples (Phase 6, Ch 169)

Bernd: *"we have number one, we have number two, and now we have three targets. Number four is price action"* — the multi-target system extends beyond fixed R-multiples to include **opposing supply/demand zones** as discrete profit targets.

```python
def expand_targets_with_price_action(entry, stop, opposing_zones, direction):
    """
    Add opposing zones (in trade direction) as price-action targets after T3.
    """
    risk = abs(entry - stop)
    targets = {
        "T1": entry + (risk if direction == "long" else -risk),
        "T2": entry + (2*risk if direction == "long" else -2*risk),
        "T3": entry + (3*risk if direction == "long" else -3*risk),
    }
    # Targets T4+: opposing zones in trade direction beyond T3
    pa_targets = []
    for z in sorted(opposing_zones, key=lambda z: z.proximal):
        if direction == "long" and z.proximal > targets["T3"]:
            pa_targets.append(z.proximal)
        elif direction == "short" and z.proximal < targets["T3"]:
            pa_targets.append(z.proximal)
    for i, p in enumerate(pa_targets[:3]):  # cap at T6
        targets[f"T{4+i}"] = p
    return targets
```

### Target-Frame Anchoring (Phase 6, Ch 169)

Targets are anchored to the **timeframe on which the trade was conceived**, not the timeframe on which the entry was refined. Bernd: *"looking for logical levels based on the time frame that you entered the trade… entered on a weekly higher time frame and refined on the daily lower time frame"*.

If you entered on a weekly setup but refined the entry on the daily, **targets are still drawn from weekly levels** — the LTF refinement only sharpens the entry/stop, not the destination.

### LTF Opposing Zone = Trade-Management Signal, NOT Profit Target (Phase 6, Ch 186)

When the trade is entered on **HTF** (e.g. weekly), an opposing zone visible on the **LTF** (e.g. daily) is **NOT a profit target** — it is a trade-management signal. Bernd: *"trading only the lower from the lower time frame into the higher time frame… it's not this is never your profit margin… you will get a retracement a reaction of the zone and you can use it for your trade management"*.

Operational rule:
- **HTF-entered trade** + opposing **LTF zone** in path → expect a retracement at that LTF zone, do NOT exit there.
- Use the LTF zone for: tighter stop / partial profit / reduced size — NOT for full exit.
- Full exit remains at the **HTF target** (T2/T3 in R-multiples or HTF opposing zone).

This prevents premature exits during normal LTF retracements within an HTF trend.

### Gap-Fill Targets (Phase 6, Ch 186)

Price gaps in equity-index and individual-stock charts function as **discrete profit targets**. Bernd: *"you're talking about gaps right here's a gap and filled it… here's a gap we almost filled"*. Gaps tend to fill before the next major leg of the trade.

When a gap exists between current price and the next R-multiple target, treat the **gap fill price** as an interim target (T1.5 or T2.5) — take partial profit there, since reversal probability spikes at gap fill. Already documented for NQ/YM/ES; reaffirmed as a universal stock concept.

### Target Calculation

```
risk = abs(entry_price - stop_price)

# Long trades:
T1 = entry + risk
T2 = entry + 2 * risk
T3 = entry + 3 * risk
T4 = entry + 4 * risk

# Short trades:
T1 = entry - risk
T2 = entry - 2 * risk
T3 = entry - 3 * risk
T4 = entry - 4 * risk
```

### Worked Example (Long Trade)

```
entry_price = 1.1000
stop_price  = 1.0960
risk        = 1.1000 - 1.0960 = 0.0040 (40 pips)

T1 = 1.1000 + 0.0040 = 1.1040  → Move stop to breakeven (1.1000)
T2 = 1.1000 + 0.0080 = 1.1080  → Close 50%, begin trailing
T3 = 1.1000 + 0.0120 = 1.1120  → Close remainder or trail
T4 = 1.1000 + 0.0160 = 1.1160  → Extended with-trend target
```

---

## Trailing Stop Rules (After T2)

> **What the paper trader actually does (verified against `BP_paper_trader.update_positions`, 2026-09-14).**
> This section is the method. The code implements less of it:
>
> | Rule below | Code |
> |---|---|
> | Breakeven | At **0.5R** (half-way to T1) on every trade (`stop_loss.breakeven_at_half_target: true`); the T1 move is the fallback |
> | 50% partial at T2 | Yes, on **every** trade, regardless of `trade_context` |
> | Zone-based trailing (§1) | **Not wired.** `apply_zone_trailing()` is defined but nothing calls it |
> | R-based trailing (§2) | After T2 the stop trails `current_price ∓ 1R`, ratcheting; not the T-level steps in §2 |
> | Remainder | Closed at T3 |
> | Counter-trend full close at T2 (§3) | Only with `BP_TYPE_LADDERS=1` (experimental, default OFF). Sideways and anticipatory ceilings are not implemented |
>
> The OTC 2025 course teaches four ladders by trade type (M2 L4 slide `frame_001472`): trend BE 2:1 / T1 4:1 /
> T2 trail on HTF; counter-trend and sideways BE 1:1 / T1 2:1 / T2 trail on LTF or opposing LTF zone; anticipatory
> BE 1:1 / T1 4:1 / T2 trail on HTF; "If only one target, take profits at first target". The slide gives no partial
> percentages, and the 0.5R breakeven appears nowhere in the 28 lessons (it comes from live sessions).
> None of the four ladders is implemented. Exit changes cannot be scored by the goldtest (it scores Stage-1 bias), so
> they need a trade-replay measurement before any default changes.

Once T2 is hit and 50% of the position is closed, the trailing stop protocol begins for the remaining 50%.

### 1. Zone-Based Trailing (Preferred)

After T2 is hit, trail the stop to **below the most recent demand zone's distal line** (for longs) or **above the most recent supply zone's distal line** (for shorts).

- Identify the nearest zone that has formed between entry and current price.
- Place the trailing stop just beyond that zone's distal line.
- As new zones form in your favor, ratchet the stop to the newest zone.

### 2. R-Based Trailing (Fallback)

If no clear zones are visible on the LTF chart, trail in **1R increments**:

- At T2 hit: stop moves to breakeven (already done at T1).
- At T3 hit: stop moves to T1 level (locking in 1R profit).
- At T4 hit: stop moves to T2 level (locking in 2R profit).

### 3. Direction-Based Maximum Targets

The market direction context determines how far to let winners run:

| Direction | Max Target | Management Style |
|-----------|-----------|-----------------|
| **With trend** | 3R - 4R+ | Let winners run. Use trailing stop aggressively. |
| **Sideways** | Max 1:2 (T2) | Take T2 and close the full position. Do not trail. |
| **Counter-trend** | **HARD CEILING: T2 (2R)** | Close FULL position at T2. No trailing, no exceptions, no "moon-shooting." (CW43-Idx, LIVE-May) |
| **Anticipatory** | 1R to 1.5R | Lowest conviction. Take profit early. Tightest management. |

**Counter-trend T2 ceiling is NON-NEGOTIABLE**: Counter-trend moves are temporary reactions against the dominant flow. They are exhausted much faster than trend-aligned moves. Taking a counter-trend trade past T2 means giving back profits to the dominant trend's resumption. ALWAYS close full counter-trend position at T2.

**Index Short exception**: For equity index short setups, only proceed when the asset is "REALLY overvalued" — Valuation must be STRONG BEARISH (≥+75), not merely mild. A mildly bearish Valuation reading on an equity index is insufficient for a short trade. (CW18)

---

## Zone Refinement (Improving R:R Before Entry)

When the HTF zone's R:R to the next opposing zone is below the minimum (default 1:2), drop down the timeframe ladder to find a tighter zone that still fits inside the HTF zone.

### Trigger Condition

```python
htf_rr = abs(target_zone - htf_proximal) / abs(htf_proximal - htf_stop)
if htf_rr < 2.0:
    refined = refine_zone(htf_zone, target, ohlcv_by_tf, income_strategy)
```

### Drill-down Ladder by Income Strategy

| Strategy | Drill-down ladder |
|----------|-------------------|
| Monthly Income | 1mo → 1wk → 1d |
| **Weekly Income** (primary) | 1wk → 1d → 4h → 60m |
| Daily Income | 1d → 4h → 60m → 30m |
| Intraday | 4h → 60m → 30m → 15m |

### Containment Requirement

The refined LTF zone MUST sit ENTIRELY INSIDE the HTF zone's price range (LTF.proximal–distal both within HTF.proximal–distal). This is the same Big Brother / Small Brother rule from `01_zone_detection.md`.

### Independent Qualifier Pass

The refined zone must independently pass qualifier checks (composite ≥ 6.0). A wide HTF zone does NOT confer quality on every LTF zone within it — each must earn its score.

### Stop Placement on Refined Zone

| Mode | Formula | When to use |
|------|---------|-------------|
| **Default (textbook)** | `LTF.distal − 0.33 × LTF.height` | Standard. Tighter R:R, smaller risk per trade. |
| **Conservative** | `HTF.distal − 0.33 × HTF.height` | When LTF is very tight and likely to wick out. Looser stop, lower R:R but more protection. |

### When to Stop Drilling

- Don't drill below 60-min for weekly-income trades — noise dominates
- Don't drill below 15-min for any strategy
- Stop when the refined zone is so tight that the spread approaches the entry-stop distance

Implementation: `BP_rules_engine.refine_zone()`. See OTC L7-L8 + Hybrid AI Module 6 Lesson 6 for live walkthroughs.

### The Three-Way Trade-Off of Refinement (Phase 6, Ch 175)

Refining to a tighter LTF zone is not a free lunch. Bernd: *"the profit margin the lower you go as much higher but obviously the probability to get filled is less and also the probability to get stopped out is higher"*.

| Going deeper into refinement | Effect |
|------------------------------|--------|
| **R:R** | ↑ Increases (tighter stop) |
| **Fill probability** | ↓ Decreases (price may reverse before reaching the LTF proximal) |
| **Stop-out probability** | ↑ Increases (less buffer for noise) |

**Net expected value** depends on whether the R:R gain compensates for both lower fill rate and higher stop-out rate. Default: refine ONLY when HTF R:R is below 1:2 — otherwise the HTF entry is the better expected-value choice.

### Refinement Workflow — Delete and Restart (Phase 6, Ch 184)

When refining to a lower TF, **do not annotate over the HTF chart** — switch to the LTF, **delete all HTF zones from the LTF view**, and re-zone from scratch using LTF candle data. Bernd's process: *"if I want to refine it on the daily chart, I really can't choose how to refine it"* → he then walks through clearing the chart and starting fresh on the daily.

This prevents HTF-zone bias from contaminating LTF zone identification.

### Hold-Time Quantified (Phase 6, Ch 185)

Long-term holds quantified in concrete bar counts:

| Strategy | Long-term hold ceiling |
|----------|------------------------|
| Monthly Income | up to 2 years |
| Weekly Income | up to 4 weekly candles (~1 month) |
| Daily Income | up to 20 daily candles (~1 month) |
| Intraday | session-to-multi-session |

Bernd: *"long term… up to two years up to four weekly candles or 20 daily candles"*.

If a trade has not hit T2 by these ceilings, the setup has degraded and the trade should be reviewed — typically closed for whatever has been earned.

---

## Position Sizing

Position sizing is risk-based. Every trade risks the same percentage of the account regardless of the instrument or setup quality.

```
account_balance = 100000  # example
risk_percentage = 0.01    # ALWAYS 1% (max 2%)
risk_amount = account_balance * risk_percentage  # = $1,000
stop_distance = abs(entry_price - stop_price)
position_size = risk_amount / stop_distance
```

### Worked Example

```
Account Balance:  $100,000
Risk Percentage:  1%
Risk Amount:      $1,000
Entry Price:      1.1000
Stop Price:       1.0960
Stop Distance:    0.0040 (40 pips)

Position Size = $1,000 / 0.0040 = 250,000 units (2.5 standard lots)
```

### Position Sizing Rules

| Rule | Value |
|------|-------|
| Risk per trade | EXACTLY 1% of account (standard) |
| Maximum risk per trade | 2% (highest-conviction setups ONLY) |
| Maximum concurrent positions | 2-3, must be UNCORRELATED |
| Minimum R:R ratio | 1:2 for ALL trades, no exceptions |
| R:R gate | If R:R < 1:2, do NOT take the trade regardless of zone quality |
| **Anticipatory / counter-trend** | **Reduce to 0.5% risk** — lower conviction = lower exposure |
| **High-impact calendar events (CPI, NFP, FOMC)** | **Reduce to 0.5% risk** or skip entirely until post-announcement zones form |
| **Prop firm challenge accounts** | Weekly timeframe NOT recommended — wide weekly stops conflict with challenge drawdown limits. Use Daily + 4H setups |

### Equity Basket Mode (Correlated Indices Exception)

When NQ, ES, and YM are ALL aligned in the same direction simultaneously AND each individually passes the bias consensus (Location + Valuation minimum, per Bernd's hierarchy):

```
# Standard rule: 1% per trade (would be 3% total = too concentrated)
# Equity basket exception: treat as ONE correlated direction
# Total risk budget = 3% spread across ≤3 positions

basket_risk_per_position = 0.03 / num_positions  # = 1% each if 3 positions
# Each position individually sized to its own stop distance but capped at 1% each
# The 3% TOTAL is the budget limit, not 1% × 3 = 3% per trade independently

# Code implementation:
def calculate_basket_position_sizes(positions, account_balance, total_budget_pct=0.03):
    """Allocate total basket budget across correlated equity index positions."""
    budget_per_position = (account_balance * total_budget_pct) / len(positions)
    return [budget_per_position / abs(p.entry - p.stop) for p in positions]
```

This is the ONLY exception to the uncorrelated-positions rule. Index correlation is acknowledged and managed via the basket budget rather than prohibited.

### Correlation Check

Before opening a new position, verify it is not correlated with existing open trades:

- EUR/USD and GBP/USD are correlated (both vs USD) — counts as ONE direction
- Gold and Silver are correlated — counts as ONE direction
- NQ + ES + YM = correlated equity basket (see above for basket mode)
- If two open trades move in the same direction due to the same driver, reduce size on the second trade or skip it entirely

---

## Partial Profit Execution

At T2 (2R), execute the following sequence exactly:

1. **Close exactly 50%** of the position at the T2 price level
2. **Move stop to breakeven** on the remaining 50% (should already be at breakeven from T1)
3. **Begin trailing stop protocol** (zone-based or R-based)
4. **Record partial PnL separately** in the trade journal

### Why 50% at T2?

- Locks in 1R of guaranteed profit on the closed portion
- The remaining 50% rides at zero risk (stop at breakeven)
- Psychological relief allows the remaining position to run without emotional interference
- Combined outcome at T2 close: 50% x 2R = 1R locked profit

---

## Set-and-Forget Execution

The Blueprint system is designed for **set-and-forget** execution to remove emotional interference.

### Execution Protocol

1. Place **entry limit order** at the zone (proximal line or within the zone per entry option)
2. Place **stop loss** at -33% Fibonacci extension simultaneously
3. Place **take-profit orders** at T1, T2, and T3 levels simultaneously
4. **Do NOT watch the trade tick by tick**
5. Only intervene at these two moments:
   - **T1 hit**: Move stop to breakeven
   - **T2 hit**: Close 50%, begin trailing
6. Between these events, do not touch the trade

### Key Mindset Rules

- "We have to learn to live with" missed entries — **NEVER chase price**
- If price blows through the zone without filling the limit order, accept it and move on
- If the trade moves against you, let the stop do its job
- Watching tick-by-tick leads to premature exits and emotional decisions

---

## Daily/Account Risk Limits

### Daily Loss Limit

| Limit | Value | Action |
|-------|-------|--------|
| Maximum daily loss | 5% of account balance | Stop trading for the entire day |
| Consecutive loss threshold | 3 losses in a row | Pause trading and review methodology compliance |

### Drawdown Management

- Track **peak-to-trough** equity drawdown continuously
- If drawdown exceeds your predefined limit (e.g., 10%), reduce position size by 50%
- Resume normal sizing only after recovering to within 5% of equity peak
- Never increase size to "make back" losses — this is the fastest path to account blowup

### Post-Loss Protocol

After 3 consecutive losses:

1. **Stop trading immediately**
2. Review each losing trade against the 7-step process
3. Check: Were zones valid? Did fundamentals align? Was entry at the zone?
4. If all 3 trades followed the system perfectly, resume trading — losses are normal
5. If any trade violated the system, identify the violation and correct before resuming
6. Consider reducing size to 0.5% risk until confidence returns

---

## Summary: Trade Management Checklist

```
PRE-TRADE:
[ ] Valuation hard gate checked — trade direction NOT vetoed by Valuation
[ ] Stop mode determined: LTF/pattern entry (-33% Fib) OR HTF weekly entry (distal only)
[ ] Stop calculated per correct mode
[ ] Position size = risk_pct% / stop distance (0.5% if counter-trend/anticipatory/high-impact event)
[ ] R:R verified >= 1:2
[ ] Entry, stop, and TP orders placed simultaneously
[ ] For counter-trend: T2 order set as FULL CLOSE (not 50% partial)
[ ] For equity basket: verify total basket risk <= 3%

DURING TRADE:
[ ] At half-T1 distance: Stop moved to breakeven (preferred) OR at T1 (conservative)
[ ] At T2 (2R): 50% position closed (or 100% if counter-trend), trailing begun
[ ] At T3 (3R): Remainder closed OR trailing continues (with-trend only)
[ ] No tick-by-tick watching between events

POST-TRADE:
[ ] Partial PnL recorded separately
[ ] R-multiple outcome logged
[ ] Daily loss limit checked (< 5%)
[ ] Consecutive loss count updated
```
