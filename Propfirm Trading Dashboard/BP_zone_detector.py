"""Supply/Demand Zone Detection Engine.

Implements zone detection with all 6 qualifiers + LOL per Blueprint methodology.
Scans price history for DBR, RBR, RBD, DBD formations and scores them.
"""

import pandas as pd
import os
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
        self.config = config or {}
        self.leg_in_min = config.get('leg_in_min_candles', 3)
        self.base_max = config.get('base_max_candles', 6)
        self.base_min = config.get('base_min_candles', 1)
        self.leg_out_mult = config.get('leg_out_body_multiplier', 2.0)
        self.base_wick_pct = config.get('base_wick_max_pct', 0.50)
        self.profit_margin_min = config.get('profit_margin_min_ratio', 3.0)

        # 2026-09-14 lecture reconciliation, EXPERIMENTAL, all DEFAULT OFF.
        # Each switches one rule to the 28-lesson spec so it can be measured alone
        # (RECONCILE_REPORT_2026-09-14.md). Read once here, not per candle.
        #   BP_EXPLOSIVE_STRICT=1  explosive = body_pct > 0.70 (M2 L4); code uses >= 0.70
        #   BP_BASE_MAX6=1         base may be 6 candles (M2 L6: 1-6, 4-6 acceptable);
        #                          config base_max_candles is 5
        #   BP_LEGIN_DECISIVE=1    leg-in = run of decisive same-direction candles ending
        #                          at the last candle before the base, length >= 1 (M2 L4);
        #                          code uses >= 70% same-direction over leg_in_min+1 candles
        #   BP_DBR_LEGOUT_FIX=1    DBR accepts an explosive candle as the FIRST leg-out
        #                          candle, like RBR/RBD/DBD already do
        _on = lambda k: os.environ.get(k) == '1'
        self._explosive_strict = _on('BP_EXPLOSIVE_STRICT')
        self._legin_decisive = _on('BP_LEGIN_DECISIVE')
        self._dbr_legout_fix = _on('BP_DBR_LEGOUT_FIX')
        self._base_max6 = _on('BP_BASE_MAX6')
        if self._base_max6:
            self.base_max = max(self.base_max, 6)

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
        # C-82 EXPERIMENTAL, DEFAULT OFF (`fair_zone_scan`).
        # The original loop below is a strict priority cascade: DBR, then RBR, then
        # RBD, then DBD -- and on a match it advances `i` past the ENTIRE formation
        # (leg_out_end + 1). So wherever a demand and a supply formation overlap in
        # time, the demand pattern is tested first, wins, and the supply pattern is
        # never evaluated at all. Measured consequence over 5y weekly bars on 10
        # symbols: 151 demand zones vs 45 supply, a 3.4:1 skew, reaching 24:1 on SI=F
        # and 16:1 on BABA -- BABA having FALLEN across that window, where supply
        # zones should dominate. Every downstream long bias inherits this.
        # The fair variant evaluates all four patterns at each bar and keeps every
        # match, advancing past the SHORTEST formation so overlapping zones survive.
        _fair = bool(self.config.get('fair_zone_scan', False)
                     or (self.config.get('rules', {}) or {}).get('fair_zone_scan', False)
                     or os.environ.get('BP_FAIR_ZONE_SCAN') == '1')
        while i < len(df) - 5:
            if _fair:
                _cands = [
                    (self._detect_dbr(df, i), 'demand', 'drop_base_rally'),
                    (self._detect_rbr(df, i), 'demand', 'rally_base_rally'),
                    (self._detect_rbd(df, i), 'supply', 'rally_base_drop'),
                    (self._detect_dbd(df, i), 'supply', 'drop_base_drop'),
                ]
                _hits = [(f, zt, nm) for f, zt, nm in _cands if f]
                if _hits:
                    for _f, _zt, _nm in _hits:
                        zones.append(self._score_zone(_f, df, symbol, timeframe, _zt, _nm,
                                                      with_trend=_aligns(_zt)))
                    i = min(f['leg_out_end'] for f, _, _ in _hits) + 1
                    continue
                i += 1
                continue

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

    def _decisive_run_start(self, df: pd.DataFrame, end: int, dir_: int) -> Optional[int]:
        """BP_LEGIN_DECISIVE: first index of the run of decisive (body > 50% of
        range) candles in `dir_` that ends at `end`; None if `end` itself isn't one."""
        j = end
        while j >= 0:
            c = df.iloc[j]
            if c['direction'] != dir_ or c['range'] <= 0 or c['body'] / c['range'] <= 0.50:
                break
            j -= 1
        return None if j == end else j + 1

    def _detect_dbr(self, df: pd.DataFrame, start: int) -> Optional[Dict]:
        """Detect Drop-Base-Rally (demand) formation."""
        leg_in_end = start
        if self._legin_decisive:
            leg_in_start = self._decisive_run_start(df, start, -1)
            if leg_in_start is None:
                return None
        else:
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
        # `<= leg_out_start` rejects an explosive FIRST leg-out candle -- the other
        # three detectors compare against base_end, which never rejects it.
        if leg_out_end is None or leg_out_end < leg_out_start + (0 if self._dbr_legout_fix else 1):
            return None

        return {
            'leg_in_start': leg_in_start, 'leg_in_end': leg_in_end,
            'base_start': base_start, 'base_end': base_end,
            'leg_out_start': leg_out_start, 'leg_out_end': leg_out_end
        }

    def _detect_rbr(self, df: pd.DataFrame, start: int) -> Optional[Dict]:
        """Detect Rally-Base-Rally (demand continuation) formation."""
        if self._legin_decisive:
            leg_in_start = self._decisive_run_start(df, start, 1)
            if leg_in_start is None:
                return None
        else:
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
        if self._legin_decisive:
            leg_in_start = self._decisive_run_start(df, start, 1)
            if leg_in_start is None:
                return None
        else:
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
        if self._legin_decisive:
            leg_in_start = self._decisive_run_start(df, start, -1)
            if leg_in_start is None:
                return None
        else:
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
            _explosive = body_pct > 0.70 if self._explosive_strict else body_pct >= 0.70
            if _explosive and candle['body'] >= self.leg_out_mult * max(avg_body, 0.0001):
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
        if (leg_out_body_pct > 0.70 if self._explosive_strict else leg_out_body_pct >= 0.70):
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
        elif base_candles <= (6 if self._base_max6 else 5):
            base_dur_score = 4.0  # 5 candles (6 under BP_BASE_MAX6) = marginal but acceptable
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

        # C-123, default OFF (BP_Q5_BOUNDED). The margin above runs from the zone to the
        # end of the LOADED HISTORY, so it grows with zone age and with how many bars
        # happen to be loaded -- measured 181 to 874 against a threshold of 5, which makes
        # the branch structure unreachable and scores the YOUNGEST zones worst (C-109).
        # Those are the zones nearest price, i.e. the tradeable ones.
        #
        # C-109 could not fix it because no bounded horizon was defined. The course
        # material names one: the profit margin runs to the OPPOSING zone, not to the
        # maximum of all subsequent price action. Measured here as the distance from the
        # proximal to the nearest opposing-side extreme within a bounded window, in zone
        # heights -- finite, independent of lookback, and it does not grow with age.
        #
        # Kept as a separate field. `margin_ratio` above is untouched so the existing
        # score and every recorded result stay byte-identical while the flag is off.
        _q5_window = int(self.config.get('profit_margin_lookahead_bars', 60))
        _fwd = df.iloc[zone['leg_out_end']:zone['leg_out_end'] + _q5_window]
        if len(_fwd):
            if zone_type == 'demand':
                _bounded_move = float(_fwd['high'].max()) - proximal
            else:
                _bounded_move = proximal - float(_fwd['low'].min())
            margin_ratio_bounded = _bounded_move / max(zone_height, 0.0001)
        else:
            margin_ratio_bounded = margin_ratio
        if os.environ.get('BP_Q5_BOUNDED') == '1':
            margin_ratio = margin_ratio_bounded

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

        # C-108 diagnostics. Q1/Q5/Q6 all collapse to the constant 10.0 for most
        # zones -- Q1 because its top branch repeats the detection gate verbatim
        # (`body_pct >= 0.70` at line 352 is also the condition for a leg-out to
        # exist at all), Q5/Q6 because trend-aligned zones are awarded full marks
        # so the qualifier cannot gate them. The underlying MEASUREMENTS still
        # differ between zones; only the scores are flat. Persist them so ranking
        # experiments can use the measurement instead of the flattened score.
        #
        # Read-only: nothing downstream consumes these, so emitting them cannot
        # change which zones qualify or how they are ordered.
        try:
            _avg_body = df['avg_body_20'].iloc[zone['leg_out_end']]
            if pd.isna(_avg_body) or _avg_body == 0:
                _avg_body = None
        except Exception:
            _avg_body = None
        departure_strength = (
            float(leg_out_candle['body'] / _avg_body) if _avg_body else None
        )

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
            # C-123 diagnostic: the bounded form, always emitted so the two can be
            # compared without re-running. Nothing consumes it unless BP_Q5_BOUNDED=1.
            'margin_ratio_bounded': round(margin_ratio_bounded, 2),
            # C-108 read-only diagnostics -- the measurements behind the flattened
            # Q1/Q6 scores. `departure_strength` is the leg-out body as a multiple
            # of avg_body_20 (detection only lower-bounds this at leg_out_multiplier,
            # so it stays informative above the gate); `bars_to_return` is Q6's raw
            # input before the with_trend override. Nothing consumes these.
            'departure_strength': (round(departure_strength, 3)
                                   if departure_strength is not None else None),
            'bars_to_return': int(bars_to_return),
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

    def rank_zones(self, zones: List[Dict], min_score: float = 5.0,
                   current_price: Optional[float] = None) -> List[Dict]:
        """Filter and rank zones by composite score.

        `current_price` is optional and only consulted when BP_ZONE_REACHABLE is
        set (C-110); without it the ordering is composite-only, as before.

        Hard-rejects:
          - Q5 MUST PASS gate failure (counter-trend zone with profit_margin=0)
          - Composite below min_score (default 5.0; methodology recommends 4.0+)
          - ZERO-HEIGHT zone (proximal == distal) — see C-88 below

        NOTE: a >25%-penetrated zone is NOT hard-rejected here — its Q3 freshness
        is already 0 (heavy composite penalty), and hard-rejecting it regressed
        the Bernd-clone match (Phase 37). The composite gate is the intended
        filter for consumed zones.

        C-88 (2026-08-26). A zone whose proximal equals its distal cannot produce
        a tradeable order. Downstream, `entry = proximal` and (weekly/monthly)
        `stop = distal`, so risk-per-unit is 0, `_calculate_targets` returns three
        targets all equal to the entry, and `trade_r_multiple` is forced to 0 by
        its own `abs(entry - stop) > 0` guard. The order is either rejected by the
        broker or stopped out the instant it fills.

        Nothing upstream could catch it: not one of the seven qualifiers in
        `_score_zone` looks at zone height. Measured on PL=F 2024-02-15
        (reproducible offline: run_goldtest.py --cases-file full_shard4.yaml
        --case 78 --cot-snapshot read --ohlcv-snapshot read), the degenerate zone
        scored `composite 8.8` — departure 10, base_duration 10, originality 12,
        profit_margin 10, arrival 10 — and ranked FIRST of ten, so it was the zone
        the signal was built on. It is not an edge case in the corpus: 3 of the 8
        Stage-2 signals in the whole 479-case out-of-sample run are this same
        PL=F zone, i.e. 37% of everything the system fired.

        Kill-switch: BP_ALLOW_ZERO_HEIGHT_ZONE=1 restores the old behaviour.
        """
        import os as _os
        _allow_degenerate = _os.environ.get('BP_ALLOW_ZERO_HEIGHT_ZONE') == '1'
        valid = [
            z for z in zones
            if z['composite_score'] >= min_score
            and not z.get('q5_failed_gate', False)
            and (_allow_degenerate
                 or float(z.get('proximal', 0)) != float(z.get('distal', 0)))
        ]
        # C-110: reachability as an ORDERING, not an exclusion.
        #
        # `valid` holds every same-type zone in the loaded history, and the sort
        # below is on composite alone, which contains no term for where price is
        # now. Measured over 65 drawn setups (goldtest/zone_choice_separation.py),
        # rank-1 was a zone a median 904 bars old while the zone they actually
        # traded was 467 bars old, and rank-1 sat a median 6.29R from their entry
        # -- worse than a pseudo-random pick of the same pool.
        #
        # Ranking reachable zones ahead of unreachable ones cut the median entry
        # error from 4.74R to 2.02R. The effect held at every band tried (2/5/10/20%)
        # and on both halves of the sample, so it comes from the filter, not the
        # width; 0.10 is the midpoint of that sweep and the most stable across halves.
        #
        # Deliberately an ordering and not a rejection: an unreachable zone still
        # ranks, just below every reachable one, so this cannot empty the candidate
        # list on a symbol where nothing is close. Default OFF pending the A/B.
        # C-124, default OFF (BP_NEAREST_FRESH). "Find nearest Supply Zone (First fresh)"
        # is how the course states step 1, and freshness is its single most-repeated
        # criterion -- 81 of 273 extracted rules (30%), ahead of HTF coverage (17%).
        #
        # Our implementation cannot express it. `freshness_score` is 0 on 91.6% of zones
        # on the trading path (C-108) because we score EVERY zone in the loaded history
        # and almost all of them have been retested, while he reads the current chart and
        # takes the first untested one. So the most important qualifier in the method is
        # a near-constant in the engine, and the composite that consumes it loses to a
        # pseudo-random ordering of its own pool (C-110).
        #
        # This expresses it as a FILTER-THEN-SORT rather than a score: among zones price
        # has not already consumed, take the closest. C-110 measured "nearest to price"
        # alone at 2.64R median entry error against 4.74R for the composite, so the
        # empirical result and the stated method agree; the engine does neither.
        #
        # Fresh zones are ordered ahead of stale ones and never exclude them, so this
        # cannot empty the candidate list.
        if _os.environ.get('BP_NEAREST_FRESH') == '1' and current_price:
            px = abs(float(current_price))
            valid.sort(key=lambda z: (
                0 if float(z.get('freshness_score', 0)) > 0 else 1,
                abs(float(z['proximal']) - current_price) / px,
            ))
            return valid

        _band = _os.environ.get('BP_ZONE_REACHABLE')
        if _band and current_price:
            try:
                band = float(_band) if _band != '1' else 0.10
            except ValueError:
                band = 0.10
            px = abs(float(current_price))
            valid.sort(
                key=lambda z: (
                    1 if abs(float(z['proximal']) - current_price) / px <= band else 0,
                    z['composite_score'],
                ),
                reverse=True,
            )
            return valid

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
