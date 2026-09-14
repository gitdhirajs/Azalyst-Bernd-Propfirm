# 6 Zone Qualifiers — Complete Scoring System

## Overview

Every detected zone must pass through a 6-qualifier scoring system before it is considered tradeable. Three qualifiers are **MUST PASS gates** — if any gate scores 0, the zone is rejected regardless of the composite score.

### Composite Formula

```
composite = (Q1_departure * 0.30) +
            (Q2_base_duration * 0.10) +
            (Q3_freshness * 0.15) +
            (Q4_originality * 0.15) +
            (Q5_profit_margin * 0.10) +
            (Q6_arrival * 0.10) +
            (LOL_bonus * 0.10)
```

**Minimum composite for trade entry: 4.0** (out of approximately 10 maximum)

### MUST PASS Gates

| Gate | Qualifier | Failure Condition |
|------|-----------|-------------------|
| Gate 1 | Q1 Departure | Score = 0 (indecisive leg-out) |
| Gate 2 | Q2 Base Duration | Score = 0 (7+ base candles) |
| Gate 3 | Q5 Profit Margin | Score = 0 (counter-trend only, < 2x zone height) |

```python
def zone_passes_gates(q1, q2, q5, is_counter_trend):
    if q1 == 0:
        return False  # Indecisive leg-out = zone fails
    if q2 == 0:
        return False  # Extended base = zone fails
    if is_counter_trend and q5 == 0:
        return False  # No profit margin for counter-trend = zone fails
    return True
```

---

## Q1: DEPARTURE (Weight: 30%) — MUST PASS

Measures the quality of the leg-out (the explosive move away from the base). This is the single most important qualifier, weighted at 30% of the composite.

### What It Measures

The leg-out proves that institutional orders were placed in the base. A weak departure means weak institutional commitment — the zone has low probability of holding on retest.

### Scoring Criteria

| Score | Condition | Description |
|-------|-----------|-------------|
| **10** | `avg_body_pct >= 0.70` AND candle range >= 2x avg range | Explosive candles, abnormally larger than surrounding candles |
| **7** | `avg_body_pct` between 0.60 and 0.70 | Very decisive but not explosive |
| **5** | `avg_body_pct` between 0.50 and 0.60 | Decisive, minimum acceptable quality |
| **0** | `avg_body_pct <= 0.50` | **ZONE FAILS** — indecisive leg-out, no institutional conviction |

### Implementation

```python
def score_departure(legout_candles, avg_range_20):
    """
    Score Q1 Departure based on leg-out candle quality.
    
    Args:
        legout_candles: list of candles in the leg-out
        avg_range_20: average candle range over prior 20 candles
    
    Returns:
        int: score 0-10
    """
    if not legout_candles:
        return 0
    
    body_pcts = []
    ranges = []
    for c in legout_candles:
        r = c.high - c.low
        if r == 0:
            body_pcts.append(0)
        else:
            body_pcts.append(abs(c.close - c.open) / r)
        ranges.append(r)
    
    avg_body_pct = sum(body_pcts) / len(body_pcts)
    avg_legout_range = sum(ranges) / len(ranges)
    size_ratio = avg_legout_range / avg_range_20 if avg_range_20 > 0 else 0
    
    if avg_body_pct <= 0.50:
        return 0   # MUST PASS GATE FAIL
    elif avg_body_pct >= 0.70 and size_ratio >= 2.0:
        return 10  # Explosive + abnormally large
    elif avg_body_pct >= 0.70 and size_ratio >= 1.5:
        return 9   # Explosive but not extreme size
    elif avg_body_pct >= 0.60:
        return 7   # Very decisive
    else:
        return 5   # Decisive (0.50 < body_pct < 0.60)
```

---

## Q2: BASE DURATION (Weight: 10%) — MUST PASS

Measures how tight the base (consolidation) is. Fewer candles = tighter base = more unfilled orders = higher probability.

### What It Measures

