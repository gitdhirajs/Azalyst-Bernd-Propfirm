"""Supply/Demand Zone Detection Engine.

Implements zone detection with all 6 qualifiers + LOL per Blueprint methodology.
Scans price history for DBR, RBR, RBD, DBD formations and scores them.
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import hashlib
import logging
import uuid

logger = logging.getLogger(__name__)


class ZoneDetector:
    """Detect supply/demand zones and score using 6 qualifiers + LOL."""

    def __init__(self, config: dict):
        self.leg_in_min = config.get('leg_in_min_candles', 3)
        self.base_max = config.get('base_max_candles', 6)
        self.base_min = config.get('base_min_candles', 1)
        self.leg_out_mult = config.get('leg_out_body_multiplier', 2.0)
        self.base_wick_pct = config.get('base_wick_max_pct', 0.50)
        self.profit_margin_min = config.get('profit_margin_min_ratio', 3.0)

        self.weights = config.get('qualifier_weights', {
            'departure': 0.30, 'base_duration': 0.10, 'freshness': 0.15,
            'originality': 0.15, 'profit_margin': 0.10, 'arrival': 0.10,
            'level_on_top': 0.10
        })

    def _flag_flip_zones(self, zones: List[Dict]) -> None:
        """Mark zones whose price range previously hosted an opposite-type
        zone (demand becoming supply or vice versa). Per the Blueprint
        textbook (Ch 13.6b), original flip zones score 12 on Q4 -- the
        highest possible weight -- because they signal an institutional
        regime change. Mutates zones in place.
        """
        # Sort by formation order so we can scan history-up
        ordered = sorted(zones, key=lambda z: z['origin_index'])
        for i, z in enumerate(ordered):
            if not z.get('is_original'):
                continue
            for prior in ordered[:i]:
                if prior['zone_type'] == z['zone_type']:
                    continue  # same direction, not a flip
                # Overlap check: do the two zones share any price range?
                z_lo, z_hi = sorted([z['proximal'], z['distal']])
                p_lo, p_hi = sorted([prior['proximal'], prior['distal']])
                if z_hi < p_lo or z_lo > p_hi:
                    continue
                # Flip confirmed
                z['is_flip'] = True
                z['originality_score'] = 12.0
                # Recompute composite with the new originality score
                lol_w = self.weights.get('level_on_top', 0.10)
                z['composite_score'] = round(
                    z['departure_score']     * self.weights['departure'] +
                    z['base_duration_score'] * self.weights['base_duration'] +
                    z['freshness_score']     * self.weights['freshness'] +
                    z['originality_score']   * self.weights['originality'] +
                    z['profit_margin_score'] * self.weights['profit_margin'] +
                    z['arrival_score']       * self.weights['arrival'] +
                    z['level_on_top_score']  * lol_w,
                    2,
                )
                break

    def detect_zones(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
        trend: Optional[str] = None,
    ) -> List[Dict]:
        """
        Scan price history and detect supply/demand zones.

        Args:
            df: OHLCV DataFrame with columns: open, high, low, close, volume
            symbol: Trading symbol
            timeframe: Chart timeframe

        Returns:
            List of zone dictionaries with all qualifier scores
        """
        if df.empty or len(df) < 20:
            return []

        df = df.copy().reset_index(drop=True)
        # FIX Bug 1+6: pandas 2.x hangs in iterrows() when the DataFrame
        # contains a tz-aware DatetimeTZDtype column (the 'timestamp' col
        # added by _fetch_one's reset_index). Convert to plain string here
        # so every slice downstream is safe to iterate.
        if 'timestamp' in df.columns:
            df['timestamp'] = df['timestamp'].astype(str)
        zones = []

        # Calculate candle properties
        df['body'] = abs(df['close'] - df['open'])
        df['range'] = df['high'] - df['low']
        df['upper_wick'] = df['high'] - df[['close', 'open']].max(axis=1)
        df['lower_wick'] = df[['close', 'open']].min(axis=1) - df['low']
        df['direction'] = np.where(df['close'] > df['open'], 1, -1)
        df['avg_body_20'] = df['body'].rolling(20).mean()

        # Helper: a zone is "with trend" when its directional bias matches
        # the higher-timeframe trend supplied by the caller.
        def _aligns(zt: str) -> Optional[bool]:
            if trend is None or trend == 'sideways':
                return None
            if trend == 'uptrend':
                return zt == 'demand'
            if trend == 'downtrend':
                return zt == 'supply'
            return None

        i = self.leg_in_min
        while i < len(df) - 5:
            # ---- Demand Zone: Drop-Base-Rally (DBR) ----
            dbr = self._detect_dbr(df, i)
            if dbr:
                zones.append(self._score_zone(dbr, df, symbol, timeframe, 'demand', 'drop_base_rally', with_trend=_aligns('demand')))
                i = dbr['leg_out_end'] + 1
                continue

            # ---- Demand Zone: Rally-Base-Rally (RBR) ----
            rbr = self._detect_rbr(df, i)
            if rbr:
                zones.append(self._score_zone(rbr, df, symbol, timeframe, 'demand', 'rally_base_rally', with_trend=_aligns('demand')))
                i = rbr['leg_out_end'] + 1
                continue

            # ---- Supply Zone: Rally-Base-Drop (RBD) ----
            rbd = self._detect_rbd(df, i)
            if rbd:
                zones.append(self._score_zone(rbd, df, symbol, timeframe, 'supply', 'rally_base_drop', with_trend=_aligns('supply')))
                i = rbd['leg_out_end'] + 1
                continue

            # ---- Supply Zone: Drop-Base-Drop (DBD) ----
            dbd = self._detect_dbd(df, i)
            if dbd:
                zones.append(self._score_zone(dbd, df, symbol, timeframe, 'supply', 'drop_base_drop', with_trend=_aligns('supply')))
                i = dbd['leg_out_end'] + 1
                continue

            i += 1

        # Tag flip zones (Q4 originality bonus per textbook Ch 13.6b)
        self._flag_flip_zones(zones)
        return zones

    def _detect_dbr(self, df: pd.DataFrame, start: int) -> Optional[Dict]:
        """Detect Drop-Base-Rally (demand) formation."""
        leg_in_end = start
        leg_in_start = start - self.leg_in_min

        if leg_in_start < 0:
            return None

        # Majority of leg-in candles must be bearish
        leg_in_slice = df.iloc[leg_in_start:leg_in_end + 1]
        bearish_pct = (leg_in_slice['direction'] == -1).mean()
        if bearish_pct < 0.70:
            return None

        base_start = leg_in_end + 1
        if base_start >= len(df) - 3:
            return None

        base_end = self._find_base(df, base_start, 'demand')
        if base_end is None:
            return None

        leg_out_start = base_end + 1
        if leg_out_start >= len(df):
            return None

        leg_out_end = self._find_leg_out(df, leg_out_start, 'bullish')
        if leg_out_end is None or leg_out_end <= leg_out_start:
            return None

        return {
            'leg_in_start': leg_in_start, 'leg_in_end': leg_in_end,
            'base_start': base_start, 'base_end': base_end,
            'leg_out_start': leg_out_start, 'leg_out_end': leg_out_end
        }

    def _detect_rbr(self, df: pd.DataFrame, start: int) -> Optional[Dict]:
        """Detect Rally-Base-Rally (demand continuation) formation."""
        leg_in_start = max(0, start - self.leg_in_min)
        leg_in_slice = df.iloc[leg_in_start:start + 1]
        bullish_pct = (leg_in_slice['direction'] == 1).mean()
        if bullish_pct < 0.70:
            return None

        base_end = self._find_base(df, start + 1, 'demand')
        if base_end is None:
            return None

        leg_out_end = self._find_leg_out(df, base_end + 1, 'bullish')
        if leg_out_end is None or leg_out_end <= base_end:
            return None

        return {
            'leg_in_start': leg_in_start, 'leg_in_end': start,
            'base_start': start + 1, 'base_end': base_end,
            'leg_out_start': base_end + 1, 'leg_out_end': leg_out_end
        }

    def _detect_rbd(self, df: pd.DataFrame, start: int) -> Optional[Dict]:
        """Detect Rally-Base-Drop (supply) formation."""
        leg_in_start = max(0, start - self.leg_in_min)
        leg_in_slice = df.iloc[leg_in_start:start + 1]
        bullish_pct = (leg_in_slice['direction'] == 1).mean()
        if bullish_pct < 0.70:
            return None

        base_end = self._find_base(df, start + 1, 'supply')
        if base_end is None:
            return None

        leg_out_end = self._find_leg_out(df, base_end + 1, 'bearish')
        if leg_out_end is None or leg_out_end <= base_end:
            return None

        return {
            'leg_in_start': leg_in_start, 'leg_in_end': start,
            'base_start': start + 1, 'base_end': base_end,
            'leg_out_start': base_end + 1, 'leg_out_end': leg_out_end
        }

    def _detect_dbd(self, df: pd.DataFrame, start: int) -> Optional[Dict]:
        """Detect Drop-Base-Drop (supply continuation) formation."""
        leg_in_start = max(0, start - self.leg_in_min)
        leg_in_slice = df.iloc[leg_in_start:start + 1]
        bearish_pct = (leg_in_slice['direction'] == -1).mean()
        if bearish_pct < 0.70:
            return None

        base_end = self._find_base(df, start + 1, 'supply')
        if base_end is None:
            return None

        leg_out_end = self._find_leg_out(df, base_end + 1, 'bearish')
        if leg_out_end is None or leg_out_end <= base_end:
            return None

        return {
            'leg_in_start': leg_in_start, 'leg_in_end': start,
            'base_start': start + 1, 'base_end': base_end,
            'leg_out_start': base_end + 1, 'leg_out_end': leg_out_end
        }

    def _find_base(
        self, df: pd.DataFrame, start: int, zone_type: str
    ) -> Optional[int]:
        """Find the base consolidation (1-6 indecisive candles)."""
        best_end = None
        for end in range(start, min(start + self.base_max + 1, len(df))):
            base_slice = df.iloc[start:end + 1]
            n_candles = len(base_slice)

            if n_candles < self.base_min:
                continue
            if n_candles > self.base_max:
                return best_end if best_end is not None else start

            # All base candles must be indecisive (body <= 50% of range)
            # Vectorized: avoids iterrows() tz-datetime hang (Bug 1 fix)
            valid = base_slice['range'] > 0
            if valid.any():
                all_indecisive = not (
                    (base_slice.loc[valid, 'body'] / base_slice.loc[valid, 'range']) > 0.50
                ).any()
            else:
                all_indecisive = True

            if all_indecisive:
                best_end = end

        return best_end

    def _find_leg_out(
        self, df: pd.DataFrame, start: int, direction: str
    ) -> Optional[int]:
        """Find explosive leg-out (body/range >= 70%) OR a price gap in the
        leg-out direction.

        Returns None when no qualifying explosive candle is found within the
        window. The previous version returned `start`, which silently produced
        invalid zones with indecisive leg-outs -- a Q1 violation per the
        Blueprint methodology (CLAUDE.md rule 9).

        Phase 6 (Ch 171): a gap in the direction of the leg-out qualifies as
        an explosive component -- gaps are the strongest possible leg-out
        signal because they prove institutional urgency exceeded available
        liquidity. Bernd: "a gap, you can usually a gap".
        """
        if start >= len(df):
            return None

        expected_dir = 1 if direction == 'bullish' else -1
        avg_body = df['avg_body_20'].iloc[start] if pd.notna(df['avg_body_20'].iloc[start]) else df['body'].iloc[max(0, start - 20):start].mean()
        if pd.isna(avg_body) or avg_body == 0:
            avg_body = df['body'].mean() or 0.0001

        for i in range(start, min(start + 20, len(df))):
            candle = df.iloc[i]
            if candle['direction'] != expected_dir:
                continue

            # Standard explosive-body check
            body_pct = candle['body'] / candle['range'] if candle['range'] > 0 else 0
            if body_pct >= 0.70 and candle['body'] >= self.leg_out_mult * max(avg_body, 0.0001):
                return i

            # Phase 6: gap-as-leg-out (Ch 171)
            if i > 0:
                prior = df.iloc[i - 1]
                if direction == 'bullish' and candle['low'] > prior['high']:
                    return i  # bullish gap up
                if direction == 'bearish' and candle['high'] < prior['low']:
                    return i  # bearish gap down

        return None

    def _score_zone(
        self, zone: Dict, df: pd.DataFrame, symbol: str, timeframe: str,
        zone_type: str, formation: str,
        with_trend: Optional[bool] = None,
    ) -> Dict:
        """Apply all 6 qualifiers + LOL and compute composite score."""
        base_slice = df.iloc[zone['base_start']:zone['base_end'] + 1]
        leg_out_candle = df.iloc[zone['leg_out_end']]

        # Zone boundaries (per textbook methodology)
        leg_out_slice = df.iloc[zone['leg_out_start']:zone['leg_out_end'] + 1]
        if zone_type == 'demand':
            proximal = max(base_slice[['open', 'close']].max(axis=1))
            distal = min(base_slice['low'].min(), leg_out_slice['low'].min())
        else:
            proximal = min(base_slice[['open', 'close']].min(axis=1))
            distal = max(base_slice['high'].max(), leg_out_slice['high'].max())

        zone_height = abs(proximal - distal)

        # Q1: Departure (CRITICAL)
        leg_out_body_pct = leg_out_candle['body'] / leg_out_candle['range'] if leg_out_candle['range'] > 0 else 0
        if leg_out_body_pct >= 0.70:
            departure_score = 10.0
        elif leg_out_body_pct >= 0.60:
            departure_score = 7.0
        elif leg_out_body_pct > 0.50:
            departure_score = 5.0
        else:
            departure_score = 0.0

        # Q2: Base Duration
        # Phase 41 S4-01: OTC M2L6 canonical cheat sheet states "Approx. 1-5 candles."
        # The old upper limit of 6 was too permissive. 6+ candles = score 0 (fails quality bar).
        # base_max_candles config also updated to 5 in BP_config.yaml.
        base_candles = zone['base_end'] - zone['base_start'] + 1
        if base_candles <= 2:
            base_dur_score = 10.0
        elif base_candles <= 4:
            base_dur_score = 7.0
        elif base_candles <= 5:
            base_dur_score = 4.0  # 5 candles = marginal but acceptable
        else:
            base_dur_score = 0.0  # 6+ candles = fails Q2

        # Q3: Freshness -- proper Blueprint gradient (OTC 2025 lesson 6):
        #   never tested        = 10
        #   wider area only     = 7   (wick touched distal, didn't pierce proximal)
        #   preferred (body)    = 3   (price closed beyond proximal body extreme)
        #   consumed (2+)       = 0
        # P1 HARD GATE (Phase 6, Ch 184): >25% penetration into zone range = INVALIDATED.
        # Bernd: "the bottom zone is taking out because the zone was tested more than 25%".
        # The penetration check fires before scoring -- if invalidated, freshness = 0
        # regardless of retest counts.
        wider_hits, preferred_hits = self._count_retests_split(df, zone, zone_type)
        invalidated_25pct = self._is_zone_invalidated_25pct(
            df, zone, zone_type, proximal=proximal, distal=distal
        )
        if invalidated_25pct:
            freshness_score = 0.0
        elif wider_hits == 0 and preferred_hits == 0:
            freshness_score = 10.0
        elif preferred_hits == 0:
            freshness_score = 7.0
        elif preferred_hits == 1:
            freshness_score = 3.0
        else:
            freshness_score = 0.0
        is_fresh = (wider_hits == 0 and preferred_hits == 0 and not invalidated_25pct)
        retests = wider_hits + preferred_hits  # for backward compat fields

        # Q4: Originality
        if formation in ('rally_base_rally', 'drop_base_drop'):
            originality_score = 10.0
            is_original = True
        else:
            originality_score = 5.0
            is_original = False
        is_flip = False

        # Q5: Profit Margin -- per Hybrid AI lesson, this is a counter-trend
        # / sideways gate. When trading WITH the trend the methodology says
        # "it really doesn't matter" so we award full credit and let other
        # qualifiers drive the score.
        if zone_type == 'demand':
            max_move = df.iloc[zone['leg_out_end']:]['high'].max()
            margin_distance = max_move - proximal
        else:
            min_move = df.iloc[zone['leg_out_end']:]['low'].min()
            margin_distance = proximal - min_move

        margin_ratio = margin_distance / max(zone_height, 0.0001)
        if with_trend is True:
            profit_score = 10.0  # Skip Q5 on trend trades per Hybrid AI Module 1
        elif margin_ratio >= 5:
            profit_score = 10.0
        elif margin_ratio >= 3:
            profit_score = 7.0
        elif margin_ratio >= 2:
            profit_score = 5.0
        else:
            profit_score = 0.0

        # Q5 MUST PASS gate: counter-trend zones with profit_score == 0 fail
        # (per OTC L6 frame 1570 + Hybrid AI Module 1). Trend trades and
        # sideways trades skip this gate. Marker stored on the zone so the
        # caller can hard-reject without recomputing.
        q5_failed_gate = (with_trend is False and profit_score == 0.0)

        # Q6: Arrival -- same trend-context rule. Skipped on trend trades.
        # Vectorized: avoids iterrows() tz-datetime hang (Bug 6 fix)
        _return_slice = df.iloc[zone['leg_out_end']:]
        if zone_type == 'demand':
            _hit = _return_slice['low'] <= proximal
        else:
            _hit = _return_slice['high'] >= proximal
        bars_to_return = int(_hit.argmax()) + 1 if _hit.any() else len(_return_slice)

        if with_trend is True:
            arrival_score = 10.0  # Skip Q6 on trend trades
        elif bars_to_return <= 5:
            arrival_score = 10.0
        elif bars_to_return <= 15:
            arrival_score = 7.0
        elif bars_to_return <= 30:
            arrival_score = 5.0
        else:
            arrival_score = 3.0

        # LOL: Level on Top (deferred to multi-TF analysis)
        lot_score = 0.0

        # Composite
        composite = (
            departure_score * self.weights['departure'] +
            base_dur_score * self.weights['base_duration'] +
            freshness_score * self.weights['freshness'] +
            originality_score * self.weights['originality'] +
            profit_score * self.weights['profit_margin'] +
            arrival_score * self.weights['arrival'] +
            lot_score * self.weights['level_on_top']
        )

        # Stable zone ID: same zone detected on different scan dates gets the
        # same ID so zone_memory suppression works across weekly scans.
        # Key = symbol + type + timeframe + origin_time + proximal (4dp) + distal (4dp).
        _origin_time_str = str(df.iloc[zone['leg_out_end']].get('timestamp', zone['leg_out_end']))
        _stable_key = f"{symbol}|{zone_type}|{timeframe}|{_origin_time_str}|{proximal:.4f}|{distal:.4f}"
        _zone_id = hashlib.md5(_stable_key.encode()).hexdigest()[:10]

        return {
            'id': _zone_id,
            'symbol': symbol,
            'zone_type': zone_type,
            'formation': formation,
            'timeframe': timeframe,
            'proximal': float(proximal),
            'distal': float(distal),
            'origin_index': int(zone['leg_out_end']),
            'origin_time': str(df.iloc[zone['leg_out_end']].get('timestamp', '')),
            'is_fresh': is_fresh,
            'is_original': is_original,
            'is_flip': is_flip,
            'retest_count': int(self._count_retests(df, zone, zone_type)),
            'base_candle_count': base_candles,
            'departure_score': round(departure_score, 2),
            'base_duration_score': round(base_dur_score, 2),
            'freshness_score': round(freshness_score, 2),
            'originality_score': round(originality_score, 2),
            'profit_margin_score': round(profit_score, 2),
            'arrival_score': round(arrival_score, 2),
            'level_on_top_score': round(lot_score, 2),
            'composite_score': round(composite, 2),
            'margin_ratio': round(margin_ratio, 2),
            'htf_aligned': False,
            'q5_failed_gate': q5_failed_gate,
            'with_trend':     with_trend,
            # NOTE: intentionally NOT emitting an 'invalidated' flag here. A 25%
            # penetration already forces Q3 freshness to 0 (so the composite is
            # heavily penalised). Adding a hard 'invalidated' flag additionally
            # (a) made rank_zones reject the zone and (b) made the Location-Fib
            # `_zone_is_usable` filter drop it as an anchor — which regressed the
            # goldtest by ~7 Bernd-clone cases (equity + PM long calls -> neutral),
            # exactly the Phase 37 finding that Bernd's own calls use the
            # UN-filtered Fib. Freshness=0 is the correct, sufficient penalty.
        }

    def _is_zone_invalidated_25pct(
        self, df: pd.DataFrame, zone: Dict, zone_type: str,
        proximal: Optional[float] = None, distal: Optional[float] = None,
    ) -> bool:
        """P1 HARD GATE (Phase 6, Ch 184): zone is INVALIDATED when price has
        penetrated more than 25% into its range (proximal -> distal direction).

        Bernd: "the bottom zone is taking out because the zone was tested more
        than 25%". This is independent of retest counts -- a single deep
        penetration kills the zone regardless of whether price wicked back out.

        `proximal`/`distal` may be passed in directly (when called from
        _score_zone before the keys are written onto the zone dict). Falls
        back to zone[...] lookup otherwise.
        """
        origin_idx = zone['leg_out_end']
        if origin_idx >= len(df) - 1:
            return False

        if proximal is None:
            proximal = zone['proximal']
        if distal is None:
            distal = zone['distal']
        # 25% threshold = 25% of the zone's depth from proximal toward distal
        if zone_type == 'demand':
            # demand: distal < proximal; 25% deep = proximal - 0.25*(proximal-distal)
            threshold_25 = proximal - 0.25 * (proximal - distal)
            future_lows = df.iloc[origin_idx + 1:]['low']
            return bool((future_lows < threshold_25).any())
        else:  # supply
            # supply: distal > proximal; 25% deep = proximal + 0.25*(distal-proximal)
            threshold_25 = proximal + 0.25 * (distal - proximal)
            future_highs = df.iloc[origin_idx + 1:]['high']
            return bool((future_highs > threshold_25).any())

    def _count_retests(self, df: pd.DataFrame, zone: Dict, zone_type: str) -> int:
        """Count how many times price has retested the zone since formation
        (any touch into the wider proximal-distal range)."""
        origin_idx = zone['leg_out_end']
        if origin_idx >= len(df) - 1:
            return 0

        base_slice = df.iloc[zone['base_start']:zone['base_end'] + 1]
        leg_out_slice = df.iloc[zone['leg_out_start']:zone['leg_out_end'] + 1]
        if zone_type == 'demand':
            proximal = max(base_slice[['open', 'close']].max(axis=1))
            distal = min(base_slice['low'].min(), leg_out_slice['low'].min())
        else:
            proximal = min(base_slice[['open', 'close']].min(axis=1))
            distal = max(base_slice['high'].max(), leg_out_slice['high'].max())

        # Vectorized: avoids iterrows() tz-datetime hang
        after_origin = df.iloc[origin_idx + 1:]
        if zone_type == 'demand':
            retests = int(((after_origin['low'] <= proximal) & (after_origin['low'] >= distal)).sum())
        else:
            retests = int(((after_origin['high'] >= proximal) & (after_origin['high'] <= distal)).sum())
        return retests

    def _count_retests_split(
        self, df: pd.DataFrame, zone: Dict, zone_type: str
    ) -> Tuple[int, int]:
        """Distinguish wider vs preferred retests for Q3 freshness.

        Per OTC 2025 lesson 6 (~0:16:41): a touch of the wider zone (the
        wick-extreme distal up to the body-extreme proximal) is a softer
        retest than a penetration past the proximal into the body-extreme
        zone proper. We count them separately and let the caller score:
            never tested  -> 10
            wider only    -> 7
            preferred hit -> 3
            consumed      -> 0

        Returns: (wider_retests, preferred_retests)
        """
        origin_idx = zone['leg_out_end']
        if origin_idx >= len(df) - 1:
            return 0, 0

        base_slice = df.iloc[zone['base_start']:zone['base_end'] + 1]
        leg_out_slice = df.iloc[zone['leg_out_start']:zone['leg_out_end'] + 1]

        if zone_type == 'demand':
            preferred = max(base_slice[['open', 'close']].max(axis=1))   # body-extreme high
            wider     = min(base_slice['low'].min(), leg_out_slice['low'].min())  # wick distal
        else:
            preferred = min(base_slice[['open', 'close']].min(axis=1))
            wider     = max(base_slice['high'].max(), leg_out_slice['high'].max())

        # Vectorized: avoids iterrows() tz-datetime hang
        after = df.iloc[origin_idx + 1:]
        wider_hits = 0
        preferred_hits = 0
        if zone_type == 'demand':
            in_wider = (after['low'] <= preferred) & (after['low'] >= wider)
            deep = in_wider & (after['low'] < preferred)
            deep_pref = deep & (
                (after['close'] < preferred) |
                (after['low'] < (preferred - 0.25 * abs(preferred - wider)))
            )
            preferred_hits = int(deep_pref.sum())
            wider_hits = int((in_wider & ~deep_pref).sum())
        else:
            in_wider = (after['high'] >= preferred) & (after['high'] <= wider)
            deep = in_wider & (after['high'] > preferred)
            deep_pref = deep & (
                (after['close'] > preferred) |
                (after['high'] > (preferred + 0.25 * abs(preferred - wider)))
            )
            preferred_hits = int(deep_pref.sum())
            wider_hits = int((in_wider & ~deep_pref).sum())
        return wider_hits, preferred_hits

    def rank_zones(self, zones: List[Dict], min_score: float = 5.0) -> List[Dict]:
        """Filter and rank zones by composite score.

        Hard-rejects:
          - Q5 MUST PASS gate failure (counter-trend zone with profit_margin=0)
          - Composite below min_score (default 5.0; methodology recommends 4.0+)

        NOTE: a >25%-penetrated zone is NOT hard-rejected here — its Q3 freshness
        is already 0 (heavy composite penalty), and hard-rejecting it regressed
        the Bernd-clone match (Phase 37). The composite gate is the intended
        filter for consumed zones.
        """
        valid = [
            z for z in zones
            if z['composite_score'] >= min_score
            and not z.get('q5_failed_gate', False)
        ]
        valid.sort(key=lambda z: z['composite_score'], reverse=True)
        return valid

    def detect_speed_bumps(
        self,
        zones: List[Dict],
        target_zone: Dict,
        current_price: float,
    ) -> List[Dict]:
        """Find opposing zones in the path between current price and the
        target. Per OTC 2025 lesson 5: these "speed bumps" are pockets of
        opposing institutional orders that can stall or reverse the trade
        before it reaches the target zone. Bernd warns NOT to trade
        through obvious speed bumps.

        Returns a list of opposing zones lying between current_price and
        target_zone.proximal, ordered nearest-to-furthest from current price.
        """
        opposite_type = 'supply' if target_zone['zone_type'] == 'demand' else 'demand'
        proximal = target_zone['proximal']

        if target_zone['zone_type'] == 'demand':
            # We're looking to buy at target proximal (below current price).
            # Speed bumps are supply zones in the range (target_proximal, current_price).
            lo, hi = proximal, current_price
        else:
            # Looking to sell at target proximal (above current price).
            # Speed bumps are demand zones in the range (current_price, target_proximal).
            lo, hi = current_price, proximal

        speed_bumps = []
        for z in zones:
            if z['zone_type'] != opposite_type:
                continue
            z_mid = (z['proximal'] + z['distal']) / 2.0
            if lo <= z_mid <= hi:
                speed_bumps.append(z)

        # Sort by distance from current price
        speed_bumps.sort(key=lambda z: abs(((z['proximal'] + z['distal']) / 2.0) - current_price))
        return speed_bumps

    def has_big_brother_coverage(
        self, ltf_zone: Dict, htf_zones: List[Dict],
    ) -> Tuple[bool, Optional[Dict]]:
        """Per OTC 2025 Lesson 3: an LTF zone is "high quality" only when an
        HTF zone of the same direction CONTAINS it (LTF.range ⊂ HTF.range).

        Phase 6 CLARIFICATION (Ch 182): this is a CONTAINMENT check on a
        single trade. Bernd, asked about stacking weekly+daily coverage:
        "That's not how it works... you have to pick" -- you pick ONE primary
        HTF for the trade, then refine downward. BB/SB is NOT multi-TF
        additive coverage where every TF aligned bumps the score. It is
        binary per trade: LTF either fits inside an HTF zone of the same
        direction, or it does not.

        Returns (covered, htf_zone | None).
        """
        ltf_lo = min(ltf_zone['proximal'], ltf_zone['distal'])
        ltf_hi = max(ltf_zone['proximal'], ltf_zone['distal'])
        for htf in htf_zones:
            if htf.get('zone_type') != ltf_zone.get('zone_type'):
                continue
            if htf.get('symbol') != ltf_zone.get('symbol'):
                continue
            htf_lo = min(htf['proximal'], htf['distal'])
            htf_hi = max(htf['proximal'], htf['distal'])
            if ltf_lo >= htf_lo and ltf_hi <= htf_hi:
                return True, htf
        return False, None

    def filter_by_big_brother(
        self, ltf_zones: List[Dict], htf_zones: List[Dict],
        require_coverage: bool = False,
    ) -> List[Dict]:
        """Tag every LTF zone with `has_big_brother` boolean and the parent
        HTF zone id when matched. When `require_coverage=True` also drop
        zones that have no big brother (strict mode).
        """
        out = []
        for z in ltf_zones:
            covered, parent = self.has_big_brother_coverage(z, htf_zones)
            z['has_big_brother'] = covered
            z['big_brother_id']  = parent['id'] if parent else None
            if require_coverage and not covered:
                continue
            out.append(z)
        return out

    def has_blocking_speed_bump(
        self,
        zones: List[Dict],
        target_zone: Dict,
        current_price: float,
        min_score: float = 5.0,
    ) -> bool:
        """A speed bump is "blocking" when at least one opposing zone in
        the path has a composite score >= min_score (i.e. it's qualified
        enough to actually stall the trade). Used to gate entries per
        rule #5: "NEVER counter-trend equilibrium: no edge".
        """
        bumps = self.detect_speed_bumps(zones, target_zone, current_price)
        return any(b['composite_score'] >= min_score for b in bumps)

    def align_multi_timeframe(
        self, htf_zones: List[Dict], ltf_zones: List[Dict]
    ) -> List[Dict]:
        """Cross-reference HTF and LTF zones for level-on-top scoring.

        Each HTF zone that contains the LTF distal contributes 2 points to LOL
        (capped at the methodology max of 10). Composite score is recomputed
        with the new LOL value rather than additively bumped, so multiple HTF
        matches don't compound silently.
        """
        lol_weight = self.weights['level_on_top']
        for ltf_zone in ltf_zones:
            stacks = 0
            for htf_zone in htf_zones:
                if ltf_zone['zone_type'] != htf_zone['zone_type']:
                    continue
                if ltf_zone['symbol'] != htf_zone['symbol']:
                    continue

                ltf_distal = ltf_zone['distal']
                htf_distal = htf_zone['distal']
                htf_proximal = htf_zone['proximal']

                if ltf_zone['zone_type'] == 'demand':
                    lo, hi = min(htf_distal, htf_proximal), max(htf_distal, htf_proximal)
                    if lo <= ltf_distal <= hi:
                        stacks += 1
                else:
                    lo, hi = min(htf_distal, htf_proximal), max(htf_distal, htf_proximal)
                    if lo <= ltf_distal <= hi:
                        stacks += 1

            if stacks > 0:
                lol = min(2.0 * stacks, 10.0)
                old_lol = ltf_zone.get('level_on_top_score', 0.0)
                ltf_zone['level_on_top_score'] = lol
                ltf_zone['htf_aligned'] = True
                ltf_zone['composite_score'] = round(
                    ltf_zone['composite_score'] + (lol - old_lol) * lol_weight, 2
                )

        return ltf_zones
