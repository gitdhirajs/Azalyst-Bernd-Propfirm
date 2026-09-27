"""Entry-side gate math (RulesEngine.entry_side_gate), 2026-09-27 defects 3, 4, 8.

Run from the dashboard folder:
    python -m pytest tests/test_engine_gate.py -p no:cacheprovider -q
"""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from BP_rules_engine import RulesEngine  # noqa: E402

gate = RulesEngine.entry_side_gate
WEEKLY = dict(max_r=3.0, max_pct=15.0)    # BP_config.yaml entry_distance, weekly


# --- the live-account cases -------------------------------------------------

def test_nzdusd_long_price_beyond_stop_rejected():
    # Live: NZDUSD long E=0.578599 SL=0.574267 was "filled" with price at 0.57297,
    # already below the stop. The old abs() gate saw 1.3R / 0.97% and passed it.
    ok, reason, _ = gate('long', 'limit', 0.578599, 0.574267, 0.57297, **WEEKLY)
    assert not ok
    assert 'beyond the stop' in reason


def test_nzdusd_passes_the_legacy_gate():
    # Documents the defect and the kill switch: BP_ENTRY_SIDE_GATE=0 -> legacy=True.
    ok, _, m = gate('long', 'limit', 0.578599, 0.574267, 0.57297, legacy=True, **WEEKLY)
    assert ok
    assert m['r_away'] == pytest.approx(1.2994, abs=1e-3)


def test_usdchf_short_77pct_into_zone_rejected():
    # Live: USDCHF short E=0.805274 SL=0.817997, price 0.81504 = 77% of the way
    # from entry to stop -- the zone was being broken, not tested.
    ok, reason, m = gate('short', 'limit', 0.805274, 0.817997, 0.81504, **WEEKLY)
    assert not ok
    assert m['penetration'] == pytest.approx(0.7676, abs=1e-3)
    assert '77%' in reason


# --- limit orders (E1/E2) ----------------------------------------------------

def test_long_limit_price_one_pct_above_entry_accepted():
    ok, reason, m = gate('long', 'limit', 1.0000, 0.9800, 1.0100, **WEEKLY)
    assert ok, reason
    assert m['r_away'] == pytest.approx(0.5)
    assert m['pct_away'] == pytest.approx(0.990, abs=1e-3)
    assert m['penetration'] == pytest.approx(-0.5)


def test_long_limit_penetration_boundary():
    # 20% through the entry -> still a test of the zone; distance cap is not
    # charged for the penetration side.
    ok, _, m = gate('long', 'limit', 1.0, 0.9, 0.98, **WEEKLY)
    assert ok and m['r_away'] == 0.0 and m['penetration'] == pytest.approx(0.2)
    # exactly 25% is allowed, 30% is not
    assert gate('long', 'limit', 1.0, 0.9, 0.975, **WEEKLY)[0]
    assert not gate('long', 'limit', 1.0, 0.9, 0.97, **WEEKLY)[0]


def test_short_limit_mirror():
    assert gate('short', 'limit', 1.0, 1.1, 0.99, **WEEKLY)[0]          # approach side
    assert gate('short', 'limit', 1.0, 1.1, 1.02, **WEEKLY)[0]          # 20% through
    assert not gate('short', 'limit', 1.0, 1.1, 1.03, **WEEKLY)[0]      # 30% through
    assert not gate('short', 'limit', 1.0, 1.1, 1.10, **WEEKLY)[0]      # at the stop


def test_limit_caps_are_directional():
    # 4R above a long limit -> too far on the approach side.
    ok, reason, m = gate('long', 'limit', 1.0, 0.99, 1.04, **WEEKLY)
    assert not ok and 'too far' in reason and m['r_away'] == pytest.approx(4.0)
    # % cap: a wide zone 3R but 20% away
    ok, reason, m = gate('long', 'limit', 100.0, 90.0, 120.0, max_r=3.0, max_pct=15.0)
    assert not ok and m['pct_away'] == pytest.approx(16.667, abs=1e-3)


# --- stop orders (E3b) -------------------------------------------------------

def test_long_stop_price_below_entry_is_pending():
    ok, reason, m = gate('long', 'stop', 1.0, 0.98, 0.995, **WEEKLY)
    assert ok, reason
    assert m['r_away'] == pytest.approx(0.25)


def test_long_stop_price_above_entry_rejected_missed():
    ok, reason, _ = gate('long', 'stop', 1.0, 0.98, 1.002, **WEEKLY)
    assert not ok and 'missed stop entry' in reason
    # exactly at the trigger is also "already triggered"
    assert not gate('long', 'stop', 1.0, 0.98, 1.0, **WEEKLY)[0]


def test_long_stop_already_triggered_by_a_later_bar_rejected():
    # price is back below the buy-stop, but a bar after the pattern traded through it
    ok, reason, _ = gate('long', 'stop', 1.0, 0.98, 0.995, high_since=1.001, **WEEKLY)
    assert not ok and 'triggered by a bar after the pattern' in reason
    assert gate('long', 'stop', 1.0, 0.98, 0.995, high_since=0.999, **WEEKLY)[0]


def test_short_stop_mirror():
    assert gate('short', 'stop', 1.0, 1.02, 1.005, **WEEKLY)[0]
    assert not gate('short', 'stop', 1.0, 1.02, 0.999, **WEEKLY)[0]
    assert not gate('short', 'stop', 1.0, 1.02, 1.005, low_since=0.998, **WEEKLY)[0]


def test_stop_order_below_its_stop_loss_rejected():
    ok, reason, _ = gate('long', 'stop', 1.0, 0.98, 0.979, **WEEKLY)
    assert not ok and 'beyond the stop' in reason


# --- validation --------------------------------------------------------------

@pytest.mark.parametrize('px', [float('nan'), float('inf'), None])
def test_non_finite_price_rejected(px):
    ok, reason, _ = gate('long', 'limit', 1.0, 0.98, px, **WEEKLY)
    assert not ok
    # legacy mode rejects it too (NaN guard is not part of the kill switch)
    assert not gate('long', 'limit', 1.0, 0.98, px, legacy=True, **WEEKLY)[0]


def test_stop_on_wrong_side_or_zero_risk_rejected():
    assert not gate('long', 'limit', 1.0, 1.01, 1.02, **WEEKLY)[0]
    assert not gate('short', 'limit', 1.0, 0.99, 0.98, **WEEKLY)[0]
    assert not gate('long', 'stop', 1.0, 1.0, 0.99, **WEEKLY)[0]


def test_metrics_always_finite():
    for args in [('long', 'limit', 1.0, 0.98, 1.01), ('short', 'stop', 1.0, 1.02, 1.005),
                 ('long', 'limit', 1.0, 1.0, 1.0)]:
        _, _, m = gate(*args, **WEEKLY)
        assert all(math.isfinite(v) for v in m.values())