The base is where institutional orders accumulate. A tight base (1-2 candles) means rapid accumulation with minimal price discovery — institutions moved quickly, leaving many unfilled orders. An extended base (7+) means orders were gradually filled during the consolidation — nothing left for price to react to on retest.

### Scoring Criteria

| Score | Base Candles | Description |
|-------|-------------|-------------|
| **10** | 1-2 | Tightest base — least risk, fastest turnaround, maximum unfilled orders |
| **7** | 3-4 | Good base — moderate accumulation period |
| **4** | 5-6 | Acceptable but wide — more orders filled during basing |
| **0** | 7+ | **ZONE FAILS** — orders filled during extended basing, zone invalid |

### Implementation

```python
def score_base_duration(base_candle_count):
    """
    Score Q2 Base Duration.
    
    Args:
        base_candle_count: number of indecisive candles in the base
    
    Returns:
        int: score 0-10
    """
    if base_candle_count <= 0:
        return 0  # No base found
    elif base_candle_count <= 2:
        return 10
    elif base_candle_count <= 4:
        return 7
    elif base_candle_count <= 6:
        return 4
    else:
        return 0  # MUST PASS GATE FAIL: 7+ candles
```

---

## Q3: FRESHNESS (Weight: 15%)

Measures how many unfilled orders remain at the zone. Each retest consumes some of the residual orders.

### What It Measures

A fresh zone (never tested) has 100% of its unfilled institutional orders intact. Each time price returns to the zone, some orders get filled, reducing the zone's ability to repel price on the next visit.

### Scoring Criteria

| Score | Condition | Description |
|-------|-----------|-------------|
| **10** | 0 retests (fresh) | Never tested — all unfilled orders intact |
| **7** | Wider version tested only | Wicks touched the zone but bodies held above/below proximal |
| **3** | Preferred version tested | Bodies broke into the zone but price ultimately held |
| **Degrading** | Multiple retests | Formula: `score = 10 / (retests + 1)` |
| **0 — INVALIDATED** | >25% penetration | Zone is consumed/dead; do NOT trade |

### CRITICAL: 25% Penetration Invalidation Rule

**AUDIT CORRECTION (Phase 6, Ch 184)**: Bernd states explicitly: *"the bottom zone is taking out because the zone is was tested more than 25%"*. A zone that has been penetrated by **more than 25% of its range** is INVALIDATED — Q3 = 0 and the zone is removed from the tradeable list. The retest formula `10/(retests+1)` applies ONLY to tests that did NOT exceed 25% penetration.

```python
def is_zone_invalidated(zone, candle_history):
    """
    A zone is INVALIDATED when price has penetrated >25% into its range.
    Penetration % = how deep into the zone (proximal->distal direction) price went.
    """
    zone_range = abs(zone.proximal - zone.distal)
    threshold_25 = zone.proximal + 0.25 * (zone.distal - zone.proximal)  # demand
    # for supply, threshold_25 = zone.proximal - 0.25 * (zone.proximal - zone.distal)
    for candle in candle_history:
        if zone.zone_type == "demand":
            if candle.low < threshold_25:  # body or wick penetrated >25%
                return True
        else:  # supply
            if candle.high > threshold_25:
                return True
    return False
```

**Why**: Beyond 25% penetration the institutional order block has been substantially consumed. Even if price wicked back out, the zone no longer carries the full unfilled-order weight. The 25% rule is a HARD invalidation gate — it overrides Q3 scoring entirely.

### Retest Detection Logic

