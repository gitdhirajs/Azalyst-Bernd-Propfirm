"""Indicator Engine - Ported Pine Script logic for COT Index, Valuation, Seasonality.

Implements all corrections from DELIVERABLE_3_INDICATOR_CORRECTION_BLUEPRINT.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class COTIndex:
    """
    Commitment of Traders Index — COT V2 formula, range -20 to 120.

    Formula (matches COT V2 120-20.txt Pine Script):
        index = 140 * (netPos - lowest(n)) / (highest(n) - lowest(n)) - 20

    Scale: -20 (most bearish possible) → 120 (most bullish possible).
    Thresholds: upper=80, lower=20 (same as V1 — but with the stretched
    scale a reading above 80 now corresponds to the top ~28.6% of range
    rather than the top 20%, so extreme signals fire more frequently).

    156-week "extreme" overlay uses the same formula over a longer window.
    A reading extreme on BOTH rolling and 156w windows = 'strong' signal.
    """

    # Textbook: 156-week extreme is the highest-conviction COT signal because
    # it captures multi-year regime extremes, not just yearly ones.
    EXTREME_LOOKBACK_WEEKS = 156

    def __init__(
        self,
        lookback_weeks: int = 52,
        upper_extreme: float = 80.0,
        lower_extreme: float = 20.0,
        extreme_lookback: int = EXTREME_LOOKBACK_WEEKS,
    ):
        self.lookback_weeks = lookback_weeks
        self.upper_extreme = upper_extreme
        self.lower_extreme = lower_extreme
        self.extreme_lookback = extreme_lookback

    def calculate(
        self,
        cot_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Calculate COT V2 Index (-20 to 120) for all three trader categories.

        Uses the COT V2 formula: 140 * (net - min_n) / (max_n - min_n) - 20.
        Range: -20 (extreme bearish) to 120 (extreme bullish).

        Args:
            cot_df: DataFrame with columns: comm_long, comm_short, noncomm_long,
                    noncomm_short, nonrep_long, nonrep_short

        Returns:
            DataFrame with columns: commercials_index, large_specs_index,
                    small_specs_index, comm_net, lspec_net, sspec_net
                    + _extreme variants for 156-week window
        """
        df = cot_df.copy()

        # Calculate net positions
        df['comm_net'] = df['comm_long'] - df['comm_short']
        df['lspec_net'] = df['noncomm_long'] - df['noncomm_short']
        df['sspec_net'] = df['nonrep_long'] - df['nonrep_short']

        window = self.lookback_weeks

        # Calculate rolling min/max for normalization
        comm_min = df['comm_net'].rolling(window=window, min_periods=1).min()
        comm_max = df['comm_net'].rolling(window=window, min_periods=1).max()
        lspec_min = df['lspec_net'].rolling(window=window, min_periods=1).min()
        lspec_max = df['lspec_net'].rolling(window=window, min_periods=1).max()
        sspec_min = df['sspec_net'].rolling(window=window, min_periods=1).min()
        sspec_max = df['sspec_net'].rolling(window=window, min_periods=1).max()

        # COT V2 formula: 140 * (value - min) / (max - min) - 20
        # Range: -20 (extreme bearish) to 120 (extreme bullish).
        # Matches pinescript/COT V2 120-20.txt (the indicator Bernd uses on
        # TradeStation).  Upper threshold=80, lower=20 unchanged from defaults.
        df['commercials_index'] = np.where(
            comm_max != comm_min,
            140.0 * (df['comm_net'] - comm_min) / (comm_max - comm_min) - 20.0,
            np.nan
        )
        df['large_specs_index'] = np.where(
            lspec_max != lspec_min,
            140.0 * (df['lspec_net'] - lspec_min) / (lspec_max - lspec_min) - 20.0,
            np.nan
        )
        df['small_specs_index'] = np.where(
            sspec_max != sspec_min,
            140.0 * (df['sspec_net'] - sspec_min) / (sspec_max - sspec_min) - 20.0,
            np.nan
        )

        # 156-week extreme overlay: same COT V2 formula over a longer window.
        # Used by the rules engine to gate "strong" signals — a reading that
        # is extreme on the rolling lookback AND on the 156w window is the
        # textbook's highest-conviction COT signal.
        ext = self.extreme_lookback
        for col in ('comm_net', 'lspec_net', 'sspec_net'):
            mn = df[col].rolling(window=ext, min_periods=1).min()
            mx = df[col].rolling(window=ext, min_periods=1).max()
            df[col + '_extreme'] = np.where(
                mx != mn,
                140.0 * (df[col] - mn) / (mx - mn) - 20.0,
                np.nan,
            )

        # ALL-TIME expanding extreme: normalize each week against all prior
        # history available up to that point (expanding window).
        #
        # Bernd: "pull as much data as you can" — a position that is extreme
        # versus the ENTIRE CFTC history (~30 years for Gold, WTI, etc.) carries
        # far more weight than a reading that is only extreme versus 156 weeks.
        #
        # Using expanding() gives a TIME SERIES so the dashboard can plot how
        # the all-time context has evolved.  The companion
        # producer_vs_retailer_summary() method uses the GLOBAL min/max for a
        # clean snapshot of "where does today's positioning rank over all time".
        for col in ('comm_net', 'lspec_net', 'sspec_net'):
            all_min = df[col].expanding(min_periods=1).min()
            all_max = df[col].expanding(min_periods=1).max()
            df[col + '_alltime'] = np.where(
                all_max != all_min,
                140.0 * (df[col] - all_min) / (all_max - all_min) - 20.0,
                np.nan,
            )

        return df

    def producer_vs_retailer_summary(self, cot_df: pd.DataFrame) -> Dict:
        """
        Full-history producer vs retailer deep comparison.

        Bernd teaches: compare producers (commercials) against retailers
        (non-reportables) over the MAXIMUM available history.  When both
        groups are at OPPOSITE all-time extremes simultaneously, that is the
        highest-conviction institutional signal in his system.

        Call this after fetching full history via
        DataFetcher.fetch_cot_full_history() to get the 30-year context.

        Returns a dict with:
          years_of_data       — float, years covered by the dataset
          total_weeks         — int, total weekly reports
          current_comm_net    — int, current commercials net contracts
          current_sspec_net   — int, current retailers net contracts
          current_lspec_net   — int, current large specs net contracts
          comm_percentile     — float 0–100, rank vs all-time history
          sspec_percentile    — float 0–100, rank vs all-time history
          lspec_percentile    — float 0–100, rank vs all-time history
          alltime_comm_index  — float, COT V2 score vs all-time (−20 to +120)
          alltime_sspec_index — float, COT V2 score vs all-time
          alltime_lspec_index — float, COT V2 score vs all-time
          signal              — 'STRONG BUY' / 'STRONG SELL' / 'BULLISH' /
                                'BEARISH' / 'NEUTRAL'
          detail              — human-readable explanation
          summary             — short label (same as signal + all-time tag)
        """
        if cot_df is None or cot_df.empty or len(cot_df) < 10:
            return {
                'summary': 'Insufficient data',
                'signal':  'NEUTRAL',
                'detail':  'Need at least 10 weeks of COT data',
                'years_of_data': 0,
                'total_weeks': 0,
            }

        df = cot_df.copy()
        df['comm_net']  = df['comm_long']    - df['comm_short']
        df['lspec_net'] = df['noncomm_long'] - df['noncomm_short']
        df['sspec_net'] = df['nonrep_long']  - df['nonrep_short']

        n = len(df)
        years = (df.index[-1] - df.index[0]).days / 365.25

        curr_comm  = df['comm_net'].iloc[-1]
        curr_sspec = df['sspec_net'].iloc[-1]
        curr_lspec = df['lspec_net'].iloc[-1]

        # Percentile rank (what fraction of all historical weeks had a LOWER net)
        comm_pct  = float((df['comm_net']  < curr_comm ).sum()  / n * 100)
        sspec_pct = float((df['sspec_net'] < curr_sspec).sum()  / n * 100)
        lspec_pct = float((df['lspec_net'] < curr_lspec).sum()  / n * 100)

        # COT V2 score vs ALL available history (global min/max, not rolling)
        def _v2(val, col):
            mn, mx = df[col].min(), df[col].max()
            if mx == mn:
                return 50.0
            return float(140.0 * (val - mn) / (mx - mn) - 20.0)

        at_comm  = _v2(curr_comm,  'comm_net')
        at_sspec = _v2(curr_sspec, 'sspec_net')
        at_lspec = _v2(curr_lspec, 'lspec_net')

        upper = self.upper_extreme   # 80
        lower = self.lower_extreme   # 20

        comm_ext_long   = at_comm  >= upper
        comm_ext_short  = at_comm  <= lower
        sspec_ext_long  = at_sspec >= upper
        sspec_ext_short = at_sspec <= lower

        # Determine signal — mirrors cross_category_signal() but on all-time scale
        if comm_ext_long and sspec_ext_short:
            signal = 'STRONG BUY'
            detail = (
                f"Commercials all-time extreme LONG ({at_comm:.1f}) + "
                f"Retailers all-time extreme SHORT ({at_sspec:.1f}) "
                f"- smart money vs dumb money at {years:.0f}-year extremes"
            )
        elif comm_ext_short and sspec_ext_long:
            signal = 'STRONG SELL'
            detail = (
                f"Commercials all-time extreme SHORT ({at_comm:.1f}) + "
                f"Retailers all-time extreme LONG ({at_sspec:.1f}) "
                f"- producers distributing into retail euphoria"
            )
        elif comm_ext_long:
            signal = 'BULLISH'
            detail = (
                f"Commercials at all-time extreme LONG ({at_comm:.1f}, "
                f"{comm_pct:.0f}th pct of {years:.0f} yrs); "
                f"retailers not yet at opposite extreme ({at_sspec:.1f})"
            )
        elif comm_ext_short:
            signal = 'BEARISH'
            detail = (
                f"Commercials at all-time extreme SHORT ({at_comm:.1f}, "
                f"{comm_pct:.0f}th pct of {years:.0f} yrs)"
            )
        elif sspec_ext_short:
            signal = 'BULLISH'
            detail = (
                f"Retailers at all-time extreme SHORT ({at_sspec:.1f}) "
                f"- contrarian buy signal over {years:.0f}-year history"
            )
        elif sspec_ext_long:
            signal = 'BEARISH'
            detail = (
                f"Retailers at all-time extreme LONG ({at_sspec:.1f}) "
                f"- contrarian sell signal"
            )
        else:
            signal = 'NEUTRAL'
            detail = (
                f"No all-time extremes - "
                f"Comm: {at_comm:.1f} ({comm_pct:.0f}th pct), "
                f"Retail: {at_sspec:.1f} ({sspec_pct:.0f}th pct) "
                f"over {years:.0f}-year history"
            )

        return {
            'summary':            signal + ' (all-time)',
            'signal':             signal,
            'detail':             detail,
            'years_of_data':      round(years, 1),
            'total_weeks':        n,
            'current_comm_net':   int(curr_comm),
            'current_sspec_net':  int(curr_sspec),
            'current_lspec_net':  int(curr_lspec),
            'comm_percentile':    round(comm_pct, 1),
            'sspec_percentile':   round(sspec_pct, 1),
            'lspec_percentile':   round(lspec_pct, 1),
            'alltime_comm_index': round(at_comm, 1),
            'alltime_sspec_index':round(at_sspec, 1),
            'alltime_lspec_index':round(at_lspec, 1),
        }

    def get_bias(
        self,
        cot_df: pd.DataFrame,
        asset_class: str = 'commodities',
        return_strength: bool = False,
    ):
        """
        Determine COT directional bias from latest data.

        Asset-class-specific interpretation (Hybrid AI course, OTC 2025):
        - Commodities / Energies: Trade WITH Commercials (>=80 bullish, <=20 bearish)
        - Forex: Non-Commercials extreme positioning
        - Equities / Indices: Non-Commercials with shorter (26-week) lookback
        - Precious Metals: Retailers CONTRARIAN (crowd reversal)

        High-conviction layer: when the rolling-window index AND the 156-week
        "historic extreme" overlay both register at the same end of the
        spectrum, the signal is strong. When only the rolling window is
        extreme, the signal is normal. Returning a 'strength' flag lets the
        rules engine treat strong signals as overrides.

        Returns:
            str when return_strength=False
            (bias, strength) tuple when return_strength=True
                strength is one of 'strong', 'normal', 'none'
        """
        if cot_df.empty:
            return ('neutral', 'none') if return_strength else 'neutral'

        latest = cot_df.iloc[-1]
        comm_idx  = latest.get('commercials_index', 50)
        lspec_idx = latest.get('large_specs_index', 50)
        sspec_idx = latest.get('small_specs_index', 50)
        comm_ext  = latest.get('comm_net_extreme', None)
        lspec_ext = latest.get('lspec_net_extreme', None)
        sspec_ext = latest.get('sspec_net_extreme', None)

        # Pick the relevant trader category for this asset class
        if asset_class in ('commodities', 'energies'):
            primary, ext = comm_idx, comm_ext
            contrarian = False
        elif asset_class == 'soft_commodities':
            # CLAUDE.md P1: Cotton/Grains/Cocoa/Coffee use Non-Commercials (large specs)
            # with a Divergence (trade-WITH) approach, same as forex/equities.
            # At extreme longs (>80) → bullish; extreme shorts (<20) → bearish.
            primary, ext = lspec_idx, lspec_ext
            contrarian = False
        elif asset_class == 'forex':
            primary, ext = lspec_idx, lspec_ext
            contrarian = False
        elif asset_class in ('equity_indices', 'equities'):
            primary, ext = lspec_idx, lspec_ext
            contrarian = False
        elif asset_class == 'precious_metals':
            # Phase 17 fix: Blueprint Cheatsheet (Phase 12) + Phase 14 corpus (Ch.107/147/122/132)
            # all confirm Commercials ① as PRIMARY for Gold/Silver/Palladium.
            # The earlier "Retailers CONTRARIAN" entry in the methodology table was incorrect —
            # Retailers are a SECONDARY confirming indicator (③), not the primary driver.
            # "Retailers bearish + Commercials bullish = perfect PM buy" (Ch.147/122/132).
            # Ch.107 (GC=F Oct 2023): Bernd explicitly shows Commercials when discussing gold COT.
            # When Commercials extreme LONG (≥80) → BULLISH; extreme SHORT (≤20) → BEARISH.
            primary, ext = comm_idx, comm_ext
            contrarian = False
        elif asset_class == 'nat_gas':
            # Phase 41 S-01 (chunk2 speech): LESSON 2 PART 3 ENERGIES frames + FT Signals Apr23
            # both show "Fund Managers" (non-commercials/lspec) as the DISPLAYED primary COT panel
            # for NG=F. The retailer panel is a SECONDARY contra signal -- Bernd says
            # "retailers buying is troublesome" (contra alarm) while reading Fund Managers as the
            # directional primary. CW07 (chunk6 speech) transcript 0:24:40 confirms retailers are a
            # VETO signal: "if retailers are getting more bullish I'm not willing to get in any long."
            # Architecture: non-commercials (lspec) are PRIMARY; retailer extreme = directional veto.
            # Using lspec (non-commercials) as primary, non-contrarian (like forex).
            # The retailer veto is handled in BP_rules_engine._analyze_fundamentals via the
            # cross_category_signal / directional-alignment veto logic.
            primary, ext = lspec_idx, lspec_ext
            contrarian = False
        else:
            primary, ext = comm_idx, comm_ext
            contrarian = False

        bias = 'neutral'
        if primary >= self.upper_extreme:
            bias = 'bearish' if contrarian else 'bullish'
        elif primary <= self.lower_extreme:
            bias = 'bullish' if contrarian else 'bearish'

        # Phase 18 — 156w-only secondary trigger:
        # When the 26w rolling index is APPROACHING extreme (≥60 for bullish, ≤40 for bearish)
        # but hasn't crossed the 80/20 threshold yet, AND the 156-week historic extreme IS already
        # beyond the threshold, Bernd acts on the "yellow line" in COT V2.
        # GC=F Aug 2023 is the canonical example: comm_idx_26w=68.59 (approaching) +
        # comm_net_extreme_156w=86.32 (historic extreme) → Bernd = long gold.
        # Signal strength is 'normal' (not 'strong') since the 26w hasn't confirmed yet.
        #
        # IMPORTANT: Only applies to COT-is-king asset classes (commodities, precious_metals,
        # energies, nat_gas). "COT is king" is Bernd's rule SPECIFICALLY for commercial hedgers
        # in commodity markets — NOT for equity indices or forex where non-commercials are used
        # and COT is a confluence enhancer, not an override trigger.
        # Restricting to COT-king classes prevents false bearish signals on ES/YM/NQ from
        # non-commercial extreme positioning at the 156w scale. (Phase 18 regression fix)
        # Phase 43 Fix-A: extend 156w approaching-extreme trigger to forex.
        # Chapter 016 (COT Non-Commercials, Phase 43 corpus audit) verbatim:
        # "when we come from multi year extremes that's when we pay attention right multi year high"
        # Bernd applies the identical multi-year extreme logic to forex non-commercials as to
        # commodity commercials. Phase 18 restricted this to COT-king classes only; the
        # forex exclusion was a regression-prevention measure for equity indices (ES/YM/NQ),
        # not a deliberate exclusion of forex. The 'large_specs_index' primary_col already
        # correctly maps to forex in the momentum trigger below.
        _COT_KING_CLASSES_156W = ('commodities', 'energies', 'precious_metals', 'nat_gas',
                                   'soft_commodities', 'forex')
        if bias == 'neutral' and asset_class in _COT_KING_CLASSES_156W:
            # Phase 45: lowered from 0.75 (60.0) → 0.625 (50.0).
            # GC=F Sep 9 2023 canonical miss: comm_idx=55-58 between reports —
            # the 26w dips below 60 during a weekly data gap but 156w stays extreme.
            # At 50 the trigger is still guarded by the 156w hard threshold (≥80).
            _approach_bull = self.upper_extreme * 0.625  # 80 * 0.625 = 50.0
            _approach_bear = self.lower_extreme + (self.upper_extreme - self.lower_extreme) * 0.25  # 20+15=35
            if ext is not None and not pd.isna(ext):
                if primary >= _approach_bull and ext >= self.upper_extreme:
                    bias = 'bearish' if contrarian else 'bullish'
                elif primary <= _approach_bear and ext <= self.lower_extreme:
                    bias = 'bullish' if contrarian else 'bearish'

            # DeepSeek Gap 4: COT momentum trigger.
            # When 26w index is trending strongly toward extreme over 5 weeks
            # and 156w is already at extreme, act early before threshold is crossed.
            if bias == 'neutral':
                primary_col = (
                    'commercials_index' if asset_class in ('commodities', 'energies', 'precious_metals')
                    else 'large_specs_index' if asset_class in ('soft_commodities', 'forex', 'equity_indices', 'equities', 'nat_gas')
                    else 'small_specs_index'
                )
                if primary_col in cot_df.columns and len(cot_df) >= 6:
                    # Keep the original [-6:-1] window: it is the calibration the
                    # Bernd-clone momentum trigger was tuned against. (Ending the
                    # window on the latest report instead is arguably "less
                    # lagged", but shifting it perturbed the tuned PM signals with
                    # no safety benefit, so leave the tuned window in place.)
                    recent = cot_df[primary_col].iloc[-6:-1]
                    if not recent.isna().any():
                        change = recent.iloc[-1] - recent.iloc[0]
                        delta = (self.upper_extreme - self.lower_extreme) * 0.25
                        if ext is not None and not pd.isna(ext):
                            if change >= delta and ext >= self.upper_extreme:
                                bias = 'bearish' if contrarian else 'bullish'
                            elif change <= -delta and ext <= self.lower_extreme:
                                bias = 'bullish' if contrarian else 'bearish'

        # Strength: strong when 156-week extreme also registers at the same end.
        #
        # For NON-contrarian indicators (commercials, large specs):
        #   Bullish = primary >= upper_extreme (group is max long) → strong if ext also >= upper_extreme
        #   Bearish = primary <= lower_extreme (group is max short) → strong if ext also <= lower_extreme
        #
        # For CONTRARIAN indicators (retailers / small specs for PMs and NG):
        #   Bullish signal = retailers at extreme SHORT (primary >= upper_extreme, i.e. sspec_idx ≥ 80)
        #     → contrarian interpretation: BUY. The 156w extreme (ext) reflects the SAME group's
        #       position, so ext >= upper_extreme confirms retailers are at a HISTORIC SHORT extreme
        #       = strongest contrarian bullish conviction.  (NOT ext <= lower_extreme — that would
        #       mean the 156w shows retailers at extreme LONG, contradicting the rolling signal.)
        #   Bearish signal = retailers at extreme LONG (primary <= lower_extreme, sspec_idx ≤ 20)
        #     → contrarian interpretation: SELL. ext <= lower_extreme confirms 156w historic LONG.
        #
        # The previous code had lines 3 and 4 inverted (Phase 17 fix — contrarian ext direction bug).
        strength = 'none'
        if bias != 'neutral':
            if ext is not None and not pd.isna(ext):
                if (bias == 'bullish' and not contrarian and ext >= self.upper_extreme) or \
                   (bias == 'bearish' and not contrarian and ext <= self.lower_extreme) or \
                   (bias == 'bullish' and contrarian and ext >= self.upper_extreme) or \
                   (bias == 'bearish' and contrarian and ext <= self.lower_extreme):
                    strength = 'strong'
                else:
                    strength = 'normal'
            else:
                strength = 'normal'

        return (bias, strength) if return_strength else bias

    def detect_divergence(
        self,
        cot_df: pd.DataFrame,
        price_df: pd.DataFrame,
        asset_class: str = 'forex',
        lookback_weeks: int = 26,
    ) -> str:
        """Detect bullish / bearish COT-vs-price divergence over the recent
        lookback window (HAI Module 3 Lesson 1 Part 3 — non-commercials).

            Bullish divergence: price makes new LOW + COT index makes HIGHER low
            Bearish divergence: price makes new HIGH + COT index makes LOWER high

        Returns 'bullish' / 'bearish' / 'none'. Only relevant for forex /
        equity_indices (where divergence is the primary non-commercial signal);
        returns 'none' for commodities / precious_metals which use trade-WITH
        or contrarian rules instead.
        """
        if cot_df is None or cot_df.empty or price_df is None or price_df.empty:
            return 'none'
        if asset_class not in ('forex', 'equity_indices', 'equities'):
            return 'none'

        cat_col = 'large_specs_index'
        if cat_col not in cot_df.columns:
            return 'none'

        try:
            # Align on date — take most recent N weeks
            cot_window = cot_df[cat_col].dropna().iloc[-lookback_weeks:]
            if len(cot_window) < 10:
                return 'none'
            price_window = price_df['close'].iloc[-lookback_weeks:]
            if len(price_window) < 10:
                return 'none'

            # Find two most recent extrema in each series (split window in half)
            half = len(cot_window) // 2
            old_lo, new_lo = price_window.iloc[:half].min(), price_window.iloc[half:].min()
            old_hi, new_hi = price_window.iloc[:half].max(), price_window.iloc[half:].max()
            cot_old_lo, cot_new_lo = cot_window.iloc[:half].min(), cot_window.iloc[half:].min()
            cot_old_hi, cot_new_hi = cot_window.iloc[:half].max(), cot_window.iloc[half:].max()

            # Bullish divergence: price LOWER low + COT HIGHER low
            if new_lo < old_lo and cot_new_lo > cot_old_lo:
                return 'bullish'
            # Bearish divergence: price HIGHER high + COT LOWER high
            if new_hi > old_hi and cot_new_hi < cot_old_hi:
                return 'bearish'
            return 'none'
        except Exception:
            return 'none'

    def cross_category_signal(
        self,
        cot_calculated: pd.DataFrame,
    ) -> Dict[str, str]:
        """Pairwise COT category relationships — the relational layer Bernd
        teaches across all three courses (OTC L2 retailers/commercials side-
        by-side; HAI Mod 3 L1 Part 2 retailers contrarian; FT outlooks
        "smart money on one side, retail on the other" pattern).

        The single-category extreme is weaker than the RELATIONAL pattern.
        When commercials AND retailers sit at OPPOSITE extremes simultaneously,
        that's the highest-conviction smart-money-vs-dumb-money setup.

        Returns dict of three signals:

          smart_vs_dumb : commercials vs retailers
              'bullish' = comm extreme long  + retailers extreme short
              'bearish' = comm extreme short + retailers extreme long
              'aligned' = both at same end (no edge — retail right by accident)
              'mixed'   = neither at extreme

          funds_vs_commercials : non-commercials vs commercials alignment
              'bullish_aligned'   = both extreme long  (trend continuation)
              'bearish_aligned'   = both extreme short
              'bullish_divergence'= commercials long + funds short (fund following next)
              'bearish_divergence'= commercials short + funds long
              'mixed'

          extreme_confluence : True when smart_vs_dumb is bullish/bearish
              (highest-conviction signal — overrides single-category neutrals)
        """
        if cot_calculated is None or cot_calculated.empty:
            return {'smart_vs_dumb': 'mixed', 'funds_vs_commercials': 'mixed',
                    'extreme_confluence': False}

        last = cot_calculated.iloc[-1]
        comm_idx  = last.get('commercials_index', 50)
        lspec_idx = last.get('large_specs_index', 50)
        sspec_idx = last.get('small_specs_index', 50)

        upper = self.upper_extreme
        lower = self.lower_extreme

        comm_long_ext  = comm_idx  >= upper
        comm_short_ext = comm_idx  <= lower
        sspec_long_ext = sspec_idx >= upper
        sspec_short_ext= sspec_idx <= lower
        lspec_long_ext = lspec_idx >= upper
        lspec_short_ext= lspec_idx <= lower

        # ---- Smart-vs-dumb (Commercials vs Retailers) ----
        # The classic "producer vs retail trader" relationship -- producers are
        # almost always right at extremes; retailers are almost always wrong.
        if comm_long_ext and sspec_short_ext:
            smart_vs_dumb = 'bullish'    # smart money long, dumb money short -> BUY
        elif comm_short_ext and sspec_long_ext:
            smart_vs_dumb = 'bearish'    # smart money short, dumb money long -> SELL
        elif (comm_long_ext and sspec_long_ext) or (comm_short_ext and sspec_short_ext):
            smart_vs_dumb = 'aligned'    # both at same end -- no smart-money edge
        else:
            smart_vs_dumb = 'mixed'

        # ---- Funds vs Commercials (Hedge Fund follow-through) ----
        # Non-commercials are trend followers; when they ALIGN with commercials
        # at extremes, the trend has confirmation. When they DIVERGE, a turning
        # point may be near (per HAI Mod 3 L1 Part 3 divergence rule).
        if comm_long_ext and lspec_long_ext:
            funds_vs_commercials = 'bullish_aligned'
        elif comm_short_ext and lspec_short_ext:
            funds_vs_commercials = 'bearish_aligned'
        elif comm_long_ext and lspec_short_ext:
            funds_vs_commercials = 'bullish_divergence'  # commercials accumulating, funds yet to follow
        elif comm_short_ext and lspec_long_ext:
            funds_vs_commercials = 'bearish_divergence'
        else:
            funds_vs_commercials = 'mixed'

        return {
            'smart_vs_dumb':         smart_vs_dumb,
            'funds_vs_commercials':  funds_vs_commercials,
            'extreme_confluence':    smart_vs_dumb in ('bullish', 'bearish'),
        }


