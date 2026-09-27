"""
Candlestick pattern recognition engine.
Implements exact conditions from DELIVERABLE_2_STRATEGY_RULEBOOK:
Hammer, Bullish Engulfing, Shooting Star, Hanging Man, Bearish Engulfing.
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, List, Any
from enum import Enum

class PatternType(str, Enum):
    HAMMER = "hammer"
    BULLISH_ENGULFING = "bullish_engulfing"
    SHOOTING_STAR = "shooting_star"
    HANGING_MAN = "hanging_man"
    BEARISH_ENGULFING = "bearish_engulfing"
    HEAD_AND_SHOULDERS = "head_and_shoulders"
    INVERSE_HEAD_AND_SHOULDERS = "inverse_head_and_shoulders"

class TradeDirection(str, Enum):
    LONG = "long"
    SHORT = "short"

class PatternDetector:
    """
    Detects candlestick patterns at supply/demand zones.
    All thresholds from the rulebook.
    """

    def __init__(self, config: Dict):
        pc = config.get('patterns', {})
        hm = pc.get('hammer', {})
        self.h_body_max = hm.get('body_max_pct', 0.30)
        self.h_lwick_min = hm.get('lower_wick_min_mult', 2.0)
        self.h_uwick_max = hm.get('upper_wick_max_pct', 0.10)

        ss = pc.get('shooting_star', {})
        self.ss_body_max = ss.get('body_max_pct', 0.30)
        self.ss_uwick_min = ss.get('upper_wick_min_mult', 2.0)
        self.ss_lwick_max = ss.get('lower_wick_max_pct', 0.10)

        hm2 = pc.get('hanging_man', {})
        self.hm_body_max = hm2.get('body_max_pct', 0.30)
        self.hm_lwick_min = hm2.get('lower_wick_min_mult', 2.0)
        self.hm_uwick_max = hm2.get('upper_wick_max_pct', 0.10)

    def detect(
        self,
        df: pd.DataFrame,
        idx: int,
        zone_type: str
    ) -> Optional[Dict]:
        """
        Detect candlestick pattern at given index.
        Returns dict with pattern details or None.

        `df` must hold COMPLETED bars only (R1, 2026-09-27): a hammer or engulfing
        read off the still-forming bar can vanish by the close. RulesEngine.
        _check_entry_pattern filters with BP_zone_detector.completed_bars first.
        """
        if idx < 1 or idx >= len(df):
            return None

        candle = df.iloc[idx]
        prev = df.iloc[idx - 1] if idx > 0 else None

        body = abs(candle['close'] - candle['open'])
        total_range = candle['high'] - candle['low']

        if total_range <= 0:
            return None

        upper_wick = candle['high'] - max(candle['close'], candle['open'])
        lower_wick = min(candle['close'], candle['open']) - candle['low']
        direction = 1 if candle['close'] > candle['open'] else -1

        # ---- Hammer (demand zone) -- textbook 7.1: must form at a higher-low
        # in an uptrend or the major low; in equilibrium/sideways the candle
        # alone isn't enough. We approximate this by requiring the prior
        # ~10 candles to have made a swing low (current low <= rolling min).
        if zone_type == 'demand':
            recent_low = df['low'].iloc[max(0, idx-10):idx].min() if idx > 0 else candle['low']
            at_swing_low = candle['low'] <= recent_low
            if self._is_hammer(body, total_range, lower_wick, upper_wick) and at_swing_low:
                return self._make_signal(
                    PatternType.HAMMER, TradeDirection.LONG,
                    candle, body, total_range, lower_wick, upper_wick, idx
                )

            if prev is not None and self._is_bullish_engulfing(candle, prev):
                return self._make_signal(
                    PatternType.BULLISH_ENGULFING, TradeDirection.LONG,
                    candle, body, total_range, lower_wick, upper_wick, idx
                )

            ihs = self._is_inverse_head_and_shoulders(df, idx)
            if ihs is not None:
                return self._make_signal(
                    PatternType.INVERSE_HEAD_AND_SHOULDERS, TradeDirection.LONG,
                    candle, body, total_range, lower_wick, upper_wick, idx,
                    custom_entry=ihs['entry'], custom_stop=ihs['stop'],
                )

        # ---- Shooting Star / Hanging Man / Bearish Engulfing (supply zone) ----
        if zone_type == 'supply':
            recent_high = df['high'].iloc[max(0, idx-10):idx].max() if idx > 0 else candle['high']
            at_swing_high = candle['high'] >= recent_high

            if self._is_shooting_star(body, total_range, upper_wick, lower_wick) and at_swing_high:
                return self._make_signal(
                    PatternType.SHOOTING_STAR, TradeDirection.SHORT,
                    candle, body, total_range, lower_wick, upper_wick, idx
                )

            if self._is_hanging_man(body, total_range, lower_wick, upper_wick) and at_swing_high:
                return self._make_signal(
                    PatternType.HANGING_MAN, TradeDirection.SHORT,
                    candle, body, total_range, lower_wick, upper_wick, idx
                )

            if prev is not None and self._is_bearish_engulfing(candle, prev):
                return self._make_signal(
                    PatternType.BEARISH_ENGULFING, TradeDirection.SHORT,
                    candle, body, total_range, lower_wick, upper_wick, idx
                )

            hs = self._is_head_and_shoulders(df, idx)
            if hs is not None:
                return self._make_signal(
                    PatternType.HEAD_AND_SHOULDERS, TradeDirection.SHORT,
                    candle, body, total_range, lower_wick, upper_wick, idx,
                    custom_entry=hs['entry'], custom_stop=hs['stop'],
                )

        return None

    def _is_head_and_shoulders(self, df, idx) -> Optional[Dict]:
        """Detect Head & Shoulders top at index `idx`.

        Looks back ~30 bars for three swing highs where the middle is the
        highest. Neckline is the average of the two intervening swing lows.
        Entry is on a close below the neckline; stop is above the right
        shoulder.
        """
        if idx < 20:
            return None
        window = df.iloc[max(0, idx-30):idx+1]
        highs = window['high'].values
        lows  = window['low'].values
        n = len(highs)
        # Identify swing highs (3-bar local max)
        swing_highs = [i for i in range(2, n-2)
                       if highs[i] > highs[i-1] and highs[i] > highs[i-2]
                       and highs[i] > highs[i+1] and highs[i] > highs[i+2]]
        if len(swing_highs) < 3:
            return None
        # Use the three most recent
        l, h, r = swing_highs[-3], swing_highs[-2], swing_highs[-1]
        if not (highs[h] > highs[l] and highs[h] > highs[r]):
            return None
        # Shoulders should be roughly equal (within 5%)
        if abs(highs[l] - highs[r]) / highs[h] > 0.05:
            return None
        # Neckline: lowest low between l..h and h..r
        neck_left  = lows[l:h+1].min()
        neck_right = lows[h:r+1].min()
        neckline = (neck_left + neck_right) / 2.0
        # Confirmation: most recent close has broken below the neckline
        if df['close'].iloc[idx] >= neckline:
            return None
        # Stop: -33% Fib of the pattern range above the right shoulder high
        # (per OTC L7 frame 917 — universal -33% rule, not a flat % buffer)
        pattern_range = highs[h] - neckline   # head-to-neckline span
        return {
            'entry': float(neckline),
            'stop':  float(highs[r] + 0.33 * pattern_range),
        }

    def _is_inverse_head_and_shoulders(self, df, idx) -> Optional[Dict]:
        """Mirror of head-and-shoulders for demand zones."""
        if idx < 20:
            return None
        window = df.iloc[max(0, idx-30):idx+1]
        highs = window['high'].values
        lows  = window['low'].values
        n = len(lows)
        swing_lows = [i for i in range(2, n-2)
                      if lows[i] < lows[i-1] and lows[i] < lows[i-2]
                      and lows[i] < lows[i+1] and lows[i] < lows[i+2]]
        if len(swing_lows) < 3:
            return None
        l, h, r = swing_lows[-3], swing_lows[-2], swing_lows[-1]
        if not (lows[h] < lows[l] and lows[h] < lows[r]):
            return None
        if abs(lows[l] - lows[r]) / max(lows[h], 1e-9) > 0.05:
            return None
        neck_left  = highs[l:h+1].max()
        neck_right = highs[h:r+1].max()
        neckline = (neck_left + neck_right) / 2.0
        if df['close'].iloc[idx] <= neckline:
            return None
        # Stop: -33% Fib below the right shoulder low (universal rule)
        pattern_range = neckline - lows[h]    # neckline-to-head span
        return {
            'entry': float(neckline),
            'stop':  float(lows[r] - 0.33 * pattern_range),
        }

    def _is_hammer(self, body, total_range, lower_wick, upper_wick) -> bool:
        if body / total_range > self.h_body_max:
            return False
        if body == 0:
            return False
        if lower_wick < self.h_lwick_min * body:
            return False
        if upper_wick > self.h_uwick_max * total_range:
            return False
        return True

    def _is_shooting_star(self, body, total_range, upper_wick, lower_wick) -> bool:
        if body / total_range > self.ss_body_max:
            return False
        if body == 0:
            return False
        if upper_wick < self.ss_uwick_min * body:
            return False
        if lower_wick > self.ss_lwick_max * total_range:
            return False
        return True

    def _is_hanging_man(self, body, total_range, lower_wick, upper_wick) -> bool:
        if body / total_range > self.hm_body_max:
            return False
        if body == 0:
            return False
        if lower_wick < self.hm_lwick_min * body:
            return False
        if upper_wick > self.hm_uwick_max * total_range:
            return False
        return True

    def _is_bullish_engulfing(self, candle, prev) -> bool:
        if candle['close'] <= candle['open']:
            return False
        if prev['close'] >= prev['open']:
            return False
        if candle['open'] >= prev['close']:
            return False
        if candle['close'] <= prev['open']:
            return False
        if candle['low'] > prev['low']:
            return False
        return True

    def _is_bearish_engulfing(self, candle, prev) -> bool:
        if candle['close'] >= candle['open']:
            return False
        if prev['close'] <= prev['open']:
            return False
        if candle['open'] <= prev['close']:
            return False
        if candle['close'] >= prev['open']:
            return False
        if candle['high'] < prev['high']:
            return False
        return True

    def _make_signal(self, pattern_type, direction, candle, body, total_range, lower_wick, upper_wick, idx, custom_entry=None, custom_stop=None):
        # R3 (2026-09-27, defect 4): each entry carries the ORDER TYPE it must be
        # placed as. A candle-pattern entry sits 0.1% BEYOND the pattern bar's extreme
        # in the trade direction (E3b, methodology/04 "stop-buy above hammer high":
        # "only triggers if price continues in the expected direction"), i.e. it is a
        # STOP order -- a long fills only when price trades UP to it. The live account
        # booked these like limits, "filling" when price was BELOW the buy-stop, which
        # is exactly the case where the setup had failed.
        # The head-and-shoulders family is the exception: detection already requires a
        # close through the neckline, and the entry is the neckline itself, so the
        # order that waits there is a neckline-retest LIMIT (price is past it in the
        # profit direction and must come back to it).
        if custom_entry is not None and custom_stop is not None:
            entry, stop = custom_entry, custom_stop
            order_type = 'limit'
        elif direction == TradeDirection.LONG:
            entry = candle['high'] * 1.001
            stop = candle['low'] - 0.33 * (candle['high'] - candle['low'])
            order_type = 'stop'
        else:
            entry = candle['low'] * 0.999
            stop = candle['high'] + 0.33 * (candle['high'] - candle['low'])
            order_type = 'stop'

        risk = abs(entry - stop)
        return {
            'order_type': order_type,
            # Pattern bar's timestamp (empty when the frame has none), for display and
            # audit: which completed bar the entry was built from.
            'candle_time': str(candle.get('timestamp', '')),
            'pattern_type': pattern_type,
            'direction': direction,
            'entry_price': round(entry, 6),
            'stop_price': round(stop, 6),
            'target_r1': round(entry + risk if direction == TradeDirection.LONG else entry - risk, 6),
            'target_r2': round(entry + 2 * risk if direction == TradeDirection.LONG else entry - 2 * risk, 6),
            'target_r3': round(entry + 3 * risk if direction == TradeDirection.LONG else entry - 3 * risk, 6),
            'confidence': 0.8,
            'candle_index': idx
        }