```python
def count_retests(zone, candle_history):
    """
    Count how many times price has revisited the zone since formation.
    
    A retest occurs when price enters the proximal-to-distal range.
    Distinguish between wick-only tests and body tests.
    """
    retests = 0
    body_tests = 0
    wick_tests = 0
    
    for candle in candle_history:
        if zone.zone_type == "demand":
            # Wick test: low touches zone but body stays above proximal
            if candle.low <= zone.proximal and candle.low >= zone.distal:
                if min(candle.open, candle.close) > zone.proximal:
                    wick_tests += 1
                else:
                    body_tests += 1
                retests += 1
        else:  # supply
            if candle.high >= zone.proximal and candle.high <= zone.distal:
                if max(candle.open, candle.close) < zone.proximal:
                    wick_tests += 1
                else:
                    body_tests += 1
                retests += 1
    
    return retests, wick_tests, body_tests


def score_freshness(retests, wick_tests, body_tests, zone, candle_history):
    """
    Score Q3 Freshness.

    Returns:
        float: score 0-10 (0 = INVALIDATED — do not trade)
    """
    # P1 HARD GATE (Phase 6, Ch 184): >25% penetration invalidates the zone outright.
    if is_zone_invalidated(zone, candle_history):
        return 0.0

    if retests == 0:
        return 10.0  # Completely fresh

    # If only wicks touched (wider version tested), partial credit
    if body_tests == 0 and wick_tests > 0:
        return max(7.0 / wick_tests, 1.0)

    # Body tests reduce score more aggressively
    return max(10.0 / (retests + 1), 0.5)
```

### Freshness Degradation Table

| Total Retests | Score | Quality Assessment |
|---------------|-------|--------------------|
| 0 | 10.0 | Fresh — highest probability |
| 1 (wick only) | 7.0 | Wider tested — still strong |
| 1 (body test) | 5.0 | Preferred tested — acceptable |
| 2 | 3.3 | Weakening — reduce position size |
| 3 | 2.5 | Stale — consider skipping |
| 4+ | < 2.0 | Exhausted — avoid |

### Preferred-Version Touch as Active Entry Trigger (Phase 6, Ch 156)

The wider/preferred distinction is not just a SCORING input — Bernd uses it as an active **entry trigger**: *"wider version hit already, but if we get into that weekly in the preferred version"*.

Operational rule:
1. If price has tagged the **wider** version of the zone (wicks only, no body close inside) and reversed, that test is **consumed** as a wider-only test (Q3 = 7).
2. The **preferred** version (the inner/tighter zone boundary at the body extremes of the base) is now the **active trigger** for entry — wait for price to return to the preferred version before placing the order.
3. Pre-emptively entering at the wider version after it has already been touched once = lower-quality entry (you are effectively playing a 2nd test of the wider zone, not a 1st test of the preferred zone).

This promotes the wider/preferred distinction from a passive scoring multiplier to an active **wait-for-preferred** entry gate.

---

## Q4: ORIGINALITY (Weight: 15%)

Measures the formation type and its implied institutional intent.

### What It Measures

Original formations (continuation patterns) indicate institutional accumulation or distribution — adding to existing positions during a trend. Non-original formations (reaction patterns) indicate reversals where institutions react to opposing pressure. Flip zones represent trapped institutional positions.

### Scoring Criteria

| Score | Formation | Description |
|-------|-----------|-------------|
| **12** | Flip Zone | Former demand becoming supply or vice versa — strongest institutional footprint |
| **10** | RBR, DBD (Original) | Continuation patterns — institutional accumulation/distribution |
| **5** | DBR, RBD (Non-Original) | Reaction patterns — weaker institutional intent |

### Implementation

```python
def score_originality(formation, is_flip_zone=False):
    """
    Score Q4 Originality.
    
    Args:
        formation: one of "RBR", "DBD", "DBR", "RBD", "FLIP"
        is_flip_zone: True if this zone is a flipped former zone
    
    Returns:
        int: score 5-12
    """
    if is_flip_zone or formation == "FLIP":
        return 12  # Exceeds normal maximum
    elif formation in ("RBR", "DBD"):
        return 10  # Original / continuation
    elif formation in ("DBR", "RBD"):
        return 5   # Non-original / reaction
    else:
        return 0   # Unknown formation
```

---

## Q5: PROFIT MARGIN (Weight: 10%) — MUST PASS (Counter-Trend Only)

Measures the distance price traveled away from the zone before returning. This determines if there is sufficient reward potential.

### What It Measures

After the leg-out creates the zone, price travels some distance before returning. If price only moved a short distance, the reward-to-risk ratio is insufficient, especially for counter-trend trades.

### Scoring Criteria

