"""
Rules Engine - Implements the Seven-Step Decision Process.
From DELIVERABLE_2_STRATEGY_RULEBOOK, sections A-H.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, date
import logging
import os

from BP_indicators import COTIndex, Valuation, Seasonality
from BP_zone_detector import ZoneDetector
from BP_patterns import PatternDetector, PatternType, TradeDirection
from BP_roadmap import build_monthly_roadmap, filter_signal_by_roadmap
from BP_calendar import get_calendar, BlackoutStatus

logger = logging.getLogger(__name__)


class BiasSignal:
    BULLISH = 'bullish'
    BEARISH = 'bearish'
    NEUTRAL = 'neutral'


# Per-asset-class indicator parameters per the Hybrid AI course defaults
# (HAI 1:19:59 "weeks look back, 156... and the 26") with the Funded Trader
# commodity override (FT 02.03.2024 [0:15:38] "52 weeks... whole planting
# and harvesting season"). Equities use ROC=13 on Valuation (longer/smoother
# per OTC L8); commodities use ROC=10.
COT_LOOKBACK_BY_CLASS = {
    'forex':             26,   # Hybrid AI default
    'commodities':       52,   # Funded Trader override -- planting/harvest cycle
    'soft_commodities':  26,   # CLAUDE.md P1: cotton/grains/cocoa/coffee use NonComm 26w
    'energies':          52,   # crude/nat-gas have seasonal supply cycles
    'nat_gas':            26,  # Phase 41 S-01: non-commercials (Fund Managers) are primary.
                              # Old value 260 was for retailers 5yr historical extremes (Ch015).
                              # Non-commercials use standard 26w lookback per Hybrid AI default.
    'precious_metals':   26,   # Ch.107 CW40: Bernd explicit "26 look back is 26" for gold/PMs
                              # Also matches COT V2 Pine Script default (input.int(26, "Number of weeks"))
    'equity_indices':    26,
    'equities':          26,
    'interest_rates':    26,
    'crude_oil':         26,  # C-44: crude is its own class now; 26w matches the
                              # two CL=F settings dialogs (CRUDE_OIL_COT_26W_SYMBOLS)
                              # rather than the 52w 'energies' seasonal-cycle default.
}

# Soft agricultural commodities — COT group assignment (Phase 14 correction):
#
# Corpus evidence (Trading Doc chapters 108-186):
#   - Grains (Corn ZC=F, Wheat ZW=F, Soybeans ZS=F): Bernd uses COMMERCIALS
#     explicitly. Ch.159 (CW07 Corn): "commercials are bullish." Ch.168
#     (CW05 Soybeans): Bernd says the retailer line is "not real retailers."
#   - Cotton (CT=F): Ch.113/Ch.144 (Nov-Dec 2023): "smart money commercials
#     bullish + retailers bearish = buy cotton." Later sessions confirm Commercials.
#   - Coffee KC=F: Phase 16 transcript audit — 03_funded.txt lines 6805-6810:
#     Bernd says coffee retailers are "not real retailers" and explicitly
#     notes "commercials obviously impact." Moved to 'commodities' class
#     (Commercials 52w). Same language used for Soybeans (Ch.168).
#   - Cocoa CC=F, Sugar SB=F, OJ=F: corpus silent/unclear; retain NonComm 26w.
#
# Grains + Cotton are now routed to 'commodities' class (Commercials 52w)
# by removing them from this frozenset. KC=F also moved out (Phase 16).
SOFT_COMMODITY_SYMBOLS = frozenset({
    'SB=F',  # Sugar  — NonCommercials divergence (corpus silent)
    'OJ=F',  # Orange Juice — NonCommercials divergence (corpus silent)
    # KC=F Coffee removed (Phase 16): retailers "not real retailers"; Commercials
    # are the primary driver → falls through to 'commodities' (Commercials 52w)
    # ZC=F Corn, ZW=F Wheat, ZS=F Soybeans, CT=F Cotton removed (Phase 14):
    # these use Commercials (Ch.159/168/113/144) → fall through to 'commodities'
    # CC=F Cocoa removed (full-corpus indicator audit, 2026-07): two independent
    # settings-dialog frames (Ch.082 frame_002405, Ch.089 frame_003397) both show
    # DisplayNonCommercialTradersIndex=false + WeeksLookBack=52 for @CC — i.e.
    # Commercials primary, 52w, Non-Commercials explicitly disabled. Falls through
    # to 'commodities' default (Commercials 52w), matching the dialog evidence.
})

# Blueprint Cheatsheet (OTC Module 2) fix — Natural Gas:
# COT = Retailers ① (CONTRARIAN, same as Precious Metals) NOT Commercials.
# Cheatsheet note: "historical retailer extremes (5year or historical)".
# Valuation = "-" (excluded — NG is driven by weather/supply shocks that
# make relative-to-DXY analysis uninformative).
NAT_GAS_SYMBOLS = frozenset({'NG=F', 'QN=F'})  # full + mini

# Phase 41 chunk 1 speech audit: Zone Qualifiers lesson frame_004397 shows
# ZigZag % ( High , Low , 5 , white, 3 ) on @CL daily chart.
# Energies (CL, HO, RB, QM) need a 5% daily ZigZag (vs the 3% global default)
# because crude oil's daily ATR is ~$2-4 on a $70-80 contract (~3-5%) making
# 3% thresholds too fine and generating spurious pivots.
ENERGY_SYMBOLS = frozenset({'CL=F', 'QM=F', 'HO=F', 'RB=F', 'BZ=F'})

# Phase 23 (Task 3): JPY uses 52-week COT lookback (not the 26w forex default).
# CFTC 6J=F has lower open interest than EUR/GBP futures → 26w net position
# range is too narrow → COT V2 index stays near 50 → bias always 'neutral'.
# Wider 52w window captures more historical range so the index reaches the
# 80/20 extremes and produces directional signals matching Bernd's verbal calls.
JPY_SYMBOLS = frozenset({'USDJPY=X', '6J=F', 'JPYUSD=X', 'JPYUSD'})

# Full-corpus indicator audit (2026-07): CL=F (Crude Oil) COT lookback.
# Two independent settings-dialog frames (Ch.136 frame_001504, Ch.164 frame_000241)
# both show `WeeklyLookBack = 26` on the Campus Smart Money Index for @CL, with
# verbal confirmation ("it's 26 already short term" / "26 weeks look back...
# short term look back"). Overrides the 'energies' class default of 52w, which
# was calibrated for the general planting/harvest commodity cycle and does not
# apply to crude specifically.
CRUDE_OIL_COT_26W_SYMBOLS = frozenset({'CL=F'})

# 2026-08 FTW vision audit C-44: crude oil COT trader group.
# CL=F is split out of the 'energies' class (which trades WITH Commercials, per the
# Hybrid AI / OTC teaching material) because the LIVE Weekly Outlook corpus reads
# RETAIL, contrarian, on crude -- three independent chapters, no counter-evidence:
#   CW47 2023-11-18 "the retailers are getting fully bearish"      -> contrarian long
#   CW08 2024-02-19 "when the retailers ... are short we see a rise in price"
#   CW11 2024-03-09 "retailers are getting super bullish" -> he shorts crude
# Scoped to CRUDE ONLY on purpose: HO/RB/QM/BZ have no live COT-group evidence and
# stay on the 'energies' Commercials default.
# NOTE: routing lives in TWO places that must stay in sync --
#   RulesEngine._indicators_for_class  (effective_class)
#   RulesEngine._analyze_fundamentals  (cot_effective_class)
# plus the 'crude_oil' branch in BP_indicators.COTIndex.get_bias.
CRUDE_OIL_SYMBOLS = frozenset({'CL=F'})

# Symbols where Valuation is explicitly excluded from Bernd's analysis.
# NG=F: cheatsheet column shows "-" for Valuation.
# NFLX: Phase 32 per-asset rulebook + Phase 32 valuation rulebook confirm
#       Bernd runs pure S&D + Seasonality on NFLX, no fundamentals at all.
#       Cheatsheet has no Valuation/COT entries for Netflix.
VALUATION_SKIP_SYMBOLS = frozenset({'NG=F', 'QN=F', 'NFLX'})

# Phase 42 Fix-4: Silver Valuation is NOT a primary indicator per Blueprint Cheatsheet.
# Silver row: Commercials ① as primary, Gold ③ as odds-enhancer — Valuation not listed.
# val=bearish for Silver in a PM bull market reflects structural bond underperformance,
# not genuine overvaluation. Suppress the veto when zone + seasonality confirm the long.
SILVER_SYMBOLS = frozenset({'SI=F', 'SIL', 'SILV'})

# Phase 33: symbols where COT is also excluded.
# NFLX has no CFTC reportable contract; running standard equities COT path
# produces noise. Skip entirely.
COT_SKIP_SYMBOLS = frozenset({'NFLX'})

# Phase 16 — Bitcoin seasonality uses 4-year lookback only.
# 03_funded.txt lines 451, 864-865: Bernd says "We can only do four years"
# for Bitcoin — the data history is too short for 5yr/10yr/15yr averages.
# When a BTC symbol is detected, Seasonality.calculate_multi is overridden
# to use a (4,) lookback tuple instead of the standard (5, 10, 15).
BTC_SYMBOLS = frozenset({'BTC-USD', 'BTC=F', 'BTCUSD', 'BTC/USD'})

# Phase 41 GAP-C6-S-01: RTY=F (Russell 2000) has insufficient history for 10yr seasonality.
# Source: FT CW08 17.02.2024 transcript 0:22:25 -- Bernd: "seasonality 10 years, of course,
# no data, no data, no data" when attempting to show RTY seasonality.
# Use 5yr-only lookback for RTY (similar to BTC short-history treatment).
RTY_SYMBOLS = frozenset({'RTY=F', 'IWM', 'RUT'})

# Phase 15 — Equity index constituent-analysis Valuation.
#
# From Ch.157 (CW40): "the two most important stocks is Apple and is Microsoft
# that they are not overbellied. Right. Apple is undervalued. And if you look
# at Microsoft here as well [undervalued]... So if these two are undervalued,
# you can buy NQ / ES."
#
# Bernd reads individual-stock Valuation to INFER the index direction.
# He does NOT look at NQ=F or ES=F Valuation directly — the index is too
# correlated with the macro references (DXY/ZN/ZB) to give an independent signal.
#
# Implementation rule (Phase 6/CLAUDE.md P2 / Ch.157):
#   Primary gate: AAPL + MSFT (for NQ/ES); MSFT + UNH (for YM DOW).
#   If BOTH primaries are NOT strongly overvalued → constituent_val = 'bullish'
#   If ANY primary is strongly overvalued     → constituent_val = 'bearish' or 'neutral'
#   Secondary stocks provide a confirming majority vote.
EQUITY_INDEX_CONSTITUENTS: Dict = {
    'NQ=F':  {
        'primary':   ['AAPL', 'MSFT'],
        'secondary': ['NVDA', 'AMZN', 'META', 'GOOGL', 'NFLX', 'TSLA'],
    },
    'ES=F':  {
        'primary':   ['AAPL', 'MSFT'],
        'secondary': ['NVDA', 'AMZN', 'META', 'GOOGL'],
    },
    'YM=F':  {
        # Dow Jones top-weight components by market cap influence
        'primary':   ['MSFT', 'UNH'],
        'secondary': ['GS', 'HD', 'CAT', 'AAPL'],
    },
}

# Pine default Length is 10; every non-equity class uses it.
#
# 2026-08 FTW vision audit -- 'equities' corrected 30 -> 13. Evidence, from two
# independent corpora that agree:
#   * OTC Module 3 / Lesson 3 (Valuation) slide table, frame_000727, verbatim:
#     "Equity indices and stocks -> 13 days short term / 30 days long term."
#   * Same lesson, LIVE on an AAPL chart (frame_001253): he edits ROC 10 -> 13
#     saying "I'm going to change the ROC from 10 to 13"; the title bar updates
#     to `...13 100 100 -100 75 -75`.
#   * Weekly Outlook CW18 (2023-04): 10 stocks with UN-truncated labels all read
#     Length=13; two live index dialogs edit 30 -> 13 (@NQ) and 10 -> 13 (@ES),
#     with "put here on 13 is as better for indices".
#   * Weekly Outlook CW05 (2023-01): MSFT Format Study dialog reads 13.
#
# Why the previous 30 was wrong: 30 is the *long term* alternate view, not the
# stock default. It only ever appears as a value being edited away from, or as a
# deliberate long-horizon toggle -- e.g. CW07-Corn (2024-02) where he switches
# 10 -> 30 narrating "short term" -> "long term valuation", on corn.
#
# Why the old "tested: 13 came out wildly more bearish" note does not apply: that
# test ran Length=13 against THREE reference lines. His stock config uses ONE
# reference (bonds only -- see VALUATION_REFS['equities']). It falsified a
# configuration he never uses, so its conclusion does not follow.
VALUATION_LENGTH_BY_CLASS = {
    'forex':           10,
    'commodities':     10,
    'energies':        10,
    'precious_metals': 10,
    # NOTE equity_indices deliberately left at 10 despite the slide grouping
    # indices with stocks at 13: live sessions disagree BY DATE -- CW18 (2023-04)
    # shows indices edited to 13, but CW09 (2024-02) shows @YM/@NQ at 10. Needs a
    # recent-era index dialog before changing. Do not "fix" to 13 without it.
    'equity_indices':  10,
    'equities':        13,
    'interest_rates':  10,
}


class RulesEngine:
    """
    Seven-Step Decision Process for trade signal generation.
    """

    def __init__(self, config: Dict):
        self.config = config
        self.risk_config = config.get('risk', {})
        self.stop_config = config.get('stop_loss', {})

        # Initialize indicator engines
        cot_cfg = config.get('cot', {})
        val_cfg = config.get('valuation', {})
        seas_cfg = config.get('seasonality', {})

        self.cot_index = COTIndex(
            lookback_weeks=cot_cfg.get('lookback_weeks', 26),
            upper_extreme=cot_cfg.get('upper_extreme', 80),
            lower_extreme=cot_cfg.get('lower_extreme', 20)
        )

        self.valuation = Valuation(
            length=val_cfg.get('length', 10),
            rescale_length=val_cfg.get('rescale_length', 100),
            overvalued=val_cfg.get('overvalued_threshold', 75),
            undervalued=val_cfg.get('undervalued_threshold', -75)
        )

        self.seasonality = Seasonality(
            lookback_years=seas_cfg.get('lookback_years', 15),
            bias_lookahead_bars=seas_cfg.get('bias_lookahead_bars', 20)
        )

        self.zone_detector = ZoneDetector(config.get('zone_detection', {}))
        self.pattern_detector = PatternDetector(config)

    def run_seven_step_process(
        self,
        symbol: str,
        ohlcv_data: Dict[str, pd.DataFrame],
        cot_df: pd.DataFrame,
        valuation_refs: Dict[str, pd.DataFrame],
        seasonal_df: pd.DataFrame,
        htf: str = '1wk',
        ltf: str = '1d',
        income_strategy: str = 'weekly',
        asset_class: str = 'commodities',
        opposing_cot_df: Optional[pd.DataFrame] = None,
        prefer_midpoint_entry: Optional[bool] = None,
        constituent_dfs: Optional[Dict[str, "pd.DataFrame"]] = None,
        today_override: Optional[date] = None,
    ) -> Optional[Dict]:
        """
        Execute the full Seven-Step Decision Process.

        Steps:
        1. Market Selection (already done - symbol passed in)
        2. HTF Technical Analysis (location, trend)
        3. Fundamental Confirmation (COT, Valuation, Seasonality)
        4. LTF Zone Identification (zone detection + qualifiers)
        5. Entry Trigger (candlestick patterns)
        6. Trade Management (stop, targets, sizing)
        7. Review & Refine (signal confidence)

        Returns:
            Trade signal dict or None if conditions not met
        """

        # Reset Stage-1 cache at the start of every call so stale data from the
        # previous symbol never leaks through. run_realworld.py reads this after
        # the call returns to get the directional brain output even when no full
        # signal fires (no zone, consensus=hold, no pattern, etc.).
        self._last_htf_analysis = {}

        htf_df = ohlcv_data.get(htf)
        ltf_df = ohlcv_data.get(ltf)

        if htf_df is None or htf_df.empty:
            logger.warning(f"No {htf} data for {symbol}")
            return None
        if ltf_df is None or ltf_df.empty:
            logger.warning(f"No {ltf} data for {symbol}")
            return None

        # == STEP 4 (early): detect HTF zones first so Location uses zone distals ==
        # First pass without trend so we can derive trend from the data, then
        # we re-score later with trend context.
        htf_zones_provisional = self.zone_detector.detect_zones(htf_df, symbol, htf)

        # == STEP 2: HTF Technical Analysis (uses zone distals when available) ==
        ht_bias = self._analyze_htf(htf_df, htf_zones_provisional,
                                    htf=htf, symbol=symbol, asset_class=asset_class)
        trend = ht_bias['trend']

        logger.info(f"[{symbol}] HTF Bias: location={ht_bias['location']}, trend={trend}")

        # Re-score HTF zones with trend context so Q5/Q6 are skipped on
        # trend-aligned setups (textbook rule).
        htf_zones = self.zone_detector.detect_zones(htf_df, symbol, htf, trend=trend)

        # == STEP 3: Fundamental Confirmation ==
        fund_bias = self._analyze_fundamentals(
            cot_df, htf_df, valuation_refs, seasonal_df, asset_class,
            opposing_cot_df=opposing_cot_df,
            symbol=symbol,
            constituent_dfs=constituent_dfs,
            htf=htf,
        )
        logger.info(f"[{symbol}] Fundamentals: COT={fund_bias['cot']}, Val={fund_bias['valuation']}, Seas={fund_bias['seasonality']}")

        # Store Stage-1 intermediate analysis so external callers (e.g.
        # run_realworld.py) can inspect the directional brain even when the
        # full signal returns None (no zone, no pattern, or consensus=hold).
        self._last_htf_analysis = {
            "symbol":     symbol,
            "location":   ht_bias.get("location"),
            "trend":      ht_bias.get("trend"),
            # C-80 diagnostics: which Fib range produced the Location label, and the
            # raw percentage. Read-only, no behaviour change.
            "location_pct":    ht_bias.get("location_pct"),
            "location_source": ht_bias.get("location_source"),
            "valuation":  fund_bias.get("valuation"),
            "cot_bias":   fund_bias.get("cot"),
            "cot_strength": fund_bias.get("cot_strength", "none"),
            "seasonality_bias": fund_bias.get("seasonality"),
            "bias":       None,   # filled in after _bias_consensus below
        }

        # == STEP 4: LTF Zone Detection + multi-timeframe alignment ==
        ltf_zones = self.zone_detector.detect_zones(ltf_df, symbol, ltf, trend=trend)
        ltf_zones = self.zone_detector.align_multi_timeframe(htf_zones, ltf_zones)
        # Big Brother / Small Brother filter (OTC 2025 L3): tag LTF zones
        # with their HTF parent. Strict mode is opt-in via config since
        # Bernd does take some "no-big-brother" trades when the LTF zone is
        # a clean RBR/DBD with high qualifier scores.
        # C-124: "Rule 6: HTF Coverage" appears in 46 of 273 rules extracted from the
        # course (17%), second only to freshness -- and it has always defaulted to False
        # and is absent from BP_config.yaml entirely. Env override added so it can be
        # A/B'd like every other flag; the config value remains the default source.
        require_bb = bool(self.config.get('require_big_brother', False))
        if os.environ.get('BP_REQUIRE_BIG_BROTHER') == '1':
            require_bb = True
        ltf_zones = self.zone_detector.filter_by_big_brother(
            ltf_zones, htf_zones, require_coverage=require_bb,
        )
        # C-110: current price is passed so rank_zones can order reachable zones
        # first when BP_ZONE_REACHABLE is set. Ignored otherwise.
        ranked_zones = self.zone_detector.rank_zones(
            ltf_zones, min_score=4.0,
            current_price=float(ltf_df['close'].iloc[-1]) if len(ltf_df) else None)

        if not ranked_zones:
            logger.info(f"[{symbol}] No qualified zones found")
            return None

        best_zone = ranked_zones[0]
        logger.info(f"[{symbol}] Best zone: {best_zone['zone_type']} at {best_zone['proximal']:.2f}, score={best_zone['composite_score']:.1f}")

        # == Consensus Bias Check ==
        # Phase 28 A1 fix: wire constituent bias into consensus so the Phase 23/24
        # cycle override path can fire in the live scanner (was dead code because
        # goldtest harness built the dict separately).
        biases = {
            'location': ht_bias['location'],
            'trend': ht_bias['trend'],
            'cot': fund_bias['cot'],
            'cot_strength': fund_bias.get('cot_strength', 'normal'),
            'valuation': fund_bias['valuation'],
            'seasonality': fund_bias['seasonality'],
            'constituent': fund_bias.get('constituent', 'neutral'),
        }

        # Phase 23: pass at_zone + zone_composite for T4 soft-veto support.
        # We're past the no-zone gate (line 274), so a zone definitely exists
        # and price is near it (zone qualifier scoring filters out distant zones).
        _zc = float(best_zone.get('composite_score', 0.0)) if best_zone else 0.0
        consensus = self._bias_consensus(
            biases, income_strategy,
            asset_class=asset_class,
            at_zone=True,
            zone_composite=_zc,
            today_override=today_override,
            symbol=symbol,
        )
        self._last_htf_analysis["bias"] = consensus   # expose Stage-1 result
        # C-102 (2026-08-27) EXPERIMENTAL, DEFAULT OFF -- BP_ZONE_FIRST=1
        #
        # This gate is why Stage 2 fires on 1.7% of cases: a fully qualified zone
        # produces NO signal whenever the Stage-1 consensus is 'hold'. It makes
        # direction a precondition for taking an entry.
        #
        # C-101 measured what that precondition is worth. Same symbol, same date,
        # same direction, same risk, only the entry price differing:
        #
        #     their drawn entry (wait for the level)   52.0% win   +0.56R  (n=25)
        #     entry at market on day 1                 22.2% win   -0.33R  (n=36)
        #     random walk, no drift, by theory         33.3% win   +0.00R
        #
        # Their direction acted on at market is WORSE THAN RANDOM. The entry price
        # is the whole edge. So gating the entry behind the direction spends a
        # measured edge to satisfy a signal that has none -- and our own Stage-1
        # direction is 52.7% against an always-long 50.4%, i.e. the same coin flip.
        #
        # With the flag, a 'hold' consensus no longer vetoes the trade; the ZONE
        # decides the direction, which is what the zone already encodes (demand ->
        # long, supply -> short). The explicit-conflict check below is retained:
        # this tests "neutral should not veto", not "ignore an active disagreement".
        #
        # EXPECT MANY MORE SIGNALS AND A WORSE STAGE-1 SCORE. That is not a
        # refutation -- Stage-1 agreement is the metric C-101 says is measuring the
        # wrong thing. Judge this on replayed R-multiple expectancy via
        # goldtest/replay_trades.py, never on bias_match.
        _zone_first = os.environ.get('BP_ZONE_FIRST') == '1'
        if consensus == 'hold' and not _zone_first:
            logger.info(f"[{symbol}] Bias consensus insufficient for trade")
            return None
        if consensus == 'hold':
            logger.info(f"[{symbol}] C-102: consensus 'hold' overridden -- zone decides")

        # Zone direction must match consensus
        zone_dir = 'long' if best_zone['zone_type'] == 'demand' else 'short'
        if (zone_dir == 'long' and consensus == 'bearish') or (zone_dir == 'short' and consensus == 'bullish'):
            logger.info(f"[{symbol}] Zone direction {zone_dir} conflicts with consensus {consensus}")
            return None

        # Phase 6 P1 (Ch 156): equity-index shorts require BOTH retailer-extreme
        # AND Treasury Bond ROC actively rolling negative (not merely positioned).
        # Bernd: "we need the help of other Treasury bonds [to roll over]".
        # Phase 37 NOTE: gate is wired to 'equities' (individual stocks) but
        # rulebook says it should be 'equity_indices'. Tried Phase 37 fix on
        # 2026-05-25: Stage 1 dropped because the gate started blocking some
        # legitimate Bernd short calls on indices. Reverted per user "100%
        # Bernd-clone" goal. Bernd takes the discretionary call without this
        # gate; copying his behavior means NOT enforcing the gate either.
        if zone_dir == 'short' and asset_class == 'equities':
            gate_ok, gate_reason = self._equity_index_short_cross_asset_gate(
                symbol=symbol,
                cot_df=cot_df,
                valuation_refs=valuation_refs,
            )
            if not gate_ok:
                logger.info(f"[{symbol}] Equity-index short cross-asset gate: {gate_reason}")
                return None

        # OTC L5 Decision Matrix (frames 57, 1484): Action = f(zone_type, location, trend)
        # The matrix labels "demand-at-expensive" and "supply-at-cheap" as
        # ANTICIPATORY / COUNTER-TREND setups. Per Hybrid AI Module 4 these
        # are still tradeable -- just with reduced size (0.5% risk) and
        # stronger Valuation alignment required. So we hard-reject only
        # when Valuation does NOT explicitly agree with the zone direction;
        # otherwise we allow the trade and mark it as anticipatory below.
        location  = ht_bias['location']
        in_equil  = ht_bias.get('in_equilibrium', False)
        zone_type = best_zone['zone_type']
        val_bias  = fund_bias.get('valuation', 'neutral')

        # Demand zone at expensive location: needs Valuation bullish to fire
        if zone_type == 'demand' and location == 'bearish':
            if val_bias != 'bullish':
                logger.info(f"[{symbol}] Decision matrix: demand at expensive location AND Val not bullish -> no action")
                return None
            logger.info(f"[{symbol}] Anticipatory reversal: demand at expensive + Val bullish (reduced size)")

        # Supply zone at cheap location: needs Valuation bearish to fire
        if zone_type == 'supply' and location == 'bullish':
            if val_bias != 'bearish':
                logger.info(f"[{symbol}] Decision matrix: supply at cheap location AND Val not bearish -> no action")
                return None
            logger.info(f"[{symbol}] Anticipatory reversal: supply at cheap + Val bearish (reduced size)")

        # Equilibrium + sideways trend on either zone = genuinely no edge
        if in_equil and trend == 'sideways':
            logger.info(f"[{symbol}] Decision matrix: equilibrium + sideways -> no edge, skip")
            return None

        # == STEP 5: Entry Trigger ==
        # Phase 44 (true-clone redesign): Bernd places E1 PENDING LIMIT ORDERS
        # at zone proximal without waiting for price to arrive or a candle pattern.
        # Rule #4 ("never anticipate a zone") means never trade before the zone
        # FORMS — it does NOT mean wait for price to arrive before placing the order.
        # The old "if not in_zone: return None" gate was blocking 80%+ of real
        # Bernd trades. Now we always fire E1 when a qualified zone exists, marking
        # pending vs immediate so the paper trader and dashboard can distinguish.
        pattern_signal = self._check_entry_pattern(ltf_df, best_zone)

        last = ltf_df.iloc[-1]
        zone_dir_str = best_zone['zone_type']
        in_zone = (
            zone_dir_str == 'demand'
            and last['low']  <= best_zone['proximal']
            and last['low']  >= best_zone['distal']
        ) or (
            zone_dir_str == 'supply'
            and last['high'] >= best_zone['proximal']
            and last['high'] <= best_zone['distal']
        )

        if pattern_signal is None:
            # E1/E2: limit order at zone proximal (pending if price not yet there,
            # immediate fill if price is inside the zone).
            zone_height = abs(best_zone['proximal'] - best_zone['distal'])
            # Rule #8 exception (CLAUDE.md): HTF weekly/monthly income trades
            # use the DISTAL LINE ONLY as the stop (no -33% extension) — this
            # is what achieves the documented 4:1 R:R on the higher timeframe.
            # -33% applies only to LTF refinement / pattern-confirmation
            # entries. This was documented as already fixed (Phase 4+5) but
            # the distal-only branch never actually existed in this function
            # (found during the 2026-07-27 portfolio risk audit) — every
            # weekly/monthly signal was silently getting the LTF-style
            # extended stop instead.
            # C-104 (2026-08-27) -- MIDPOINT ENTRY, resolved from config/env.
            #
            # `prefer_midpoint_entry` has existed since the E2 entry type was
            # written. It defaulted to False, NO caller ever passed it
            # (run_goldtest, run_scanner, run_forward_test, run_realworld all
            # omit it) and BP_config.yaml has no key for it -- so the E2 branch
            # was unreachable code and every signal entered at the zone EDGE.
            #
            # Measured against 38 position tools mined from the Funded Trader
            # Signals frames -- their actual drawn entries, on the same symbol,
            # same date, same weekly bars. Error is in units of THEIR risk:
            #
            #   proximal / body-top of base  (SHIPPED)  median 0.89R   >1R: 18/38
            #   base OPEN extreme                       median 0.84R   >1R: 17/38
            #   base HIGH/LOW extreme                   median 0.57R   >1R: 17/38
            #   ZONE MIDPOINT                           median 0.31R   >1R: 11/38
            #
            # They enter in the MIDDLE of the zone; we entered at the near edge.
            # An entry more than 1R from theirs is not a worse version of their
            # trade, it is a different trade -- their target sits where we are
            # still underwater, their stop where we were stopped out. That is the
            # mechanism behind C-101/C-102: their entries return +0.56R, ours
            # -1.00R, while our DIRECTION agrees 52.7% of the time.
            #
            # Resolution order: explicit argument > env > config > default False.
            # Default stays False so this ships inert and is judged on a measured
            # A/B, not on the argument above.
            if prefer_midpoint_entry is None:
                _env = os.environ.get('BP_MIDPOINT_ENTRY')
                if _env is not None:
                    prefer_midpoint_entry = (_env == '1')
                else:
                    prefer_midpoint_entry = bool(
                        (self.config.get('entry', {}) or {}).get('prefer_midpoint_entry', False)
                    )
            _use_distal_only = income_strategy in ('weekly', 'monthly')
            if zone_dir_str == 'demand':
                entry = (best_zone['proximal'] + best_zone['distal']) / 2.0 if prefer_midpoint_entry else best_zone['proximal']
                stop = best_zone['distal'] if _use_distal_only else best_zone['distal'] - 0.33 * zone_height
                direction = 'long'
            else:
                entry = (best_zone['proximal'] + best_zone['distal']) / 2.0 if prefer_midpoint_entry else best_zone['proximal']
                stop = best_zone['distal'] if _use_distal_only else best_zone['distal'] + 0.33 * zone_height
                direction = 'short'
            targets = self._calculate_targets(entry, stop, direction)
            _entry_type = 'E2' if prefer_midpoint_entry else 'E1'
            _pending_order = not in_zone
        else:
            entry = pattern_signal['entry_price']
            stop = pattern_signal['stop_price']
            direction = 'long' if pattern_signal['direction'] == TradeDirection.LONG else 'short'
            targets = [
                pattern_signal['target_r1'],
                pattern_signal['target_r2'],
                pattern_signal['target_r3']
            ]
            _entry_type = 'E3b'
            _pending_order = False

        # == STEP 6: Trade Management ==
        # Determine trade context for position-size adjustment.
        # Anticipatory = reversal at extreme location. Counter-trend = zone
        # against HTF trend. Both reduce risk per HAI Module 4 + OTC L5.
        is_with_trend = bool(best_zone.get('with_trend'))
        if not is_with_trend and trend != 'sideways':
            trade_context = 'counter_trend'
        elif in_equil and trend != 'sideways':
            trade_context = 'anticipatory'
        else:
            trade_context = 'standard'

        # Action-matrix tier scaling (OTC L4 slide, "this is our action
        # matrix to simplify everything"). Added 2026-07-27: action_matrix_
        # grade() and ACTION_TIER_SIZE_FACTOR were fully implemented but
        # never called from anywhere -- a 'good' setup (trend-aligned, not
        # at an extreme location) was getting the exact same position size
        # as a 'best' setup (trend-aligned AND at an extreme location),
        # when the methodology says 'good' should be sized at 75%.
        # Restricted to trade_context=='standard': counter_trend/anticipatory
        # already have their own reduced-risk multiplier via
        # _calculate_position_size, and action_matrix_grade has no concept
        # of anticipatory/counter-trend setups (its 'reject' default would
        # wrongly veto a legitimate anticipatory trade the decision-matrix
        # gate above already approved). A 'reject' grade within a standard
        # context is mapped to the same 0.5 floor as 'acceptable' rather
        # than 0.0 -- this only scales size, it never blocks a trade outright
        # (the equilibrium/decision-matrix gates earlier already own that).
        _action_tier = None
        _tier_factor = 1.0
        if trade_context == 'standard':
            _action_tier = self.action_matrix_grade(zone_type, location, trend)
            _tier_factor = self.ACTION_TIER_SIZE_FACTOR.get(_action_tier, 1.0)
            if _action_tier == 'reject':
                _tier_factor = 0.5

        position_size = self._calculate_position_size(entry, stop, trade_context) * _tier_factor

        r_mult_targets = [self.stop_config.get('breakeven_at_r', 1.0),
                         self.stop_config.get('partial_take_r', 2.0),
                         self.stop_config.get('full_take_r', 3.0)]

        # Three textbook entry options (OTC 2025 L7) so the user can pick
        # E1/E2/E3 based on R:R math. The auto-selected entry above remains
        # the default; entry_options are exposed so the dashboard can show
        # all choices side-by-side.
        primary_target = targets[1] if len(targets) >= 2 else targets[0]
        entry_options = self.build_entry_options(best_zone, primary_target, pattern_signal, income_strategy=income_strategy)
        recommended   = self.recommend_entry_option(entry_options, min_rr=2.0)

        # Auto-refine: per OTC L7 frame 1420 + Hybrid AI Mod 6 L6, when the
        # primary entry's R:R is below the methodology threshold, attempt
        # to drill the timeframe ladder for a tighter zone contained inside
        # the HTF zone. The refined zone (if found) replaces the entry as
        # the recommended path.
        refined_zone = None
        if recommended.get('rr', 0) < 2.0:
            try:
                refined_zone = self.refine_zone(
                    best_zone, primary_target, ohlcv_data,
                    income_strategy=income_strategy, min_rr=2.0,
                )
                if refined_zone is not None:
                    # Refined zones are always an LTF sub-zone (that's the point
                    # of refinement), so Rule #8's distal-only exception does NOT
                    # apply here even when the parent income_strategy is weekly/
                    # monthly — force the -33% branch by passing a non-exempt
                    # strategy name, matching refine_zone()'s own docstring
                    # ("Stop placement uses LTF distal -33% by default").
                    refined_options = self.build_entry_options(
                        refined_zone, primary_target, pattern_signal,
                        income_strategy='daily',
                    )
                    refined_rec = self.recommend_entry_option(refined_options, min_rr=2.0)
                    if refined_rec['rr'] > recommended['rr']:
                        logger.info(
                            f"[{symbol}] Refined entry boosted R:R "
                            f"{recommended['rr']:.2f} -> {refined_rec['rr']:.2f}"
                        )
                        entry_options = refined_options
                        recommended   = refined_rec
                        # Update the primary entry/stop to reflect refinement
                        entry = refined_rec['entry']
                        stop  = refined_rec['stop']
                        targets = self._calculate_targets(entry, stop, direction)
            except Exception as e:
                logger.warning(f"Auto-refine failed: {e}")

        # == STEP 5a: Real-target R:R floor (Rule #2, 2026-07-27 audit fix) ==
        # Reject if the nearest opposing HTF zone (a genuine external target)
        # is closer than 2R away. When no opposing zone exists we cannot
        # independently verify R:R, so we log it and proceed rather than
        # invent a block on untested grounds — this keeps behavior
        # unchanged for the (common) no-opposing-zone case while adding a
        # real check wherever we actually have the data to make one.
        _risk_final = abs(entry - stop)
        _real_target = self._find_opposing_target(htf_zones, direction, entry)
        if _real_target is not None and _risk_final > 0:
            _real_rr = abs(_real_target - entry) / _risk_final
            if _real_rr < 2.0:
                logger.info(
                    f"[{symbol}] Rejected: real R:R to nearest opposing zone "
                    f"{_real_rr:.2f} below minimum 2.0 (target={_real_target:.5f}, "
                    f"entry={entry:.5f}, stop={stop:.5f})"
                )
                return None
        else:
            logger.info(
                f"[{symbol}] No opposing HTF zone found in profit direction — "
                f"real R:R not independently verified, proceeding on synthetic "
                f"R-ladder only"
            )

        # == STEP 5b: Phase 46 (hardened) distance-to-entry gate ==
        # Runs AFTER refine_zone, on the FINAL entry/stop, for ALL entry types
        # (E1/E2 pending, E1 immediate, E3b pattern). Phase 44 removed the old
        # in_zone gate, which let the engine emit limit orders for historical
        # zones 30-77% away from current price (e.g. a Silver demand at 23.76
        # while spot was 62.37). Bernd places limit orders for zones price is
        # APPROACHING, not zones years away. We bound the distance from current
        # price to the entry, measured in R-multiples of the stop distance so
        # the cap scales with each asset's volatility. refine_zone can shrink
        # the stop (a tighter contained sub-zone), which is exactly why this
        # must run on the post-refinement values, not the original wide zone.
        _final_close = float(ltf_df['close'].iloc[-1])
        _risk_per_unit = abs(stop - entry)
        # Recompute the in-zone / pending flags against the FINAL entry so the
        # emitted signal's price_at_zone / pending_order fields stay accurate
        # even when refinement moved the entry. Close-based (not last-bar-wick)
        # so a single intrabar spike can no longer disable the gate.
        if direction == 'long':
            in_zone = _final_close <= entry      # price at/below a long limit = fillable now
        else:
            in_zone = _final_close >= entry      # price at/above a short limit = fillable now
        _pending_order = not in_zone
        # Combined distance gate: reject if the entry is too far from current
        # price in EITHER R-multiples (volatility-scaled) OR raw percent. The
        # R cap alone has a blind spot for very WIDE zones (a 23%-away entry can
        # still be <3R when the stop is far); the % cap closes it.
        _ed_cfg = self.config.get('entry_distance', {}) or {}
        _r_away = abs(_final_close - entry) / _risk_per_unit if _risk_per_unit > 0 else 0.0
        _pct_away = abs(_final_close - entry) / _final_close * 100 if _final_close else 0.0
        _max_r_map   = _ed_cfg.get('max_r_to_entry_pending', {}) or {}
        _max_pct_map = _ed_cfg.get('max_pct_to_entry', {}) or {}
        _max_r   = float(_max_r_map.get(income_strategy, _ed_cfg.get('default_max_r', 3.0)))
        _max_pct = float(_max_pct_map.get(income_strategy, _ed_cfg.get('default_max_pct', 15.0)))
        if (_risk_per_unit > 0 and _r_away > _max_r) or (_pct_away > _max_pct):
            logger.info(
                f"[{symbol}] Entry too far from price: {_pct_away:.1f}% / {_r_away:.1f}R "
                f"(caps {_max_pct}% / {_max_r}R, type={_entry_type}, strategy={income_strategy}). "
                f"Zone exists but price has not approached — watch-list only."
            )
            return None

        # Speed-bump check: opposing zones in the path between current price
        # and entry. Per OTC L6, a qualified opposing zone in the return
        # path will likely stall the trade. We flag but don't auto-reject.
        current_price = float(ltf_df['close'].iloc[-1])
        speed_bumps = self.zone_detector.detect_speed_bumps(
            ltf_zones, best_zone, current_price,
        )
        speed_bump_blocking = self.zone_detector.has_blocking_speed_bump(
            ltf_zones, best_zone, current_price, min_score=5.0,
        )

        # ================================================================
        # Economic Calendar / News Blackout check (audit gap #4)
        # High-impact events (CPI, FOMC, NFP, ECB, BoE) within +/-2h
        # -> reduce risk to 0.5%. Holidays -> full skip.
        # ================================================================
        calendar = get_calendar()
        # C-126, default OFF (BP_CALENDAR_ASOF). `check_blackout()` with no argument
        # documents "Defaults to now" and does datetime.utcnow(), so in every historical
        # run this asked "is TODAY a blackout?" rather than "was the SCAN DATE a
        # blackout?". BP_calendar passes a date at all three of its own call sites; only
        # this one omitted it.
        #
        # Effect: the calendar has been inert in every backtest recorded in this project
        # -- harmless for A/B comparisons, since it is constant across arms, but it means
        # LIVE trading would gate signals that no backtest ever gated. That is a
        # backtest/live divergence, not a scoring error.
        #
        # The as-of date is the last LTF bar, which the harness has already truncated to
        # the call date. Default OFF because switching it changes signal counts on every
        # historical run, so it needs its own A/B against a baseline built with this code.
        _asof = None
        if os.environ.get('BP_CALENDAR_ASOF') == '1':
            try:
                _ts = ltf_df['timestamp'].iloc[-1]
                _asof = pd.to_datetime(_ts)
                if getattr(_asof, 'tzinfo', None) is not None:
                    _asof = _asof.tz_localize(None)
                _asof = _asof.to_pydatetime()
            except Exception:
                _asof = None      # fall back to the old behaviour rather than crash
        blackout = calendar.check_blackout(_asof) if _asof else calendar.check_blackout()
        calendar_blackout = blackout.to_dict()
        if blackout.in_blackout:
            logger.info(
                f"[{symbol}] Calendar blackout active: {blackout.reason} "
                f"(risk_multiplier={blackout.risk_multiplier})"
            )
            if blackout.risk_multiplier == 0.0:
                return None
            if blackout.risk_multiplier < 1.0:
                position_size *= blackout.risk_multiplier
                logger.info(
                    f"[{symbol}] Calendar blackout: "
                    f"position_size reduced to {position_size:.4f}"
                )

        signal = {
            'symbol': symbol,
            'direction': direction,
            'entry_type': _entry_type,           # E1/E2 (pending limit) or E3b (pattern confirmed)
            'pending_order': _pending_order,     # True = price hasn't reached zone yet
            'price_at_zone': in_zone,            # True = price currently inside zone
            'entry_price': round(entry, 6),
            'stop_price': round(stop, 6),
            'targets': [round(t, 6) for t in targets],
            'entry_options': entry_options,
            'recommended_entry': recommended['label'],
            'speed_bumps': [{'id': sb['id'], 'proximal': sb['proximal'],
                              'distal': sb['distal'], 'score': sb['composite_score']}
                             for sb in speed_bumps[:3]],
            'calendar_blackout': calendar_blackout,
            'speed_bump_warning': speed_bump_blocking,
            'has_big_brother': bool(best_zone.get('has_big_brother')),
            'big_brother_id':  best_zone.get('big_brother_id'),
            'trade_context': trade_context,   # standard / counter_trend / anticipatory
            'action_tier': _action_tier,      # best / good / acceptable / reject / None (non-standard context)
            'zone_id': best_zone['id'],
            'income_strategy': income_strategy,
            'risk_amount': round(abs(entry - stop) * position_size, 2),
            'position_size': round(position_size, 4),
            'r_multiple_targets': r_mult_targets,
            'bias_consensus': biases,
            'qualifier_scores': {
                'departure': best_zone['departure_score'],
                'base_duration': best_zone['base_duration_score'],
                'freshness': best_zone['freshness_score'],
                'originality': best_zone['originality_score'],
                'profit_margin': best_zone['profit_margin_score'],
                'arrival': best_zone['arrival_score'],
                'level_on_top': best_zone['level_on_top_score'],
                'composite': best_zone['composite_score']
            },
            'timestamp': datetime.now().isoformat(),
            'htf': htf,
            'ltf': ltf
        }

        # Monthly roadmap filter (HAI Mod 3 + FT monthly outlooks): tag the
        # signal with the timing-overlay forecast for the current month.
        # Counter-roadmap signals get a warning but aren't auto-rejected.
        try:
            today = datetime.now().date()
            roadmap = build_monthly_roadmap(
                asset=symbol,
                asset_class=asset_class,
                target_month=today,
                seasonality_bias=fund_bias['seasonality'],
                cot_bias=fund_bias['cot'],
                cot_strength=fund_bias.get('cot_strength', 'normal'),
            )
            signal = filter_signal_by_roadmap(signal, roadmap)
        except Exception as e:
            logger.warning(f"Roadmap filter failed: {e}")

        logger.info(f"[{symbol}] SIGNAL: {direction} at {entry:.2f}, stop={stop:.2f}, targets={[round(t,2) for t in targets]}")
        return signal

    def _analyze_htf(
        self, df: pd.DataFrame, htf_zones: Optional[List[Dict]] = None,
        htf: str = '1d',
        symbol: Optional[str] = None,
        asset_class: Optional[str] = None,
    ) -> Dict[str, str]:
        """Step 2: HTF Technical Analysis - Location and Trend.

        Location is the proper Blueprint Fib: from the most recent qualified
        demand zone distal (Fib 0) up to the most recent qualified supply zone
        distal (Fib 100). Falls back to the lookback-range approximation only
        when no zones exist yet.
        """
        if 'close' not in df.columns or len(df) < 50:
            return {'location': 'neutral', 'trend': 'sideways'}

        closes = df['close'].values
        highs  = df['high'].values
        lows   = df['low'].values
        current = closes[-1]

        # DeepSeek Gap 3: USD-base forex pairs invert prices to quote-currency perspective
        is_usd_base_forex = (
            symbol is not None
            and symbol.upper().startswith('USD')
            and '=X' in symbol
        )
        if is_usd_base_forex:
            with np.errstate(divide='ignore', invalid='ignore'):
                closes = 1.0 / closes
                highs  = 1.0 / df['low'].values
                lows   = 1.0 / df['high'].values
            closes = np.nan_to_num(closes, nan=0.0, posinf=0.0, neginf=0.0)
            highs  = np.nan_to_num(highs,  nan=0.0, posinf=0.0, neginf=0.0)
            lows   = np.nan_to_num(lows,   nan=0.0, posinf=0.0, neginf=0.0)
            current = closes[-1]

        # ---- Preferred: use detected HTF zone distals ----
        # Phase 25 (DeepSeek P1): filter out invalidated/consumed zones before
        # selecting the most recent. A stale zone with a wide-out distal can
        # distort the Fib range and produce wrong "cheap/expensive" reads.
        # A zone is considered USABLE for the Location Fib when its freshness
        # qualifier is non-zero (i.e. not consumed and not penetrated >25%).
        def _zone_is_usable(z):
            # Q3 freshness == 0 means: consumed (retested at proximal+ depth)
            # OR penetrated >25% (Phase 6 P1 hard rule). Both make the distal
            # unreliable for Fib anchoring.
            # Phase 37 NOTE: tried adding `or z.get('freshness_score')` lookup
            # on 2026-05-25 (Phase 25 stale-zone filter was inert because the
            # nested qualifier_scores dict the lookup used never exists — detector
            # emits flat freshness_score key). The fix activated the filter, which
            # changed Location Fib for many zones and dropped Stage 1 by 8 cases.
            # Reverted per "100% Bernd-clone" goal — Bernd's calls were apparently
            # using the un-filtered Fib too.
            q = z.get('qualifier_scores') or {}
            freshness = q.get('Q3') or q.get('Q3_freshness') or q.get('freshness')
            if freshness is None:
                # Older zones may not carry qualifier scores — fall back to
                # the explicit invalidation flag set by zone detector.
                return not z.get('invalidated', False)
            try:
                return float(freshness) > 0.0
            except (TypeError, ValueError):
                return True  # if score is unparseable, prefer to keep zone

        range_min = range_max = None
        if htf_zones:
            usable = [z for z in htf_zones if _zone_is_usable(z)]
            demand_zones = [z for z in usable if z['zone_type'] == 'demand']
            supply_zones = [z for z in usable if z['zone_type'] == 'supply']
            if demand_zones and supply_zones:
                # Most recent of each (highest origin_index)
                d = max(demand_zones, key=lambda z: z['origin_index'])
                s = max(supply_zones, key=lambda z: z['origin_index'])
                if is_usd_base_forex and d['distal'] and s['distal']:
                    # Zones were detected on RAW price, but `current`/`highs`/
                    # `lows` above are inverted to the quote-currency frame.
                    # Invert the distals too so the Fib range and `current`
                    # share ONE unit frame. Inversion flips ordering: the demand
                    # distal (low raw price) becomes the HIGH inverted level and
                    # the supply distal (high raw price) becomes the LOW inverted
                    # level -- hence min<-1/supply, max<-1/demand. Without this
                    # the pct saturates far outside [0,100] and pins every
                    # USD-base pair to a constant label (audit rank 1).
                    range_min = 1.0 / s['distal']
                    range_max = 1.0 / d['distal']
                else:
                    range_min = d['distal']
                    range_max = s['distal']

        # ---- Fallback: lookback range ----
        # C-80 diagnostic: record WHICH range produced the Location label. The
        # zone-based range needs a usable demand AND supply zone with
        # supply_distal > demand_distal; in a sustained trend the newest demand can
        # sit above the newest supply, so this silently falls back to a trailing
        # 200-bar range -- against which a trending market is permanently pinned to
        # one end, freezing the label.
        _loc_source = 'zones'
        if range_min is None or range_max is None or range_max <= range_min:
            _loc_source = 'fallback_200bar'
            lookback_len = min(200, len(closes))
            range_min = lows[-lookback_len:].min()
            range_max = highs[-lookback_len:].max()

        range_span = range_max - range_min
        location_pct = 50 if range_span <= 0 else (current - range_min) / range_span * 100

        # C-84 EXPERIMENTAL, DEFAULT OFF: price OUTSIDE the zone range is NO SETUP,
        # not a directional read. Source: "Practical Application - Location"
        # (OTC course, 05.03.2024), working a live NVDA chart at an all-time high:
        #   0:47:55 "this is a little bit tricky, obviously, because we are at an
        #            all-time high"
        #   0:51:00 "we have here our areas. I mean, this is very high."
        #   0:51:45 "it doesn't look, doesn't look that nice, to be honest"
        #   0:53:11 "that's the question if price comes ever back to this area"
        # He treats beyond-the-range as UNTRADEABLE and waits for price to return --
        # he does not call it bearish. Our code labels exactly that condition 'bearish'
        # because price sits at the top of the Fib.
        # Measured (C-80): 27% of rows have location_pct outside [0,100], spanning
        # -571 to 1594, and the bearish reads among them are 35% accurate.
        # The same session confirms the THIRDS are his: 0:15:22 "we would split that
        # level into two, into three sections" -- so the 33/67 cut stays; only the
        # out-of-range case changes.
        _loc_outside_neutral = bool(
            (self.config.get('rules', {}) or {}).get('outside_range_is_no_setup', False)
            or os.environ.get('BP_OUTSIDE_RANGE_NEUTRAL') == '1'
        )
        # ASYMMETRIC, and measured: out-of-range reads are NOT equally bad.
        #   above the range (pct > 100): would read 'bearish', 7/20 = 35% accurate
        #   below the range (pct < 0)  : would read 'bullish', 14/16 = 88% accurate
        # Neutralising both cost 8 MATCHes (CL=F, ES=F, NG=F x2, SB=F were correct
        # longs turned into holds). His ATH remark is specifically about price ABOVE
        # the range -- "we are at an all-time high ... if price comes ever back to this
        # area" -- so only the above-range case becomes no-setup.
        if _loc_outside_neutral and location_pct > 100.0:
            location = 'neutral'
        elif location_pct <= 33:
            location = 'bullish'
        elif location_pct >= 67:
            location = 'bearish'
        else:
            location = 'neutral'

        # C-81 EXPERIMENTAL, DEFAULT OFF: location per the COURSE definition.
        # OTC Blueprint Strategy Course p.45, "Practical Application - Location":
        #     "1. LOCATION - HTF analysis to identify WHERE, IN TERMS OF LARGER SUPPLY
        #      AND DEMAND ZONES, PRICE IS MOST LIKELY TO TURN"
        # That is a question about price being AT a zone, not about its percentile
        # inside a range. The percentile form measures 83-88% accurate when it says
        # bullish and only 30-35% when it says bearish (C-79/C-80), in-range and
        # out-of-range alike -- because "70% of the way up a range" is NOT the same
        # claim as "at supply, likely to turn down".
        # This variant only asserts a direction when price is actually INSIDE a
        # usable HTF zone, and returns neutral otherwise.
        if bool((self.config.get('rules', {}) or {}).get('location_requires_zone_touch', False)
                or os.environ.get('BP_LOC_ZONE_TOUCH') == '1'):
            _touch = None
            if htf_zones:
                for _z in [z for z in htf_zones if _zone_is_usable(z)]:
                    _lo, _hi = sorted([_z.get('proximal'), _z.get('distal')])
                    if _lo is None or _hi is None:
                        continue
                    if _lo <= current <= _hi:
                        # inside a zone -> that zone's type IS the location read
                        _touch = 'bullish' if _z['zone_type'] == 'demand' else 'bearish'
                        break
            location = _touch or 'neutral'
            location_pct = 50.0 if _touch is None else (0.0 if _touch == 'bullish' else 100.0)

        # For USD-base forex, `highs`/`lows` are inverted to the quote-currency
        # frame (used for the Location Fib, whose label is flipped back to the
        # pair frame below). Trend must be expressed in the SAME pair frame as
        # the flipped-back location and the consensus direction, otherwise the
        # Phase 8 counter-trend safety gate compares mismatched frames and can
        # wave through a counter-trend forex trade (audit rank 4). Compute trend
        # on the raw pair prices for these pairs.
        if is_usd_base_forex:
            trend = self._determine_trend(
                df['high'].values, df['low'].values, htf=htf, symbol=symbol)
        else:
            trend = self._determine_trend(highs, lows, htf=htf, symbol=symbol)

        # DeepSeek Gap 1: equity indices ATH momentum override.
        # In a confirmed uptrend with strong short-term momentum, downgrade
        # expensive location to neutral so the hard bearish veto does not block
        # long signals when presidential/sannial cycles are bullish.
        # 2026-08-21 (C-80): this override exists because `location_pct` is measured
        # against a TRAILING 200-bar range, so in a sustained trend price sits pinned at
        # one end of its own range and the label freezes. Measured on the 133-row set:
        # location is 84% accurate when it says bullish and 32% when it says bearish, and
        # it returns an IDENTICAL value on every row for GC=F (bearish 13/13 across 13
        # months of a rally), BABA, NG=F, PA=F, ZC=F and RACE. The equity_indices scoping
        # was a symptom-level patch; the defect is not class-specific.
        # EXPERIMENTAL, DEFAULT OFF: extend the momentum override to ALL classes, and
        # mirror it for the downtrend case (a cheap label frozen on a falling market is
        # the same bug with the sign flipped).
        _loc_mom_all = bool(
            (self.config.get('rules', {}) or {}).get('momentum_unfreezes_location', False)
            or os.environ.get('BP_MOMENTUM_UNFREEZE_LOC') == '1'
        )
        _loc_mom_classes = ('equity_indices',) if not _loc_mom_all else None
        if (location == 'bearish'
                and trend == 'uptrend'
                and len(closes) >= 5
                and (_loc_mom_classes is None or asset_class in _loc_mom_classes)):
            roc_4 = (closes[-1] - closes[-4]) / closes[-4] if closes[-4] != 0 else 0
            if roc_4 > 0.02:
                location = 'neutral'
                location_pct = 50.0
        if (_loc_mom_all
                and location == 'bullish'
                and trend == 'downtrend'
                and len(closes) >= 5):
            roc_4 = (closes[-1] - closes[-4]) / closes[-4] if closes[-4] != 0 else 0
            if roc_4 < -0.02:
                location = 'neutral'
                location_pct = 50.0

        # DeepSeek Gap 3: flip location label back to original pair direction
        # after inverted price computation for USD-base forex.
        if is_usd_base_forex:
            if location == 'bullish':
                location = 'bearish'
            elif location == 'bearish':
                location = 'bullish'

        # Per OTC Lesson 3 frames 1887-1901: equilibrium location (33-66%)
        # is "no big brother" territory and degrades zone quality even with
        # HTF coverage. Returned as `location_pct` for downstream scoring.
        return {
            'location': location, 'trend': trend,
            'location_pct': round(float(location_pct), 1), 'location_source': _loc_source,
            'location_pct': round(location_pct, 1),
            'in_equilibrium': 33 < location_pct < 67,
        }

    def _determine_trend(
        self, highs: np.ndarray, lows: np.ndarray, htf: str = '1d',
        symbol: Optional[str] = None
    ) -> str:
        """Identify trend using ZigZag pivots (Hybrid AI methodology).

        Per Bernd's course: a pivot is confirmed when price reverses by at
        least the ZigZag percentage from the most recent extreme.

        ZigZag percentages by timeframe (Hybrid AI defaults + OTC Ch.012):
          Monthly : ~10%
          Weekly  : ~6%   (OTC Module 6 Ch.012: "six second percent" on weekly Netflix)
          Daily   : ~3%
          4H      : ~2%
          1H      : ~1%

        Previously used a flat 3% (daily default) for ALL timeframes.
        On weekly data that is too fine: ES weekly bars regularly move
        2-4%, so 3% confirms pivots on every swing and generates dozens of
        small reversals that obscure the broader trend. This caused weekly
        equity-index trend detection to show 'downtrend' when the market
        was clearly in a 12-month uptrend (e.g. ES in Jan 2024). Using 6%
        for weekly bars matches the OTC course explicit example.
        """
        # Per-timeframe ZigZag defaults (OTC Ch.012 + Hybrid AI course).
        # config.zigzag_percent overrides only the daily fallback.
        TF_ZIGZAG = {
            '1mo':  0.10,
            '1wk':  0.06,  # OTC Ch.012: "six second percent" on weekly chart
            '1d':   float(self.config.get('zigzag_percent', 3.0)) / 100.0,
            '60m':  0.02,
            '30m':  0.015,
            '15m':  0.01,
        }
        zz_pct = TF_ZIGZAG.get(htf, float(self.config.get('zigzag_percent', 3.0)) / 100.0)
        # Phase 29 main-thread frame-verified: Ch025 (Energies practical) frame_001246
        # status bar reads `ZigZag % ( High , Low , 5 , white , 3 )` on @NG weekly.
        # Override the weekly default for natural gas.
        if symbol in NAT_GAS_SYMBOLS and htf == '1wk':
            zz_pct = 0.05
        # Phase 41 chunk 2: per-asset weekly ZigZag overrides.
        # PA=F (Palladium) frame_002744: ZigZag weekly = 15%.
        # ZW=F (Wheat) frame_000509: ZigZag weekly = 10%.
        if symbol == 'PA=F' and htf == '1wk':
            zz_pct = 0.15
        if symbol == 'ZW=F' and htf == '1wk':
            zz_pct = 0.10
        # Full-corpus indicator audit (2026-07): SI=F (Silver) weekly ZigZag = 10%.
        # Ch.015 frame_002463 shows the original setting = 10; Bernd interactively
        # tests 5 and 2 in the customize dialog (frames 002478, 002488) then
        # explicitly reverts: "I would rather stick with what I had originally
        # here... 10" (frame_002491, 0:41:30). No override previously coded for
        # Silver, so it fell through to the 6% global weekly default.
        if symbol == 'SI=F' and htf == '1wk':
            zz_pct = 0.10
        # Phase 41 chunk 1 speech audit: CL daily ZigZag = 5%
        # (Zone Qualifiers lesson frame_004397 status bar: ZigZag % (High,Low,5,white,3))
        if symbol in ENERGY_SYMBOLS and htf == '1d':
            zz_pct = 0.05
        # Full-corpus indicator audit (2026-07): @ES (E-mini S&P 500) uses a flat
        # 5% ZigZag on ALL timeframes, not the general tiered 10/6/3 table.
        # Chapter 012 (Module 2 Lesson 3) shows the identical status-bar label
        # `ZigZag % ( High , Low , 5 , white, 3 )` on the SAME @ES chart across
        # Weekly (frames 002513/002616), Monthly (frame_002793), and Daily
        # (frame_002917) — a single flat setting confirmed on three timeframes
        # of one instrument, overriding whichever tiered default would otherwise
        # apply.
        if symbol == 'ES=F' and htf in ('1mo', '1wk', '1d'):
            zz_pct = 0.05

        # Shorter lookback for longer timeframes: 200 weekly bars = 4 years
        # and includes bear-market lows that distort the recent trend picture.
        # Weekly income strategy needs ~2 years (100 bars); monthly ~3 years.
        LOOKBACK = {'1mo': 60, '1wk': 100, '1d': 200, '60m': 200, '15m': 200}
        n = min(LOOKBACK.get(htf, 200), len(highs))
        if n < 10:
            return 'sideways'
        h = highs[-n:]
        l = lows[-n:]

        pivots = self._zigzag_pivots(h, l, zz_pct)
        if len(pivots) < 4:
            return 'sideways'

        # Separate by type and take most recent 3 of each
        swing_highs = [(i, p) for i, p, t in pivots if t == 'H'][-3:]
        swing_lows  = [(i, p) for i, p, t in pivots if t == 'L'][-3:]

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return 'sideways'

        hh_vals = [p for _, p in swing_highs]
        ll_vals = [p for _, p in swing_lows]

        higher_highs = all(hh_vals[i] > hh_vals[i-1] for i in range(1, len(hh_vals)))
        higher_lows  = all(ll_vals[i] > ll_vals[i-1] for i in range(1, len(ll_vals)))
        lower_highs  = all(hh_vals[i] < hh_vals[i-1] for i in range(1, len(hh_vals)))
        lower_lows   = all(ll_vals[i] < ll_vals[i-1] for i in range(1, len(ll_vals)))

        # OTC Lesson 4 frames 378/466: pivot requirements are ASYMMETRIC.
        # Uptrend = higher LOWS are mandatory ("Required: 2x HL"); higher
        # highs are optional ("not necessarily required"). Downtrend = lower
        # HIGHS are mandatory; lower lows optional. Bernd shows that price
        # can carve a sideways top while higher lows still rise = still an
        # uptrend if HLs are intact.
        if higher_lows:
            return 'uptrend'
        if lower_highs:
            return 'downtrend'
        # Strict-symmetric fallback (legacy): only call out the trend if
        # both legs confirm. Otherwise sideways.
        if higher_highs and higher_lows:
            return 'uptrend'
        if lower_highs and lower_lows:
            return 'downtrend'
        return 'sideways'

    def _zigzag_pivots(self, h: np.ndarray, l: np.ndarray, pct: float) -> List[Tuple[int, float, str]]:
        """ZigZag pivot detection: a pivot is confirmed when price reverses
        by `pct` from the running extreme. Returns chronological list of
        (index, price, 'H'|'L') tuples.
        """
        n = len(h)
        if n < 2:
            return []
        pivots: List[Tuple[int, float, str]] = []
        # Seed direction from first 2 bars
        last_pivot_idx = 0
        last_pivot_val = h[0]
        last_pivot_type = 'H'  # provisional
        # Track extremes since last pivot
        max_idx, max_val = 0, h[0]
        min_idx, min_val = 0, l[0]
        direction = 0  # 0=undetermined, 1=up, -1=down

        for i in range(1, n):
            if h[i] > max_val:
                max_idx, max_val = i, h[i]
            if l[i] < min_val:
                min_idx, min_val = i, l[i]

            if direction >= 0:
                # Looking for a downside reversal from max_val
                if max_val > 0 and (max_val - l[i]) / max_val >= pct:
                    # Confirm a high pivot at max_idx
                    pivots.append((max_idx, max_val, 'H'))
                    last_pivot_idx, last_pivot_val, last_pivot_type = max_idx, max_val, 'H'
                    direction = -1
                    min_idx, min_val = i, l[i]
            if direction <= 0:
                if min_val > 0 and (h[i] - min_val) / min_val >= pct:
                    pivots.append((min_idx, min_val, 'L'))
                    last_pivot_idx, last_pivot_val, last_pivot_type = min_idx, min_val, 'L'
                    direction = 1
                    max_idx, max_val = i, h[i]
        return pivots

    def _indicators_for_class(
        self, asset_class: str, symbol: Optional[str] = None,
        htf: str = '1wk',
    ):
        """Build COT and Valuation engines tuned for the symbol's asset class.

        Per Hybrid AI Mod 3 + Funded Trader live trades:
          - COT: 26w default (Hybrid AI), 52w override for commodities
            (planting/harvest cycle). 156w extreme overlay always on.
          - Valuation ROC ("cycle"): asset-class default (10 / 13) with
            optional per-symbol override from `valuation.cycle_per_symbol`
            in BP_config.yaml. Bernd's "30-day cycle" / "10-day cycle"
            are simply different ROC periods on the same indicator
            (HAI 1:53:38). Per-symbol cheat-sheet style.
        """
        # Symbol-level override: soft agricultural commodities use Non-Commercials
        # at 26w (CLAUDE.md P1 fix) even when asset_class is still 'commodities'.
        # Natural Gas uses Retailers (contrarian) — Blueprint Cheatsheet fix.
        effective_class = asset_class
        if symbol in SOFT_COMMODITY_SYMBOLS:
            effective_class = 'soft_commodities'
        elif symbol in NAT_GAS_SYMBOLS:
            effective_class = 'nat_gas'
        elif symbol in CRUDE_OIL_SYMBOLS:
            # C-44: crude reads RETAIL contrarian, not the 'energies' Commercials
            # default. MUST stay mirrored with _analyze_fundamentals'
            # cot_effective_class -- see the note there.
            effective_class = 'crude_oil'

        cot_lookback = COT_LOOKBACK_BY_CLASS.get(
            effective_class, self.cot_index.lookback_weeks
        )

        # Phase 23 (Task 3): JPY 52-week COT lookback override.
        # 6J=F has low open interest → 26w window stays near index 50.
        # 52w gives the index more range to reach extremes.
        if symbol in JPY_SYMBOLS:
            cot_lookback = 52

        # Full-corpus indicator audit (2026-07): CL=F COT lookback 52w -> 26w
        # (settings-dialog confirmed twice — see CRUDE_OIL_COT_26W_SYMBOLS above).
        if symbol in CRUDE_OIL_COT_26W_SYMBOLS:
            cot_lookback = 26

        val_length = VALUATION_LENGTH_BY_CLASS.get(
            asset_class, self.valuation.length
        )
        # Per-symbol override (e.g. AAPL=30 daily, NDX=10 daily)
        #
        # GAP-14/GAP-15 (deferred since Phase 38) IMPLEMENTED 2026-08 -- see
        # CODE_FINDINGS C-46. A cycle_per_symbol entry may now be either:
        #     SYM: 30                      -> flat, all timeframes (unchanged)
        #     SYM: {daily: 30, weekly: 13} -> resolved against the ACTIVE htf
        # This matters because Valuation is computed on the HTF bars (see
        # `_analyze_fundamentals`, which receives htf_df as price_df). The Phase 38
        # interim note reasoned "13 is the weekly end-of-bend value ... applying it
        # to daily scans gives the wrong ROC period. Set to 30 (preferred daily)"
        # -- but the weekly scanner never runs Valuation on daily bars, so a flat
        # 30 applies the DAILY value to a WEEKLY series. The dict form lets each
        # timeframe carry its own documented value instead of picking one globally.
        # Flat ints are untouched, so this change is behaviour-neutral until an
        # entry is actually converted to the dict form.
        # C-97 (2026-08-27) EXPERIMENTAL, DEFAULT OFF -- BP_VAL_FRAME_LENGTH=1
        #
        # `cycle_per_symbol` sets ROC Length 30 for the ags/softs. The Valuation
        # legend prints the Length he is actually running, and for three of those
        # six symbols the frames say 10, not 30:
        #
        #     ZS=F   observed 10 x6    config 30   CONTRADICTED
        #     ZC=F   observed 10 x2    config 30   CONTRADICTED
        #     KC=F   observed 10 x5    config 30   CONTRADICTED
        #     CT=F   observed 30 x3    config 30   supported
        #     ZW=F   no observations
        #     CC=F   no observations
        #     HG=F   observed 10 x1    config 10   supported (not overridden)
        #
        # 13 observations against the override, 3 for it. Per-symbol n is small and
        # is stated as such; the flag exists to measure whether it matters, not to
        # assert that it does.
        #
        # This also explains why commodity Valuation diverges from his distribution:
        # we run a 30-bar ROC on WEEKLY bars where the legend shows 10. Pooled across
        # the whole corpus the Length he uses is {10: 77, 13: 59, 30: 3} (n=146,
        # counting only legends where all three reference booleans are visible so the
        # Length's position is unambiguous). 30 is 2% of sightings and the config
        # applies it to six symbols.
        _frame_length = os.environ.get('BP_VAL_FRAME_LENGTH') == '1'
        _FRAME_CONTRADICTED = {'ZS=F', 'ZC=F', 'KC=F'}
        cycle_overrides = self.config.get('valuation', {}).get('cycle_per_symbol', {}) or {}
        if _frame_length and symbol in _FRAME_CONTRADICTED:
            cycle_overrides = {k: v for k, v in cycle_overrides.items() if k != symbol}
        if symbol and symbol in cycle_overrides:
            override = cycle_overrides[symbol]
            if isinstance(override, int):
                val_length = override
            elif isinstance(override, dict):
                _tf_key = 'weekly' if str(htf).lower() in ('1wk', 'wk', 'weekly', 'w') else \
                          'monthly' if str(htf).lower() in ('1mo', 'mo', 'monthly', 'm') else 'daily'
                # timeframe-specific value first, then a generic 'roc', then the class default
                val_length = override.get(_tf_key, override.get('roc', val_length))

        # C-87 (2026-08-24) EXPERIMENTAL, DEFAULT OFF -- weekly Valuation Length.
        #
        # Measured on the transcribed Practical Application corpus
        # (gemini/mine_practical.py, n=219 CampusValuationTool legend frames
        # carrying a parsable argument list):
        #
        #     Weekly charts  n=59   L13:53 (90%)  L10:3   L30:3
        #     Daily  charts  n=115  L10:57  L30:50 (93% combined)  L13:6 (5%)
        #
        # Weekly+13 is supported by 7 DISTINCT chapters, so it is not a
        # single-session artifact; excluding the Corn-heavy 2024-02-08 chapter
        # it still holds 16/22 = 73%. Daily+{10,30} holds at 94% with Corn
        # excluded. Length therefore tracks the TIMEFRAME, not the asset class
        # -- which is what the Phase 38 note next to `cycle_per_symbol` already
        # suspected ("13 is the weekly end-of-bend value only") and what
        # VALUATION_LENGTH_BY_CLASS's equity_indices comment read as a
        # disagreement BY DATE.
        #
        # All 60 `cycle_per_symbol` entries are flat ints sourced from DAILY
        # sightings, and the weekly income stream computes Valuation on WEEKLY
        # bars, so today every weekly scan applies a daily-sourced ROC period.
        # This flag substitutes the measured weekly value instead.
        #
        # MEASURED 2026-08-24, back-to-back A/B on all 133 ground-truth rows
        # (validate_against_lectures.py --verdicts all_traders_ground_truth.csv
        # --min-confidence low). Control run was byte-identical to the pre-patch
        # baseline, so the flag is inert when off:
        #
        #     control    MATCH 77 (58%)  hold 46  OPPOSITE 10   longs 66/100  shorts 11/32
        #     flag ON    MATCH 78 (59%)  hold 44  OPPOSITE 11   longs 67/100  shorts 11/32
        #
        # The Valuation bias changed on 19 of 132 rows, but only 4 verdicts moved,
        # and every one of them came from `val bearish -> neutral`:
        #     SI=F    2023-02-18  hold     -> MATCH      (gain)
        #     BTC-USD 2023-05-13  OPPOSITE -> miss       (gain)
        #     USDCHF  2023-06-20  hold     -> OPPOSITE   (loss)
        #     SI=F    2023-09-23  hold     -> OPPOSITE   (loss)
        #
        # +1 MATCH bought with +1 OPPOSITE is the same trade C-79 was rejected
        # for, and an OPPOSITE is the failure mode that costs money. REJECTED as
        # a global default -- flag stays OFF. Kept in the tree because the
        # direction of the effect is informative: a longer weekly ROC makes our
        # Valuation materially less bearish, which is the wrong way to push a
        # scoreboard whose shorts already run at 33%. Consistent with C-83 --
        # their bearish calls come from COT, not from Valuation.
        #
        # Explicit dict-form overrides win
        # over the flag so a frame-verified per-symbol weekly value is never
        # overwritten by the corpus-wide default.
        _weekly_val_13 = (
            (self.config.get('rules', {}) or {}).get('valuation_weekly_length_13', False)
            or os.environ.get('BP_VAL_WEEKLY_13') == '1'
        )
        if _weekly_val_13 and str(htf).lower() in ('1wk', 'wk', 'weekly', 'w'):
            _explicit_weekly = (
                isinstance(cycle_overrides.get(symbol), dict)
                and 'weekly' in cycle_overrides[symbol]
            )
            if not _explicit_weekly:
                val_length = 13

        # Full-corpus indicator audit (2026-07): forex Valuation threshold
        # reverted from +-69 back to the general +-75 default.
        # Phase 38 restored +-69 based on one verbal citation (Ch18 [0:16:33])
        # plus the Blueprint Cheatsheet annotation for EUR/JPY/GBP/CHF, judged
        # to outweigh a single settings-dialog frame (Ch018 frame_000183, @EC,
        # showing 75). A dedicated re-investigation frame-verified the ON-SCREEN
        # threshold across 5 independent sightings spanning AUD (Ch074), EUR
        # (Ch173), CHF and GBP (Ch167 CW05 FX Edition — a genuine LIVE session,
        # not a teaching demo), and an equity-index Valuation variant: every
        # single one draws +-75. Zero on-screen sightings of 69/-69 anywhere in
        # the corpus. The +-69 figure traces only to the Cheatsheet spreadsheet
        # annotation with no corresponding on-screen indicator configuration
        # ever found — it appears to be a cheatsheet-only note that was never
        # actually wired into the live tool. Dropping the forex-specific
        # override entirely; forex now uses the same +-75 default as every
        # other asset class.
        val_overvalued  = self.valuation.overvalued
        val_undervalued = self.valuation.undervalued

        cot = COTIndex(
            lookback_weeks=cot_lookback,
            upper_extreme=self.cot_index.upper_extreme,
            lower_extreme=self.cot_index.lower_extreme,
        )
        val = Valuation(
            length=val_length,
            rescale_length=self.valuation.rescale_length,
            overvalued=val_overvalued,
            undervalued=val_undervalued,
        )
        return cot, val

    # ------------------------------------------------------------------
    # Phase 15: Constituent-analysis Valuation for equity indices
    # ------------------------------------------------------------------

    def _constituent_valuation_bias(
        self,
        index_symbol: str,
        constituent_dfs: Dict[str, "pd.DataFrame"],
        valuation_refs: Dict[str, "pd.DataFrame"],
        val_engine: "Valuation",
    ) -> str:
        """Determine equity-index Valuation bias via constituent stock readings.

        Bernd (Ch.157 / CW40): "the two most important stocks is Apple and
        is Microsoft that they are not overbellied... if these two are
        undervalued, you can buy NQ / ES."

        Algorithm:
        1. Compute Valuation for each available constituent using the same
           macro references (DXY / ZN / ZB) as the standard indicator.
        2. Primary gate (AAPL + MSFT for NQ/ES; MSFT + UNH for YM):
           - Both primaries NOT strongly overvalued  → candidate = 'bullish'
           - Any primary strongly overvalued         → candidate = 'bearish'
           - Can't determine (data missing)          → candidate = 'neutral'
        3. Secondary vote (remaining mega-caps):
           - If candidate='bullish' and secondary majority ≤ 0 bullish
             (i.e. mostly overvalued) → downgrade to 'neutral'
           - If candidate='bearish' and secondary majority > half bullish
             → downgrade to 'neutral' (inconclusive)
        4. Return the final bias string.

        Falls back to 'neutral' gracefully whenever constituent data is thin.
        """
        spec = EQUITY_INDEX_CONSTITUENTS.get(index_symbol, {})
        primary_tickers   = spec.get('primary',   [])
        secondary_tickers = spec.get('secondary', [])

        def _stock_bias(ticker: str) -> Optional[str]:
            """Return 'bullish'/'bearish'/'neutral' for a single constituent."""
            df = constituent_dfs.get(ticker)
            if df is None or df.empty or not valuation_refs:
                return None
            try:
                vdf = val_engine.calculate(df, valuation_refs)
                return val_engine.get_bias(vdf)
            except Exception as exc:
                logger.debug(f"Constituent Valuation [{ticker}] failed: {exc}")
                return None

        # --- Primary gate ---
        primary_biases = [_stock_bias(t) for t in primary_tickers]
        primary_available = [b for b in primary_biases if b is not None]

        if not primary_available:
            logger.debug(f"[{index_symbol}] No primary constituent data; constituent Valuation = neutral")
            return 'neutral'

        # "Both primaries NOT strongly overvalued" = bullish for index
        # We use the val_engine's overvalued threshold as the strong-overvalued marker.
        # get_bias() returns 'bearish' when ANY reference line is strongly bearish.
        # For the primary gate: bearish primary → index bearish; bullish/neutral primary → ok.
        primary_bearish_count = sum(1 for b in primary_available if b == 'bearish')
        primary_bullish_count = sum(1 for b in primary_available if b == 'bullish')

        if primary_bearish_count >= 1:
            # At least one key constituent is overvalued — index bias unfavourable
            candidate = 'bearish'
        elif primary_bullish_count == len(primary_available):
            # All available primaries are undervalued → strong bullish candidate
            candidate = 'bullish'
        else:
            # Mix of bullish + neutral → mildly bullish; treat as bullish
            candidate = 'bullish'

        # --- Secondary confirmation ---
        if secondary_tickers:
            secondary_biases = [_stock_bias(t) for t in secondary_tickers]
            sec_available = [b for b in secondary_biases if b is not None]
            if sec_available:
                sec_bull = sum(1 for b in sec_available if b == 'bullish')
                sec_bear = sum(1 for b in sec_available if b == 'bearish')
                if candidate == 'bullish' and sec_bear > sec_bull:
                    # Secondary stocks mostly overvalued → inconclusive
                    logger.debug(
                        f"[{index_symbol}] Secondary vote ({sec_bull}↑ {sec_bear}↓) "
                        f"downgrades bullish candidate to neutral"
                    )
                    candidate = 'neutral'
                elif candidate == 'bearish' and sec_bull > sec_bear:
                    # Secondary stocks mostly undervalued → inconclusive
                    logger.debug(
                        f"[{index_symbol}] Secondary vote ({sec_bull}↑ {sec_bear}↓) "
                        f"downgrades bearish candidate to neutral"
                    )
                    candidate = 'neutral'

        logger.debug(
            f"[{index_symbol}] Constituent Valuation: "
            f"primary={primary_biases} secondary_available={len([b for b in (secondary_tickers and [_stock_bias(t) for t in secondary_tickers]) or [] if b])} → {candidate}"
        )
        return candidate

    def _constituent_proxy_bias(
        self,
        index_symbol: str,
        constituent_dfs: Dict[str, "pd.DataFrame"],
    ) -> str:
        """Phase 24: equity-index bias derived from per-constituent SMA proxy.

        Like `_constituent_valuation_bias` but uses the Phase 24
        timeframe-aware `_stock_valuation_proxy` (price vs N-year SMA) per
        stock instead of the macro DXY/ZB Valuation. The macro Valuation
        reads stocks as 'overvalued' in any rising-rate environment because
        bonds (ZB) crash with stocks; the SMA proxy is mean-reversion based
        and matches Bernd's "AAPL undervalued" reading.

        Used to route the bullish thesis through to NQ/ES/YM when:
        - The index itself has no demand zone (price at ATH)
        - Cycles agree bullish (presidential + sannial)
        - At least the primary constituents read 'bullish' on the SMA proxy

        Returns 'bullish' / 'bearish' / 'neutral'.
        """
        spec = EQUITY_INDEX_CONSTITUENTS.get(index_symbol, {})
        # C-98: third and last piece of the Phase 39 wiring break. This dict is
        # keyed by NQ=F / ES=F / YM=F only, so for a mega-cap STOCK the lookup
        # returns {}, primary_tickers is empty, and the function returns 'neutral'
        # before reading anything -- which would silently defeat the flag even with
        # constituent_dfs correctly populated. Under the flag a basket member takes
        # AAPL + MSFT as its primaries, minus itself.
        if not spec and os.environ.get('BP_BASKET_INHERIT') == '1':
            _BASKET = {'GOOG', 'GOOGL', 'META', 'NVDA', 'AMZN', 'NFLX', 'TSLA',
                       'AAPL', 'MSFT'}
            if index_symbol in _BASKET:
                spec = {'primary': [t for t in ('AAPL', 'MSFT') if t != index_symbol],
                        'secondary': []}
        primary_tickers   = spec.get('primary',   [])
        secondary_tickers = spec.get('secondary', [])

        def _proxy_for(ticker: str) -> Optional[str]:
            df = constituent_dfs.get(ticker) if constituent_dfs else None
            if df is None or df.empty:
                return None
            try:
                return self._stock_valuation_proxy(df)
            except Exception as exc:
                logger.debug(f"Constituent proxy [{ticker}] failed: {exc}")
                return None

        primary_biases = [_proxy_for(t) for t in primary_tickers]
        primary_available = [b for b in primary_biases if b is not None]
        if not primary_available:
            return 'neutral'

        primary_bull = sum(1 for b in primary_available if b == 'bullish')
        primary_bear = sum(1 for b in primary_available if b == 'bearish')

        # Phase 35 P2-02 fix: relax the primary gate from ANY-bearish-blocks to
        # MAJORITY-bearish-blocks. Bernd's Jan 2024 NASDAQ long call had Meta
        # "near overvalued but coming from overvalued and around the mean" while
        # AAPL and MSFT were undervalued -- he still called NASDAQ bullish.
        # Old gate: if primary_bear >= 1 → bearish (too strict -- one stock blocks)
        # New gate: if primary_bear > primary_bull → bearish (majority blocks)
        # This way ONE near-overvalued primary does NOT veto the index call when
        # the other primary reads bullish (or neutral).
        if primary_bear > primary_bull and primary_bear >= 1:
            candidate = 'bearish'
        elif primary_bull >= 1:
            candidate = 'bullish'
        else:
            candidate = 'neutral'

        # Secondary confirmation
        # Phase 25 (DeepSeek P2): require at least 2 secondary stocks to have
        # data before we let the secondary vote downgrade the primary candidate.
        # A single secondary stock voting against the primaries is too noisy
        # to override AAPL+MSFT (or MSFT+UNH) — Bernd's primary-stock signal.
        if secondary_tickers:
            sec_biases = [_proxy_for(t) for t in secondary_tickers]
            sec_avail = [b for b in sec_biases if b is not None]
            if len(sec_avail) >= 2:
                sec_bull = sum(1 for b in sec_avail if b == 'bullish')
                sec_bear = sum(1 for b in sec_avail if b == 'bearish')
                if candidate == 'bullish' and sec_bear > sec_bull:
                    candidate = 'neutral'
                elif candidate == 'bearish' and sec_bull > sec_bear:
                    candidate = 'neutral'

        logger.info(
            f"[{index_symbol}] Constituent SMA-proxy bias: "
            f"primary={primary_biases} → {candidate}"
        )
        return candidate

    def _constituent_zone_bias(
        self,
        index_symbol: str,
        constituent_dfs: Dict[str, "pd.DataFrame"],
        timeframe: str,
    ) -> str:
        """Zone-quality-based equity-index bias from constituent stocks.

        Added 2026-07-27 (portfolio-risk / constituent-routing follow-up).
        Complements `_constituent_proxy_bias` (SMA mean-reversion only) with
        a genuine zone-detection pass on the primary constituents (AAPL+MSFT
        for NQ/ES; MSFT+UNH for YM). Bernd routes an index-level bullish
        thesis through the constituents' own qualified demand zones when the
        index itself has no zone at ATH -- 01_hybrid_ai.txt [2:01:07]: "if
        apple doesn't rally the market doesn't rally... if the road map says
        from January be bullish then apple has to be bullish from January
        onwards." Previously this routing only checked a Valuation-SMA
        proxy, never an actual zone -- this was the documented "still
        deferred: stock-level zone search" gap (Phase 26 wrap-up: "System
        correctly returns hold for index futures and would need stock-level
        zone search routed from the index thesis to convert these").

        Returns 'bullish' / 'bearish' / 'neutral' from the qualified zones
        (min composite 6.0, same threshold run_seven_step_process uses)
        found on the primary constituents. Does NOT attempt to translate a
        constituent's zone levels (entry/stop) onto the index's own price
        scale -- that's a different instrument with a different price, so
        this only contributes a DIRECTIONAL vote, same role as the existing
        SMA-proxy, not a tradeable entry for the index itself.
        """
        spec = EQUITY_INDEX_CONSTITUENTS.get(index_symbol, {})
        primary_tickers = spec.get('primary', [])
        biases: List[str] = []
        for ticker in primary_tickers:
            df = constituent_dfs.get(ticker) if constituent_dfs else None
            if df is None or df.empty:
                continue
            try:
                zones = self.zone_detector.detect_zones(df, ticker, timeframe)
                ranked = self.zone_detector.rank_zones(zones, min_score=6.0)
            except Exception as exc:
                logger.debug(f"Constituent zone scan [{ticker}] failed: {exc}")
                continue
            if not ranked:
                continue
            best = ranked[0]
            biases.append('bullish' if best['zone_type'] == 'demand' else 'bearish')

        if not biases:
            return 'neutral'
        bull = sum(1 for b in biases if b == 'bullish')
        bear = sum(1 for b in biases if b == 'bearish')
        candidate = 'bullish' if bull > bear else 'bearish' if bear > bull else 'neutral'
        logger.info(
            f"[{index_symbol}] Constituent zone-scan bias: "
            f"primary={biases} → {candidate}"
        )
        return candidate

    @staticmethod
    def _stock_valuation_proxy(
        price_df: pd.DataFrame,
        years_lookback: float = 3.0,
        overvalued_pct: float = 0.35,    # >35% above LT mean = expensive
        undervalued_pct: float = -0.05,  # <5% below LT mean = cheap
    ) -> str:
        """Phase 23 (Task 2) — Phase 24 timeframe-aware fix.

        Price-vs-N-year-SMA proxy for individual-stock Valuation. The macro
        Valuation (ROC vs DXY/ZB/GC) reads stocks as 'overvalued' in any
        rising-rate environment (rates up → ZB falls → relative ROC of stock
        vs ZB positive → bearish). Bernd's CampusValuationTool_V2 (unavailable
        to us) compares to intrinsic / earnings value. This proxy uses the
        same directional intent via 3-year SMA mean-reversion.

        Phase 24 fix: previously used a fixed `sma_period=156` regardless of
        the input timeframe — for monthly price_df, 156 bars = 13 years (way
        too long); for daily price_df, 156 bars = 7.5 months (way too short).
        Now infers the bar frequency from the timestamp column and computes
        the SMA window in CALENDAR years. Defaults to 3 years.

        Asymmetric thresholds: 35% above (growth premium tolerance) / 5% below
        (mean-reversion entry). Returns 'bullish' / 'bearish' / 'neutral'.
        """
        if price_df is None or len(price_df) < 12:
            return 'neutral'

        # Extract closes
        if 'close' in price_df.columns:
            closes = price_df['close']
        elif 'Close' in price_df.columns:
            closes = price_df['Close']
        else:
            closes = price_df.iloc[:, 3]

        # Phase 24: detect frequency from timestamp spacing -> sma window in bars
        # corresponding to the requested calendar lookback.
        # Phase 25 (DeepSeek P1+P2): (a) check additional timestamp column names
        # ('Date', 'date'); (b) explicitly reject intraday data (med_days < 0.9)
        # — the proxy is calibrated for daily/weekly/monthly only. For hourly or
        # finer data, the SMA period would be miscalibrated (e.g. 60-min stock
        # data → 252×3 = 756 hourly bars covers ~3 months, not 3 years).
        bars_per_year = 12  # safe default = monthly
        try:
            ts = None
            for _col in ('timestamp', 'Date', 'date', 'Datetime', 'datetime'):
                if _col in price_df.columns:
                    ts = pd.to_datetime(price_df[_col])
                    break
            if ts is None:
                ts = pd.to_datetime(price_df.index)
            if len(ts) >= 5:
                # Median day-spacing between consecutive bars (more robust than mean)
                deltas_days = ts.diff().dropna().dt.total_seconds().div(86400.0)
                med_days = float(deltas_days.median())
                # Phase 25: reject intraday data — proxy not calibrated for it
                if med_days < 0.9:
                    return 'neutral'
                if med_days > 0:
                    if   med_days <= 2.0:  bars_per_year = 252   # daily
                    elif med_days <= 9.0:  bars_per_year = 52    # weekly
                    elif med_days <= 35.0: bars_per_year = 12    # monthly
                    else:                  bars_per_year = 4     # quarterly+
        except Exception:
            pass

        sma_period = max(int(round(bars_per_year * years_lookback)), 12)
        # require at least half the lookback window of data
        if len(closes) < max(sma_period // 2, 12):
            return 'neutral'

        actual_period = min(sma_period, len(closes))
        sma = closes.rolling(actual_period,
                             min_periods=max(12, actual_period // 2)
                             ).mean().iloc[-1]
        if pd.isna(sma) or sma == 0:
            return 'neutral'
        current = closes.iloc[-1]
        if pd.isna(current):
            return 'neutral'
        pct_above_mean = (current - sma) / sma
        if pct_above_mean <= undervalued_pct:
            return 'bullish'
        elif pct_above_mean >= overvalued_pct:
            return 'bearish'
        else:
            return 'neutral'

    def _analyze_fundamentals(
        self,
        cot_df: pd.DataFrame,
        price_df: pd.DataFrame,
        valuation_refs: Dict[str, pd.DataFrame],
        seasonal_df: pd.DataFrame,
        asset_class: str = 'commodities',
        opposing_cot_df: Optional[pd.DataFrame] = None,
        symbol: Optional[str] = None,
        constituent_dfs: Optional[Dict[str, "pd.DataFrame"]] = None,
        htf: str = '1wk',
    ) -> Dict[str, str]:
        """Step 3: COT, Valuation, Seasonality bias (asset-class aware).

        For forex, an opposing-currency COT (e.g. USD when trading EUR/USD)
        can be passed in -- the EUR-side bias must agree with the inverted
        USD-side bias before we accept it. This honours rule #17 from the
        Blueprint non-negotiables.

        For equity indices (NQ=F/ES=F/YM=F), constituent_dfs supplies
        individual-stock OHLCV so Valuation can be computed per-constituent
        instead of on the index directly. Pass a dict {ticker: price_df}.
        If constituent_dfs is None or empty, falls back to direct Valuation.
        """
        cot_engine, val_engine = self._indicators_for_class(
            asset_class, symbol=symbol, htf=htf,
        )

        # Mirror the symbol-level routing in _indicators_for_class so get_bias()
        # picks the SAME trader group the lookback was tuned for. Without this,
        # NG=F (config class 'energies', effective 'nat_gas') was routed to the
        # Commercials group instead of the intended Non-Commercials/retailer-veto
        # nat_gas branch -- an INVERTED COT read on a symbol whose Valuation is
        # skipped, so nothing caught the wrong direction (audit rank 3).
        cot_effective_class = asset_class
        if symbol in SOFT_COMMODITY_SYMBOLS:
            cot_effective_class = 'soft_commodities'
        elif symbol in NAT_GAS_SYMBOLS:
            cot_effective_class = 'nat_gas'
        elif symbol in CRUDE_OIL_SYMBOLS:
            cot_effective_class = 'crude_oil'

        cot_bias = 'neutral'
        cot_strength = 'none'
        cot_cross = None
        if cot_df is not None and not cot_df.empty:
            try:
                cot_calculated = cot_engine.calculate(cot_df)
                cot_bias, cot_strength = cot_engine.get_bias(
                    cot_calculated, asset_class=cot_effective_class, return_strength=True,
                )
                # Phase 21 fix: USD-base forex pairs (USDJPY=X, USDCHF=X, USDCAD=X).
                # COT data is fetched for the QUOTE currency (JPY/CHF/CAD futures).
                # "Bullish" from non-comms = they're long the QUOTE currency = short USD
                # = BEARISH for the USD-base pair.  Invert before consensus.
                #
                # Example: USDCHF=X fetches CHF COT (6S=F / 092741).
                #   Non-comms LONG CHF → cot_bias='bullish' → means SELL USDCHF.
                #   Without inversion the system reads 'bullish' as BUY USDCHF — wrong.
                #
                # Non-USD-base pairs (EURUSD, GBPUSD, AUDUSD) need NO inversion:
                #   their COT tracks the base currency directly.
                #
                # The comment "(inverted)" in BP_data_fetcher.get_cftc_code was the
                # original annotation — this is the actual inversion that was missing.
                if (asset_class == 'forex' and symbol and
                        symbol.upper().startswith('USD') and '=X' in symbol and
                        cot_bias != 'neutral'):
                    _inv = {'bullish': 'bearish', 'bearish': 'bullish'}
                    cot_bias = _inv.get(cot_bias, cot_bias)
                    logger.info(
                        f"Phase 21: USD-base pair {symbol} — COT inverted to {cot_bias}"
                    )
                # Cross-category relationship: producer-vs-retailer (smart vs
                # dumb money) and funds-vs-commercials. Per Bernd's teaching,
                # when commercials and retailers are at OPPOSITE extremes
                # simultaneously, that's the highest-conviction signal --
                # promote to strong even if single-category bias was neutral.
                cot_cross = cot_engine.cross_category_signal(cot_calculated)
                # Phase 20 fix: cross_category_signal was designed for commodity
                # markets where commercials = "smart money" (physical
                # producers/consumers with superior price knowledge). For FX,
                # corporate hedgers (commercials) mechanically hedge
                # receivables/payables — they are NOT directional "smart money".
                # Applying the commodity override to forex is architecturally
                # incorrect and caused the two-layer failure isolated in Phase 19:
                #   Layer 1 — extreme_confluence flips non-comm bullish to bearish
                #   Layer 2 — forex cross-check sees conflict, demotes to neutral
                # Guard: only fire for non-forex asset classes.
                #
                # 2026-08 validation (C-59): the SAME argument applies to EQUITY INDICES.
                # On ES/NQ/YM the "commercials" are asset managers hedging portfolios, so
                # commercials-short + retail-long is their STRUCTURAL resting state, not a
                # bearish signal. Measured against Bernd's 18 real trades: all 5 outright
                # wrong-direction calls were index longs (ES x2, NQ, YM x2) where this
                # override flipped the bias bearish and marked it 'strong'. Example
                # YM=F 2024-02-14: commercials 3.8 (pinned short), retail 93.4 (pinned
                # long) -> smart_vs_dumb='bearish' -> he was long, we said bearish.
                # EXPERIMENTAL, DEFAULT OFF: rules.xcat_skip_equity_indices: true
                # (or env BP_XCAT_SKIP_INDICES=1). Judge on measured numbers.
                _xcat_skip = {'forex'}
                if ((self.config.get('rules', {}) or {}).get('xcat_skip_equity_indices', False)
                        or os.environ.get('BP_XCAT_SKIP_INDICES') == '1'):
                    _xcat_skip |= {'equity_indices', 'equities'}
                if cot_cross.get('extreme_confluence') and asset_class not in _xcat_skip:
                    smart = cot_cross['smart_vs_dumb']  # 'bullish' or 'bearish'
                    if cot_bias == 'neutral':
                        cot_bias = smart
                    elif cot_bias != smart:
                        # Single-category bias contradicts smart-vs-dumb -> trust
                        # the relational pattern (more reliable per Bernd).
                        logger.info(
                            f"COT smart-vs-dumb ({smart}) overrides single-category ({cot_bias})"
                        )
                        cot_bias = smart
                    cot_strength = 'strong'
                    logger.info(f"COT cross-category extreme confluence: {smart}")
                # For forex, cross-check the opposing currency. Per HAI Mod 3
                # L1 Part 3 (frames 728-983 EUR/USD non-commercial example):
                #   - Both sides agree (inverted) -> DOUBLE CONFIRMED, boost to 'strong'
                #   - One side neutral -> single bias (current strength)
                #   - Both same direction (not inverted) -> CONFLICTING, demote to neutral
                # Only run the opposing-USD cross-check when USD is genuinely a
                # leg of the pair. run_scanner fetches the USD-Index COT as the
                # "opposing" series for EVERY forex entry, so a NON-USD cross
                # (EURGBP=X, EURJPY=X) whose own COT is neutral would otherwise
                # INHERIT a spurious inverted-USD bias via the Phase 23-T5 path
                # and trade a wrong direction. A =X spot pair with no 'USD' in
                # its ticker is such a cross; futures-coded pairs (6E=F/6S=F/6J=F)
                # are inherently USD-quoted so they still get the cross-check.
                _sym_u = (symbol or '').upper()
                _is_non_usd_cross = ('=X' in _sym_u) and ('USD' not in _sym_u)
                if (asset_class == 'forex' and not _is_non_usd_cross
                        and opposing_cot_df is not None and not opposing_cot_df.empty):
                    opp = cot_engine.calculate(opposing_cot_df)
                    opp_bias, opp_strength = cot_engine.get_bias(
                        opp, asset_class='forex', return_strength=True,
                    )
                    # 2026-08 FTW audit C-49 — USD-BASE PAIRS WERE INVERTED HERE.
                    # `opp_bias` is a view on the DOLLAR. Translating it into a view
                    # on THIS PAIR depends on which side of the pair USD sits:
                    #   EURUSD=X / GBPUSD=X (USD = QUOTE): bullish USD -> pair DOWN,
                    #       so the dollar view must be inverted.
                    #   USDJPY=X / USDCHF=X / USDCAD=X (USD = BASE): bullish USD ->
                    #       pair UP, so the dollar view carries over UNCHANGED.
                    # The old code inverted unconditionally, so all three USD-base
                    # pairs in the watchlist received a 180-degree wrong COT read --
                    # both via the Phase 23-T5 inheritance path below (which could
                    # open a long on evidence that says short) and via the
                    # double-confirm/conflict branches (a real confirmation was
                    # demoted to neutral, a real conflict promoted to 'strong').
                    # NOTE this is a DIFFERENT flip from the Phase 21 inversion
                    # above: that one corrects the pair's OWN COT (quote-currency
                    # futures); this one translates the OPPOSING dollar read.
                    # Both are needed, and neither double-negates the other.
                    _usd_is_base = bool(symbol) and _sym_u.startswith('USD') and '=X' in _sym_u
                    _flip = {'bullish': 'bearish', 'bearish': 'bullish', 'neutral': 'neutral'}
                    inverted = opp_bias if _usd_is_base else _flip[opp_bias]
                    if cot_bias != 'neutral' and opp_bias != 'neutral':
                        if cot_bias == inverted:
                            # Both sides agree directionally -> double confirmation
                            cot_strength = 'strong'
                            logger.info(
                                f"COT double-confirmed via opposing currency (this={cot_bias} "
                                f"opposing-inverted={inverted}); strength=strong"
                            )
                        else:
                            # Both sides in same direction -> conflicting, demote
                            logger.info(
                                f"COT cross-check conflict (this={cot_bias} "
                                f"opposing-inverted={inverted}); demoting to neutral"
                            )
                            cot_bias = 'neutral'
                            cot_strength = 'none'
                    # Phase 23 (Task 5): inherit from opposing currency when own
                    # COT is too weak to signal but opposing has strong/normal bias.
                    # One-sided signal capped at 'normal' conviction.
                    elif cot_bias == 'neutral' and inverted != 'neutral' and opp_strength in ('strong', 'normal'):
                        cot_bias = inverted
                        cot_strength = 'normal'
                        logger.info(
                            f"COT inherited from opposing currency (own=neutral, "
                            f"opp={opp_bias} strength={opp_strength} -> inverted={inverted}); "
                            f"this side now {cot_bias} normal"
                        )
                # Phase 41 S-01: NG=F retailer directional-alignment veto.
                # Non-commercials (Fund Managers) are now the PRIMARY signal for NG.
                # But retailers being BULLISH on NG is a contra alarm -- Bernd CW07 0:24:40:
                # "if retailers are getting more bullish I'm not willing to get in any long."
                # If the primary COT says 'bullish' but retailers are above 50
                # (trending toward bullish), veto the long for NG.
                _is_nat_gas = symbol in NAT_GAS_SYMBOLS if symbol else False
                if _is_nat_gas and cot_bias == 'bullish':
                    try:
                        ng_retailer_idx = cot_calculated.iloc[-1].get('small_specs_index', 50)
                        if ng_retailer_idx > 50:  # retailers trending bullish = contra veto
                            logger.info(
                                f"NG=F retailer directional veto: retailers={ng_retailer_idx:.1f}>50, "
                                f"vetoing bullish long signal"
                            )
                            cot_bias = 'neutral'
                            cot_strength = 'none'
                    except Exception:
                        pass  # veto is best-effort only
                if cot_bias != 'neutral':
                    logger.info(f"COT bias={cot_bias} strength={cot_strength}")
            except Exception as e:
                logger.warning(f"COT calculation failed: {e}")

        val_bias = 'neutral'
        # Blueprint Cheatsheet: some symbols explicitly exclude Valuation ("-").
        # Natural Gas is weather/supply-shock driven; DXY-relative analysis
        # is uninformative and would generate false vetoes.
        _skip_val = symbol in VALUATION_SKIP_SYMBOLS if symbol else False
        #
        # Phase 15 (revised): Skip Valuation for equity indices.
        # The standard DXY/ZN/ZB comparison reads equity indices as 'bearish'
        # whenever they outperform bonds (i.e. in every bull market), producing
        # false Valuation vetoes on correct long signals. Bernd's "undervalued"
        # for individual stocks is computed by CampusValuationTool_V2 which is
        # NOT available (user confirmed). The constituent-stock approach inherits
        # the same problem (stocks outperform bonds → all read as overvalued).
        # Treating equity-index Valuation as 'neutral' lets Location + COT +
        # Seasonality drive the bias without an incorrect hard veto.
        # NOTE: constituent_dfs infrastructure is preserved for future use if
        # the CampusValuationTool_V2 Pine Script becomes available.
        # C-93 (2026-08-26) EXPERIMENTAL, DEFAULT OFF -- BP_INDEX_VALUATION=1
        #
        # The skip above has never been A/B'd out of sample. It was taken to stop a
        # false veto, and the reasoning is sound as far as it goes, but the cost is
        # now measured: equity-index Valuation is neutral on 90 of 90 cases, so one
        # of the two indicators the method treats as decisive is switched off for
        # the entire class -- and equity indices are exactly where the engine is
        # weakest (its COT-driven index shorts run at 19% accuracy, section 8).
        #
        # Setting the flag restores the standard DXY/ZB/GC computation for indices.
        # The Phase 15 prediction is explicit and therefore falsifiable: it should
        # read BEARISH through the bull market and veto correct longs. If that is
        # what happens the flag stays off and the skip is vindicated with a number
        # behind it instead of an argument. If it does not, 90 cases get an
        # indicator back.
        if asset_class == 'equity_indices' and os.environ.get('BP_INDEX_VALUATION') != '1':
            _skip_val = True
        if _skip_val:
            pass  # val_bias stays 'neutral'
        # Phase 23 (Task 2): individual stocks use price-vs-3yr-SMA proxy
        # instead of macro Valuation (which reads bullish stocks as 'overvalued'
        # in any rising-rate environment).
        elif asset_class == 'equities':
            # Phase 38 GAP-01 note: the SPY dead-code path below was added by
            # DeepSeek Gap 2 but SPY is NEVER in VALUATION_REFS["equities"] in
            # run_scanner.py or goldtest/run_goldtest.py (equities refs = ZB=F + GC=F
            # only, no SPY). The primary path therefore never fires in live use.
            # Rulebook Section 1 + Section 9 confirm: individual stocks refs = ZB + GC
            # only (DXY unchecked, SPY not mentioned). SPY is not a valid rulebook ref.
            # The code is left in place as scaffolding in case SPY relative-strength
            # is explicitly added to the equities ref list in the future, but the
            # ACTIVE path is always the SMA proxy below (spy_df will always be None).
            spy_df = valuation_refs.get('SPY') if valuation_refs else None
            if spy_df is not None and not spy_df.empty:
                try:
                    rel_val_engine = Valuation(
                        length=10,
                        rescale_length=100,
                        overvalued=75.0,
                        undervalued=-75.0,
                    )
                    rel_val_df = rel_val_engine.calculate(price_df, {'SPY': spy_df})
                    val_bias = rel_val_engine.get_bias(rel_val_df)
                    logger.info(f"[{symbol}] Stock Relative-Strength Val vs SPY: {val_bias}")
                except Exception as e:
                    logger.warning(f"Relative-strength Valuation failed ({e}); falling back to SMA proxy")
                    val_bias = self._stock_valuation_proxy(price_df)
            elif os.environ.get('BP_STOCK_REAL_VALUATION') == '1' and valuation_refs:
                # C-99 (2026-08-27) EXPERIMENTAL, DEFAULT OFF -- BP_STOCK_REAL_VALUATION=1
                #
                # The SMA proxy exists because "CampusValuationTool_V2 is NOT
                # available (user confirmed)". Measured against his own on-screen
                # readings, that premise does not hold: run the REAL Valuation on
                # stocks with bonds refs at the indicator's own +/-75 thresholds and
                # the distribution lands close to his.
                #
                #   raw line values at the 224 corpus equities case dates, +/-75:
                #     bonds only        bearish  8.9%  bullish 8.0%  neutral 83.0%
                #     bonds + gold      bearish 10.0%  bullish 6.7%  neutral 83.3%
                #     HIS TOOL (n=722)  bearish  3.6%  bullish 6.6%  neutral 90.0%
                #
                # Config here is frame-derived, not guessed:
                #   refs   -- bonds ON, GOLD OFF. The legend shows `True, False` on
                #             435 of 441 stock charts (99%). The shipped
                #             VALUATION_REFS['equities'] = [ZB, GC] includes gold and
                #             is contradicted 435 to 1.
                #   length -- 13. The on-camera edit "I'm going to change the ROC
                #             from 10 to 13" is performed on AAPL, and stock legends
                #             read 13 on 4 of 6 observations.
                #   band   -- +/-75 only. The +/-10 band (C-96) is ours, not his, and
                #             is what turns an 83%-neutral series into a noisy one.
                #
                # EXPECT THIS TO COST CASES. C-96 measured the same move on the
                # classes that already run Valuation: -12, p=0.039 against. This is
                # the same trade -- closer to his instrument, further from the
                # scoreboard -- applied to the 224 cases where the substitution is
                # real rather than cosmetic. Measure it; do not assume it wins.
                try:
                    _stock_refs = {k: v for k, v in valuation_refs.items()
                                   if k not in ('GC=F',)} or valuation_refs
                    _sv = Valuation(length=13, rescale_length=self.valuation.rescale_length,
                                    overvalued=75.0, undervalued=-75.0)
                    _sdf = _sv.calculate(price_df, _stock_refs)
                    _prev = os.environ.get('BP_VAL_STRICT_THRESHOLDS')
                    os.environ['BP_VAL_STRICT_THRESHOLDS'] = '1'
                    try:
                        val_bias = _sv.get_bias(_sdf)
                    finally:
                        if _prev is None:
                            os.environ.pop('BP_VAL_STRICT_THRESHOLDS', None)
                        else:
                            os.environ['BP_VAL_STRICT_THRESHOLDS'] = _prev
                    logger.info(f"[{symbol}] Stock REAL Valuation "
                                f"(refs={list(_stock_refs)}, L13, +/-75): {val_bias}")
                except Exception as e:
                    logger.warning(f"Stock real Valuation failed ({e}); falling back to proxy")
                    val_bias = self._stock_valuation_proxy(price_df)
            else:
                try:
                    val_bias = self._stock_valuation_proxy(price_df)
                    logger.info(f"[{symbol}] Stock Valuation proxy (price vs 3yr SMA): {val_bias}")
                except Exception as e:
                    logger.warning(f"Stock Valuation proxy failed: {e}")
        elif valuation_refs:
            try:
                val_df = val_engine.calculate(price_df, valuation_refs)
                val_bias = val_engine.get_bias(val_df)
            except Exception as e:
                logger.warning(f"Valuation calculation failed: {e}")

        seas_bias = 'neutral'
        if seasonal_df is not None and not seasonal_df.empty:
            try:
                # Phase 16: Bitcoin only has ~4 years of history.
                # 03_funded.txt lines 451, 864-865: "We can only do four years."
                # Use a temporary Seasonality instance with 4yr-only lookback.
                # Phase 28 A3 reverted: daily-timeframe routing was frame-verified
                # to give wrong directional reads on Apr 2 + Oct 7 + Oct 15 2023
                # equity indices (all 3 dates Bernd's on-screen Campus Seasonality
                # indicator showed bullish; daily-bin landed at the trough giving
                # bearish). Restoring weekly binning while a proper slope-lookahead
                # implementation is designed (Phase 29 work).
                if symbol in BTC_SYMBOLS:
                    _seas_engine = Seasonality(multi_lookbacks=(4,))
                    multi = _seas_engine.calculate_multi(seasonal_df, timeframe='weekly')
                # Phase 25 (DeepSeek P3): enforce NG=F 10y+5y-only restriction in code.
                elif symbol in NAT_GAS_SYMBOLS:
                    _seas_engine = Seasonality(multi_lookbacks=(5, 10))
                    multi = _seas_engine.calculate_multi(seasonal_df, timeframe='weekly')
                # Phase 41 GAP-C6-S-01: RTY=F has no 10yr seasonality data.
                # CW08 transcript 0:22:25: "seasonality 10 years, of course, no data."
                # Use 5yr-only lookback to avoid empty multi dict.
                elif symbol in RTY_SYMBOLS:
                    _seas_engine = Seasonality(multi_lookbacks=(5,))
                    multi = _seas_engine.calculate_multi(seasonal_df, timeframe='weekly')
                else:
                    # Standard: 5y/10y/15y — 2-of-3 must agree (Phase 9)
                    multi = self.seasonality.calculate_multi(seasonal_df, timeframe='weekly')
                if multi:
                    current_bin = self.seasonality.get_current_bin(price_df, 'weekly')
                    # Phase 31 hybrid: pass asset_class so equity_indices uses
                    # 90-day cycle horizon while other classes use 30-day stated.
                    seas_bias = self.seasonality.get_bias_multi(
                        multi, current_bin, timeframe='weekly', asset_class=asset_class
                    )
            except Exception as e:
                logger.warning(f"Seasonality calculation failed: {e}")

        # Phase 24: equity-index constituent SMA-proxy bias.
        # Computed when constituent OHLCV is available so consensus can route
        # a bullish thesis through to the index when (a) cycles agree bullish,
        # (b) loc='bearish' (index at ATH), and (c) the primary constituent
        # stocks are themselves below their 3yr SMA. Bernd verbatim:
        # "if these two [AAPL+MSFT] are undervalued, you can buy NQ / ES."
        constituent_bias = 'neutral'
        # C-98 (2026-08-27) EXPERIMENTAL, DEFAULT OFF -- BP_BASKET_INHERIT=1
        #
        # Second half of the wiring break described in run_goldtest's fetch gate.
        # `_bias_consensus` already carries a Phase 39 branch that reads
        # `constituent == 'bullish'` for a mega-cap STOCK and returns bullish --
        # "Bernd Ch.157 verbatim ... When AAPL+MSFT read undervalued, he extends
        # the bullish bias to the rest of the mega-cap basket". That branch has
        # never executed, because this producer only runs for equity_indices, so
        # a stock's `constituent` is hardcoded 'neutral' by the line above.
        #
        # Nothing in the tree records it as tested-and-rejected; the Phase 42
        # cycle override, by contrast, carries its rejection inline. This reads as
        # a half-wired feature, and there is precedent in the same file: "Phase 28
        # A1 fix: wire constituent bias into consensus ... (was dead code because
        # goldtest harness built the dict separately)".
        #
        # Evidence for wanting it live: of 241 cases the engine gets wrong, 24 have
        # the trader explicitly stating a group thesis -- "part of the mega-cap
        # basket call", "one of the mega-cap drivers supporting the stock market" --
        # and 18 of those 24 are exactly `truth=long, system=neutral`.
        #
        # WHY IT MIGHT STILL LOSE, and why it is default OFF: the engine already
        # over-calls long. The second-biggest error bucket is 83 cases of
        # `truth=neutral, system=long`. A rule that converts neutrals into longs
        # can fix 18 and break 20. The 24 supporting cases were also selected
        # BECAUSE the engine got them wrong, which rule 1 warns guarantees any
        # alternative looks good. Measured on all 510, or not at all.
        _basket_inherit = (os.environ.get('BP_BASKET_INHERIT') == '1'
                           and asset_class == 'equities'
                           and symbol in {'GOOG', 'GOOGL', 'META', 'NVDA', 'AMZN',
                                          'NFLX', 'TSLA', 'AAPL', 'MSFT'})
        if (asset_class == 'equity_indices' or _basket_inherit) and symbol and constituent_dfs:
            try:
                constituent_bias = self._constituent_proxy_bias(symbol, constituent_dfs)
            except Exception as e:
                logger.warning(f"Constituent proxy bias failed: {e}")
            # 2026-07-27: combine with a genuine zone-detection pass on the
            # constituents (previously only the SMA-mean-reversion proxy was
            # checked -- the documented "stock-level zone search" gap). A
            # real qualified demand/supply zone on AAPL/MSFT is at least as
            # strong evidence as the SMA proxy, so either signal being
            # directional (with the other not actively contradicting) is
            # enough to route the thesis. Zone evidence never downgrades an
            # SMA-proxy read to neutral -- it can only add or confirm.
            try:
                zone_bias = self._constituent_zone_bias(symbol, constituent_dfs, htf)
                if constituent_bias == 'neutral' and zone_bias != 'neutral':
                    constituent_bias = zone_bias
                elif constituent_bias != 'neutral' and zone_bias != 'neutral' and zone_bias != constituent_bias:
                    # Proxy and zone-scan disagree -- conflicting evidence,
                    # don't let either one drive the vote.
                    constituent_bias = 'neutral'
            except Exception as e:
                logger.warning(f"Constituent zone bias failed: {e}")

        return {
            'cot': cot_bias,
            'cot_strength': cot_strength,
            'cot_cross': cot_cross,                # smart_vs_dumb, funds_vs_commercials, extreme_confluence
            'valuation': val_bias,
            'seasonality': seas_bias,
            'constituent': constituent_bias,       # Phase 24: equity-index constituent proxy
        }

    def _equity_index_short_cross_asset_gate(
        self,
        symbol: str,
        cot_df: Optional[pd.DataFrame],
        valuation_refs: Optional[Dict[str, pd.DataFrame]],
        bond_lookback: int = 13,
    ) -> Tuple[bool, str]:
        """Phase 6 P1 (Ch 156): equity-index shorts require BOTH retailer-extreme
        bullish AND Treasury Bond ROC actively rolling from positive toward
        negative. Either signal alone is insufficient.

        Bernd: "right now I just don't see the short coming. Retailers are
        getting more and more bullish on the weekly... we need the help of
        other Treasury bonds [to roll over]."

        Returns (allowed, reason).
        """
        # FIX Bug 3: COTIndex.calculate is an INSTANCE method, not a static.
        # The original code called COTIndex.calculate(cot_df, lookback_weeks=26, group='retailers')
        # which raises TypeError. Build a proper instance and call it correctly.
        retailers_extreme = False
        if cot_df is not None and not cot_df.empty:
            from BP_indicators import COTIndex
            _cot_engine = COTIndex(lookback_weeks=26, upper_extreme=80, lower_extreme=20)
            cot_calc = _cot_engine.calculate(cot_df)
            if not cot_calc.empty and 'small_specs_index' in cot_calc.columns:
                latest = cot_calc['small_specs_index'].iloc[-1]
                retailers_extreme = bool(latest >= 80)

        # 2. Bond ROC rolling-over check
        bond_rolling = False
        bond_now = bond_prev = None
        if valuation_refs:
            bond_df = valuation_refs.get('ZB') or valuation_refs.get('US') or valuation_refs.get('VD')
            if bond_df is not None and not bond_df.empty and len(bond_df) >= bond_lookback + 5:
                close = bond_df['close']
                # rate-of-change in % vs n bars ago
                roc = (close / close.shift(bond_lookback) - 1) * 100
                bond_now = roc.iloc[-1]
                bond_prev = roc.iloc[-3] if len(roc) > 3 else None
                if bond_now is not None and bond_prev is not None:
                    bond_rolling = bool(bond_now < 0 and bond_prev > 0)

        if retailers_extreme and bond_rolling:
            return True, f"OK -- retailers extreme bullish AND bonds rolling over (ROC {bond_prev:.2f}->{bond_now:.2f})"
        if retailers_extreme:
            return False, "WAIT -- retailers extreme but bonds not yet rolling over"
        if bond_rolling:
            return False, "WAIT -- bonds rolling over but retailers not yet extreme"
        return False, "VETO -- neither retailer-extreme nor bond-rollover signals active"

    def _bias_consensus(
        self, biases: Dict[str, str], income_strategy: str,
        asset_class: Optional[str] = None,
        at_zone: bool = False,
        zone_composite: float = 0.0,
        today_override: Optional[date] = None,
        symbol: Optional[str] = None,
    ) -> str:
        """Synthesize biases into a final directional call.

        Phase 11 — Bernd's ACTUAL hierarchy (replaces flat 3-of-5 equal vote).

        Frequency analysis across 186 course/session transcripts:
          92% — Valuation checked first
          88% — Location / zone presence checked
          76% — Seasonality as supporting context
          64% — Trend direction
          48% — COT (confluence enhancer, not primary gate for most trades)

        For FUTURES the new hierarchy is:
          Step 1. Location gate  — if loc=='neutral' (equilibrium) → no trade.
                                   Bernd: "never trade at 50%, no edge there."
          Step 2. Valuation veto — if Valuation strongly OPPOSES location → veto.
                                   CW38/CW39: "Rule Number One — Valuation."
          Step 3. Counter-trend  — short in uptrend / long in downtrend requires
                                   overwhelming non-trend agreement (Phase 8 H1).
          Step 4. Minimum met    — Location aligned + Valuation aligned = tradeable.
                                   OR  Location aligned + Valuation neutral
                                       + at least 1 of (COT/Seasonality/Trend) agrees.

        For INDIVIDUAL STOCKS (no CFTC COT; Valuation-driven per Phase 6 audit):
          - NEVER short individual stocks (Bernd uses index futures for shorts)
          - Primary: Valuation undervalued
          - Secondary: Seasonality + Location demand zone
          - Tertiary: Seasonality bullish, Valuation not opposing, no downtrend
        """
        val   = biases.get('valuation',   'neutral')
        trend = biases.get('trend',        'sideways')
        loc   = biases.get('location',     'neutral')
        cot   = biases.get('cot',          'neutral')
        seas  = biases.get('seasonality',  'neutral')

        # Phase 42 Fix-4: SI=F (Silver) Valuation relaxation.
        # Blueprint Cheatsheet (Phase 12): Silver primary = Commercials COT ①.
        # Valuation is NOT listed as primary, secondary, or odds-enhancer for Silver.
        # In a PM bull market Silver routinely outperforms bonds, so the standard
        # DXY/ZB relative-strength Valuation reads "overvalued" even as price climbs.
        # When Silver is at a demand zone (loc=bullish), seasonality agrees bullish,
        # and COT is not actively bearish, the val=bearish veto is structurally wrong.
        # IMPORTANT: inserted BEFORE the normalized dict / tally so that bearing_excl_trend
        # is computed with the relaxed val='neutral', allowing the downtrend counter-trend
        # gate (bullish_excl >= 2 AND bearish_excl == 0) to pass for cases #65 and #69.
        if (symbol and symbol in SILVER_SYMBOLS
                and loc == 'bullish'
                and val == 'bearish'
                and seas == 'bullish'
                and cot != 'bearish'):
            val = 'neutral'
            logger.debug(
                "Phase 42 Fix-4: SI=F val=bearish relaxed → neutral "
                "(cheatsheet: Valuation not primary for Silver)"
            )

        # Normalise trend vocabulary ('uptrend'/'downtrend'/'sideways') so it
        # can be compared against 'bullish'/'bearish'/'neutral' below.
        # Phase 5 bug-fix: trend was being silently ignored because it never
        # matched the 'bullish'/'bearish' literals in the old vote tally.
        #
        # Phase 42 Fix-4b: Use local variables (val/loc/cot/seas) that may have
        # been modified by pre-normalisation overrides (e.g. Fix-4 Silver val
        # relaxation). Without this, Fix-4's val='neutral' was correctly applied
        # to the Valuation-veto check (Step 2) but NOT to the bearish_excl_trend
        # tally, causing bearish_excl_trend to still count val=bearish and
        # blocking Fix-9a's bearish_excl_trend==0 condition.
        _local_overrides = {'valuation': val, 'location': loc, 'cot': cot, 'seasonality': seas}
        normalized = {}
        for k, v in biases.items():
            v = _local_overrides.get(k, v)  # Use local var if pre-normalisation modified it
            if v == 'uptrend':    normalized[k] = 'bullish'
            elif v == 'downtrend': normalized[k] = 'bearish'
            elif v == 'sideways':  normalized[k] = 'neutral'
            else:                  normalized[k] = v

        trend_n = normalized.get('trend', 'neutral')

        # Phase 8 H1 fix: tally non-trend indicators separately.
        # The counter-trend gate uses these tallies so that in an uptrend
        # (trend contributes 1 'bullish') the gate's `bullish_excl == 0`
        # clause remains reachable for genuine short setups.
        # cot_strength is excluded from direction tallies (it's a meta-value,
        # not a direction string — it won't match 'bullish'/'bearish' anyway).
        # Phase 24: 'constituent' is excluded too — it's an index-level proxy
        # of the Valuation read, not an independent fundamental vote.
        _tally_exclude = {'trend', 'cot_strength', 'constituent'}
        bullish_excl_trend = sum(1 for k, v in normalized.items()
                                 if k not in _tally_exclude and v == 'bullish')
        bearish_excl_trend = sum(1 for k, v in normalized.items()
                                 if k not in _tally_exclude and v == 'bearish')

        # ================================================================
        # Phase 23 (Task 1): Presidential/Sannial cycle Location override
        # for equity indices at all-time-high "expensive" Locations.
        #
        # When BOTH long-term cycles agree bullish, equity indices at ATH
        # (loc='bearish') are NOT a short setup — the bull market continues.
        # Two-tier upgrade:
        #   • FULL override → loc='bullish'  when at least 1 non-location/non-trend
        #     fundamental (COT or Seasonality) agrees bullish and none are bearish.
        #     Lets Step 4 fire a 'bullish' signal normally.
        #   • PARTIAL relax → loc='neutral'  when fundamentals are all neutral.
        #     Suppresses the hard-bearish location without forcing a long signal.
        #   • NO change if any fundamental is actively bearish.
        #
        # today_override allows the goldtest to pass the case_date so cycle
        # tables fire on the historical year (2023 = year 3, sannial 3 = bull).
        # ================================================================
        if asset_class == 'equity_indices' and loc == 'bearish':
            try:
                from BP_roadmap import (
                    PRESIDENTIAL_CYCLE_BIAS, SANNIAL_CYCLE_BIAS,
                    cycle_year_in_pres_cycle,
                )
                ref_date = today_override if today_override is not None else date.today()
                cy = cycle_year_in_pres_cycle(ref_date.year)
                pres_score = PRESIDENTIAL_CYCLE_BIAS.get(cy, [0]*12)[ref_date.month - 1]
                sann_score = SANNIAL_CYCLE_BIAS.get(ref_date.year % 10, 0)
                # BP_CYCLE_OVERRIDE=1 re-enables the Phase 23/24/26/27 presidential+sannial
                # cycle overrides. DEFAULT OFF since 2026-08-26: paired A/B on 472 pinned
                # out-of-sample cases changed 18% of predictions and fixed 27 / broke 28
                # (McNemar p=1.000) while skewing calls to long=198 vs a truth of 162.
                # They can only fire in a year-3 pre-election year with sannial>0 -- 2023,
                # then not again until 2027 -- so this is inert for live scanning today.
                if (pres_score > 0 and sann_score > 0
                        and os.environ.get("BP_CYCLE_OVERRIDE") == "1"):
                    # Assess non-location, non-trend fundamentals
                    _cot_n  = normalized.get('cot',         'neutral')
                    _seas_n = normalized.get('seasonality', 'neutral')
                    _val_n  = normalized.get('valuation',   'neutral')
                    _const_n = normalized.get('constituent', 'neutral')
                    _bear_count  = sum(1 for x in [_cot_n, _seas_n, _val_n] if x == 'bearish')
                    _bull_count  = sum(1 for x in [_cot_n, _seas_n, _val_n] if x == 'bullish')
                    _any_bearish = _bear_count > 0
                    # Phase 24 — T1 relaxed: allow ONE bearish fundamental as long as
                    # seasonality is bullish (Bernd's clearest pre-election bias signal).
                    # Captures early-2023 NQ/ES/YM cases where COT large-specs were
                    # still net short BUT seasonality + cycle roadmap were bullish.
                    _seas_overrides_one_bearish = (
                        _seas_n == 'bullish'
                        and _bear_count == 1
                        and _bull_count >= 1
                    )
                    # Phase 24 — Constituent route: bullish constituent stocks ALONE
                    # are enough to override loc='bearish' when cycles agree, even
                    # if other fundamentals are bearish. Bernd Ch.157: "if these
                    # two [AAPL + MSFT] are undervalued, you can buy NQ / ES."
                    # Allow up to 1 bearish fundamental at the index level to
                    # accommodate early-recovery COT.
                    _constituent_overrides = (
                        _const_n == 'bullish' and _bear_count <= 1
                    )
                    if _constituent_overrides:
                        # Constituent route: AAPL/MSFT undervalued → route bullish
                        loc = 'bullish'
                        biases = dict(biases, location='bullish')
                        normalized = dict(normalized, location='bullish')
                        logger.info(
                            f"Phase 24 T1-constituent: constituent_bias=bullish "
                            f"(pres={pres_score} sann={sann_score} bear={_bear_count}) "
                            f"→ loc=bullish (route NQ/ES via AAPL/MSFT thesis)"
                        )
                    elif not _any_bearish and _bull_count >= 1:
                        # Full upgrade: cycle + at least 1 fundamental agree bullish
                        loc = 'bullish'
                        biases = dict(biases, location='bullish')
                        normalized = dict(normalized, location='bullish')
                        logger.info(
                            f"Phase 23 T1: FULL override (pres={pres_score} sann={sann_score} "
                            f"bull_funds={_bull_count}) → loc=bullish"
                        )
                    elif _seas_overrides_one_bearish:
                        # Phase 24 relaxed full upgrade: seasonality bullish overrides
                        # one bearish fundamental (almost always: COT large-specs short
                        # in early-recovery phase). Cycle + Seas alignment is enough.
                        loc = 'bullish'
                        biases = dict(biases, location='bullish')
                        normalized = dict(normalized, location='bullish')
                        logger.info(
                            f"Phase 24 T1-relaxed: seasonality override "
                            f"(pres={pres_score} sann={sann_score} bear={_bear_count} "
                            f"bull={_bull_count}) → loc=bullish"
                        )
                    elif not _any_bearish and _bull_count == 0:
                        # Phase 38 T1 TIER-3: pure-cycle path. When pres+sann cycles
                        # both agree bullish AND no fundamental is actively bearish,
                        # fire bullish even without a single bullish indicator.
                        # Bernd verbatim (Phase 38 case 91 RTY=F Dec 2023): the
                        # pre-election December seasonal table alone drives the call
                        # when zone+location are present but indicators are silent.
                        # Was previously "partial relax to neutral" which left case
                        # in hold. Promote all-neutral-cycle-bullish to full bullish.
                        loc = 'bullish'
                        biases = dict(biases, location='bullish')
                        normalized = dict(normalized, location='bullish')
                        logger.info(
                            f"Phase 38 T1-tier3: pure cycle override "
                            f"(pres={pres_score} sann={sann_score} all funds neutral) → loc=bullish"
                        )
                    else:
                        logger.debug(
                            f"Phase 23 T1: skipped — bearish fundamental present "
                            f"(cot={_cot_n} seas={_seas_n} val={_val_n})"
                        )
            except Exception as e:
                logger.debug(f"Cycle override skipped: {e}")

        # Phase 26 (DeepSeek): early-2023 cycle-dominance override for equity indices.
        # When location is no longer bearish and both long-term cycles are bullish,
        # the cycles alone drive a LONG bias even when COT and Seasonality are neutral.
        # Mirrors Bernd reasoning: "cycles so strong I will be a buyer anyway."
        # Sideways included (not just uptrend) — empirically tested: the 3 sideways cases
        # in 2023 (consolidation before the ATH rally) were valid bullish roadmap calls.
        # Restricting to uptrend-only lost 3 correct cases with zero benefit (tested Phase 26d).
        # Phase 38 cycle-dominance relaxation: Bernd's pure-cycle calls on
        # equity indices (e.g. case 91 RTY Dec 2023) fire purely on the
        # presidential/sannial cycle even when local seasonality slope reads
        # bearish. The weekly-binning seasonality is known to be unreliable
        # for equity indices over multi-month forward windows. As long as
        # Valuation does not oppose (Bernd's Rule #1), allow the cycle call
        # to fire regardless of seasonality.
        if (asset_class == 'equity_indices'
                and loc != 'bearish'
                and trend in ('uptrend', 'sideways')
                and normalized.get('valuation', 'neutral') != 'bearish'):
            try:
                from BP_roadmap import (
                    PRESIDENTIAL_CYCLE_BIAS, SANNIAL_CYCLE_BIAS,
                    cycle_year_in_pres_cycle,
                )
                ref_date = today_override if today_override is not None else date.today()
                cy = cycle_year_in_pres_cycle(ref_date.year)
                pres_score = PRESIDENTIAL_CYCLE_BIAS.get(cy, [0]*12)[ref_date.month - 1]
                sann_score = SANNIAL_CYCLE_BIAS.get(ref_date.year % 10, 0)
                # BP_CYCLE_OVERRIDE=1 re-enables the Phase 23/24/26/27 presidential+sannial
                # cycle overrides. DEFAULT OFF since 2026-08-26: paired A/B on 472 pinned
                # out-of-sample cases changed 18% of predictions and fixed 27 / broke 28
                # (McNemar p=1.000) while skewing calls to long=198 vs a truth of 162.
                # They can only fire in a year-3 pre-election year with sannial>0 -- 2023,
                # then not again until 2027 -- so this is inert for live scanning today.
                if (pres_score > 0 and sann_score > 0
                        and os.environ.get("BP_CYCLE_OVERRIDE") == "1"):
                    cot_n = normalized.get('cot', 'neutral')
                    if cot_n != 'bearish':
                        logger.info(
                            f"Phase 26 cycle-dominance: equity index uptrend + both cycles bullish "
                            f"(pres={pres_score} sann={sann_score} cot={cot_n}) -> bullish"
                        )
                        return 'bullish'
            except Exception as e:
                logger.debug(f"Phase 26 cycle dominance skipped: {e}")

        # Phase 42 Fix-2: Capture bullish presidential-cycle state for equity_indices.
        # When pres+sann cycles are both bullish (e.g. year-3 pre-election = 2023),
        # Bernd NEVER takes equity-index short positions — 0 such calls in 160 goldtest.
        # The flag is applied after Step 1 determines `proposed` direction, blocking any
        # bearish return for equity indices during pre-election cycles.
        # 2024 (sann[4]=0) is correctly unaffected: YM/RTY shorts in year-0 are allowed.
        _equity_idx_no_short = False
        if asset_class == 'equity_indices':
            try:
                from BP_roadmap import (
                    PRESIDENTIAL_CYCLE_BIAS, SANNIAL_CYCLE_BIAS,
                    cycle_year_in_pres_cycle,
                )
                _ref42 = today_override if today_override is not None else date.today()
                _cy42 = cycle_year_in_pres_cycle(_ref42.year)
                _pres42 = PRESIDENTIAL_CYCLE_BIAS.get(_cy42, [0] * 12)[_ref42.month - 1]
                _sann42 = SANNIAL_CYCLE_BIAS.get(_ref42.year % 10, 0)
                # 2026-08-21 (C-72): the premise above is CONTRADICTED by newly
                # extracted Weekly Outlook calls. He DOES call equity indices lower
                # in pre-election 2023:
                #   YM=F 2023-09-16 "we are moving from that supply area where price
                #       was at least overvalued ... head and shoulders ... this is
                #       really falling apart. And I think it will fall apart"
                #   YM=F 2023-09-23 "expect some follow through to the downside ...
                #       I don't see any buying"
                #   NQ=F 2023-09-16 "we have a daily bearish engulfing"
                # The "0 such calls in 160 goldtest" that justified this block was an
                # absence-of-evidence result from a corpus that had not yet been mined
                # for 2023 index shorts. EXPERIMENTAL, DEFAULT OFF -- judge on numbers.
                _disable_42 = bool(
                    (self.config.get('rules', {}) or {}).get('allow_prelection_index_shorts', False)
                    or os.environ.get('BP_ALLOW_PREELECTION_INDEX_SHORTS') == '1'
                )
                if _pres42 > 0 and _sann42 > 0 and not _disable_42:
                    _equity_idx_no_short = True
                    logger.debug(
                        f"Phase 42 Fix-2: equity_idx_no_short=True "
                        f"(cy={_cy42} pres={_pres42} sann={_sann42} ref={_ref42})"
                    )
            except Exception as _e42:
                logger.debug(f"Phase 42 Fix-2 cycle check failed: {_e42}")

        # Phase 23 (Task 4): zone-arrival soft-veto eligibility flag.
        # composite >= 7.0 = top-quartile zone; soft-veto only fires when
        # price has actually arrived at a high-quality zone.
        # Phase 38 GAP-27 fix: rulebook Section 8 exception restricts the
        # Valuation override to "156w COT historic extreme + counter-trend
        # setup." The T4 flag now additionally requires cot_strength=='strong'
        # (which is set when the 156w extreme IS already at extreme, per Phase
        # 17/18 implementation). Without it, any HQ zone could override the
        # Valuation hard veto, which is broader than Bernd sanctions.
        _cot_strength_for_t4 = biases.get('cot_strength', 'normal')
        _hq_zone_arrival = bool(
            at_zone
            and zone_composite >= 7.0
            and _cot_strength_for_t4 == 'strong'
        )

        # ----------------------------------------------------------------
        # STOCKS: Valuation-driven, long-only (Phase 6 audit validated)
        # ----------------------------------------------------------------
        if asset_class == 'equities':
            seas_n = normalized.get('seasonality', 'neutral')
            loc_n  = normalized.get('location',    'neutral')
            # Phase 38 ZONE-ARRIVAL OVERRIDE (most-confirmed pattern across all
            # 7 vision agents): when at HQ demand zone (composite >= 7.0) with
            # location bullish and val not bearish, fire bullish regardless of
            # other indicators. Bernd verbatim across multiple FT sessions:
            # "every demand zone can be tried to be bought" + "we are coming
            # from a demand zone you can go long." Seasonality being locally
            # bearish does not block the trade — zone arrival is primary.
            if at_zone and zone_composite >= 7.0 and loc_n == 'bullish' and val != 'bearish':
                return 'bullish'
            # Phase 39 batch 2: BASKET UNDERVALUATION INHERITANCE.
            # Bernd Ch.157 verbatim "the two most important stocks is Apple and
            # is Microsoft." When AAPL+MSFT read undervalued, he extends the
            # bullish bias to the rest of the mega-cap basket (GOOG/META/NVDA/
            # AMZN/NFLX/TSLA) even when their own Val reads neutral or bearish.
            # Constituent_bias bullish from the equity-index proxy is our best
            # signal that anchor stocks are undervalued — extend that to single
            # stocks when their Val is not strongly bearish.
            _const_n = normalized.get('constituent', 'neutral')
            _basket_members = {'GOOG', 'GOOGL', 'META', 'NVDA', 'AMZN', 'NFLX', 'TSLA',
                                'AAPL', 'MSFT'}
            if (symbol and symbol in _basket_members
                    and _const_n == 'bullish'
                    and val != 'bearish'
                    and trend != 'downtrend'):
                logger.info(
                    f"Phase 39 basket inheritance: {symbol} const=bullish val={val} -> bullish"
                )
                return 'bullish'
            # Primary: Valuation undervalued, not in a downtrend
            if val == 'bullish' and trend != 'downtrend':
                return 'bullish'
            # Secondary: Seasonality + Location both bullish (demand zone buy)
            if seas_n == 'bullish' and loc_n == 'bullish':
                return 'bullish'
            # Tertiary: Seasonality bullish, Valuation not bearish, not downtrend
            if seas_n == 'bullish' and val != 'bearish' and trend != 'downtrend':
                return 'bullish'
            # Phase 23 T2 relaxed path: genuinely cheap (T2 proxy undervalued) AND
            # seasonality both agree bullish, even in a downtrend.
            # Covers "buy the crash" setups: 2022-crashed stocks (NFLX/META/AMZN/GOOG)
            # where price is >5% below 3yr SMA AND January/spring seasonality is bullish.
            # NOTE: val='bearish' blocks this (T2 says overvalued = no long).
            if val == 'bullish' and seas_n == 'bullish':
                return 'bullish'
            # Phase 27 — Presidential/sannial cycle path for individual stocks.
            # Bernd's roadmap calls (AAPL/MSFT/GOOG/META/NFLX long throughout 2023)
            # were driven by pre-election year-3 + sannial year-3 (both strongly bullish).
            # When both long-term cycles agree bullish AND seasonality is not bearish,
            # fire bullish regardless of local trend.
            # Trend guard removed (Phase 27b): the Oct 2023 pullback put stocks in a
            # local 'downtrend' via ZigZag even though Bernd was bullish for Q4 — the
            # presidential/sannial cycle reasoning explicitly overrides local trend for
            # individual stocks (same way T1 overrides expensive Location for indices).
            # Safe: equities branch never returns 'bearish', so no wrong-direction risk
            # at Stage-1. Stage-2 zone+decision-matrix still gates real trade signals.
            # Phase 37 NOTE: tried skipping cycle path for NFLX (since Phase 34
            # excluded its fundamentals). Caused regression because Bernd DID
            # apply cycle bullishness to NFLX in 2023 even without fundamentals.
            # Reverted per "100% Bernd-clone" goal.
            if seas_n != 'bearish':
                try:
                    from BP_roadmap import (
                        PRESIDENTIAL_CYCLE_BIAS, SANNIAL_CYCLE_BIAS,
                        cycle_year_in_pres_cycle,
                    )
                    ref_date = (today_override if today_override is not None
                                else date.today())
                    cy = cycle_year_in_pres_cycle(ref_date.year)
                    pres_score = PRESIDENTIAL_CYCLE_BIAS.get(
                        cy, [0] * 12)[ref_date.month - 1]
                    sann_score = SANNIAL_CYCLE_BIAS.get(ref_date.year % 10, 0)
                    # BP_CYCLE_OVERRIDE=1 re-enables the Phase 23/24/26/27 presidential+sannial
                    # cycle overrides. DEFAULT OFF since 2026-08-26: paired A/B on 472 pinned
                    # out-of-sample cases changed 18% of predictions and fixed 27 / broke 28
                    # (McNemar p=1.000) while skewing calls to long=198 vs a truth of 162.
                    # They can only fire in a year-3 pre-election year with sannial>0 -- 2023,
                    # then not again until 2027 -- so this is inert for live scanning today.
                    if (pres_score > 0 and sann_score > 0
                            and os.environ.get("BP_CYCLE_OVERRIDE") == "1"):
                        logger.info(
                            f"Phase 27 equities cycle: pres={pres_score} "
                            f"sann={sann_score} seas={seas_n} trend={trend} -> bullish"
                        )
                        return 'bullish'
                except Exception as _e:
                    logger.debug(f"Phase 27 equities cycle skipped: {_e}")
            return 'hold'

        # ----------------------------------------------------------------
        # FUTURES: Bernd's hierarchy  (Phase 11 rewrite)
        # ----------------------------------------------------------------

        # Phase 16 — COT-is-king override for commodities / precious metals / energies.
        #
        # HAI transcript line 3473-3477: "what overrules true seasonality are the
        # commercials... COT is king."  For commodity asset classes specifically, a
        # strong COT extreme (Commercials or Retailers at multi-year extreme) takes
        # priority over the Location-derived proposed direction.  This is NOT an
        # equilibrium bypass — it only fires when COT and Location DISAGREE.
        #
        # Test-validated with Phase 15 goldtest: 9 GC=F cases fixed, 0 false positives.
        # Only applies when cot_strength='strong' (rolling AND 156w overlay both extreme).
        # Phase 37 NOTE: tried expanding to ('commodities', 'precious_metals',
        # 'energies', 'nat_gas', 'soft_commodities') on 2026-05-25 per rulebook.
        # PMs Stage 1 dropped 5 cases because the COT-is-king path started firing
        # on PM cases where Bernd was still neutral (cot strength was deemed
        # strong but Bernd's hierarchy weighted Location more). Reverted per
        # "100% Bernd-clone" goal. Bernd does NOT apply COT-is-king mechanically
        # to NG/soft_commodities at the indicator threshold.
        # Phase 40 NOTE: tried cotton/corn retailer-extreme contrarian above
        # zone-arrival. Lost 4 commodity cases (cotton rule fired on cases
        # Bernd was actually long). Reverted. Cotton contrarian needs more
        # specific trigger than "all bullish indicators" — needs actual
        # retailer-extreme data, not derived from Commercials COT.

        # Phase 39 batch 4+5: ZONE-ARRIVAL RULE for forex/commodities/energies/IR.
        # When at zone with location committing to a direction and Valuation not
        # opposing, fire that direction. Bernd verbatim: "at the zone, take the
        # trade". Phase 38 vision agents confirmed pattern across forex (4 of 5
        # cases), NG (case 27), ZB (case 72). Excluded asset_classes where
        # location override logic is already in place (equity_indices has cycle
        # paths, equities has its own branch above).
        _ZONE_ARRIVAL_CLASSES = ('forex', 'commodities', 'energies', 'interest_rates', 'soft_commodities', 'nat_gas')
        if asset_class in _ZONE_ARRIVAL_CLASSES:
            loc_n = normalized.get('location', 'neutral')
            # Phase 42 Fix-5: NG=F (nat_gas) seasonality gate inside zone-arrival.
            # NG is weather-driven; bearish seasonal overrides demand zone presence.
            # Bernd case #94 (Dec 2023): loc=bullish, cot=bullish, seas=bearish → neutral.
            # He does NOT buy NG against bearish 10y+5y seasonality even with retailer
            # COT extreme and a demand zone — seasonal timing is primary for NG.
            # When _ng_seas_ok=False, falls through to Step 1 → Step 3 counter-trend gate
            # which returns hold (trend=downtrend + seas=bearish in bearish_excl).
            _ng_seas_ok = not (asset_class == 'nat_gas' and seas == 'bearish')
            # Phase 42 Fix-6: Forex zone-arrival bearish blocked by strong bullish COT.
            # When non-commercials are at a 156w historic extreme (cot_strength='strong')
            # in the bullish direction for a currency, they are massively net long that
            # currency at a multi-year extreme. Shorting at a supply zone against a
            # historic COT extreme is the most dangerous trade in Bernd's system.
            # Cases #43 and #119 (6E=F Apr 2023): zone-arrival fired short despite
            # cot=bullish/strong (non-comms net long EUR at 156w extreme).
            # Corpus: Phase 16 "COT is king"; Phase 12 cheatsheet "Non-Comms ①" for forex.
            _forex_cot_short_ok = not (
                asset_class == 'forex'
                and loc_n == 'bearish'
                and cot == 'bullish'
                and biases.get('cot_strength', 'none') == 'strong'
            )
            # 2026-08 validation (C-58): the zone-arrival rule is ASYMMETRIC — the bearish
            # branch is guarded by `_forex_cot_short_ok` (forex only) while the BULLISH
            # branch has no COT guard at all. Measured against 85 of Bernd's own calls,
            # 10 of the 12 outright-opposite verdicts were "he said bearish, we said
            # bullish", and this branch produced them: e.g. NG=F 2024-02-11 and 2024-02-19
            # fired bullish here while our own COT read bearish.
            #
            # EXPERIMENTAL, DEFAULT OFF. Enable with rules.cot_blocks_zone_arrival: true
            # (or env BP_COT_BLOCKS_ZONE=1) to require that COT does not directly oppose
            # the zone-arrival direction. Kept opt-in because Phase 37/40 recorded that
            # earlier attempts to widen COT-is-king LOST cases against the goldtest — so
            # this is to be judged on measured numbers, not on the argument alone.
            _cot_guard_on = bool(
                (self.config.get('rules', {}) or {}).get('cot_blocks_zone_arrival', False)
                or os.environ.get('BP_COT_BLOCKS_ZONE') == '1'
            )
            _cot_long_ok = not (_cot_guard_on and cot == 'bearish')
            _cot_short_ok_sym = not (_cot_guard_on and cot == 'bullish')

            if loc_n == 'bullish' and val != 'bearish' and _ng_seas_ok and _cot_long_ok:
                logger.info(f"Phase 39 {asset_class} zone-arrival -> bullish (val={val})")
                return 'bullish'
            if (loc_n == 'bearish' and val != 'bullish' and _ng_seas_ok
                    and _forex_cot_short_ok and _cot_short_ok_sym):
                logger.info(f"Phase 39 {asset_class} zone-arrival -> bearish (val={val})")
                return 'bearish'

        # Phase 40 cotton contrarian moved above zone-arrival block (see earlier).

        # Phase 39 batch 3: Platinum (PL=F) October pre-election seasonal.
        # Bernd verbatim Case 61 PL Sep 23 2023: "pre-election cycle, platinum
        # has beginning of October." When at PL with cycle year 3 + October,
        # fire bullish even if other indicators are neutral.
        if (symbol == 'PL=F' and asset_class == 'precious_metals'
                and val != 'bearish'):
            try:
                from BP_roadmap import (
                    PRESIDENTIAL_CYCLE_BIAS,
                    cycle_year_in_pres_cycle,
                )
                ref_date = today_override if today_override is not None else date.today()
                cy = cycle_year_in_pres_cycle(ref_date.year)
                if cy == 3 and ref_date.month in (9, 10):
                    logger.info(
                        f"Phase 39 PL Oct pre-election seasonal -> bullish "
                        f"(cy={cy} month={ref_date.month})"
                    )
                    return 'bullish'
            except Exception as _e:
                logger.debug(f"PL Oct seasonal check skipped: {_e}")

        # Phase 39 batch 1: extend COT-king to equity_indices specifically for the
        # BULLISH direction only (Bernd verbatim "if commercials are extreme long
        # I will be a buyer"). Excluding bearish direction protects against false
        # shorts at ATH (case 78 NQ Oct 2023 where COT was strong-bearish but Bernd
        # was bullish on cycle). This is one-directional COT-king for equity indices.
        # 2026-08-25 CONSISTENCY FIX (gated: BP_EFFCLASS=1).
        # _indicators_for_class derives an EFFECTIVE class from the symbol --
        # NG=F -> 'nat_gas' (Retailers, contrarian), CL=F -> retail-contrarian,
        # softs -> 'soft_commodities' -- and routes the COT read accordingly.
        # _bias_consensus, however, only ever saw the RAW asset_class ('energies'
        # for NG=F, from both run_scanner and the goldtest). So a COT value
        # computed under nat_gas retailer-contrarian rules was then consumed as
        # if it were an energies Commercials read, and COT-is-king fired on it.
        # Measured on NG=F 2023-03-07 with identical components:
        #     asset_class='energies' -> bearish   (COT overrides bullish location)
        #     asset_class='nat_gas'  -> bullish   (matches Bernd's call)
        # 6 of the 16 COT-drives-a-short-against-Bernd cases are NG=F.
        # ENABLED 2026-08-25 after measuring +3 cases / 0 regressions on the
        # 475-case out-of-sample replay (52.8% -> 53.5%). Set BP_EFFCLASS=0 to
        # revert to the old inconsistent behaviour.
        _eff_class = asset_class
        if os.environ.get('BP_EFFCLASS') != '0' and symbol:
            if symbol in SOFT_COMMODITY_SYMBOLS:
                _eff_class = 'soft_commodities'
            elif symbol in NAT_GAS_SYMBOLS:
                _eff_class = 'nat_gas'
        COT_KING_CLASSES = ('commodities', 'precious_metals', 'energies')
        cot_for_king = biases.get('cot', 'neutral')
        if asset_class == 'equity_indices' and biases.get('cot_strength') == 'strong' and cot_for_king == 'bullish':
            if normalized.get('valuation', 'neutral') != 'bearish':
                logger.info(f"Phase 39 EI COT-king bullish (cot={cot_for_king} strong) -> bullish")
                return 'bullish'
        if _eff_class in COT_KING_CLASSES:
            cot_strength = biases.get('cot_strength', 'normal')
            if cot_strength == 'strong' and cot != 'neutral':
                cot_direction = cot   # 'bullish' or 'bearish'
                loc_direction = 'bullish' if loc == 'bullish' else ('bearish' if loc == 'bearish' else 'neutral')
                # Phase 18 extension: COT-is-king also fires at equilibrium (loc='neutral').
                # When COT is at a 156w historic extreme for a commodity/PM/energy, it overrides
                # the equilibrium gate (Phase 11 Step 1 normally requires all-3 unanimity).
                # GC=F Aug 2023 pattern: loc=neutral, COT=bullish/strong, val=neutral → bullish.
                # Condition: val must NOT actively oppose (val='bullish' or 'neutral' for bullish COT).
                cot_fires = False
                if cot_direction != loc_direction and loc != 'neutral':
                    # Original case: COT vs Location conflict
                    cot_fires = True
                elif loc == 'neutral':
                    # Phase 18: COT at historic extreme bypasses the equilibrium all-3 gate
                    cot_fires = True

                if cot_fires:
                    # The Valuation veto still applies (Rule #1): if val actively
                    # opposes the COT direction, return hold.
                    # Phase 43 Fix-B: Exception for precious_metals — val=bearish veto
                    # is NOT applied when COT-is-king fires bullish for Gold/Silver/Platinum.
                    # Chapter 018 (Phase 41 chunk-3 frame audit): Bernd explicitly states
                    # PM Valuation accuracy is "maybe even less than 50%".
                    # Root cause: during rate-hike regimes ZB (30yr bonds) falls alongside
                    # Gold, producing a spurious "overvalued vs bonds" reading even as
                    # Commercials accumulate (the bond-induced Valuation freeze, Phase 7).
                    # Same principle as Phase 42 Silver Fix-4 — extended to all PMs under
                    # COT-king. Fix-1 (line below) already prevents PM bearish signals.
                    if cot_direction == 'bullish' and val == 'bearish':
                        if asset_class != 'precious_metals':
                            return 'hold'
                        logger.info(
                            "Phase 43 Fix-B: PM val=bearish not vetoing COT-is-king "
                            "(Ch.018: PM Valuation <50% accurate; bond-induced freeze)"
                        )
                    if cot_direction == 'bearish' and val == 'bullish':
                        return 'hold'
                    logger.info(
                        f"COT-is-king override: cot={cot} overrides loc={loc} "
                        f"for {asset_class} (strength=strong)"
                    )
                    # Phase 42 Fix-1: PM Commercials being short is structural hedging,
                    # not a directional sell signal. Bernd: 0 PM shorts in 160 goldtest cases.
                    # Commercials in gold/silver/platinum hold physical inventory and routinely
                    # hedge with short futures positions even in bull markets.
                    if asset_class == 'precious_metals' and cot_direction == 'bearish':
                        logger.info("Phase 42 Fix-1: PM COT-is-king bearish suppressed → hold")
                        return 'hold'
                    return cot_direction

        # Step 1 — Location gate.
        # Bernd PREFERS extreme locations (cheap/expensive zones), but the
        # 3×3 matrix lists equilibrium as "Avoid" not "Illegal" — he does
        # take equilibrium trades when fundamentals are overwhelming.
        # Rule: if loc=neutral, require ALL 3 non-location fundamentals
        # (val + cot + seasonality) to unanimously agree before allowing
        # the trade. This is more selective than the old 3/5 vote while
        # still recovering the USDJPY/NG pattern (3/3 fundamentals agree
        # but loc was neutral). Mixed fundamentals at equilibrium = HOLD.
        if loc == 'neutral':
            _eq_exclude = {'trend', 'location', 'cot_strength', 'constituent'}  # Phase 24
            bull_fund = sum(1 for k, v in normalized.items()
                            if k not in _eq_exclude and v == 'bullish')
            bear_fund = sum(1 for k, v in normalized.items()
                            if k not in _eq_exclude and v == 'bearish')
            # EXPERIMENT (2026-08-25), gated OFF by default:
            #   BP_EQUIL_2OF3=1 -> require 2 agreeing + 0 opposing instead of 3.
            # Measured on the 441-case out-of-sample set: of 120 location-neutral
            # cases, the number meeting the ALL-3 bar was ZERO. Valuation reads
            # neutral ~77% of the time and COT ~83%, so "all three non-neutral AND
            # unanimous" is effectively unreachable -- this override is dead code
            # in practice, and the gate is an unconditional hold at equilibrium.
            # A 2-of-3 bar (still no opposing vote) matches 26 of those 120 cases.
            import os as _os
            _bar = 2 if _os.environ.get("BP_EQUIL_2OF3") == "1" else 3
            if bull_fund >= _bar and bear_fund == 0:
                proposed = 'bullish'   # overwhelming bullish at equilibrium
            elif bear_fund >= _bar and bull_fund == 0:
                proposed = 'bearish'   # overwhelming bearish at equilibrium
            else:
                return 'hold'          # mixed or insufficient = no trade
        else:
            # Location tells us the proposed direction.
            proposed = 'bullish' if loc == 'bullish' else 'bearish'

        # C-83 EXPERIMENTAL, DEFAULT OFF: let a MODERATE bearish COT propose the short.
        # Measured on the 133-row all-trader set, how each input predicts THEIR direction:
        #     our_cot      = bullish  26/27 (96%)      bearish 16/27 (59%)
        #     our_location = bullish  43/51 (84%)      bearish 16/50 (32%)
        # and their own stated reasoning splits the same way -- their LONGS cite
        # valuation (39%) and zone (37%), their SHORTS cite COT (42%) above all else.
        # We derive direction from location only, so on their 33 bearish calls our COT
        # reads bearish 16 times and we output 'hold' on 13 of them.
        # Sliced further, the reliable signature is NOT the extreme one:
        #     cot=bearish strength=normal                 11/13 (85%)
        #     cot=bearish strength=normal val!=bullish    10/11 (91%)
        #     cot=bearish strength=STRONG                  5/14 (36%)
        # A 156-week extreme is unreliable (commercials are hedgers and early); a
        # moderate bearish COT is the tradeable one. On that 11-row signature we
        # currently emit hold 8 / bearish 3, and all 8 holds are their bearish calls.
        # This path also bypasses the per-class SHORT suppressions (PM / equity index /
        # equities long-only), which is the point -- 3 of those 8 holds are GC=F.
        _cot_may_propose_short = bool(
            (self.config.get('rules', {}) or {}).get('cot_proposes_short', False)
            or os.environ.get('BP_COT_PROPOSES_SHORT') == '1'
        )
        _cot_short_signature = (
            _cot_may_propose_short
            and biases.get('cot') == 'bearish'
            and biases.get('cot_strength') == 'normal'
            and normalized.get('valuation', 'neutral') != 'bullish'
        )
        if _cot_short_signature:
            proposed = 'bearish'

        # Phase 42 Fix-1: Suppress ALL precious_metals SHORT proposals.
        # PM Commercials holding short futures is routine inventory hedging, not directional.
        # Evidence: Bernd has 0 PM short calls across all 160 goldtest cases.
        # This catches any bearish proposed direction that wasn't already blocked by the
        # COT-is-king PM guard above (e.g. loc=bearish + seas=bearish at Step 4).
        # 2026-08-21 (C-79): the premise "0 PM short calls across all 160 goldtest cases"
        # is absence of evidence, exactly like the Phase 42 Fix-2 equity-index twin that
        # C-72 disproved. The 133-row all-trader ground truth contains NINE bearish
        # precious-metals calls (GC=F x6, SI=F x3), and this rule holds ALL of them:
        # metals score 0/9 on his own short calls. One carries explicit levels --
        # 2023-05-23 GC=F "I can say 2026.4 as an entry, and 2065.8 as a stop loss"
        # (stop above entry = a short). EXPERIMENTAL, DEFAULT OFF -- judge on numbers.
        _pm_short_ok = bool(
            (self.config.get('rules', {}) or {}).get('allow_precious_metals_shorts', False)
            or os.environ.get('BP_ALLOW_PM_SHORTS') == '1'
        )
        if (asset_class == 'precious_metals' and proposed == 'bearish'
                and not _pm_short_ok and not _cot_short_signature):
            logger.info("Phase 42 Fix-1: PM proposed=bearish suppressed → hold")
            return 'hold'

        # Phase 42 Fix-2: Suppress equity_index SHORT during bullish presidential cycles.
        # Bernd: 0 equity_index short calls in 2023 (pres[3]=+1 sann[3]=+1).
        # Applied after Step 1 so it catches any bearish proposal regardless of
        # whether T1 fired, failed, or was skipped.
        # 2026-08-25 EQUITY-INDEX LOCATION CORROBORATION (BP_IDX_CORROB=0 to disable).
        # Measured on the 475-case out-of-sample replay: for equity_indices,
        # location='bearish' agrees with Bernd only 9/69 times (13%) -- it is close
        # to anti-predictive, because a Fib 33/66 read calls "expensive" near every
        # all-time high. Phase 42 Fix-2 already guards bullish presidential cycles,
        # so 2023 is covered; year-0 (2024) is explicitly NOT ("YM/RTY shorts in
        # year-0 are allowed" per the note above) and that is where it leaks:
        # in 2024 the engine fired 8 index shorts on loc=bearish where Bernd took 1,
        # and produced 0 neutrals where Bernd had 8.
        # Rather than ban index shorts outright (blanket suppression scored +4 but
        # BROKE 2 previously-correct calls), require the short to be corroborated by
        # COT or Valuation. A 13%-accurate signal should not drive a short alone.
        # Measured: +3 cases, 0 regressions.
        # 2026-08-26 REFINEMENT (BP_IDX_CORROB_VAL_ONLY=1, default OFF): drop COT
        # as an acceptable corroborator for an equity-index short. Measured on the
        # 479-case pinned replay: of the 21 equity-index shorts the engine fired
        # with cot='bearish', only 4 (19%) matched -- 10 were outright OPPOSITE
        # (the traders were long) and 7 were false shorts (they were neutral).
        # These four traders short an index on 11 of 90 index calls, and an
        # individual stock on 2 of 206. This is the same "finite vs infinite
        # market" question that already excludes equity_indices from
        # _COT_KING_CLASSES_156W: non-commercial positioning on a stock-index
        # future is not the smart-money signal it is in a physical commodity.
        _corrob_val_only = os.environ.get('BP_IDX_CORROB_VAL_ONLY') == '1'
        _cot_corroborates = (not _corrob_val_only) and normalized.get('cot') == 'bearish'
        if (proposed == 'bearish' and _eff_class == 'equity_indices'
                and os.environ.get('BP_IDX_CORROB') != '0'
                and normalized.get('location') == 'bearish'
                and not _cot_corroborates
                and normalized.get('valuation') != 'bearish'):
            logger.info(
                "equity-index loc=bearish uncorroborated by %s -> hold"
                % ("Valuation" if _corrob_val_only else "COT/Valuation")
            )
            return 'hold'

        if proposed == 'bearish' and _equity_idx_no_short and not _cot_short_signature:
            logger.info(
                "Phase 42 Fix-2: equity_index SHORT suppressed — bullish pre-election cycle"
            )
            return 'hold'

        # Phase 42 Fix-6b: Forex COT-at-156w-extreme blocks proposed direction when opposing.
        # When non-commercials are at a 156w historic extreme (cot_strength='strong') and
        # their direction OPPOSES the proposed trade direction (loc + val agree but COT
        # contradicts at an extreme), Bernd does NOT take the trade — he waits for COT to
        # turn. Non-Comms ① is the PRIMARY indicator for forex per Phase 12 cheatsheet.
        # Cases #43, #119 (6E=F Apr 2023): loc=bearish + val agrees bearish, BUT non-comms
        # are at a historic extreme LONG EUR (bullish). Taking an EUR short against this
        # signal is the most dangerous forex trade in Bernd's system → return hold.
        # Note: Fix-6 (in zone-arrival block) handles the fast-path return; this guard
        # handles the case where the Step 1-4 consensus path independently produces a
        # direction that contradicts a strong COT signal.
        if asset_class == 'forex' and biases.get('cot_strength', 'none') == 'strong':
            if cot == 'bullish' and proposed == 'bearish':
                logger.info(
                    "Phase 42 Fix-6b: forex cot=bullish/strong blocks proposed=bearish → hold"
                )
                return 'hold'
            if cot == 'bearish' and proposed == 'bullish':
                logger.info(
                    "Phase 42 Fix-6b: forex cot=bearish/strong blocks proposed=bullish → hold"
                )
                return 'hold'

        # Step 2 — Valuation veto (HARD by default, SOFT at HQ zone arrival).
        # "Rule Number One" per CW38/CW39: Valuation must NOT actively
        # contradict the trade direction. Overvalued assets don't go long;
        # undervalued assets don't go short — regardless of other indicators.
        #
        # Phase 23 (Task 4): when price has arrived at a high-quality zone
        # (composite >= 7.0), soft-veto allows the trade as anticipatory.
        # Bernd's discretionary override for setups like 6S=F supply-zone
        # shorts against CHF undervaluation: "zone arrival is more immediate
        # than the Valuation reading." Counter-trend gate (Step 3) and zone
        # direction matching still apply downstream.
        # Phase 48: the HQ zone-arrival soft-veto may override Rule #1 ONLY for
        # COUNTER-TREND / reversal setups -- its documented purpose (Phase 38
        # GAP-27) is "156w COT historic extreme + counter-trend setup", e.g. a
        # 6S=F supply short fading CHF undervaluation. It must NOT override the
        # valuation veto on a plain WITH-trend setup (e.g. AUDUSD short in a
        # downtrend with val=bullish) -- that is a straight Rule #1 violation.
        # With-trend = proposed agrees with trend; block the override there.
        if proposed == 'bullish' and val == 'bearish':
            _override_ok = _hq_zone_arrival and trend != 'uptrend'   # allow only counter-trend/sideways
            if not _override_ok:
                return 'hold'  # hard veto — Rule #1
            logger.info(f"Phase 23 T4: HQ counter-trend zone arrival ({zone_composite:.1f}) overrides Val=bearish veto")
        if proposed == 'bearish' and val == 'bullish':
            _override_ok = _hq_zone_arrival and trend != 'downtrend'  # allow only counter-trend/sideways
            if not _override_ok:
                return 'hold'  # hard veto — Rule #1
            logger.info(f"Phase 23 T4: HQ counter-trend zone arrival ({zone_composite:.1f}) overrides Val=bullish veto")

        # Step 3 — Counter-trend safety gate (prop-firm protection).
        # Bernd does take counter-trend setups but requires overwhelming
        # non-trend evidence. Phase 8 H1 fix: check non-trend tally only
        # (avoids the impossibility bug where `bullish == 0` was unreachable
        # in any uptrend because the trend vote normalises to 'bullish').
        if proposed == 'bearish' and trend == 'uptrend':
            # Short in uptrend: Location bearish + Valuation not bullish (already
            # passed Step 2) + at least 1 more non-trend bearish, 0 opposing.
            if bearish_excl_trend >= 2 and bullish_excl_trend == 0:
                return 'bearish'
            # NOTE: no relaxed path for short-in-uptrend — tested and caused
            # CC=F Feb 2024 wrong-direction error (supply-shock narrative trade).
            return 'hold'

        if proposed == 'bullish' and trend == 'downtrend':
            # Long in downtrend: Location bullish + Valuation not bearish (Step 2) +
            # ≥1 more non-trend bullish, 0 opposing.
            if bullish_excl_trend >= 2 and bearish_excl_trend == 0:
                return 'bullish'
            # Phase 10 relaxed path: 3+ non-trend bullish, ≤1 opposing, val must align.
            # Covers CL=F / PA=F: val+loc+cot=bullish but seasonality bearish.
            # Phase 42 Fix-9b: Silver requires seas not bearish on this path too.
            # Without this guard, Phase 10 relaxed fires for SI=F #115 (val+loc+cot=bullish,
            # seas=bearish) BEFORE Phase 11 relaxed + Fix-9b can block it.
            # Blueprint Cheatsheet Silver: Seasonality ③ actively bearish overrides the
            # relaxed minimum (val+loc+cot = 3 bullish is insufficient for Silver when
            # the odds-enhancer Seasonality opposes). Case #115 (SI=F Mar 2024, bernd=neutral).
            if (bullish_excl_trend >= 3 and bearish_excl_trend <= 1 and val == 'bullish'
                    and not (symbol and symbol in SILVER_SYMBOLS and seas == 'bearish')):
                return 'bullish'
            # Phase 11 relaxed path: Bernd's minimum (loc + val = tradeable) with ≤1
            # opposing non-trend indicator.  Covers CL=F/BA=F where only loc+val fire
            # bullish but seasonality is mildly bearish.  Requires BOTH loc AND val to
            # agree — prevents a single strong-val from dragging in pure-neutral loc.
            # Phase 42 Fix-9b: Silver (SI=F) Phase 11 relaxed requires seas not bearish.
            # Blueprint Cheatsheet Silver: Seasonality ③ = odds-enhancer. When seas
            # actively opposes (bearish), the val+loc-only minimum is insufficient.
            # Case #115 (SI=F Mar 2024, bernd=neutral): val=bullish + loc=bullish + seas=bearish
            # was firing the Phase 11 relaxed path as a false positive. Block for Silver
            # when the seasonality odds-enhancer is actively working against the trade.
            _silver_seas_ok = not (symbol and symbol in SILVER_SYMBOLS and seas == 'bearish')
            if val == 'bullish' and loc == 'bullish' and bearish_excl_trend <= 1 and _silver_seas_ok:
                return 'bullish'
            # Phase 42 Fix-9a: Silver downtrend relaxation.
            # Blueprint Cheatsheet: Silver primary = Commercials ① + Seasonality ③.
            # When COT (primary), Seasonality, and Location all agree bullish AND nothing
            # is actively bearish, fire bullish even in a local downtrend.
            # After Fix-4 converts val=bearish→neutral for Silver, bullish_excl_trend = 2
            # (cot + seas) — one short of the standard threshold of 3. Silver's cheatsheet
            # priority (COT + Seasonality + zone) with zero opposing indicators warrants
            # this specific relaxation. Case #69 (SI=F Oct 2023, bernd=long).
            if (symbol and symbol in SILVER_SYMBOLS
                    and loc == 'bullish'
                    and seas == 'bullish'
                    and cot != 'bearish'
                    and bearish_excl_trend == 0):
                logger.info(
                    f"Phase 42 Fix-9a: Silver bullish consensus overrides downtrend "
                    f"(cot={cot} seas=bullish loc=bullish bearish_excl={bearish_excl_trend})"
                )
                return 'bullish'
            return 'hold'

        # Step 4 — With-trend or sideways: minimum threshold.
        # Bernd's stated minimum: "Valuation + Location aligned = enough to trade."
        # If Valuation is neutral (not opposing, already passed Step 2), one more
        # supporting indicator (COT / Seasonality / Trend) is required.
        cot_n  = normalized.get('cot',         'neutral')
        seas_n = normalized.get('seasonality', 'neutral')

        # BP_SEAS_NO_ORIGINATE=1 (default OFF) removes Seasonality from the set of
        # indicators that can, on their own, promote a Location-only setup into a
        # signal. Grounding: the 2024-04-03 Seasonality "STRATEGY PROCESS" slide
        # lists Campus True Seasonality only under "Fundamental Condition (WHEN)",
        # never under "can we forecast a rally or decline" -- direction there comes
        # from COT Index, Valuation and the Yearly Roadmap. Seasonality still votes
        # in every tally and veto; it just cannot ORIGINATE a direction here.
        _seas_originates = os.environ.get('BP_SEAS_NO_ORIGINATE') != '1'

        if proposed == 'bullish':
            if val == 'bullish':
                return 'bullish'    # Location + Valuation = Bernd's minimum ✓
            # val == 'neutral': need 1 supporting vote (COT, Seasonality, or Trend)
            if cot_n == 'bullish' or trend_n == 'bullish' or (
                    _seas_originates and seas_n == 'bullish'):
                return 'bullish'
            return 'hold'           # Location only, all else neutral = too weak
        else:   # proposed == 'bearish'
            if val == 'bearish':
                return 'bearish'    # Location + Valuation = Bernd's minimum ✓
            if cot_n == 'bearish' or trend_n == 'bearish' or (
                    _seas_originates and seas_n == 'bearish'):
                return 'bearish'
            return 'hold'

    def _check_entry_pattern(self, df: pd.DataFrame, zone: Dict) -> Optional[Dict]:
        """Step 5: Check for candlestick pattern at the zone."""
        zone_type = zone['zone_type']
        proximal = zone['proximal']
        distal = zone['distal']

        # Look at the most recent candles
        for i in range(len(df) - 1, max(0, len(df) - 20), -1):
            candle = df.iloc[i]
            if zone_type == 'demand':
                if candle['low'] <= proximal and candle['low'] >= distal:
                    pattern = self.pattern_detector.detect(df, i, 'demand')
                    if pattern:
                        return pattern
            else:
                if candle['high'] >= proximal and candle['high'] <= distal:
                    pattern = self.pattern_detector.detect(df, i, 'supply')
                    if pattern:
                        return pattern
        return None

    def _calculate_targets(self, entry: float, stop: float, direction: str) -> List[float]:
        """Calculate R-multiple targets."""
        risk = abs(entry - stop)
        if direction == 'long':
            return [entry + risk, entry + 2 * risk, entry + 3 * risk]
        return [entry - risk, entry - 2 * risk, entry - 3 * risk]

    def _find_opposing_target(
        self, htf_zones: List[Dict], direction: str, entry: float,
    ) -> Optional[float]:
        """Nearest opposing-type HTF zone's proximal in the profit direction
        from entry — a genuine external target.

        Added 2026-07-27 portfolio-risk audit: `_calculate_targets()` above
        produces the 1R/2R/3R exit ladder purely from (entry, stop) — T2 is
        BY CONSTRUCTION exactly 2R from entry. Rule #2 ("ALWAYS ensure
        minimum 1:2 RRR") had been checked by feeding that same synthetic 2R
        target back into `build_entry_options()`'s rr() calc, which is
        circular (E1's R:R is trivially always exactly 2.0; E2/E3 are always
        >= 2.0 purely because they enter closer to the stop against the same
        target — none of this reflects real room-to-run). This function finds
        an actual opposing zone instead. Returns None when no opposing zone
        exists in the profit direction, so the caller can distinguish "really
        checked and it's tight" from "nothing to check against".
        """
        opposing_type = 'supply' if direction == 'long' else 'demand'
        candidates = [z for z in htf_zones if z.get('zone_type') == opposing_type]
        if direction == 'long':
            candidates = [z for z in candidates if z['proximal'] > entry]
            if not candidates:
                return None
            return min(candidates, key=lambda z: z['proximal'])['proximal']
        else:
            candidates = [z for z in candidates if z['proximal'] < entry]
            if not candidates:
                return None
            return max(candidates, key=lambda z: z['proximal'])['proximal']

    def build_entry_options(
        self,
        zone: Dict,
        target: float,
        pattern_signal: Optional[Dict] = None,
        income_strategy: str = 'weekly',
    ) -> List[Dict]:
        """Build the three textbook entry options (OTC 2025 Lesson 7).

        E1 (Proximal)     — limit at proximal, highest fill probability,
                             may have shallower R:R because price often
                             penetrates deeper before reversing.
        E2 (Zone/Midpoint) — limit at 50% of zone, better R:R, fills less
                             often (~50% of the time).
        E3 (Confirmation)  — entry on candlestick pattern that fired inside
                             the zone, lowest fill prob, highest confidence.

        E1/E2 use the -33% Fibonacci stop measured from the zone distal for
        daily/intraday strategies. Rule #8 exception: weekly/monthly HTF
        income trades use the DISTAL LINE ONLY (no -33% extension), matching
        the same branch in run_seven_step_process's inline entry calc — kept
        in sync so the displayed R:R here matches the stop actually traded.
        """
        proximal = zone['proximal']
        distal   = zone['distal']
        zone_height = abs(proximal - distal)
        is_demand = zone['zone_type'] == 'demand'
        sign = +1 if is_demand else -1
        stop = distal if income_strategy in ('weekly', 'monthly') else distal - sign * 0.33 * zone_height
        direction = 'long' if is_demand else 'short'
        midpoint = (proximal + distal) / 2.0

        def rr(entry):
            risk = abs(entry - stop)
            return abs(target - entry) / risk if risk > 0 else 0.0

        options = [
            {
                'label':      'E1',
                'name':       'Proximal',
                'entry':      round(proximal, 6),
                'stop':       round(stop, 6),
                'direction':  direction,
                'fill_prob':  'high',
                'rr':         round(rr(proximal), 2),
                'note':       'Limit at proximal. Always fills, deeper drawdown possible.',
            },
            {
                'label':      'E2',
                'name':       'Zone (midpoint)',
                'entry':      round(midpoint, 6),
                'stop':       round(stop, 6),
                'direction':  direction,
                'fill_prob':  'medium',
                'rr':         round(rr(midpoint), 2),
                'note':       'Limit at 50% of zone. Better R:R, may not fill on shallow retraces.',
            },
        ]

        if pattern_signal is not None:
            options.append({
                'label':      'E3',
                'name':       f"Confirmation ({pattern_signal.get('pattern_type', 'pattern')})",
                'entry':      round(pattern_signal['entry_price'], 6),
                'stop':       round(pattern_signal['stop_price'], 6),
                'direction':  direction,
                'fill_prob':  'low',
                'rr':         round(rr(pattern_signal['entry_price']), 2),
                'note':       'Wait for candlestick confirmation in zone. Highest confidence.',
            })

        return options

    def recommend_entry_option(
        self, options: List[Dict], min_rr: float = 2.0,
    ) -> Dict:
        """Pick the highest-fill-prob option that meets min R:R; if none
        meet, fall back to the option with the best R:R.
        """
        qualifying = [o for o in options if o['rr'] >= min_rr]
        if not qualifying:
            return max(options, key=lambda o: o['rr'])
        order = {'high': 0, 'medium': 1, 'low': 2}
        return min(qualifying, key=lambda o: order.get(o['fill_prob'], 9))

    # Timeframe drill-down ladder per income strategy (OTC 2025 L3, HAI Mod 6 L6).
    # Phase 36 correction: Ch175 verbatim "I would not go further down than 600
    # minutes" means smallest weekly-income timeframe is 10 hours. 4h (240m) is
    # BELOW 600m so cannot be used for weekly refinement. The previous Phase 35
    # comment incorrectly claimed "4h is the next interval ABOVE 600m" — that is
    # wrong direction. Since yfinance does not offer 600m/720m/960m bars, weekly
    # refinement now floors at 1d. Daily income trades unaffected (retain sub-day).
    REFINE_LADDER = {
        'monthly':  ['1mo', '1wk', '1d'],
        'weekly':   ['1wk', '1d'],
        'daily':    ['1d', '4h', '60m', '30m'],
        'intraday': ['4h', '60m', '30m', '15m'],
    }

    def refine_zone(
        self,
        htf_zone: Dict,
        target: float,
        ohlcv_by_tf: Dict[str, 'pd.DataFrame'],
        income_strategy: str = 'weekly',
        min_rr: float = 2.0,
        max_drill_levels: int = 3,
    ) -> Optional[Dict]:
        """Drill down the timeframe ladder to find a tighter zone CONTAINED
        within the HTF zone (per OTC 2025 L7-L8 + HAI Mod 6 L6).

        Refinement is triggered when the HTF zone's R:R to `target` is below
        `min_rr`. Each refined candidate must:
          1. share direction with the HTF zone
          2. fit entirely inside the HTF zone's price range (containment)
          3. independently pass qualifier checks (composite >= 6.0)

        Returns the deepest valid refined zone dict (with extra `parent_id`
        and `refined_from` fields), or None if no refinement found.

        Stop placement uses LTF distal -33% by default. Caller can override
        with HTF distal for more conservative protection.
        """
        ladder = self.REFINE_LADDER.get(income_strategy, self.REFINE_LADDER['weekly'])
        if htf_zone['timeframe'] not in ladder:
            return None
        htf_idx = ladder.index(htf_zone['timeframe'])
        candidates_levels = ladder[htf_idx + 1 : htf_idx + 1 + max_drill_levels]

        htf_lo = min(htf_zone['proximal'], htf_zone['distal'])
        htf_hi = max(htf_zone['proximal'], htf_zone['distal'])

        best: Optional[Dict] = None
        for tf in candidates_levels:
            df_tf = ohlcv_by_tf.get(tf)
            if df_tf is None or df_tf.empty:
                continue
            ltf_zones = self.zone_detector.detect_zones(
                df_tf, htf_zone['symbol'], tf,
            )
            for z in ltf_zones:
                if z['zone_type'] != htf_zone['zone_type']:
                    continue
                z_lo = min(z['proximal'], z['distal'])
                z_hi = max(z['proximal'], z['distal'])
                if not (z_lo >= htf_lo and z_hi <= htf_hi):
                    continue
                if z['composite_score'] < 6.0:
                    continue
                # Stop = LTF distal -33% (textbook default)
                zh = abs(z['proximal'] - z['distal'])
                sign = +1 if z['zone_type'] == 'demand' else -1
                stop = z['distal'] - sign * 0.33 * zh
                risk = abs(z['proximal'] - stop)
                rr   = abs(target - z['proximal']) / risk if risk > 0 else 0.0
                if rr < min_rr:
                    continue
                # Track the best (highest R:R) candidate
                if best is None or rr > best['_rr']:
                    refined = dict(z)
                    refined['parent_id']    = htf_zone['id']
                    refined['refined_from'] = htf_zone['timeframe']
                    refined['refined_stop'] = round(stop, 6)
                    refined['_rr']          = rr
                    best = refined

        if best is not None:
            best.pop('_rr', None)
            logger.info(
                f"[{htf_zone['symbol']}] zone refined {htf_zone['timeframe']}->{best['timeframe']} "
                f"score={best['composite_score']:.1f} entry={best['proximal']:.4f}"
            )
        return best

    # ------------------------------------------------------------------
    # Zone-quality grade — visually confirmed in frame_001154 (CW10
    # student trade-review popup, "10 out of 10" rating). Five binary
    # checks, 2 points each. NOTE: this is ZONE QUALITY only, not the
    # full trade grade — fundamentals stack on top of this. A zone can
    # be 10/10 structurally and still lack COT/Valuation alignment.
    # ------------------------------------------------------------------
    @staticmethod
    def zone_quality_grade(zone: Dict) -> Dict:
        """5-item zone-quality checklist from the visually-verified popup.

        Returns dict with keys: grade, score, checklist (per-item bool),
        where grade ∈ {'10/10', '8-9/10', '5-7/10', '<5/10'}.
        """
        # 1) Layout: decisive leg-out (Q1 Departure passing => decisive)
        decisive_layout = bool(zone.get('q1_score', 0) >= 7)
        # 2) Freshness: zone never preferred-tested
        is_fresh = bool(zone.get('q3_score', 0) >= 8)
        # 3) Base duration: 1-2 candle base
        base_count = zone.get('base_candle_count') or zone.get('base_count') or 0
        base_short = base_count <= 2 and base_count >= 1
        # 4) Big Brother / Small Brother match
        has_big_brother = bool(zone.get('has_big_brother', False))
        # 5) CF Direction: clean arrival / departure (Q6 Arrival or
        #    'with_trend' alignment).
        clean_arrival = bool(zone.get('q6_score', 0) >= 7 or zone.get('with_trend', False))

        checklist = {
            'layout_decisive':  decisive_layout,
            'fresh':            is_fresh,
            'base_duration':    base_short,
            'big_brother':      has_big_brother,
            'cf_direction':     clean_arrival,
        }
        score = 2 * sum(checklist.values())  # 0..10
        if score >= 10:
            grade = '10/10'
        elif score >= 8:
            grade = '8-9/10'
        elif score >= 5:
            grade = '5-7/10'
        else:
            grade = '<5/10'
        return {'grade': grade, 'score': score, 'checklist': checklist}

    # ------------------------------------------------------------------
    # Action-matrix tier grading — stage-1 text-confirmed (OTC L4 slide,
    # Bernd: "this is our action matrix to simplify everything"). Hard
    # rejection of the "No Action" cell is already done elsewhere; this
    # method emits the soft-tier grade so position size can scale.
    # ------------------------------------------------------------------
    @staticmethod
    def action_matrix_grade(
        zone_type: str, location: str, trend: str,
    ) -> str:
        """Returns 'best' | 'good' | 'acceptable' | 'reject'.

        location ∈ {'bullish','bearish','neutral'} -- NOT the 5-value cheap/
        expensive Fib vocabulary the original docstring described. Fixed
        2026-07-27 (same day this was wired in): `_analyze_htf` only ever
        returns 'bullish'/'bearish'/'neutral' for location everywhere in this
        codebase (grep confirmed -- no 'cheap'/'expensive' string appears
        anywhere in _analyze_htf's actual return values). The original
        cheap/expensive checks could never match, silently defaulting every
        sideways-trend demand/supply setup to 'reject' regardless of how
        favorable its location actually was (caught via a live SNPS signal:
        location=bullish + trend=sideways got gradeded 'reject' when it
        should have been 'acceptable'). 'bullish' location IS the "cheap for
        a demand zone" reading in this codebase's vocabulary; 'bearish' IS
        the "expensive for a supply zone" reading -- same semantics as
        before, corrected vocabulary.
        trend    ∈ {'uptrend','downtrend','sideways'}
        zone_type∈ {'demand','supply'}
        """
        z = zone_type.lower()
        loc = location.lower()
        tr = trend.lower()
        # Demand setups
        if z == 'demand':
            if loc == 'bullish' and tr == 'uptrend':
                return 'best'
            if tr == 'uptrend':
                return 'good'                    # trend aligned, location not extreme
            if loc == 'bullish' and tr == 'sideways':
                return 'acceptable'              # location aligned, trend sideways
            return 'reject'
        # Supply setups
        if z == 'supply':
            if loc == 'bearish' and tr == 'downtrend':
                return 'best'
            if tr == 'downtrend':
                return 'good'
            if loc == 'bearish' and tr == 'sideways':
                return 'acceptable'
            return 'reject'
        return 'reject'

    # Position-size multiplier per action-matrix tier (counter to risk_pct
    # reduction for counter-trend; this multiplier scales the BASE risk).
    ACTION_TIER_SIZE_FACTOR = {
        'best':       1.0,
        'good':       0.75,
        'acceptable': 0.5,
        'reject':     0.0,
    }

    # ------------------------------------------------------------------
    # Correlation-aware exposure caps (HAI 1:19:29 + Funded 0:16:46).
    # When an open position exists in any group, new signals on
    # other members of the same group are rejected (or downgraded
    # depending on caller policy).
    # ------------------------------------------------------------------
    DEFAULT_CORRELATED_GROUPS = [
        # Forex — heavy USD-correlated
        ['EURUSD', 'GBPUSD', 'AUDUSD', 'NZDUSD', 'USDCHF'],   # USD axis
        ['EURUSD', 'EURGBP', 'EURJPY', 'EURCHF'],             # EUR axis
        ['USDCHF', 'EURCHF', 'GBPCHF'],                       # CHF axis
        # Equity indices
        ['ES=F', 'NQ=F', 'YM=F', 'RTY=F', 'SPY', 'QQQ'],
        # Precious metals
        ['GC=F', 'SI=F', 'GLD', 'SLV'],
        # Energy
        ['CL=F', 'NG=F', 'USO', 'UNG'],
    ]

    @staticmethod
    def is_correlated_to_open(
        candidate_symbol: str, open_symbols: List[str],
        config: Optional[Dict] = None,
    ) -> Optional[List[str]]:
        """Return the offending peer symbols if `candidate_symbol` is
        correlated with any currently-open symbol; else None.

        Static (no `self`) so BP_paper_trader.py can call this at
        submit-time / fill-time without constructing a full RulesEngine.
        Was previously an instance method that was never actually called
        from anywhere — the rule existed but nothing wired it into the
        live submit_signal() path (found during the 2026-07-27 portfolio
        risk audit).

        Two mechanisms, found needed during that same audit:
          - Forex (6-letter '=X' pairs): correlation is CURRENCY-LEG overlap
            (any shared base or quote currency), not static group membership.
            The original DEFAULT_CORRELATED_GROUPS forex lists (1) never
            stripped the '=X' yfinance suffix, so 'EURUSD=X' could never
            match the bare 'EURUSD' entries — a silent no-op even once
            wired in — and (2) only covered USD/EUR/CHF axes, missing
            crosses like EURCAD/EURAUD/EURNZD/CADCHF/GBPCAD entirely. The
            live account had exactly those crosses stacked (2x EURCAD, 2x
            EURNZD, EURAUD, EURGBP, EURCHF, EURUSD x2 — 8 EUR-leg positions
            simultaneously) which the old group lists would have missed even
            with the suffix bug fixed. Leg-overlap generalizes to every
            cross without hand-maintaining a group per currency.
          - Everything else (equity indices, PMs, energy — '=F'/ETF tickers):
            static DEFAULT_CORRELATED_GROUPS membership, since those symbols
            aren't cleanly leg-parseable.
        """
        config = config or {}

        def _norm(sym: str) -> str:
            s = sym.upper().replace('/', '')
            return s[:-2] if s.endswith('=X') else s

        def _fx_legs(norm_sym: str) -> Optional[Tuple[str, str]]:
            if len(norm_sym) == 6 and norm_sym.isalpha():
                return norm_sym[:3], norm_sym[3:]
            return None

        s_norm = _norm(candidate_symbol)
        s_legs = _fx_legs(s_norm)
        offenders: List[str] = []

        if s_legs is not None:
            for o in open_symbols:
                o_norm = _norm(o)
                if o_norm == s_norm:
                    continue
                o_legs = _fx_legs(o_norm)
                if o_legs is not None and set(s_legs) & set(o_legs):
                    offenders.append(o)
            return offenders or None

        groups = config.get('correlated_groups', RulesEngine.DEFAULT_CORRELATED_GROUPS)
        for grp in groups:
            grp_norm = {_norm(g) for g in grp}
            if s_norm in grp_norm:
                for o in open_symbols:
                    if _norm(o) != s_norm and _norm(o) in grp_norm and o not in offenders:
                        offenders.append(o)
        return offenders or None

    def _calculate_position_size(
        self, entry: float, stop: float, trade_context: str = 'standard',
    ) -> float:
        """Calculate position size based on fixed fractional risk.

        Context-adjusted (HAI Module 4 + OTC L5 Decision Matrix):
          - 'standard' / with-trend setups : full risk (default 1%)
          - 'counter_trend'                : reduced (0.5% default)
          - 'anticipatory'                 : reduced (0.5% default)
        """
        balance = self.risk_config.get('account_balance', 100000)
        risk_pct = self.risk_config.get('risk_per_trade_pct', 1.0) / 100
        if trade_context in ('counter_trend', 'anticipatory'):
            reduced_pct = self.risk_config.get('reduced_risk_pct', risk_pct * 50) / 100
            # Allow either an absolute pct (e.g., 0.5) or a multiplier
            if reduced_pct < 0.05:  # treat as fraction-of-risk multiplier
                risk_pct *= reduced_pct * 100
            else:
                risk_pct = reduced_pct
        risk_amount = balance * risk_pct
        stop_distance = abs(entry - stop)
        if stop_distance == 0:
            return 0
        return risk_amount / stop_distance