class COTReport:
    """
    Raw COT positions report -- mirrors the textbook's COTReport_OTC.txt
    Pine Script. Plots actual contract counts (longs as positive numbers,
    shorts as negative) and the net for each trader category. Used to
    track the *direction* of institutional flows over time, complementary
    to the normalized COTIndex.
    """

    def calculate(self, cot_df: pd.DataFrame) -> pd.DataFrame:
        if cot_df is None or cot_df.empty:
            return pd.DataFrame()
        df = cot_df.copy()
        # Net positions
        df['comm_net']    = df['comm_long']    - df['comm_short']
        df['lspec_net']   = df['noncomm_long'] - df['noncomm_short']
        df['sspec_net']   = df['nonrep_long']  - df['nonrep_short']
        # Shorts as negative (Pine Script convention with shortnegative=true)
        df['comm_short_neg']    = -df['comm_short']
        df['noncomm_short_neg'] = -df['noncomm_short']
        df['nonrep_short_neg']  = -df['nonrep_short']
        return df

    # Asset classes that exclude this indicator (no commercial-data coverage Bernd
    # trusts for the zero-line rule). Confirmed visually in the HAI Module 4 PMs
    # practical: "in platinum it will not show this".
    _ZERO_LINE_EXCLUSIONS = {'platinum'}

    def zero_line_signal(
        self,
        cot_df: pd.DataFrame,
        asset_class: str,
        symbol_hint: str = '',
    ) -> Optional[Dict[str, str]]:
        """
        Implements Bernd's "Golden Rule" zero-line crossing on the raw COT Report
        commercials net curve. Asset-class-specific because the implication
        flips between metals and equities.

        Visually confirmed (frame_002887, COT PART 2 lesson):
            "Golden Rule Precious Metals: If Commercials are NET Long
             — The ultimate buy signal."

        Visually confirmed inverse for equity indices (frame_000534/000557,
        CW24 funded session): commercials net long = bearish (commercials
        hedging long inventory).

        Returns {'signal': 'buy'|'sell', 'rule': '...', 'state': 'entered'|'sustained'}
        or None when the rule does not apply / no signal.
        """
        if cot_df is None or cot_df.empty or 'comm_long' not in cot_df.columns:
            return None
        # Platinum exclusion (HAI Mod 4 PMs practical: "in platinum it will not show this").
        if symbol_hint:
            sh = symbol_hint.lower()
            if any(p in sh for p in ('platinum', 'pl=f', 'ppltf')) or sh.startswith('pl'):
                return None
        if asset_class in self._ZERO_LINE_EXCLUSIONS:
            return None

        net = cot_df['comm_long'] - cot_df['comm_short']
        if len(net) < 2:
            return None
        last, prev = net.iloc[-1], net.iloc[-2]
        if pd.isna(last) or pd.isna(prev):
            return None

        # precious_metals excl. platinum: net long = BUY (Golden Rule).
        # equities/indices: net long = SELL (commercials hedge inventory).
        # Other classes return None — defer to COT Index.
        if asset_class in {'precious_metals', 'metals'}:
            if last > 0 and prev <= 0:
                return {'signal': 'buy', 'state': 'entered',
                        'rule': 'commercials net long crossed above zero (PM golden rule)'}
            if last > 0 and prev > 0:
                return {'signal': 'buy', 'state': 'sustained',
                        'rule': 'commercials sustained net long (PM golden rule)'}
            return None
        if asset_class in {'equities', 'indices', 'equity_indices'}:
            if last > 0 and prev <= 0:
                return {'signal': 'sell', 'state': 'entered',
                        'rule': 'commercials net long crossed above zero (equity index inverse rule)'}
            if last > 0 and prev > 0:
                return {'signal': 'sell', 'state': 'sustained',
                        'rule': 'commercials sustained net long (equity index inverse rule)'}
            if last < 0 and prev >= 0:
                return {'signal': 'buy', 'state': 'entered',
                        'rule': 'commercials net short crossed below zero (equity index inverse rule)'}
            if last < 0 and prev < 0:
                return {'signal': 'buy', 'state': 'sustained',
                        'rule': 'commercials sustained net short (equity index inverse rule)'}
            return None
        return None