| Score | Distance (multiples of zone height) | Description |
|-------|--------------------------------------|-------------|
| **10** | >= 5x zone height | Excellent margin — strong institutional move |
| **7** | >= 3x zone height | Good margin — Hybrid AI M4 L1 Pt 3 (0:40:45): the *conservative* rule, "minimum of 1 to 3 away from the zone before price comes back, regardless of trend" |
| **5** | >= 2x zone height | Acceptable margin — the floor: "profit margin of at least bigger than 1 to 2" (same lesson, 0:46:21) |
| **0** | < 2x zone height | **ZONE FAILS** (counter-trend only) — insufficient reward |

> **Doc sync 2026-09-05**: this table now matches `BP_zone_detector.py` (10/7/5 at 5×/3×/2×, else 0; gate applies when `with_trend is False`). The earlier "3 at ≥1.5×" tier and "<1×" fail line never existed in code. Note `BP_config.yaml: profit_margin_min_ratio: 3.0` is read into `ZoneDetector.profit_margin_min` but **never used** — the thresholds are the literals above. With-trend zones score 10 unconditionally ("it really doesn't matter", Hybrid AI M4 L1 Pt 3).

### MUST PASS Gate

- **Counter-trend trades**: Score = 0 means ZONE FAILS. There must be meaningful distance.
- **With-trend trades**: Score = 0 is allowed (zone does not fail), but composite will be lower.

### Implementation

```python
def score_profit_margin(zone, price_data_after_zone):
    """
    Score Q5 Profit Margin.
    
    Measures how far price traveled from the zone before returning.
    
    Args:
        zone: the Zone object
        price_data_after_zone: OHLCV data from zone formation to current price
    
    Returns:
        int: score 0-10
    """
    zone_height = abs(zone.proximal - zone.distal)
    if zone_height == 0:
        return 0
    
    if zone.zone_type == "demand":
        # How far up did price go after the demand zone formed?
        max_price = max(c.high for c in price_data_after_zone)
        distance = max_price - zone.proximal
    else:  # supply
        # How far down did price go after the supply zone formed?
        min_price = min(c.low for c in price_data_after_zone)
        distance = zone.proximal - min_price
    
    ratio = distance / zone_height
    
    if ratio >= 5.0:
        return 10
    elif ratio >= 3.0:
        return 7
    elif ratio >= 2.0:
        return 5
    else:
        return 0  # MUST PASS GATE FAIL (counter-trend) — matches BP_zone_detector.py


def check_profit_margin_gate(q5_score, is_counter_trend):
    """Check if Q5 passes the MUST PASS gate."""
    if is_counter_trend and q5_score == 0:
        return False
    return True
```

---

## Q6: ARRIVAL (Weight: 10%)

Measures how price returns to the zone. Only scored for sideways and counter-trend trades.

### What It Measures

The manner in which price returns to a zone affects the probability of a successful trade. A fast, clean impulse back to the zone means fewer opposing orders were placed during the return — the zone is more likely to hold. A slow, stair-stepping return creates opposing zones (speed bumps) that can block the trade.

### Scoring Criteria

| Score | Arrival Type | Description |
|-------|-------------|-------------|
| **10** | Fast / clean impulse | Single directional move, no opposing zones created in the return path |
| **5** | Slow / stair-stepping | Leaves speed-bump zones on the return — opposing supply zones for demand, opposing demand zones for supply |
| **0** | Blocked | Adjacent opposing zone directly blocks the path to entry |

### When to Score

| Trade Context | Score Arrival? |
|---------------|---------------|
| With-trend | **NO** — skip entirely (not applicable) |
| Sideways | YES |
| Counter-trend | YES |

### Implementation

