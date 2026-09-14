# Supply & Demand Zone Detection — Complete Algorithm

## 1. Candle Classification (Foundation)

Every candle in the market is classified by its **body-to-range ratio**. This single metric determines whether a candle represents indecision or conviction.

### Formula

```
body_pct = abs(close - open) / (high - low)
```

If `high == low` (zero-range candle / doji), set `body_pct = 0`.

### Classification Table

| Classification | Body % Threshold | Role in Zone | Description |
|----------------|-----------------|--------------|-------------|
| **Indecisive** | `body_pct <= 0.50` | BASE candle | Buyers and sellers in equilibrium. Unfilled institutional orders accumulate here. |
| **Decisive** | `body_pct > 0.50` | LEG-IN candle | One side winning. Directional momentum present. |
| **Explosive** | `body_pct >= 0.70` | LEG-OUT candle | Strong institutional conviction. **REQUIRED** for a valid zone. |

### Direction

```
direction = "bullish" if close > open else "bearish"
```

For doji candles (`close == open`), direction is neutral and the candle is always classified as indecisive/base.

### Where `BP_zone_detector.py` differs from this section (verified 2026-09-14)

Lecture column cites the OTC 2025 course frames (`D:\Trading\Output\Bernd_Skorupinski Campus Blueprint OTC\…\4. Module 2 Supply and Demand\`), checked 2026-09-14.

| Rule | OTC 2025 lectures (frame) | Code today | Experimental flag (default OFF) |
|---|---|---|---|
| Explosive | L2 slide `frame_000090`: "body **> 70%** of range, abnormally bigger than previous candles". Narration at 0:04:47 says "at least 70%" — the lesson is inconsistent; only a body of exactly 70% differs | `>= 0.70` (detection and Q1 score) | `BP_EXPLOSIVE_STRICT=1` |
| Leg-in | L2 rule card `frame_000403`: "Made of **a** decisive / explosive candle" — no minimum count | ≥ 70% of the `leg_in_min_candles + 1` (= 4) candles in the leg's direction; decisiveness not checked | `BP_LEGIN_DECISIVE=1` (run of ≥ 1 decisive candles) |
| Base maximum | Inconsistent: L6 table `frame_000575` Great 1–3 / Acceptable 4–6 / Not acceptable >6; L6 cheat sheet `frame_002069` "Approx. 1 - 5 candles" | `base_max_candles: 5`; a 6-candle base is never detected | `BP_BASE_MAX6=1` |
| Leg-out / departure | LTF: "explosive candle" **or** "decisive candle (abnormally bigger) followed by another decisive candle"; HTF (location zones): "Decisive candle (abnormally bigger)" (L6 `frame_000251`, L2 `frame_000403`) | Explosive candle or gap required on every timeframe; neither alternative is implemented | — (not yet built) |
| Explosive first leg-out candle | Valid for every formation | DBR rejects it (`leg_out_end <= leg_out_start`); RBR/RBD/DBD accept it | `BP_DBR_LEGOUT_FIX=1` |
| Freshness | L6 `frame_001125`: LTF beginners no test of wider, advanced no test of preferred; **HTF** may be tested ~25% of preferred | 25% penetration rule applied on every timeframe | — |
| Doji direction | Neutral | `np.where(close > open, 1, -1)` counts a doji as bearish | — |
| Gap as leg-out | Not in the OTC 2025 lessons (Ch.171 is a Practical Application session) | Implemented | — |

Flag results are in `RECONCILE_REPORT_2026-09-14.md`. Keep the code as-is unless a paired A/B on the
pinned out-of-sample set shows a gain.

---

## 2. Zone Anatomy

Every valid supply/demand zone consists of exactly three components in sequence:

```
[LEG-IN] → [BASE] → [LEG-OUT]
```

### Leg-In (Arrival Momentum)

- **Minimum**: 3 consecutive candles moving in the same direction
- **Candle quality**: Each candle must be decisive (`body_pct > 0.50`)
- **Direction**: All candles must share the same directional bias (all bullish or all bearish)
- **Importance**: Less critical than leg-out. Shows momentum arriving at the zone but does not determine zone validity on its own.

### Base (Institutional Accumulation / Distribution)

- **Candle quality**: ALL candles must be indecisive (`body_pct <= 0.50`)
- **Minimum**: 1 candle
- **Maximum**: 6 candles
- **7+ candles = ZONE INVALID** — extended basing means institutional orders have been filled during the consolidation; no unfilled orders remain for price to return to
- **Tighter is stronger**: 1-2 base candles indicate rapid institutional activity with minimal price discovery — highest quality zones

### Leg-Out (MOST CRITICAL Component)

- **Candle quality**: Must contain explosive candles (`body_pct >= 0.70`)
- **Size requirement**: Candles must be abnormally larger than surrounding candles (ideally 2x+ the average candle range of the preceding 20 candles)
- **HARD RULE**: If the leg-out is indecisive (`body_pct <= 0.50`), the **ZONE FAILS regardless of all other qualities**
- **What it proves**: Institutional orders were placed in the base and executed aggressively, creating the explosive departure

#### Gaps as Leg-Outs (Phase 6, Ch 171)

A **price gap** in the direction of the leg-out **counts as / substitutes for an explosive candle**. Bernd: *"a gap, you can usually a gap"* — gaps are the strongest possible leg-out signal because they prove institutional urgency exceeded available liquidity. Common in equities and individual stocks (overnight / earnings gaps), occasional on commodity Sunday opens.

```python
def has_gap_legout(prior_candle, current_candle, direction):
    """A gap in the leg-out direction qualifies as the explosive component."""
    if direction == "up":
        return current_candle.low > prior_candle.high
    else:
        return current_candle.high < prior_candle.low
```

When a gap is present, treat the gap-out candle as `body_pct = 1.0` for zone validity even if its actual body is smaller — the gap itself is the institutional signature.

#### Discretionary Candle Classification (Edge Case, Ch 171/177)

When a candle straddles the decisive/indecisive thresholds (body_pct near 50%) AND its position could be read as either part of the base or part of the leg-out, the trader has discretion. Bernd: *"we could argue that the green candle could be part of the leg out. So we would only have the red candle as the basing candle"*. Both interpretations are valid; pick the one that produces the cleaner formation (typically the assignment that gives a more compact base + a cleaner leg-out).

This discretion applies ONLY to ambiguous threshold cases — the deterministic `body_pct` rule still governs the clear cases.

---

## 3. Four Formation Types

The direction of the leg-in combined with the direction of the leg-out determines the formation type:

| Formation | Leg-In Direction | Leg-Out Direction | Zone Type | Originality | Score |
|-----------|-----------------|-------------------|-----------|-------------|-------|
| **DBR** (Drop-Base-Rally) | Bearish | Bullish | DEMAND | Non-original | 5/10 |
| **RBR** (Rally-Base-Rally) | Bullish | Bullish | DEMAND | Original | 10/10 |
| **RBD** (Rally-Base-Drop) | Bullish | Bearish | SUPPLY | Non-original | 5/10 |
| **DBD** (Drop-Base-Drop) | Bearish | Bearish | SUPPLY | Original | 10/10 |

### Why Originals Score Higher

- **RBR / DBD (Original, Continuation)**: Price was already moving in the leg-out direction before the base. The base represents institutional **accumulation** (demand) or **distribution** (supply) — adding to existing positions. These zones carry stronger unfilled order residue.
- **DBR / RBD (Non-Original, Reaction)**: Price reversed direction at the base. This is a **reaction** to opposing pressure, not a planned institutional campaign. Weaker residual orders.

---

## 4. Zone Drawing — Proximal & Distal Lines

### Definitions

| Line | Fibonacci Label | Meaning |
|------|----------------|---------|
| **Proximal** | Fib 100 | The entry side of the zone — where price first touches when returning |
| **Distal** | Fib 0 | The stop-loss side of the zone — the far boundary |
| **Stop Loss** | Fib -33 | Extension beyond distal for stop placement |

### Demand Zone Boundaries

```
proximal = max(max(c.open, c.close) for c in base_candles)     # Highest BODY extreme
distal   = min(c.low for c in base_candles + legout_candles)    # Lowest WICK
stop     = distal - 0.33 * (proximal - distal)                  # Fib -33 extension
```

### Supply Zone Boundaries

```
proximal = min(min(c.open, c.close) for c in base_candles)     # Lowest BODY extreme
distal   = max(c.high for c in base_candles + legout_candles)   # Highest WICK
stop     = distal + 0.33 * (distal - proximal)                  # Fib -33 extension
```

### Two Drawing Versions

| Version | Proximal Uses | Distal Uses | When to Use |
|---------|--------------|-------------|-------------|
| **Preferred (Tight)** | Body extremes only | Body extremes only | Primary entry — tighter zone, better precision, better R:R |
| **Wider** | Body extremes | Wick extremes | LOL analysis, HTF coverage, conservative stop placement |

### Fibonacci Coding Convention

When drawing zones on charts or in code, ALWAYS use:
- **100 = Proximal** (entry side)
- **0 = Distal** (far boundary)
- **-33 = Stop Loss** (extension beyond distal)

This convention applies regardless of whether the zone is supply or demand.

### Annotation Discipline (Phase 6, Ch 182)

**Mandatory hygiene rule**: Every zone must have its **proximal price** annotated on the chart. Bernd: *"you have to add the price on your proximal… always. Because you will never understand"* (your own analysis later). When zones are saved without the price label, traders lose the ability to verify retests and reconstruct decisions days/weeks later.

```python
# When persisting a zone:
zone.label = f"{zone.zone_type[:1].upper()} {zone.proximal:.4f}"  # e.g. "D 1.0852" or "S 4521.50"
```

### Daily-Perspective Base-Candle Inclusion (Phase 6, Ch 171)

When a weekly zone overlays a daily zone, a daily-perspective trader has discretion to **include or exclude** base candles that are part of the weekly aggregate. Bernd: *"we could argue that we could include them into our level, but it would also not be wrong to exclude them"*.

Both interpretations are valid. Pick the one that produces the cleaner, more conservative zone for your timeframe — usually excluding HTF-overlapping candles to keep the LTF base tighter.

### Single-Candle Fallback (Phase 6, Ch 178)

When **no formation/zone exists** at the level of interest (no clean leg-in/base/leg-out structure), mark the **last candle** as a single-candle reference level instead of trying to force a zone. Bernd: *"I would mark the last candle"*. This is a tracking marker, not a tradeable zone — but it preserves the level for future qualification when a proper formation eventually develops around it.

---

## 5. Detection Algorithm (Pseudocode)

```python
def classify_candle(candle):
    """Classify a single candle by body percentage."""
    range_size = candle.high - candle.low
    if range_size == 0:
        return {"body_pct": 0, "type": "indecisive", "direction": "neutral"}
    
    body_pct = abs(candle.close - candle.open) / range_size
    direction = "bullish" if candle.close > candle.open else "bearish"
    
    if body_pct >= 0.70:
        ctype = "explosive"
    elif body_pct > 0.50:
        ctype = "decisive"
    else:
        ctype = "indecisive"
    
    return {"body_pct": body_pct, "type": ctype, "direction": direction}


def scan_leg_in(data, start_index, direction):
    """
    Scan backwards or forwards for 3+ consecutive decisive candles 
    in the same direction.
    Returns: LegIn object with start, end indices, or None.
    """
    count = 0
    i = start_index
    while i >= 0:
        c = classify_candle(data[i])
        if c["type"] in ("decisive", "explosive") and c["direction"] == direction:
            count += 1
            i -= 1
        else:
            break
    
    if count >= 3:
        return LegIn(start=i + 1, end=start_index, direction=direction, count=count)
    return None


def scan_base(data, start_index):
    """
    Scan forward for 1-6 consecutive indecisive candles.
    Returns: Base object or None.
    """
    count = 0
    i = start_index
    while i < len(data):
        c = classify_candle(data[i])
        if c["type"] == "indecisive":
            count += 1
            i += 1
        else:
            break
    
    if 1 <= count <= 6:
        return Base(start=start_index, end=start_index + count - 1, count=count)
    return None  # 0 candles or 7+ = invalid


def scan_leg_out(data, start_index, avg_range_20):
    """
    Scan forward for 1+ explosive candles that are abnormally large.
    Returns: LegOut object or None.
    """
    count = 0
    i = start_index
    direction = None
    while i < len(data):
        c = classify_candle(data[i])
        candle_range = data[i].high - data[i].low
        
        if c["body_pct"] >= 0.70 and candle_range >= 1.5 * avg_range_20:
            if direction is None:
                direction = c["direction"]
            if c["direction"] == direction:
                count += 1
                i += 1
            else:
                break
        else:
            break
    
    if count >= 1 and direction is not None:
        return LegOut(start=start_index, end=start_index + count - 1,
                      direction=direction, count=count)
    return None


def detect_zones(ohlcv_data):
    """
    Main zone detection loop.
    Scans the entire OHLCV dataset for valid supply/demand zones.
    """
    zones = []
    avg_range_20 = compute_rolling_avg_range(ohlcv_data, period=20)
    
    for i in range(len(ohlcv_data)):
        # Step 1: Check for base starting at index i
        base = scan_base(ohlcv_data, i)
        if not base:
            continue
        if base.count > 6:
            continue  # INVALID: too many base candles
        
        # Step 2: Check for leg-in before the base
        leg_in_index = base.start - 1
        if leg_in_index < 0:
            continue
        
        li_candle = classify_candle(ohlcv_data[leg_in_index])
        leg_in = scan_leg_in(ohlcv_data, leg_in_index, li_candle["direction"])
        if not leg_in:
            continue
        
        # Step 3: Check for leg-out after the base
        legout_start = base.end + 1
        if legout_start >= len(ohlcv_data):
            continue
        
        leg_out = scan_leg_out(ohlcv_data, legout_start, avg_range_20[legout_start])
        if not leg_out:
            continue  # No explosive departure = INVALID
        
        # Step 4: Determine formation type
        leg_in_dir = leg_in.direction
        leg_out_dir = leg_out.direction
        
        if leg_in_dir == "bearish" and leg_out_dir == "bullish":
            formation = "DBR"
        elif leg_in_dir == "bullish" and leg_out_dir == "bullish":
            formation = "RBR"
        elif leg_in_dir == "bullish" and leg_out_dir == "bearish":
            formation = "RBD"
        elif leg_in_dir == "bearish" and leg_out_dir == "bearish":
            formation = "DBD"
        else:
            continue
        
        # Step 5: Determine zone type
        zone_type = "demand" if formation in ("DBR", "RBR") else "supply"
        
        # Step 6: Calculate zone boundaries
        base_candles = ohlcv_data[base.start : base.end + 1]
        legout_candles = ohlcv_data[leg_out.start : leg_out.end + 1]
        combined = base_candles + legout_candles
        
        if zone_type == "demand":
            proximal = max(max(c.open, c.close) for c in base_candles)
            distal = min(c.low for c in combined)
        else:  # supply
            proximal = min(min(c.open, c.close) for c in base_candles)
            distal = max(c.high for c in combined)
        
        zone_height = abs(proximal - distal)
        stop = distal - 0.33 * zone_height if zone_type == "demand" else distal + 0.33 * zone_height
        
        # Step 7: Determine originality
        is_original = formation in ("RBR", "DBD")
        
        zones.append(Zone(
            zone_type=zone_type,
            formation=formation,
            proximal=proximal,
            distal=distal,
            stop=stop,
            zone_height=zone_height,
            base_count=base.count,
            legout_count=leg_out.count,
            is_original=is_original,
            base_start_index=base.start,
            base_end_index=base.end,
            legout_body_pct=avg_body_pct(legout_candles),
            freshness=0,  # 0 retests = fresh
            timestamp=ohlcv_data[base.start].timestamp
        ))
    
    return zones
```

---

## 6. Flip Zones

A **flip zone** occurs when a former demand zone becomes supply, or a former supply zone becomes demand.

### How a Flip Occurs

1. A valid demand zone is established (e.g., RBR at 1.2000-1.1980)
2. Price returns and **breaks through the zone entirely** (trades through the distal line)
3. The zone is invalidated as demand
4. Price later rallies back UP to the same level
5. The former demand zone now acts as **supply** — the flipped zone

### Scoring

- **Originality score: 12/10** (exceeds maximum for standard formations)
- Flip zones represent the strongest institutional footprint because they show where large players were trapped and will defend the opposite direction

### Detection in Code

```python
def detect_flip_zones(active_zones, invalidated_zones, current_price):
    flip_zones = []
    for old_zone in invalidated_zones:
        # Check if price has returned to the invalidated zone's range
        if old_zone.zone_type == "demand":
            # Former demand, now potential supply
            if current_price >= old_zone.proximal:
                flipped = Zone(
                    zone_type="supply",
                    formation="FLIP",
                    proximal=old_zone.proximal,
                    distal=old_zone.distal,
                    originality_score=12,
                    source_zone=old_zone
                )
                flip_zones.append(flipped)
        else:
            # Former supply, now potential demand
            if current_price <= old_zone.proximal:
                flipped = Zone(
                    zone_type="demand",
                    formation="FLIP",
                    proximal=old_zone.proximal,
                    distal=old_zone.distal,
                    originality_score=12,
                    source_zone=old_zone
                )
                flip_zones.append(flipped)
    return flip_zones
```

---

## 7. Zone Invalidation Rules

A zone is removed from the active list when any of these conditions is met:

| Rule | Condition | Result |
|------|-----------|--------|
| **Indecisive leg-out** | Leg-out `body_pct <= 0.50` | Zone never created (fails at detection) |
| **Extended base** | Base candle count > 6 | Zone never created (fails at detection) |
| **Full consumption** | Price trades completely through the distal line | Zone invalidated — remove from active list |
| **Retest degradation** | Each time price touches the zone | Freshness degrades: `score = 10 / (retests + 1)` |

### Retest Tracking

```python
def update_zone_freshness(zone, current_candle):
    """Call on each new candle to check if zone was retested."""
    if zone.zone_type == "demand":
        if current_candle.low <= zone.proximal and current_candle.low >= zone.distal:
            zone.retests += 1
            zone.freshness_score = 10 / (zone.retests + 1)
        if current_candle.low < zone.distal:
            zone.is_valid = False  # Fully consumed
    else:  # supply
        if current_candle.high >= zone.proximal and current_candle.high <= zone.distal:
            zone.retests += 1
            zone.freshness_score = 10 / (zone.retests + 1)
        if current_candle.high > zone.distal:
            zone.is_valid = False  # Fully consumed
```

### Freshness Score Table

| Retests | Freshness Score | Quality |
|---------|----------------|---------|
| 0 | 10.0 | Fresh — highest probability |
| 1 (wider only) | 7.0 | Wicks touched, body held — acceptable |
| 2 (preferred) | 3.0 | Body broke proximal — weakening |
| 3+ | 0.0 | Consumed — invalid |

(See `02_zone_qualifiers.md` Q3 for the full retest classification — wider vs preferred distinction matters more than the raw count.)

---

## 8. Big Brother / Small Brother (HTF/LTF zone containment)

**Concept (OTC L3)**: An LTF zone is "high quality" only when an HTF zone of the **same direction** fully **contains** it (LTF range ⊂ HTF range). The HTF zone is the "big brother", the LTF is the "small brother".

### CRITICAL: Containment, NOT Multi-TF Stacking

**AUDIT CORRECTION (Phase 6, Ch 182)**: A student asked about "big brother coverage of the weekly with the daily timeframe" — Bernd answered: *"That's not how it works… you have to pick"*. BB/SB is a **CONTAINMENT CHECK** on a single trade, not multi-TF additive coverage.

**The right way**:
1. **Pick ONE primary HTF** for the trade (weekly for Weekly Income, daily for Daily Income, etc.).
2. Identify the HTF zone you intend to trade.
3. Refine downward to find the LTF zone (the "small brother") that fits **inside** the HTF zone of the **same direction**.
4. Confirm containment: `LTF_proximal ≥ HTF_proximal` AND `LTF_distal ≤ HTF_distal` (for demand; mirror for supply).

**The wrong way** (do NOT do this):
- Drawing zones on weekly + daily + 4H + 60m and calling that "stacked coverage".
- Treating BB/SB as a vote multiplier where more TFs aligned = better trade.

BB/SB is binary per trade: the LTF zone EITHER fits inside an HTF zone of the same direction, or it does not. Recursion across the income ladder (Weekly Income uses weekly as BB; Daily Income uses daily as BB; Intraday uses 4H) is fine — but each trade has ONE BB↔SB pair.

### Containment Rule

```python
def has_big_brother_coverage(ltf_zone, htf_zones):
    ltf_lo, ltf_hi = sorted([ltf_zone.proximal, ltf_zone.distal])
    for htf in htf_zones:
        if htf.zone_type != ltf_zone.zone_type:
            continue   # direction mismatch -> no coverage
        htf_lo, htf_hi = sorted([htf.proximal, htf.distal])
        if ltf_lo >= htf_lo and ltf_hi <= htf_hi:
            return True, htf
    return False, None
```

### Trade Quality Matrix

| HTF context | LTF zone | Outcome |
|-------------|----------|---------|
| Bullish trend + low location (≤33%) + LTF demand inside HTF demand | covered + aligned | **BEST** — highest-conviction trade |
| Bullish trend + equilibrium location (33–66%) + covered LTF | covered but mid-location | **MEDIUM** — Bernd notes "no big brother" feel |
| Sideways HTF + any LTF | usually no coverage | **AVOID** unless extreme location |
| Counter-trend equilibrium | irrelevant | **AVOID** — worst scenario per OTC L5 |

### Wick-over-Wick Substitute (Edge Case)

When no clean HTF formation is visible, two adjacent overlapping wicks of the same direction (e.g. two consecutive weekly candles failing at the same swing high) can act as the big brother. Quoted from OTC L3 0:38:04 — "WIC over WIC offers us HTF coverage". Currently not auto-detected; must be marked manually.

### Speed Bumps (Path Obstacles)

When trading toward a target zone, the path between current price and the target may contain opposing-direction zones — these are "speed bumps". Bernd warns NOT to trade through obvious speed bumps because they consume institutional orders before price can reach your zone.

```python
def detect_speed_bumps(zones, target_zone, current_price):
    opposite = 'supply' if target_zone.zone_type == 'demand' else 'demand'
    if target_zone.zone_type == 'demand':
        lo, hi = target_zone.proximal, current_price   # below current price
    else:
        lo, hi = current_price, target_zone.proximal   # above current price
    return [z for z in zones if z.zone_type == opposite
            and lo <= (z.proximal + z.distal) / 2 <= hi]
```

A "blocking" speed bump = composite score ≥ 5.0 (qualified enough to actually stall the trade). Code flags but does not auto-reject — Bernd takes some trades through speed bumps when entry/exit math is overwhelming.