class Valuation:
    """
    Valuation Indicator - compares symbol % change vs macro references.
    Corrected per Blueprint: asset-class-specific references, dynamic thresholds.
    """

    def __init__(
        self,
        length: int = 10,  # Default ROC; override to 13 for equities
        rescale_length: int = 100,
        overvalued: float = 75.0,
        undervalued: float = -75.0
    ):
        self.length = length
        self.rescale_length = rescale_length
        self.overvalued = overvalued
        self.undervalued = undervalued

    def calculate(
        self,
        symbol_df: pd.DataFrame,
        reference_dfs: Dict[str, pd.DataFrame]
    ) -> pd.DataFrame:
        """
        Calculate valuation metric.

        Args:
            symbol_df: OHLCV DataFrame for the trading symbol
            reference_dfs: Dict mapping reference name to OHLCV DataFrame

        Returns:
            DataFrame with rescaled differences (-100 to +100)
        """
        df = symbol_df.copy()
        df.set_index('timestamp', inplace=True)
        # Strip timezone so index comparisons never raise TypeError when
        # Yahoo returns tz-aware timestamps on some symbols and tz-naive on others.
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        # Percentage change of symbol over N periods
        sym_perc = (df['close'] - df['close'].shift(self.length)) / df['close'].shift(self.length) * 100

        results = pd.DataFrame(index=df.index)

        for i, (ref_name, ref_df) in enumerate(reference_dfs.items()):
            ref_df_indexed = ref_df.copy()
            ref_df_indexed.set_index('timestamp', inplace=True)
            # Strip tz from the reference index too (must match the symbol index).
            if ref_df_indexed.index.tz is not None:
                ref_df_indexed.index = ref_df_indexed.index.tz_localize(None)

            # Align indices
            common_idx = df.index.intersection(ref_df_indexed.index)
            if len(common_idx) < self.length:
                continue

            ref_close = ref_df_indexed.loc[common_idx, 'close']
            sym_close = df.loc[common_idx, 'close']

            ref_perc = (ref_close - ref_close.shift(self.length)) / ref_close.shift(self.length) * 100

            # Difference: symbol %change minus reference %change
            diff = sym_perc.loc[common_idx] - ref_perc

            # Rescale to -100/+100
            col_name = f'valuation_{ref_name}'
            results[col_name] = self._rescale(diff, self.rescale_length)

        # Composite valuation score (simple average of available references)
        val_cols = [c for c in results.columns if c.startswith('valuation_')]
        if val_cols:
            results['valuation_composite'] = results[val_cols].mean(axis=1)

        return results

    def _rescale(self, series: pd.Series, length: int) -> pd.Series:
        """Rescale values to -100/+100 range using a rolling min/max window.

        Adaptive `min_periods`: textbook uses length=100 (Pine Script default),
        but on a monthly chart with ~10 years of history that's only 120 bars
        and `min_periods=length/2=50` leaves the first 50 rows blank. For
        shorter series we relax min_periods to length/4 so the rescale
        starts producing values earlier without distorting the recent
        readings. On weekly/daily charts with hundreds of bars, the effect
        on the latest value is negligible.
        """
        n = series.notna().sum()
        # On short series, relax min_periods so we get readings instead of NaN.
        # length // 4 keeps the rescale meaningful (≥25% of window populated).
        min_p = max(length // 4, max(1, n // 4)) if n < length else max(length // 2, 1)
        rolling_min = series.rolling(window=length, min_periods=min_p).min()
        rolling_max = series.rolling(window=length, min_periods=min_p).max()

        denom = rolling_max - rolling_min
        scaled = np.where(
            denom != 0,
            (series - rolling_min) / denom * 200 - 100,
            np.nan
        )
        return pd.Series(scaled, index=series.index)

    def get_bias(self, valuation_df: pd.DataFrame, return_strength: bool = False):
        """Determine valuation bias by reading each REFERENCE LINE individually.

        This mirrors the Pine Script `Valuation` indicator (CampusValuationTool):
        the indicator plots 3 separate lines (one per reference symbol) and
        the trader visually reads each one against the +/- 75 threshold.
        Bernd does NOT average the lines; he says things like "DXY line is
        undervalued, bond line is undervalued, gold line is undervalued =
        all 3 agree, strong bullish bias".

        Bias decision per line:
          line >= +75  -> bearish (extreme overvalued)
          line >= +10  -> mild bearish
          line <= -10  -> mild bullish
          line <= -75  -> bullish (extreme undervalued)
          else         -> neutral (within +/- 10 of mean)

        Aggregate across the lines:
          - All available lines agree (ignoring near-mean): that direction.
            STRONG when any line is in extreme territory; MILD otherwise.
          - Majority (>=2 of 3) agree with no opposing extreme: that direction (mild).
          - Mixed -> neutral.

        Returns 'bullish' / 'bearish' / 'neutral' (or tuple with strength).
        """
        empty_result = ('neutral', 'none') if return_strength else 'neutral'
        if valuation_df.empty:
            return empty_result

        latest = valuation_df.iloc[-1]
        line_cols = [
            c for c in valuation_df.columns
            if c.startswith('valuation_') and c != 'valuation_composite'
        ]
        if not line_cols:
            return empty_result

        votes = []  # list of (direction, strength_tier) per available line
        for col in line_cols:
            v = latest.get(col)
            if pd.isna(v):
                continue
            v = float(v)
            if v >= self.overvalued:
                votes.append(('bearish', 'extreme'))
            elif v >= 10.0:
                votes.append(('bearish', 'mild'))
            elif v <= self.undervalued:
                votes.append(('bullish', 'extreme'))
            elif v <= -10.0:
                votes.append(('bullish', 'mild'))
            else:
                votes.append(('neutral', 'flat'))

        if not votes:
            return empty_result

        bull = sum(1 for d, _ in votes if d == 'bullish')
        bear = sum(1 for d, _ in votes if d == 'bearish')
        n = len(votes)

        any_extreme_bull = any(s == 'extreme' for d, s in votes if d == 'bullish')
        any_extreme_bear = any(s == 'extreme' for d, s in votes if d == 'bearish')

        # All available lines agree (no opposing direction)
        if bull == n and n >= 1:
            strength = 'strong' if any_extreme_bull else 'mild'
            return ('bullish', strength) if return_strength else 'bullish'
        if bear == n and n >= 1:
            strength = 'strong' if any_extreme_bear else 'mild'
            return ('bearish', strength) if return_strength else 'bearish'

        # Majority (>=2 of 3) agree, with no opposing line
        if bull >= 2 and bear == 0:
            strength = 'strong' if any_extreme_bull else 'mild'
            return ('bullish', strength) if return_strength else 'bullish'
        if bear >= 2 and bull == 0:
            strength = 'strong' if any_extreme_bear else 'mild'
            return ('bearish', strength) if return_strength else 'bearish'

        return empty_result


class Seasonality:
    """
    Seasonality Indicator - de-trended average seasonal pattern.
    Corrected per Blueprint: directional bias label.

    Implements the Pine Script logic from Seasonality_OTC.txt:
    1. Calculate daily/weekly price changes
    2. Accumulate per period (day of year / week of year)
    3. Average across years
    4. De-trend linearly
    5. Produce cumulative seasonal line
    """

    # Per textbook Ch 8: bias is strongest when 5y, 10y, AND 15y patterns all
    # point the same direction. A single lookback over-states conviction.
    DEFAULT_LOOKBACKS = (5, 10, 15)

    def __init__(
        self,
        lookback_years: int = 15,
        bias_lookahead_bars: int = 20,
        multi_lookbacks: Optional[Tuple[int, ...]] = None,
    ):
        self.lookback_years = lookback_years
        self.bias_lookahead_bars = bias_lookahead_bars
        self.multi_lookbacks = tuple(multi_lookbacks) if multi_lookbacks else self.DEFAULT_LOOKBACKS

    def calculate(
        self,
        df: pd.DataFrame,
        timeframe: str = 'daily'
    ) -> pd.DataFrame:
        """
        Calculate seasonal pattern.

        Args:
            df: OHLCV DataFrame with timestamp index
            timeframe: 'daily', 'weekly', or 'monthly'

        Returns:
            DataFrame with 'seasonal_value' column (de-trended cumulative seasonal)
        """
        if df.empty or len(df) < 252:
            return pd.DataFrame()

        df = df.copy()
        df.set_index('timestamp', inplace=True)

        # Determine bin count and assign bin numbers
        if timeframe == 'weekly':
            df['bin'] = df.index.isocalendar().week.astype(int) - 1
            num_bins = 52
        elif timeframe == 'monthly':
            df['bin'] = df.index.month - 1
            num_bins = 12
        else:  # daily
            # Pine Script uses TRADING day of year (_tdoy), not calendar dayofyear.
            # Assign rank within each calendar year so Q4 trading days map to
            # bins 200-251 instead of being silently dropped (calendar day > 252).
            years = df.index.year
            trading_day_of_year = df.groupby(years).cumcount()  # 0-indexed within year
            df['bin'] = trading_day_of_year
            num_bins = 252

        # Calculate daily changes
        df['chg'] = df['close'] - df['close'].shift(1)

        # Accumulate per bin — vectorised groupby (replaces slow iterrows loop
        # that caused pandas 2.x tz-hang on tz-aware DatetimeIndex slices).
        bin_sums = np.zeros(num_bins)
        bin_counts = np.zeros(num_bins)
        valid = df[df['chg'].notna() & df['bin'].between(0, num_bins - 1)]
        if not valid.empty:
            grp = valid.groupby('bin')['chg'].agg(['sum', 'count'])
            bin_sums[grp.index.astype(int)] = grp['sum'].values
            bin_counts[grp.index.astype(int)] = grp['count'].values

        if bin_counts.max() == 0:
            return pd.DataFrame()

        # Average per bin
        bin_avg = np.where(bin_counts > 0, bin_sums / bin_counts, 0.0)

        # Cumulative seasonal path
        seasonal_cum = np.cumsum(bin_avg)

        # Linear de-trending
        n = len(seasonal_cum)
        if n > 1:
            slope = seasonal_cum[-1] / n
            trend_line = np.arange(n) * slope
            seasonal_detrended = seasonal_cum - trend_line
        else:
            seasonal_detrended = seasonal_cum

        # Create output with bin-to-date mapping
        result = pd.DataFrame({
            'bin': range(num_bins),
            'bin_avg_change': bin_avg,
            'seasonal_value': seasonal_detrended
        })

        return result

    # Phase 31 hybrid: per-asset-class lookahead in DAYS forward.
    # equity_indices uses ~3-month cycle horizon (Bernd's monthly roadmap).
    # Everything else uses Bernd's stated 30-day forward read.
    LOOKAHEAD_DAYS_BY_CLASS = {
        # equity_indices uses the long cycle horizon because Bernd's monthly
        # roadmap calls span quarters. Baseline 30 weekly bins ~ 210 days.
        # Empirically 180 days recovers most of baseline's accidental matches.
        'equity_indices': 180,
        'equities': 30,
        'commodities': 30,
        'precious_metals': 30,
        'energies': 30,
        'nat_gas': 30,
        'soft_commodities': 30,
        'forex': 30,
        'crypto': 30,
        'interest_rates': 30,
    }

    def get_bias(self, seasonal_df: pd.DataFrame, current_bin: int,
                 timeframe: str = 'weekly', asset_class: Optional[str] = None) -> str:
        """Determine seasonality bias for upcoming period (single lookback).

        Phase 31 hybrid: lookahead is in DAYS forward (Bernd verbatim "I just
        project 30 days in the future for me that's enough") with per-asset-
        class overrides for equity indices which Bernd reads on monthly-
        roadmap horizon (~3 months). Days are converted to bins based on
        the binning timeframe:
          daily  : 1 bin per day  -> lookahead_bins = days
          weekly : 1 bin per week -> lookahead_bins = ceil(days/7)
          monthly: 1 bin per month-> lookahead_bins = ceil(days/30)

        Falls back to self.bias_lookahead_bars (raw bin count) when no
        asset_class is provided, preserving prior callers.
        """
        if seasonal_df.empty:
            return 'neutral'

        if asset_class:
            lookahead_days = self.LOOKAHEAD_DAYS_BY_CLASS.get(asset_class, self.bias_lookahead_bars)
            if timeframe == 'weekly':
                lookahead_bins = max(2, int(round(lookahead_days / 7)))
            elif timeframe == 'monthly':
                lookahead_bins = max(1, int(round(lookahead_days / 30)))
            else:  # daily
                lookahead_bins = lookahead_days
        else:
            # Legacy path: treat bias_lookahead_bars as raw bin count
            lookahead_bins = self.bias_lookahead_bars

        # Look at the slope over next N bins (forward projection).
        # NOTE: this deliberately CLAMPS to year-end rather than wrapping to
        # bin 0. A modulo wrap is more "cyclically pure", but the downstream
        # cycle-path guards (Phase 23/27/42 `seas != bearish`) were calibrated
        # against this bounded projection: wrapping flips the late-year (Oct-Dec)
        # seasonal slope sign and neutralises ~8 of Bernd's cycle-driven long
        # calls with no safety benefit. Keep the bounded projection so the
        # Bernd-clone match holds. (Reverted the wrap after it regressed the
        # goldtest by 10 Stage-1 cases, all long->neutral.)
        end_bin = min(current_bin + lookahead_bins, len(seasonal_df) - 1)
        start_val = seasonal_df.loc[seasonal_df['bin'] == current_bin % len(seasonal_df), 'seasonal_value']
        end_val = seasonal_df.loc[seasonal_df['bin'] == end_bin % len(seasonal_df), 'seasonal_value']

        if start_val.empty or end_val.empty:
            return 'neutral'

        slope = end_val.values[0] - start_val.values[0]

        if slope > 0.01:
            return 'bullish'
        elif slope < -0.01:
            return 'bearish'
        return 'neutral'

    def calculate_multi(
        self,
        df: pd.DataFrame,
        timeframe: str = 'weekly',
    ) -> Dict[int, pd.DataFrame]:
        """Run `calculate` for each lookback in self.multi_lookbacks.

        For each lookback we slice the input DataFrame to the most recent
        N years of data so the seasonal averaging only sees that horizon,
        then call calculate() on the slice.
        """
        if df.empty:
            return {}
        # Ensure datetime index for slicing
        if 'timestamp' in df.columns:
            df_indexed = df.set_index('timestamp')
        else:
            df_indexed = df
        results: Dict[int, pd.DataFrame] = {}
        try:
            most_recent = df_indexed.index.max()
        except Exception:
            return {}
        for years in self.multi_lookbacks:
            cutoff = pd.Timestamp(most_recent) - pd.Timedelta(days=int(years * 365.25))
            # Make cutoff tz-aware when the index is tz-aware so the >= comparison
            # never raises "Cannot compare tz-naive and tz-aware" TypeError.
            if df_indexed.index.tz is not None and cutoff.tzinfo is None:
                cutoff = cutoff.tz_localize(df_indexed.index.tz)
            slice_df = df_indexed.loc[df_indexed.index >= cutoff].reset_index()
            if len(slice_df) < 50:
                continue
            seas = self.calculate(slice_df, timeframe=timeframe)
            if not seas.empty:
                results[years] = seas
        return results

    def get_bias_multi(
        self,
        seasonal_by_lookback: Dict[int, pd.DataFrame],
        current_bin: int,
        return_strength: bool = False,
        timeframe: str = 'weekly',
        asset_class: Optional[str] = None,
    ):
        """Bias from multi-lookback (HAI Mod 3 L3 — True Seasonality):

            'all stars align' = STRONG (all 3 lookbacks agree)
            2-of-3 same direction with no opposing = MODERATE
            otherwise NEUTRAL

        With return_strength=True returns (bias, strength) tuple where
        strength is 'strong' / 'moderate' / 'none'. Without, returns just
        the bias string (legacy: only returns directional when ALL agree).
        """
        if not seasonal_by_lookback:
            return ('neutral', 'none') if return_strength else 'neutral'

        votes = [self.get_bias(seas, current_bin, timeframe=timeframe, asset_class=asset_class) for seas in seasonal_by_lookback.values()]
        if not votes:
            return ('neutral', 'none') if return_strength else 'neutral'

        bull = sum(1 for v in votes if v == 'bullish')
        bear = sum(1 for v in votes if v == 'bearish')

        # Strong: all-must-agree
        if bull == len(votes):
            return ('bullish', 'strong') if return_strength else 'bullish'
        if bear == len(votes):
            return ('bearish', 'strong') if return_strength else 'bearish'
        # Moderate: 2/3 agree with 0 opposing.
        # Previously returned 'neutral' when return_strength=False — that silently
        # discarded every case where two lookbacks agreed but the third was flat.
        # In practice this made seasonality require unanimous agreement and fire
        # far too rarely. The directional bias is still valid at moderate strength.
        if bull >= 2 and bear == 0:
            return ('bullish', 'moderate') if return_strength else 'bullish'
        if bear >= 2 and bull == 0:
            return ('bearish', 'moderate') if return_strength else 'bearish'
        return ('neutral', 'none') if return_strength else 'neutral'

    def get_current_bin(self, df: pd.DataFrame, timeframe: str = 'weekly') -> int:
        """Get the current seasonal bin number."""
        latest_date = df['timestamp'].max() if 'timestamp' in df.columns else df.index.max()
        if timeframe == 'weekly':
            return pd.Timestamp(latest_date).isocalendar().week - 1
        elif timeframe == 'monthly':
            return pd.Timestamp(latest_date).month - 1
        else:
            return pd.Timestamp(latest_date).dayofyear - 1


# ---------------------------------------------------------------------------
# Multi-lookback Seasonality is the rolling-average seasonal we already had.
# Audit 2026-04-28 confirmed visually that what Bernd calls "True Seasonality"
# is a DIFFERENT indicator (`_Campus True Seasonality V1.1_protected_V1`) which
# outputs a single forward-projected curve (not three overlapping curves).
# Keep MultiLookbackSeasonality as an alias for the existing class so we're
# explicit about the distinction in code and docs; True Seasonality lives in
# its own class below.
# ---------------------------------------------------------------------------
MultiLookbackSeasonality = Seasonality


class TrueSeasonality:
    """
    True Seasonality v1.1 (proprietary forward-projection seasonal indicator).

    Visually confirmed in Stage 2 audit (HAI Module 3 Lesson 3 — `_Campus True
    Seasonality V1.1_protected_V1`, typical params (lookback_years=10,
    forward_bars=150)). Differs from `Seasonality.calculate_multi` in two
    important ways:

    1. Outputs a SINGLE composite line, not three lookback curves.
    2. Projects FORWARD `forward_bars` past the current date, so the trader
       sees the dominant seasonal cycle for the upcoming period.

    Used as the PRIMARY seasonal tool when COT and Valuation give no signal
    (e.g. natural gas — Bernd 1:14:38 HAI: "true seasonality will be an odds
    enhancer or secondary tool, very rarely a primary tool... only primary
    when we have nothing else to work on, like in the case of natural gas").
    """

    def __init__(
        self,
        lookback_years: int = 25,
        forward_bars: int = 150,
        bin_strategy: str = 'day_of_year',  # 'day_of_year' | 'week' | 'month'
    ):
        # Visually confirmed Bernd loads >=25 years of history. Default
        # forward projection 150 bars on daily charts.
        self.lookback_years = lookback_years
        self.forward_bars = forward_bars
        self.bin_strategy = bin_strategy

    def calculate_forward(
        self,
        df: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Compute the forward-projected seasonal path.

        Returns a DataFrame with columns:
            ['timestamp', 'projection_value', 'is_forward']
        where `is_forward=True` for the projected segment to the right of
        the latest historical bar.
        """
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.copy()
        if 'timestamp' in df.columns:
            df = df.set_index('timestamp')
        df = df.sort_index()

        # Slice to lookback_years
        cutoff = df.index.max() - pd.Timedelta(days=int(self.lookback_years * 365.25))
        df = df.loc[df.index >= cutoff]
        if len(df) < 252:
            return pd.DataFrame()

        # Detrended log-return per bar
        log_ret = np.log(df['close']).diff()
        log_ret = log_ret - log_ret.mean()  # remove long-run drift

        # Bin by calendar position
        if self.bin_strategy == 'week':
            bins = df.index.isocalendar().week.astype(int) - 1
            n_bins = 52
        elif self.bin_strategy == 'month':
            bins = df.index.month - 1
            n_bins = 12
        else:
            bins = df.index.dayofyear - 1
            n_bins = 365

        # Per-bin mean detrended return = the seasonal pattern
        sums = np.zeros(n_bins)
        counts = np.zeros(n_bins)
        for b, r in zip(bins, log_ret):
            if 0 <= b < n_bins and not np.isnan(r):
                sums[b] += r
                counts[b] += 1
        mean_per_bin = np.where(counts > 0, sums / counts, 0.0)

        # Build forward projection from the last bar
        last_ts = df.index[-1]
        last_close = df['close'].iloc[-1]
        # Determine bar interval from history
        if len(df) >= 2:
            bar_interval = (df.index[-1] - df.index[-2])
        else:
            bar_interval = pd.Timedelta(days=1)

        # Project forward bars
        future_idx = pd.date_range(
            start=last_ts + bar_interval,
            periods=self.forward_bars,
            freq=bar_interval,
        )
        if self.bin_strategy == 'week':
            future_bins = future_idx.isocalendar().week.astype(int) - 1
        elif self.bin_strategy == 'month':
            future_bins = future_idx.month - 1
        else:
            future_bins = future_idx.dayofyear - 1

        future_returns = np.array([mean_per_bin[int(b) % n_bins] for b in future_bins])
        # Cumulative path in price-space (geometric)
        cum_path = last_close * np.exp(np.cumsum(future_returns))

        forward = pd.DataFrame({
            'timestamp': future_idx,
            'projection_value': cum_path,
            'is_forward': True,
        })

        # Also emit recent historical context (last 365 bars)
        hist_segment = df.tail(365)
        hist = pd.DataFrame({
            'timestamp': hist_segment.index,
            'projection_value': hist_segment['close'].values,
            'is_forward': False,
        })
        return pd.concat([hist, forward], ignore_index=True)

    def get_bias(
        self,
        forward_df: pd.DataFrame,
    ) -> Tuple[str, str]:
        """
        Returns (bias, strength) where bias ∈ {'bullish','bearish','neutral'}
        and strength ∈ {'strong','moderate','none'}.

        Uses the SLOPE of the forward-projected curve over its first N bars.
        """
        if forward_df is None or forward_df.empty:
            return ('neutral', 'none')
        fwd = forward_df[forward_df['is_forward']]
        if len(fwd) < 5:
            return ('neutral', 'none')
        first_val = float(fwd['projection_value'].iloc[0])
        last_val = float(fwd['projection_value'].iloc[-1])
        if first_val <= 0:
            return ('neutral', 'none')
        pct_change = (last_val - first_val) / first_val * 100
        # Strong if forward path moves >2%, moderate if >0.5%
        if pct_change > 2.0:
            return ('bullish', 'strong')
        if pct_change > 0.5:
            return ('bullish', 'moderate')
        if pct_change < -2.0:
            return ('bearish', 'strong')
        if pct_change < -0.5:
            return ('bearish', 'moderate')
        return ('neutral', 'none')


class TradingDayOfMonth:
    """
    Trading Day of Month (TDOM) — visually confirmed in Stage 2 as a
    TradeStation RadarScreen tab (column header
    `_Campus True Seasonality Radarscreen V1_protected`). Rows = trading
    day index 1..N within a month, columns = per-symbol historical
    bullish-percentage scores (0..100).

    Bernd uses TDOM as the FINAL gate after COT/Valuation/Seasonality —
    "the trading day of the months it is good enough yes I think it is
    good enough" (HAI 0:20:33). Threshold qualitative: ≥67 = strong;
    33-50 = neutral; <33 = avoid (counter-signal).
    """

    def __init__(self, lookback_years: int = 15):
        self.lookback_years = lookback_years

    def _trading_day_of_month(self, df: pd.DataFrame) -> pd.Series:
        """Map each timestamp to its trading-day-of-month index (1..N)
        among the trading days observed in that calendar month."""
        ts = df.index if 'timestamp' not in df.columns else df['timestamp']
        ts = pd.DatetimeIndex(ts)
        ym = ts.to_period('M')
        order = np.zeros(len(ts), dtype=int)
        ym_arr = np.asarray(ym)
        for period in ym.unique():
            idxs = np.where(ym_arr == period)[0]
            for k, i in enumerate(idxs, start=1):
                order[i] = k
        return pd.Series(order, index=range(len(ts)))

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Returns a DataFrame indexed by trading_day_of_month (1..23) with
        columns ['count', 'bullish_count', 'pct_bullish', 'avg_return'].
        """
        if df is None or df.empty:
            return pd.DataFrame()
        d = df.copy()
        if 'timestamp' in d.columns:
            d = d.set_index('timestamp')
        d = d.sort_index()
        cutoff = d.index.max() - pd.Timedelta(days=int(self.lookback_years * 365.25))
        d = d.loc[d.index >= cutoff]
        if len(d) < 252:
            return pd.DataFrame()
        d['tdom'] = self._trading_day_of_month(d).values
        d['ret'] = d['close'].pct_change()
        d['bullish'] = (d['ret'] > 0).astype(int)
        grp = d.groupby('tdom').agg(
            count=('ret', 'count'),
            bullish_count=('bullish', 'sum'),
            avg_return=('ret', 'mean'),
        )
        grp['pct_bullish'] = (grp['bullish_count'] / grp['count']) * 100.0
        return grp

    def get_bias(
        self, df: pd.DataFrame, query_date: Optional[pd.Timestamp] = None,
    ) -> Tuple[str, float]:
        """Returns (bias, score) for the trading-day-of-month containing
        `query_date` (default: latest bar). Bias ∈ {'bullish','bearish',
        'neutral'}; score ∈ [0..100].

        Threshold (visually confirmed qualitative): ≥67 = bullish bias,
        ≤33 = bearish bias, otherwise neutral.
        """
        table = self.calculate(df)
        if table.empty:
            return ('neutral', 50.0)
        if query_date is None:
            ts = df.index.max() if 'timestamp' not in df.columns else df['timestamp'].max()
            query_date = pd.Timestamp(ts)
        # Compute the tdom of the query date relative to its month.
        if 'timestamp' in df.columns:
            df_idx = df.set_index('timestamp').sort_index()
        else:
            df_idx = df.sort_index()
        same_month = df_idx[df_idx.index.to_period('M') == query_date.to_period('M')]
        # Find position of query_date in the same-month sequence (1-indexed).
        positions = list(same_month.index)
        if not positions:
            return ('neutral', 50.0)
        try:
            tdom_idx = positions.index(query_date) + 1
        except ValueError:
            # Query date may not be in the data; pick nearest preceding bar.
            preceding = [p for p in positions if p <= query_date]
            tdom_idx = len(preceding) if preceding else 1
        if tdom_idx not in table.index:
            return ('neutral', 50.0)
        score = float(table.loc[tdom_idx, 'pct_bullish'])
        if score >= 67:
            return ('bullish', score)
        if score <= 33:
            return ('bearish', score)
        return ('neutral', score)