```python
def score_arrival(zone, return_candles, all_active_zones, trade_context):
    """
    Score Q6 Arrival.
    
    Args:
        zone: the target Zone being tested
        return_candles: candles from the furthest point back to zone
        all_active_zones: list of all currently valid zones
        trade_context: "with_trend", "sideways", or "counter_trend"
    
    Returns:
        int: score 0-10, or None if not applicable
    """
    if trade_context == "with_trend":
        return None  # Not scored for with-trend trades
    
    # Check for opposing zones in the return path
    opposing_zones_in_path = []
    for oz in all_active_zones:
        if oz == zone:
            continue
        # For a demand zone, check if supply zones sit between current price and zone
        if zone.zone_type == "demand" and oz.zone_type == "supply":
            if oz.proximal > zone.proximal:  # Supply zone above demand
                opposing_zones_in_path.append(oz)
        elif zone.zone_type == "supply" and oz.zone_type == "demand":
            if oz.proximal < zone.proximal:  # Demand zone below supply
                opposing_zones_in_path.append(oz)
    
    # Check if any opposing zone is adjacent (directly blocking)
    for oz in opposing_zones_in_path:
        zone_gap = abs(oz.proximal - zone.proximal)
        if zone_gap < abs(zone.proximal - zone.distal) * 0.5:
            return 0  # Adjacent opposing zone blocks path
    
    # Analyze return candle structure
    # Count how many small bases/consolidations occurred during return
    consolidation_count = 0
    consecutive_indecisive = 0
    for c in return_candles:
        body_pct = abs(c.close - c.open) / (c.high - c.low) if (c.high - c.low) > 0 else 0
        if body_pct <= 0.50:
            consecutive_indecisive += 1
            if consecutive_indecisive >= 2:
                consolidation_count += 1
                consecutive_indecisive = 0
        else:
            consecutive_indecisive = 0
    
    if consolidation_count == 0 and len(opposing_zones_in_path) == 0:
        return 10  # Clean impulse return
    elif consolidation_count <= 2 and len(opposing_zones_in_path) <= 1:
        return 5   # Slow / stair-stepping
    else:
        return 2   # Heavily congested return
```

---

## LOL BONUS: Level-on-Top-of-Level (Weight: 10%, Max 5 Points)

Bonus points when multiple zones from different timeframes stack at the same price level.

### What It Measures

When a zone on one timeframe aligns with a zone on a different timeframe at the same price, the combined unfilled order pool is significantly larger. This dramatically increases the probability of price reacting at that level.

### Scoring

| Condition | Points |
|-----------|--------|
| Two zones from different timeframes overlap | +3 |
| Three or more zones overlap | +5 (max) |
| No overlap | +0 |

### Three Entry Options for LOL Setups

| Option | Entry | Stop | Description |
|--------|-------|------|-------------|
| **Option 1** | First (nearest) proximal | Below second (deeper) distal | Combine levels — enter at closest zone, stop protects both |
| **Option 2** | Wider version of deeper level | Below deeper level's distal | Enter at the more significant deeper zone |
| **Option 3** | Skip first level entirely | Full position at deeper level | Wait for deeper fill — best R:R if it fills |
| **Option 4** (Phase 6, Ch 177) | Upper area only (supply) / Lower area only (demand) of the wide LOL range | Beyond the chosen sub-zone's distal | When full LOL range yields R:R < 2:1, trade only the favourable sub-area to recover R:R |

**Option 4 — Trade-Upper-Area-Only sub-option**: Bernd: *"we only trade the upper area"* — when the LOL spans a wide composite range and the full-range entry yields R:R below the 2:1 minimum, slice the LOL into upper/lower halves and trade only the half closest to the next opposing zone (upper half for supply, lower half for demand). Stop tightens accordingly; R:R is recovered at the cost of giving up the deeper-fill scenario.

### Implementation

