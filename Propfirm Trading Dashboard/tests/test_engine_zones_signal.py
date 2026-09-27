"""Zone formation, completed-bar handling and the engine -> paper-trader signal
contract (2026-09-27 fixes R1-R6), on synthetic OHLC frames.

Run from the dashboard folder:
    python -m pytest tests/test_engine_zones_signal.py -p no:cacheprovider -q
"""
import math
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import BP_rules_engine as re_mod                          # noqa: E402
from BP_rules_engine import RulesEngine                   # noqa: E402
from BP_zone_detector import ZoneDetector, completed_bars  # noqa: E402

ZD_CFG = {'leg_in_min_candles': 3, 'base_max_candles': 5, 'base_min_candles': 1,
          'leg_out_body_multiplier': 2.0}
ENGINE_CFG = {
    'zone_detection': ZD_CFG,
    'entry_distance': {'default_max_r': 3.0, 'max_r_to_entry_pending': {'weekly': 3.0},
                       'default_max_pct': 15.0, 'max_pct_to_entry': {'weekly': 15.0}},
    'risk': {'account_balance': 5000.0, 'risk_per_trade_pct': 1.0, 'reduced_risk_pct': 0.5},
    'stop_loss': {},
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Every BP_* switch at its default for each test."""
    for k in list(os.environ):
        if k.startswith('BP_'):
            monkeypatch.delenv(k, raising=False)


# --- synthetic candles -------------------------------------------------------
# Filler: alternating 20%-body candles (never a leg-in, never a leg-out).
def filler(n, px=100.0):
    return [(px, px + 0.6, px - 0.4, px + 0.2) if k % 2 == 0 else
            (px + 0.2, px + 0.6, px - 0.4, px) for k in range(n)]


LEG_IN = [(100.0, 100.9, 99.9, 100.6), (100.6, 101.5, 100.5, 101.2),
          (101.2, 102.1, 101.1, 101.8)]                     # 60% bullish bodies
BASE = [(101.8, 102.2, 101.5, 101.9), (101.9, 102.2, 101.6, 101.8)]  # indecisive
LEG_OUT = (101.8, 104.1, 101.7, 104.0)                      # 92% bullish, explosive
RALLY = [(104.0, 104.6, 103.9, 104.3), (104.3, 104.9, 104.2, 104.6),
         (104.6, 105.2, 104.5, 104.9), (104.9, 105.4, 104.8, 105.1)]
# RBR demand: proximal 101.9 (base body top), distal 101.5 (base low).
PROX, DIST = 101.9, 101.5


def decline(n, start=105.1, step=0.4):
    """55%-body bearish candles, overlapping (no gaps), never explosive."""
    rows, o = [], start
    for _ in range(n):
        c = o - step
        rows.append((o, o + 0.2, c - 0.13, c))
        o = c
    return rows


def frame(rows, incomplete_last=False, with_flag=True):
    ts = pd.date_range('2026-01-01', periods=len(rows), freq='D', tz='UTC')
    df = pd.DataFrame(rows, columns=['open', 'high', 'low', 'close'])
    df.insert(0, 'timestamp', ts)
    df['volume'] = 1000.0
    if with_flag:
        df['is_complete'] = True
        if incomplete_last:
            df.loc[df.index[-1], 'is_complete'] = False
    return df


def base_rows():
    """filler(30) + RBR + rally + decline to 102.3 (lows stay above the zone)."""
    return filler(30) + LEG_IN + BASE + [LEG_OUT] + RALLY + decline(7)


def rbr_zones(zones):
    return [z for z in zones if z['zone_type'] == 'demand'
            and z['formation'] == 'rally_base_rally']


# --- R1: completed bars only -------------------------------------------------

def test_completed_bars_helper(monkeypatch):
    df = frame(filler(5), incomplete_last=True)
    assert len(completed_bars(df)) == 4
    assert list(completed_bars(df).index) == [0, 1, 2, 3]      # labels preserved
    no_flag = df.drop(columns='is_complete')
    assert completed_bars(no_flag) is no_flag                  # missing column = all complete
    monkeypatch.setenv('BP_COMPLETED_BARS', '0')
    assert len(completed_bars(df)) == 5


def _inprogress_legout_rows():
    # 4-candle base so the leg-out can sit on the very last bar
    base4 = BASE + [(101.8, 102.2, 101.55, 101.85), (101.85, 102.2, 101.6, 101.8)]
    return filler(30) + LEG_IN + base4 + [LEG_OUT]


def test_no_zone_from_the_still_forming_leg_out(monkeypatch):
    zd = ZoneDetector(ZD_CFG)
    df = frame(_inprogress_legout_rows(), incomplete_last=True)
    assert rbr_zones(zd.detect_zones(df, 'T', '1d', legout_adjacent=True)) == []
    assert rbr_zones(zd.detect_zones(df, 'T', '1d')) == []
    # kill switch: the old behaviour built the zone on the unfinished candle
    monkeypatch.setenv('BP_COMPLETED_BARS', '0')
    z = rbr_zones(zd.detect_zones(df, 'T', '1d', legout_adjacent=True))
    assert len(z) == 1 and z[0]['origin_index'] == len(df) - 1


def _hammer_rows():
    # completed history, then a hammer that dips into the zone (low 101.6)
    return base_rows() + [(102.0, 102.05, 101.6, 102.02)]


def test_no_pattern_from_the_still_forming_bar():
    eng = RulesEngine(ENGINE_CFG)
    zone = {'zone_type': 'demand', 'proximal': PROX, 'distal': DIST}
    assert eng._check_entry_pattern(frame(_hammer_rows(), incomplete_last=True), zone) is None
    p = eng._check_entry_pattern(frame(_hammer_rows()), zone)
    assert p is not None and p['pattern_type'] == 'hammer'
    assert p['order_type'] == 'stop'                         # R3: E3b is a stop entry
    assert p['entry_price'] == pytest.approx(102.05 * 1.001, abs=1e-6)
    assert p['high_since'] is None                           # nothing after the pattern yet


def test_pattern_reports_extremes_after_the_pattern_bar():
    eng = RulesEngine(ENGINE_CFG)
    zone = {'zone_type': 'demand', 'proximal': PROX, 'distal': DIST}
    rows = _hammer_rows() + [(102.02, 102.3, 101.95, 102.1)]  # live bar trades through
    p = eng._check_entry_pattern(frame(rows, incomplete_last=True), zone)
    assert p['high_since'] == pytest.approx(102.3)
    ok, reason, _ = RulesEngine.entry_side_gate(
        'long', p['order_type'], p['entry_price'], p['stop_price'], 102.1,
        3.0, 15.0, high_since=p['high_since'], low_since=p['low_since'])
    assert not ok and 'missed stop entry' in reason


# --- R5: leg-out must follow the base ----------------------------------------

def test_opposite_decisive_candle_after_base_blocks_adjacent_zone():
    zd = ZoneDetector(ZD_CFG)
    drop = (101.8, 101.9, 100.9, 101.2)                       # 60% bearish, low 100.9
    jump = (101.2, 103.6, 101.1, 103.5)                       # 92% bullish
    rows = filler(30) + LEG_IN + BASE + [drop, jump] + RALLY + decline(4)
    df = frame(rows)

    legacy = rbr_zones(zd.detect_zones(df, 'T', '1d'))
    assert len(legacy) == 1
    z = legacy[0]
    # the decline through the base became part of the formation: distal widened
    assert z['distal'] == pytest.approx(100.9)
    # ... so the Q3 window (after the leg-out) never saw it as a test ...
    assert z['freshness_score'] == 10.0
    # ... but R4 measures from the base end and marks it broken
    assert z['invalidated_25pct'] is True and z['trade_usable'] is False

    assert rbr_zones(zd.detect_zones(df, 'T', '1d', legout_adjacent=True)) == []


def test_one_decisive_same_direction_candle_before_explosive_is_allowed():
    zd = ZoneDetector(ZD_CFG)
    step = (101.8, 102.5, 101.7, 102.3)                       # 62% bullish decisive
    jump = (102.3, 104.6, 102.2, 104.5)                       # explosive
    rows = filler(30) + LEG_IN + BASE + [step, jump] + RALLY + decline(4, start=105.1)
    df = frame(rows)
    z = rbr_zones(zd.detect_zones(df, 'T', '1d', legout_adjacent=True))
    assert len(z) == 1
    # distal = base low; the decisive first leg-out candle (low 101.7) is part of
    # the leg-out and does not count as a test of the zone
    assert z[0]['distal'] == pytest.approx(DIST) and z[0]['trade_usable']
    assert z[0]['origin_index'] == 30 + 3 + 2 + 1             # the explosive candle

    # two decisive candles before the explosive one: too far from the base
    rows2 = filler(30) + LEG_IN + BASE + [step, (102.3, 103.0, 102.2, 102.8), jump] \
        + RALLY + decline(4)
    assert rbr_zones(zd.detect_zones(frame(rows2), 'T', '1d', legout_adjacent=True)) == []


# --- R4: penetrated / consumed zones are not trade zones ---------------------

def test_penetrated_zone_is_not_a_trade_zone(monkeypatch):
    dip = (104.0, 104.1, 101.75, 103.9)            # low 101.75 < 25% line 101.8
    rows = filler(30) + LEG_IN + BASE + [LEG_OUT, dip] + RALLY[1:] + decline(7)
    zd = ZoneDetector(ZD_CFG)
    z = rbr_zones(zd.detect_zones(frame(rows), 'T', '1d', legout_adjacent=True))[0]
    assert z['invalidated_25pct'] and not z['trade_usable']
    assert zd.filter_trade_zones([z]) == []
    monkeypatch.setenv('BP_HARD_INVALIDATE_25', '0')
    assert ZoneDetector(ZD_CFG).filter_trade_zones([z]) == [z]


def test_twice_preferred_tested_zone_is_consumed():
    # two closes below the proximal, both inside the top 25% of the zone
    tests = [(102.2, 102.3, 101.85, 101.88), (101.88, 102.0, 101.86, 101.89)]
    rows = filler(30) + LEG_IN + BASE + [LEG_OUT] + RALLY + decline(6) + tests + decline(3, 103.4, 0.3)
    zd = ZoneDetector(ZD_CFG)
    z = rbr_zones(zd.detect_zones(frame(rows), 'T', '1d', legout_adjacent=True))[0]
    assert not z['invalidated_25pct']
    assert z['consumed'] and not z['trade_usable']


# --- R6: zone ids do not move ------------------------------------------------

def test_zone_id_stable_when_a_live_bar_is_appended():
    zd = ZoneDetector(ZD_CFG)
    done = frame(base_rows())
    live = frame(base_rows() + [(102.3, 102.6, 101.0, 101.2)], incomplete_last=True)
    ids = lambda d: sorted(z['id'] for z in zd.detect_zones(d, 'T', '1d', legout_adjacent=True))
    assert ids(done) and ids(done) == ids(live)


def test_zone_id_uses_dates_when_frame_is_date_indexed():
    zd = ZoneDetector(ZD_CFG)
    df = frame(base_rows(), with_flag=False).set_index('timestamp')
    a = rbr_zones(zd.detect_zones(df, 'T', '1d'))[0]
    b = rbr_zones(zd.detect_zones(df.iloc[2:], 'T', '1d'))[0]  # window slid by 2 bars
    assert a['origin_time'].startswith('2026-02-0')
    assert a['id'] == b['id']


# --- run_seven_step_process: the signal contract -----------------------------

class _NoBlackout:
    in_blackout = False
    risk_multiplier = 1.0

    def to_dict(self):
        return {'in_blackout': False}


class _Cal:
    def check_blackout(self, *a, **k):
        return _NoBlackout()


@pytest.fixture
def engine(monkeypatch):
    eng = RulesEngine(ENGINE_CFG)
    seen = {}
    monkeypatch.setattr(re_mod, 'get_calendar', lambda: _Cal())
    monkeypatch.setattr(eng, '_analyze_htf', lambda *a, **k: {
        'location': 'bullish', 'trend': 'uptrend', 'location_pct': 20.0,
        'location_source': 'zones', 'in_equilibrium': False})
    monkeypatch.setattr(eng, '_analyze_fundamentals', lambda *a, **k: {
        'cot': 'neutral', 'cot_strength': 'none', 'valuation': 'bullish',
        'seasonality': 'neutral', 'constituent': 'neutral'})

    def _consensus(biases, strategy, **k):
        seen['zone_composite'] = k.get('zone_composite')
        return 'bullish'
    monkeypatch.setattr(eng, '_bias_consensus', _consensus)
    eng._seen = seen
    return eng


def run(eng, df):
    return eng.run_seven_step_process(
        symbol='TEST', ohlcv_data={'1wk': df, '1d': df}, cot_df=pd.DataFrame(),
        valuation_refs={}, seasonal_df=pd.DataFrame(), htf='1wk', ltf='1d',
        income_strategy='weekly', asset_class='forex')


def _with_live(close, low=None):
    low = close - 0.1 if low is None else low
    return frame(base_rows() + [(102.3, max(102.4, close + 0.05), low, close)],
                 incomplete_last=True)


def test_signal_contract_fields(engine):
    sig = run(engine, _with_live(102.5))
    assert sig is not None
    assert sig['entry_type'] == 'E1' and sig['order_type'] == 'limit'
    assert sig['pending_order'] is True and sig['price_at_zone'] is False
    assert sig['entry_price'] == pytest.approx(PROX) and sig['stop_price'] == pytest.approx(DIST)
    assert sig['current_price'] == pytest.approx(102.5)      # the live bar's close
    assert sig['setup_key'] == 'TEST|long|101.9|101.5'
    t = datetime.fromisoformat(sig['signal_time'])
    assert t.utcoffset().total_seconds() == 0
    assert sig['entry_gate']['r_away'] == pytest.approx(1.5)


@pytest.mark.parametrize('close,low', [
    (101.592, 101.55),     # 77% of the way from entry to stop
    (101.45, 101.40),      # beyond the stop
])
def test_signal_rejected_when_price_is_through_the_zone(engine, close, low):
    assert run(engine, _with_live(close, low)) is None


def test_signal_rejected_on_nan_price(engine):
    df = _with_live(102.5)
    df.loc[df.index[-1], 'close'] = np.nan
    assert run(engine, df) is None


def test_legacy_gate_kill_switch_restores_old_acceptance(engine, monkeypatch):
    monkeypatch.setenv('BP_ENTRY_SIDE_GATE', '0')
    sig = run(engine, _with_live(101.45, 101.40))           # below the stop, 1.1R "away"
    assert sig is not None and sig['pending_order'] is True


def test_penetrated_zone_not_traded_and_bias_input_unchanged(engine, monkeypatch):
    dip = (104.0, 104.1, 101.75, 103.9)
    rows = filler(30) + LEG_IN + BASE + [LEG_OUT, dip] + RALLY[1:] + decline(7) \
        + [(102.3, 102.6, 102.2, 102.5)]
    df = frame(rows, incomplete_last=True)
    assert run(engine, df) is None
    composite_on = engine._seen['zone_composite']
    monkeypatch.setenv('BP_HARD_INVALIDATE_25', '0')
    monkeypatch.setenv('BP_LEGOUT_ADJACENT', '0')
    engine.zone_detector = ZoneDetector(ZD_CFG)               # re-read the switches
    assert run(engine, df) is not None
    assert engine._seen['zone_composite'] == composite_on     # consensus input unchanged


def _far_and_near_zone_rows():
    """An old fresh RBR 50 points below (price never came back), a slow rally with
    no zones, then the near RBR at 101.9 -- equal composites, old one ranks first."""
    shift = lambda rows, d: [tuple(v - d for v in r) for r in rows]
    old = filler(30, 50.0) + shift(LEG_IN + BASE + [LEG_OUT], 50.0)
    rally, o = [], 54.0
    while o < 99.4:
        rally.append((o, o + 1.3, o - 0.1, o + 0.6))          # 43% bodies
        o += 0.6
    return old + rally + filler(12) + LEG_IN + BASE + [LEG_OUT] + RALLY + decline(7) \
        + [(102.3, 102.6, 102.2, 102.5)]


def test_trade_zone_is_the_reachable_one(engine, monkeypatch):
    df = frame(_far_and_near_zone_rows(), incomplete_last=True)
    usable = [z for z in engine.zone_detector.filter_trade_zones(
        engine.zone_detector.rank_zones(engine.zone_detector.detect_zones(
            df, 'TEST', '1d', trend='uptrend', legout_adjacent=True), min_score=4.0))]
    assert usable[0]['proximal'] == pytest.approx(PROX - 50.0)   # far zone ranks first
    sig = run(engine, df)
    assert sig is not None and sig['entry_price'] == pytest.approx(PROX)
    monkeypatch.setenv('BP_TRADE_ZONE_REACHABLE', '0')        # old pick: far zone, gated out
    assert run(engine, df) is None
