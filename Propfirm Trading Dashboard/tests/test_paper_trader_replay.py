"""Tests for PaperTrader.replay_bars (2026-09-27 execution-layer fixes).

Run from the dashboard folder:
    python -m pytest tests -p no:cacheprovider -q
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import BP_paper_trader as pt                                    # noqa: E402
from BP_paper_trader import PaperTrader, TradeStatus, make_setup_key  # noqa: E402

UTC = timezone.utc


def cfg(**risk):
    r = {"max_open_positions": 20, "correlation_check_enabled": False,
         "pending_order_max_age_days": {"weekly": 14, "daily": 5, "monthly": 30, "intraday": 2}}
    r.update(risk)
    return {
        "prop_firm": {"enabled": True, "account_size": 5000.0,
                      "max_daily_loss_usd": 150.0, "max_total_loss_usd": 300.0,
                      "daily_reset_hour_utc": 22},
        "risk": r,
        "stop_loss": {"breakeven_at_half_target": True},
        "entry_distance": {"default_max_r": 3.0, "max_r_to_entry_pending": {"weekly": 3.0},
                           "default_max_pct": 15.0, "max_pct_to_entry": {"weekly": 15.0}},
    }


def bars(start, rows, freq="h"):
    """rows = [(open, high, low, close), ...] as consecutive 1h bars from `start`."""
    ts = pd.date_range(pd.Timestamp(start), periods=len(rows), freq=freq, tz="UTC")
    o, h, l, c = zip(*rows)
    return pd.DataFrame({"timestamp": ts, "open": o, "high": h, "low": l, "close": c,
                         "volume": [100] * len(rows)})


def signal(symbol="EURUSD=X", direction="long", entry=1.1000, stop=1.0950,
           targets=(1.1050, 1.1100, 1.1150), size=10000.0, risk=50.0,
           signal_time="2026-07-30T10:30:00+00:00", order_type="limit", **kw):
    s = {"symbol": symbol, "direction": direction, "entry_price": entry,
         "stop_price": stop, "targets": list(targets), "position_size": size,
         "risk_amount": risk, "signal_time": signal_time, "order_type": order_type,
         "income_strategy": "weekly", "zone_id": kw.pop("zone_id", f"z-{symbol}-{entry}"),
         "pending_order": True, "price_at_zone": False}
    s.update(kw)
    return s


@pytest.fixture(autouse=True)
def _default_env(monkeypatch):
    for k in ("BP_BAR_REPLAY", "BP_PENDING_DISTANCE_RECHECK", "BP_STOP_ORDER_INVALIDATE",
              "BP_SETUP_KEY_DEDUP", "BP_TYPE_LADDERS"):
        monkeypatch.delenv(k, raising=False)


def hist(trader, pid):
    return next(p for p in trader.trade_history if p.id == pid)


# ------------------------------------------------------------------ submit
def test_submit_is_always_pending_even_at_zone():
    t = PaperTrader(cfg())
    pid = t.submit_signal(signal(price_at_zone=True, pending_order=False))
    p = t.positions[pid]
    assert p.status == TradeStatus.PENDING
    assert p.placed_at == datetime(2026, 7, 30, 10, 30, tzinfo=UTC)
    assert p.order_type == "limit"
    assert p.setup_key == make_setup_key("EURUSD=X", "long", 1.1, 1.095)


def test_kill_switch_restores_immediate_fill_and_disables_replay(monkeypatch):
    monkeypatch.setenv("BP_BAR_REPLAY", "0")
    t = PaperTrader(cfg())
    pid = t.submit_signal(signal(price_at_zone=True, pending_order=True))
    assert t.positions[pid].status == TradeStatus.ACTIVE
    ev = t.replay_bars("EURUSD=X", bars("2026-07-30T11:00Z", [(1.09, 1.09, 1.08, 1.085)]))
    assert ev == {"fills": [], "closed": [], "cancelled": []}
    assert t.positions[pid].status == TradeStatus.ACTIVE


# ------------------------------------------------------------------ fills
def test_fill_ignores_bars_that_started_before_placement():
    t = PaperTrader(cfg())
    pid = t.submit_signal(signal(signal_time="2026-07-30T10:30:00Z"))
    # 09:00 and 10:00 bars trade through the entry, but began before the order
    # existed (the 10:00 bar CONTAINS the placement: conservative -> ignored).
    b = bars("2026-07-30T09:00Z", [(1.102, 1.103, 1.098, 1.102),
                                   (1.102, 1.103, 1.098, 1.102),
                                   (1.102, 1.103, 1.1005, 1.102)])
    ev = t.replay_bars("EURUSD=X", b)
    assert ev["fills"] == []
    assert t.positions[pid].status == TradeStatus.PENDING
    assert t.positions[pid].last_priced_ts == datetime(2026, 7, 30, 12, tzinfo=UTC)


def test_limit_and_stop_fill_in_opposite_directions():
    t = PaperTrader(cfg())
    lim = t.submit_signal(signal(symbol="EURUSD=X", entry=1.1000, stop=1.0950))
    stp = t.submit_signal(signal(symbol="GBPUSD=X", entry=1.3000, stop=1.2950,
                                 targets=(1.305, 1.31, 1.315), order_type="stop"))
    # Price DROPS through both entries: only the limit may fill. The buy-stop is
    # below price-trading-down territory -- the old code "filled" it here (defect 4).
    down = {"EURUSD=X": bars("2026-07-30T11:00Z", [(1.1010, 1.1012, 1.0990, 1.0995)]),
            "GBPUSD=X": bars("2026-07-30T11:00Z", [(1.2990, 1.2995, 1.2970, 1.2980)])}
    ev = t.replay_bars_multi(down)
    assert [f["position_id"] for f in ev["fills"]] == [lim]
    assert t.positions[lim].status == TradeStatus.ACTIVE
    assert t.positions[stp].status == TradeStatus.PENDING
    # Price RISES through the buy-stop: now it fills.
    ev = t.replay_bars("GBPUSD=X", bars("2026-07-30T12:00Z", [(1.2985, 1.3010, 1.2980, 1.3005)]))
    assert [f["position_id"] for f in ev["fills"]] == [stp]
    assert t.positions[stp].fill_price == pytest.approx(1.3000)


def test_short_limit_and_short_stop():
    t = PaperTrader(cfg())
    sl = t.submit_signal(signal(symbol="USDJPY=X", direction="short", entry=150.0, stop=151.0,
                                targets=(149.0, 148.0, 147.0), size=700.0))
    ss = t.submit_signal(signal(symbol="CHFJPY=X", direction="short", entry=180.0, stop=181.0,
                                targets=(179.0, 178.0, 177.0), size=700.0, order_type="stop"))
    ev = t.replay_bars_multi({
        "USDJPY=X": bars("2026-07-30T11:00Z", [(149.8, 150.05, 149.7, 149.9)]),   # up to entry
        "CHFJPY=X": bars("2026-07-30T11:00Z", [(180.2, 180.3, 179.95, 180.0)]),   # down to entry
    })
    assert {f["position_id"] for f in ev["fills"]} == {sl, ss}
    assert t.positions[sl].fill_price == pytest.approx(150.0)
    assert t.positions[ss].fill_price == pytest.approx(180.0)


def test_gap_fills_at_the_open():
    t = PaperTrader(cfg())
    lim = t.submit_signal(signal(symbol="EURUSD=X", entry=1.1000, stop=1.0950))
    stp = t.submit_signal(signal(symbol="GBPUSD=X", entry=1.3000, stop=1.2950,
                                 targets=(1.305, 1.31, 1.315), order_type="stop"))
    t.replay_bars_multi({
        # opens BELOW the buy-limit: fills at the better open
        "EURUSD=X": bars("2026-07-30T11:00Z", [(1.0980, 1.0990, 1.0970, 1.0985)]),
        # opens ABOVE the buy-stop: fills at the worse open
        "GBPUSD=X": bars("2026-07-30T11:00Z", [(1.3020, 1.3030, 1.3010, 1.3025)]),
    })
    assert t.positions[lim].fill_price == pytest.approx(1.0980)
    assert t.positions[stp].fill_price == pytest.approx(1.3020)
    assert t.positions[lim].entry_price == pytest.approx(1.1000)   # order level kept


def test_fill_bar_that_also_hits_stop_is_a_loss():
    t = PaperTrader(cfg())
    pid = t.submit_signal(signal(entry=1.1000, stop=1.0950))
    # One bar trades through the entry AND the stop (and also up to T1).
    ev = t.replay_bars("EURUSD=X", bars("2026-07-30T11:00Z", [(1.1010, 1.1060, 1.0940, 1.0960)]))
    assert len(ev["fills"]) == 1 and len(ev["closed"]) == 1
    p = hist(t, pid)
    assert p.status == TradeStatus.CLOSED and p.close_reason == "stop"
    assert p.close_price == pytest.approx(1.0950)
    assert p.realized_pnl == pytest.approx(-50.0)
    assert p.trade_r_multiple == pytest.approx(-1.0)
    assert p.close_time == datetime(2026, 7, 30, 11, tzinfo=UTC)
    assert t.balance == pytest.approx(4950.0)


# ------------------------------------------------------------------ active
def _filled_long(t, **kw):
    pid = t.submit_signal(signal(**kw))
    t.replay_bars("EURUSD=X", bars("2026-07-30T11:00Z", [(1.1005, 1.1008, 1.0998, 1.1003)]))
    assert t.positions[pid].status == TradeStatus.ACTIVE
    return pid


def test_stop_wins_when_bar_reaches_stop_and_target():
    t = PaperTrader(cfg())
    pid = _filled_long(t)
    ev = t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [(1.1003, 1.1160, 1.0940, 1.1000)]))
    p = hist(t, pid)
    assert p.close_reason == "stop" and p.close_price == pytest.approx(1.0950)
    assert not p.partial_taken
    assert ev["closed"][0]["r_multiple"] == pytest.approx(-1.0)


def test_gap_through_stop_exits_at_open():
    t = PaperTrader(cfg())
    pid = _filled_long(t)
    t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [(1.0930, 1.0940, 1.0920, 1.0935)]))
    p = hist(t, pid)
    assert p.close_price == pytest.approx(1.0930)
    assert p.realized_pnl == pytest.approx((1.0930 - 1.1000) * 10000)


def test_breakeven_armed_on_bar_k_applies_from_bar_k_plus_1_chfjpy_2026_07_30():
    """CHFJPY 2026-07-30 (defect 6 reproduction).

    Short limit filled when a HIGH touched the entry at 23:00 on 29 Jul; the
    half-T1 breakeven level was reached at 13:00 on 30 Jul. The old path saw a
    single daily bar containing both the entry-touching high and the BE-level
    low: it armed breakeven from the low and then "hit" the stop-at-entry with
    the high of the SAME bar -> a winning trade scratched at $0. With bars
    replayed in order the trade must NOT be scratched.
    """
    t = PaperTrader(cfg())
    pid = t.submit_signal(signal(symbol="CHFJPY=X", direction="short", entry=185.00,
                                 stop=186.00, targets=(184.00, 183.00, 182.00),
                                 size=1.0 / 150 * 100000 * 0.07, risk=46.7,
                                 signal_time="2026-07-29T20:00:00Z"))
    rows = [(184.80, 185.00, 184.75, 184.90)]                    # 23:00 fill (high = entry)
    rows += [(184.90 - 0.01 * i, 184.95 - 0.01 * i, 184.70 - 0.01 * i, 184.85 - 0.01 * i)
             for i in range(13)]                                 # 00:00..12:00, highs < entry
    rows += [(184.62, 185.00, 184.45, 184.55)]                   # 13:00: low <= 184.50 AND high = entry
    rows += [(184.55, 184.80, 184.30, 184.40),                   # 14:00..16:00 below entry
             (184.40, 184.60, 184.20, 184.30),
             (184.30, 184.50, 184.10, 184.20)]
    b = bars("2026-07-29T23:00Z", rows)
    ev = t.replay_bars("CHFJPY=X", b)
    assert len(ev["fills"]) == 1 and ev["fills"][0]["filled_at"].startswith("2026-07-29T23:00")
    assert ev["closed"] == []                                    # NOT scratched
    p = t.positions[pid]
    assert p.status == TradeStatus.ACTIVE
    assert p.breakeven_triggered and p.current_stop == pytest.approx(185.00)
    # The next bar that trades back to entry DOES take the breakeven stop.
    ev = t.replay_bars("CHFJPY=X", bars("2026-07-30T17:00Z", [(184.30, 185.10, 184.25, 185.05)]))
    p = hist(t, pid)
    assert p.close_reason == "breakeven" and p.realized_pnl == pytest.approx(0.0)
    assert t.scratch_trades == 1


def test_legacy_single_daily_bar_scratches_the_same_chfjpy_trade():
    """Documents the old behaviour the test above guards against."""
    t = PaperTrader(cfg())
    pid = t.submit_signal(signal(symbol="CHFJPY=X", direction="short", entry=185.00,
                                 stop=186.00, targets=(184.00, 183.00, 182.00), size=466.7,
                                 signal_time="2026-07-29T20:00:00Z"))
    t.positions[pid].status = TradeStatus.ACTIVE      # filled at 23:00 in the old path too
    t.positions[pid].fill_price = 185.00
    daily = {"CHFJPY=X": {"high": 185.00, "low": 184.10, "close": 184.20,
                          "bid": 184.20, "ask": 184.20}}
    closed = t.update_positions(daily)
    assert closed and closed[0]["close_reason"] == "breakeven"


def test_t2_partial_then_trail_reports_blended_r():
    t = PaperTrader(cfg())
    pid = _filled_long(t)                                # limit filled at 1.1000
    b = bars("2026-07-30T12:00Z", [
        (1.1003, 1.1105, 1.1000, 1.1100),   # T1 + T2 on this bar: BE/partial, trail from next bar
        (1.1100, 1.1110, 1.1060, 1.1070),   # trail stop = T1 level 1.1050 not hit
        (1.1070, 1.1075, 1.1040, 1.1045),   # hits trail 1.1050
    ])
    ev = t.replay_bars("EURUSD=X", b)
    p = hist(t, pid)
    assert p.partial_taken and p.partial_price == pytest.approx(1.1100)
    assert p.close_reason == "trail" and p.close_price == pytest.approx(1.1050)
    exp_pnl = (1.1100 - 1.1000) * 5000 + (1.1050 - 1.1000) * 5000     # $50 + $25
    assert p.realized_pnl == pytest.approx(exp_pnl)
    assert p.trade_r_multiple == pytest.approx(1.5)                  # not the runner's +1.0
    assert ev["closed"][0]["close_reason"] == "trail"


def test_t3_closes_remainder():
    t = PaperTrader(cfg())
    pid = _filled_long(t)
    t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [(1.1003, 1.1160, 1.1001, 1.1150)]))
    p = hist(t, pid)
    assert p.close_reason == "T3" and p.close_price == pytest.approx(1.1150)
    assert p.realized_pnl == pytest.approx((1.11 - 1.1) * 5000 + (1.115 - 1.1) * 5000)
    assert p.trade_r_multiple == pytest.approx(2.5)                  # not a flat 3.0


# ------------------------------------------------------------------ time
def test_weekend_no_bars_nothing_happens():
    t = PaperTrader(cfg())
    pid = _filled_long(t)
    before = (t.positions[pid].current_stop, t.positions[pid].last_priced_ts, t.balance)
    empty = bars("2026-08-01T00:00Z", [(1, 1, 1, 1)]).iloc[0:0]
    for df in (empty, None):
        ev = t.replay_bars("EURUSD=X", df)
        assert ev == {"fills": [], "closed": [], "cancelled": []}
    p = t.positions[pid]
    assert (p.current_stop, p.last_priced_ts, t.balance) == before


def test_non_finite_bars_are_skipped():
    t = PaperTrader(cfg())
    pid = t.submit_signal(signal())
    nan = float("nan")
    t.replay_bars("EURUSD=X", bars("2026-07-30T11:00Z", [(nan, nan, nan, nan)]))
    assert t.positions[pid].status == TradeStatus.PENDING
    assert t.positions[pid].last_priced_ts is None


def test_pending_expires_by_bar_time_not_wall_clock():
    t = PaperTrader(cfg())
    pid = t.submit_signal(signal(signal_time="2026-07-01T00:30:00Z"))   # weekly: 14d
    # Price stays far above the entry (but inside the drift caps) for 15 days.
    rows = [(1.1030, 1.1040, 1.1020, 1.1030)] * (15 * 24)
    ev = t.replay_bars("EURUSD=X", bars("2026-07-01T01:00Z", rows))
    p = hist(t, pid)
    assert p.status == TradeStatus.CANCELLED and p.close_reason == "expired"
    assert p.close_time == datetime(2026, 7, 15, 0, 30, tzinfo=UTC)
    assert ev["cancelled"][0]["close_reason"] == "expired"


def test_replaying_the_same_bars_twice_is_idempotent():
    t = PaperTrader(cfg())
    pid = _filled_long(t)
    b = bars("2026-07-30T12:00Z", [(1.1003, 1.1030, 1.1000, 1.1020)])  # arms half-T1 BE
    t.replay_bars("EURUSD=X", b)
    state = (t.positions[pid].current_stop, t.positions[pid].breakeven_triggered)
    t.replay_bars("EURUSD=X", b)                                          # same bar again
    t.replay_bars("EURUSD=X", bars("2026-07-30T11:00Z", [(1.09, 1.09, 1.08, 1.085)]))  # older
    assert t.positions[pid].status == TradeStatus.ACTIVE
    assert (t.positions[pid].current_stop, t.positions[pid].breakeven_triggered) == state
    assert t.last_priced_ts("EURUSD=X") == datetime(2026, 7, 30, 13, tzinfo=UTC)


def test_daily_loss_rolls_on_bar_time_and_never_backwards():
    t = PaperTrader(cfg())
    t.maybe_roll_day(datetime(2026, 7, 30, 12, tzinfo=UTC))
    assert t.current_date == "2026-07-30"
    t.balance = 4900.0
    t.maybe_roll_day(datetime(2026, 7, 29, 12, tzinfo=UTC))          # older: ignored
    assert t.current_date == "2026-07-30" and t.today_starting_equity == 5000.0
    t.maybe_roll_day(datetime(2026, 7, 30, 22, tzinfo=UTC))          # 22:00 UTC reset
    assert t.current_date == "2026-07-31" and t.today_starting_equity == 4900.0


def test_days_elapsed_is_utc_and_never_negative():
    t = PaperTrader(cfg())
    t.challenge_started_at = (datetime.now(UTC) - timedelta(days=3, hours=1)).isoformat()
    assert t.get_account_summary()["prop_firm"]["days_elapsed"] == 3
    # A legacy naive IST stamp 5.5h "in the future" relative to UTC used to give -1.
    t.challenge_started_at = (datetime.now(UTC) + timedelta(hours=5, minutes=30)).replace(
        tzinfo=None).isoformat()
    assert t.get_account_summary()["prop_firm"]["days_elapsed"] == 0


# ------------------------------------------------------------------ drift / invalidation
def test_drift_is_directional():
    t = PaperTrader(cfg())
    a = t.submit_signal(signal(symbol="EURUSD=X", entry=1.1000, stop=1.0950))
    # Price above the buy-limit by 4R (0.02) -> away on the approach side -> drifted.
    t.replay_bars("EURUSD=X", bars("2026-07-30T11:00Z", [(1.1180, 1.1210, 1.1150, 1.1200)]))
    assert hist(t, a).close_reason == "drifted"
    # A buy-stop long waits ABOVE price; the same 4R ABOVE its entry is the
    # triggered side, not "away" -- and it filled, so it is active.
    b = t.submit_signal(signal(symbol="GBPUSD=X", entry=1.3000, stop=1.2950,
                               targets=(1.305, 1.31, 1.315), order_type="stop",
                               signal_time="2026-07-30T12:30:00Z"))
    t.replay_bars("GBPUSD=X", bars("2026-07-30T13:00Z", [(1.3190, 1.3210, 1.3170, 1.3200)]))
    assert t.positions[b].status == TradeStatus.ACTIVE


def test_drift_recheck_kill_switch(monkeypatch):
    monkeypatch.setenv("BP_PENDING_DISTANCE_RECHECK", "0")
    t = PaperTrader(cfg())
    a = t.submit_signal(signal())
    t.replay_bars("EURUSD=X", bars("2026-07-30T11:00Z", [(1.1180, 1.1210, 1.1150, 1.1200)]))
    assert t.positions[a].status == TradeStatus.PENDING


def test_stop_order_cancelled_when_stop_trades_first():
    t = PaperTrader(cfg())
    pid = t.submit_signal(signal(symbol="GBPUSD=X", entry=1.3000, stop=1.2950,
                                 targets=(1.305, 1.31, 1.315), order_type="stop"))
    t.replay_bars("GBPUSD=X", bars("2026-07-30T11:00Z", [(1.2970, 1.2975, 1.2940, 1.2960)]))
    p = hist(t, pid)
    assert p.status == TradeStatus.CANCELLED and p.close_reason == "invalidated"


# ------------------------------------------------------------------ dedup / gates
def test_setup_key_dedup_blocks_recent_closed_setup_and_zone_memory():
    t = PaperTrader(cfg())
    pid = t.submit_signal(signal(zone_id="zA"))
    t.replay_bars("EURUSD=X", bars("2026-07-30T11:00Z", [(1.1010, 1.1060, 1.0940, 1.0960)]))
    assert hist(t, pid).status == TradeStatus.CLOSED
    hist(t, pid).close_time = datetime.now(UTC) - timedelta(days=1)   # recent close
    # EURNZD case: same levels, NEW zone id (the id drifted daily) -> rejected.
    assert t.submit_signal(signal(zone_id="zB")) is None
    # Same zone id, different levels -> rejected by zone_memory.
    assert t.submit_signal(signal(zone_id="zA", entry=1.1010, stop=1.0960)) is None
    # A live duplicate is rejected too.
    other = t.submit_signal(signal(symbol="GBPUSD=X", entry=1.3, stop=1.295, zone_id="g1"))
    assert other and t.submit_signal(signal(symbol="GBPUSD=X", entry=1.3, stop=1.295,
                                            zone_id="g2")) is None


def test_setup_key_dedup_window_expires(monkeypatch):
    t = PaperTrader(cfg())
    pid = t.submit_signal(signal(zone_id="zA"))
    t.replay_bars("EURUSD=X", bars("2026-07-30T11:00Z", [(1.1010, 1.1060, 1.0940, 1.0960)]))
    hist(t, pid).close_time = datetime.now(UTC) - timedelta(days=31)
    assert t.submit_signal(signal(zone_id="zB")) is not None
    monkeypatch.setenv("BP_SETUP_KEY_DEDUP", "0")
    t2 = PaperTrader(cfg())
    t2.trade_history = list(t.trade_history)
    hist(t2, pid).close_time = datetime.now(UTC)
    assert t2.submit_signal(signal(zone_id="zC")) is not None


def test_fill_time_gates_follow_bar_time_across_symbols():
    t = PaperTrader(cfg(max_open_positions=1))
    a = t.submit_signal(signal(symbol="EURUSD=X", zone_id="a"))
    b = t.submit_signal(signal(symbol="AUDUSD=X", entry=0.6600, stop=0.6550,
                               targets=(0.665, 0.67, 0.675), zone_id="b"))
    # AUDUSD reaches its entry at 11:00, EURUSD only at 12:00. Symbol order in the
    # dict must not matter: AUDUSD fills first and takes the only slot.
    ev = t.replay_bars_multi({
        "EURUSD=X": bars("2026-07-30T11:00Z", [(1.1010, 1.1020, 1.1005, 1.1010),
                                               (1.1010, 1.1012, 1.0995, 1.1000)]),
        "AUDUSD=X": bars("2026-07-30T11:00Z", [(0.6610, 0.6612, 0.6598, 0.6605),
                                               (0.6605, 0.6610, 0.6601, 0.6608)]),
    })
    assert [f["position_id"] for f in ev["fills"]] == [b]
    assert hist(t, a).status == TradeStatus.CANCELLED and hist(t, a).close_reason == "cancelled"


def test_wall_clock_backstop_expiry():
    t = PaperTrader(cfg())
    pid = t.submit_signal(signal(signal_time="2026-07-01T00:30:00Z"))
    assert t.expire_stale_pending(now=datetime(2026, 7, 16, tzinfo=UTC)) == []   # 14d + 2d grace
    out = t.expire_stale_pending(now=datetime(2026, 7, 17, 1, tzinfo=UTC))
    assert out and hist(t, pid).close_reason == "expired"