```python
def score_lol(zone, all_zones_all_timeframes):
    """
    Score LOL (Level on Level) bonus.
    
    Args:
        zone: the target zone
        all_zones_all_timeframes: dict of {timeframe: [Zone, ...]}
    
    Returns:
        int: 0, 3, or 5
    """
    overlapping_tf_count = 0
    zone_tf = zone.timeframe
    
    for tf, zones in all_zones_all_timeframes.items():
        if tf == zone_tf:
            continue  # Skip same timeframe
        
        for other_zone in zones:
            if other_zone.zone_type != zone.zone_type:
                continue  # Must be same type (both demand or both supply)
            
            # Check for price overlap
            if zone.zone_type == "demand":
                overlap = (other_zone.distal <= zone.proximal and 
                          other_zone.proximal >= zone.distal)
            else:
                overlap = (other_zone.proximal <= zone.distal and 
                          other_zone.distal >= zone.proximal)
            
            if overlap:
                overlapping_tf_count += 1
                break  # Count each timeframe only once
    
    if overlapping_tf_count >= 2:
        return 5   # Three or more timeframes
    elif overlapping_tf_count == 1:
        return 3   # Two timeframes
    else:
        return 0   # No LOL
```

---

## Complete Scoring Pipeline

```python
def score_zone(zone, candle_history, all_active_zones, all_zones_all_tf,
               price_data_after_zone, return_candles, avg_range_20,
               trade_context, is_flip_zone=False):
    """
    Complete zone scoring pipeline.
    
    Returns:
        dict with individual scores, composite score, and pass/fail status
    """
    # Score each qualifier
    q1 = score_departure(zone.legout_candles, avg_range_20)
    q2 = score_base_duration(zone.base_count)
    
    retests, wick_tests, body_tests = count_retests(zone, candle_history)
    q3 = score_freshness(retests, wick_tests, body_tests)
    
    q4 = score_originality(zone.formation, is_flip_zone)
    q5 = score_profit_margin(zone, price_data_after_zone)
    
    q6_raw = score_arrival(zone, return_candles, all_active_zones, trade_context)
    q6 = q6_raw if q6_raw is not None else 10  # Default 10 if not applicable
    
    lol = score_lol(zone, all_zones_all_tf)
    
    # Check MUST PASS gates
    is_counter_trend = (trade_context == "counter_trend")
    
    gate_pass = True
    fail_reason = None
    
    if q1 == 0:
        gate_pass = False
        fail_reason = "Q1 DEPARTURE FAIL: Indecisive leg-out"
    elif q2 == 0:
        gate_pass = False
        fail_reason = "Q2 BASE DURATION FAIL: 7+ base candles"
    elif is_counter_trend and q5 == 0:
        gate_pass = False
        fail_reason = "Q5 PROFIT MARGIN FAIL: Insufficient margin for counter-trend"
    
    # Calculate composite
    composite = (q1 * 0.30) + (q2 * 0.10) + (q3 * 0.15) + \
                (q4 * 0.15) + (q5 * 0.10) + (q6 * 0.10) + (lol * 0.10)
    
    # Final tradeable determination
    is_tradeable = gate_pass and composite >= 4.0
    
    return {
        "q1_departure": q1,
        "q2_base_duration": q2,
        "q3_freshness": q3,
        "q4_originality": q4,
        "q5_profit_margin": q5,
        "q6_arrival": q6,
        "lol_bonus": lol,
        "composite": round(composite, 2),
        "gate_pass": gate_pass,
        "fail_reason": fail_reason,
        "is_tradeable": is_tradeable,
        "trade_context": trade_context
    }
```

---

## Scoring Summary Table

| Qualifier | Weight | MUST PASS | Score Range | Fail Condition |
|-----------|--------|-----------|-------------|----------------|
| Q1 Departure | 30% | YES | 0, 5, 7, 10 | body_pct <= 0.50 |
| Q2 Base Duration | 10% | YES | 0, 4, 7, 10 | 7+ candles |
| Q3 Freshness | 15% | No | 0.5 - 10.0 | Degrades per retest |
| Q4 Originality | 15% | No | 5, 10, 12 | N/A (always scores) |
| Q5 Profit Margin | 10% | YES (counter-trend) | 0, 5, 7, 10 | < 2x zone height |
| Q6 Arrival | 10% | No | 0, 5, 10 | Blocked path |
| LOL Bonus | 10% | No | 0, 3, 5 | No overlap |

**Maximum theoretical composite**: approximately 10.7 (with flip zone originality at 12 and LOL at 5)

**Minimum for trade**: 4.0
