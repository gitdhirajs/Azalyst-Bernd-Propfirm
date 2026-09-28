"""Cross-file integration tests for the 2026-09-27 execution-layer rebuild.

Each of the four sides (data fetcher, rules engine, paper trader + run_scanner,
send_discord) has its own unit tests. These tests wire the REAL pieces together
the way run_scanner.scan_all_markets does, to check the interface contract:

  engine signal dict  -> PaperTrader.submit_signal          (order_type, signal_time, setup_key)
  DataFetcher.fetch_bars_since -> run_scanner.replay_open_orders -> replay_bars_multi
  PaperTrader state   -> run_scanner save/load               (last_priced_ts, fill_price, ...)
  scan_results payload -> send_discord.compute_events        (fills, close_reason, cancellations)

No network: yfinance is replaced by a fake DataFetcher._fetch_one, the clock by a
pinned BP_data_fetcher._utcnow, and requests.post raises.

Run from the dashboard folder:
    python -m pytest tests -p no:cacheprovider -q
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

# Same guard as test_paper_trader_state.py: run_scanner must write its logs and
# state into a temp folder, and must not load the live webhook.
os.environ.setdefault("BP_STATE_DIR", tempfile.mkdtemp(prefix="bp_state_integ_"))
os.environ.pop("DISCORD_WEBHOOK_URL", None)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import BP_data_fetcher as dfm                                        # noqa: E402
import run_scanner as rs                                             # noqa: E402
import send_discord as sd                                            # noqa: E402
from BP_data_fetcher import DataFetcher                              # noqa: E402
from BP_paper_trader import PaperTrader, TradeStatus, make_setup_key  # noqa: E402
from test_engine_zones_signal import (                               # noqa: E402,F401
    engine, run as run_engine, _with_live, PROX, DIST)

UTC = timezone.utc

CFG = {
    "prop_firm": {"enabled": True, "account_size": 5000.0, "max_daily_loss_usd": 150.0,
                  "max_total_loss_usd": 300.0, "daily_reset_hour_utc": 22,
                  "profit_target_pct": 6.0},
    "risk": {"max_open_positions": 20, "correlation_check_enabled": False,
             "pending_order_max_age_days": {"weekly": 14}},
    # Current live management (BP_config.yaml 2026-09-27): fixed bracket, 100% at T2.
    "stop_loss": {"management": "fixed", "take_profit_target": 2,
                  "breakeven_at_half_target": False},
    "entry_distance": {"default_max_r": 3.0, "max_r_to_entry_pending": {"weekly": 3.0},
                       "default_max_pct": 15.0, "max_pct_to_entry": {"weekly": 15.0}},
}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    for k in list(os.environ):
        if k.startswith("BP_") and k != "BP_STATE_DIR":
            monkeypatch.delenv(k, raising=False)

    def _boom(*a, **k):
        raise AssertionError("network call to Discord during a test")
    monkeypatch.setattr(sd.requests, "post", _boom)
    monkeypatch.setattr(sd, "_MIN_COMPOSITE_CACHE", 7.0, raising=False)
    monkeypatch.setattr(sd, "_ALERT_COMPOSITE_CACHE", 5.5, raising=False)


def _long_signal(**kw):
    s = {"symbol": "EURUSD=X", "direction": "long", "entry_price": 1.1000,
         "stop_price": 1.0950, "targets": [1.1050, 1.1100, 1.1150],
         "position_size": 10000.0, "risk_amount": 50.0, "income_strategy": "weekly",
         "zone_id": "z1", "order_type": "limit", "pending_order": True,
         "price_at_zone": False, "signal_time": "2026-07-30T10:30:00+00:00",
         "trade_context": "standard"}
    s.update(kw)
    return s


# --- a yfinance-shaped 1h feed ------------------------------------------------

class _FakeYahoo:
    """Stands in for DataFetcher._fetch_one: returns 1h bars the way _fetch_one
    does (a 'timestamp' column, tz-aware in the exchange zone -- Europe/London
    for FX), and records every call."""

    def __init__(self, rows_utc):
        self.rows = dict(rows_utc)            # {utc start str: (o, h, l, c)}
        self.calls = []

    def __call__(self, symbol, interval, period, start, end, retries):
        self.calls.append((symbol, interval, period))
        ts = pd.DatetimeIndex(pd.to_datetime(list(self.rows), utc=True)).tz_convert("Europe/London")
        o, h, l, c = zip(*self.rows.values())
        return pd.DataFrame({"timestamp": ts, "open": o, "high": h, "low": l, "close": c,
                             "volume": [0.0] * len(ts)})


def _pin_now(monkeypatch, iso):
    monkeypatch.setattr(dfm, "_utcnow", lambda: pd.Timestamp(iso))


# =============================================================================
# 1. engine signal -> paper trader
# =============================================================================

def test_engine_signal_is_accepted_by_the_trader_as_a_pending_order(engine):
    sig = run_engine(engine, _with_live(102.5))
    assert sig is not None
    # run_scanner adds sizing, then submits with placed_at = max(signal_time, now)
    sig = {**sig, "position_size": 125.0, "risk_amount": 50.0}
    trader = PaperTrader(CFG)
    pid = trader.submit_signal(sig)
    assert pid is not None
    pos = trader.positions[pid]
    assert pos.status == TradeStatus.PENDING               # never filled at signal time
    assert pos.order_type == sig["order_type"] == "limit"
    assert pos.placed_at == datetime.fromisoformat(sig["signal_time"])
    assert pos.placed_at.utcoffset() == timedelta(0)
    # engine and trader agree on the dedup key, byte for byte
    assert sig["setup_key"] == make_setup_key("TEST", "long", PROX, DIST)
    assert pos.setup_key == sig["setup_key"]
    # the next hourly run re-emits the same setup: it must not stack a second order
    assert trader.submit_signal(dict(sig, zone_id="another-id")) is None


def test_engine_signal_survives_json_round_trip_into_the_trader(engine):
    """scan_results.json carries json_safe(signals); a consumer re-submitting from
    the JSON must see the same order."""
    sig = run_engine(engine, _with_live(102.5))
    back = json.loads(json.dumps(rs.json_safe({**sig, "position_size": 125.0,
                                               "risk_amount": 50.0})))
    pid = PaperTrader(CFG).submit_signal(back)
    assert pid is not None


# =============================================================================
# 2. fetch_bars_since -> replay_open_orders -> save/load -> replay again
# =============================================================================

def test_replay_open_orders_prices_from_placement_and_resumes_after_reload(monkeypatch, tmp_path):
    monkeypatch.setattr(rs, "PAPER_STATE_FILE", tmp_path / "paper_trader_state.json")
    trader = PaperTrader(CFG)
    pid = trader.submit_signal(_long_signal())

    feed = _FakeYahoo({
        "2026-07-30T08:00Z": (1.1010, 1.1015, 1.0990, 1.1005),   # before the order existed
        "2026-07-30T09:00Z": (1.1005, 1.1012, 1.1001, 1.1008),
        "2026-07-30T10:00Z": (1.1008, 1.1012, 1.0995, 1.1006),   # contains placement 10:30
        "2026-07-30T11:00Z": (1.1006, 1.1011, 1.1004, 1.1009),
        "2026-07-30T12:00Z": (1.1009, 1.1010, 1.0998, 1.1004),   # fills at 1.1000
        "2026-07-30T13:00Z": (1.1004, 1.1040, 1.1003, 1.1035),
        "2026-07-30T14:00Z": (1.1035, 1.1060, 1.1030, 1.1055),
        "2026-07-30T15:00Z": (1.1055, 1.1200, 1.0900, 1.1100),   # in progress at 15:30
    })
    fetcher = DataFetcher()
    monkeypatch.setattr(fetcher, "_fetch_one", feed)
    _pin_now(monkeypatch, "2026-07-30T15:30Z")

    events, last_close = rs.replay_open_orders(trader, fetcher)
    pos = trader.positions[pid]
    assert [e["position_id"] for e in events["fills"]] == [pid]
    assert pos.status == TradeStatus.ACTIVE
    assert pos.filled_at == datetime(2026, 7, 30, 12, tzinfo=UTC)
    assert pos.fill_price == pytest.approx(1.1000)
    # the still-forming 15:00 bar (which would have stopped AND targeted it) is not used
    assert pos.last_priced_ts == datetime(2026, 7, 30, 15, tzinfo=UTC)
    assert last_close["EURUSD=X"] == pytest.approx(1.1055)

    # persist exactly like the scanner does, reload into a fresh process-equivalent
    rs.save_paper_trader_state(trader)
    t2 = PaperTrader(CFG)
    rs.load_paper_trader_state(t2)
    p2 = t2.positions[pid]
    for f in ("placed_at", "filled_at", "last_priced_ts"):
        assert getattr(p2, f) == getattr(pos, f) and getattr(p2, f).tzinfo is not None
    assert (p2.order_type, p2.setup_key, p2.fill_price) == (pos.order_type, pos.setup_key,
                                                            pos.fill_price)

    # Next run, 3 hours later. Yahoo re-serves the old bars and has REVISED the
    # already-priced 13:00 bar down through the stop: it must not be re-applied.
    feed.rows["2026-07-30T13:00Z"] = (1.1004, 1.1040, 1.0900, 1.1035)
    feed.rows["2026-07-30T15:00Z"] = (1.1055, 1.1070, 1.1050, 1.1065)
    feed.rows["2026-07-30T16:00Z"] = (1.1065, 1.1105, 1.1060, 1.1100)   # T2 = 1.1100
    feed.rows["2026-07-30T17:00Z"] = (1.1100, 1.1110, 1.1090, 1.1095)
    _pin_now(monkeypatch, "2026-07-30T18:30Z")
    seen_since = []
    real = fetcher.fetch_bars_since
    monkeypatch.setattr(fetcher, "fetch_bars_since",
                        lambda s, since, iv="60m": seen_since.append(since) or real(s, since, iv))
    events2, _ = rs.replay_open_orders(t2, fetcher)
    assert seen_since == [datetime(2026, 7, 30, 15, tzinfo=UTC)]
    assert events2["fills"] == []
    assert len(events2["closed"]) == 1
    c = events2["closed"][0]
    assert c["close_reason"] == "T2" and c["r_multiple"] == pytest.approx(2.0)
    assert c["close_time"].startswith("2026-07-30T16:00")


def test_replay_open_orders_with_no_new_bars_changes_nothing(monkeypatch):
    """Weekend: Yahoo returns only bars already priced -> no events, stamps unchanged."""
    trader = PaperTrader(CFG)
    pid = trader.submit_signal(_long_signal(signal_time="2026-07-31T19:30:00+00:00"))
    feed = _FakeYahoo({"2026-07-31T19:00Z": (1.1010, 1.1015, 1.0990, 1.1005)})
    fetcher = DataFetcher()
    monkeypatch.setattr(fetcher, "_fetch_one", feed)
    _pin_now(monkeypatch, "2026-08-01T12:00Z")                 # Saturday
    events, last_close = rs.replay_open_orders(trader, fetcher)
    assert events == {"fills": [], "closed": [], "cancelled": [], "partials": []} and last_close == {}
    assert trader.positions[pid].status == TradeStatus.PENDING
    assert trader.positions[pid].last_priced_ts is None


# =============================================================================
# 3. scan_results payload (as run_scanner builds it) -> send_discord
# =============================================================================

def _payload(trader, events, start="2026-09-27T00:17:00+00:00"):
    """The keys of run_scanner.scan_all_markets' results that send_discord reads,
    built the same way and pushed through JSON like scan_results.json."""
    trader.challenge_started_at = start
    acct = trader.get_account_summary()
    res = {
        "scan_time": "2026-07-30T18:17:00+00:00", "watchlist_scanned": 41, "errors": [],
        "signals": [], "account": acct,
        "positions": trader.get_open_positions(),
        "pending_orders": trader.get_pending_orders(),
        "trade_history": trader.get_trade_history(limit=100),
        "fills": events.get("fills", []),
        "closed_this_run": events.get("closed", []),
        "cancelled_this_run": events.get("cancelled", []),
    }
    return json.loads(json.dumps(rs.json_safe(res)))


def _discord_state_with_pending(trader):
    scan = _payload(trader, {})
    now = datetime(2026, 7, 30, 11, 17, tzinfo=UTC)
    ev = sd.compute_events(scan, {})
    return sd.build_state(scan, {}, ev, now, posted=True)


def test_fill_and_stop_inside_one_replay_reach_discord_with_reason_and_r():
    trader = PaperTrader(CFG)
    pid = trader.submit_signal(_long_signal())
    prev = _discord_state_with_pending(trader)
    assert pid in prev["pending_orders_seen"]

    ev = trader.replay_bars("EURUSD=X", pd.DataFrame({
        "timestamp": pd.to_datetime(["2026-07-30T11:00Z", "2026-07-30T12:00Z"], utc=True),
        "open": [1.1010, 1.0990], "high": [1.1012, 1.0995],
        "low": [1.0998, 1.0940], "close": [1.1000, 1.0945]}))
    assert len(ev["fills"]) == 1 and len(ev["closed"]) == 1

    scan = _payload(trader, ev)
    out = sd.compute_events(scan, prev)
    assert [f.get("id") or f.get("position_id") for f in out["fills"]] == [pid]
    assert [c["id"] for c in out["closed"]] == [pid]
    assert out["cancelled"] == []
    closed = out["closed"][0]
    assert closed["close_reason"] == "stop"
    assert closed["r_multiple"] == pytest.approx(-1.0)
    txt = sd.closed_block(out["closed"])
    assert "-1.00R" in txt and "stop" in txt
    assert sd.order_label(out["fills"][0]) == "BUY-LIMIT"
    assert sd.decide_post(scan, prev, out, datetime(2026, 7, 30, 13, 17, tzinfo=UTC)) == "news"


@pytest.mark.xfail(strict=True, reason=(
    "CONTRACT GAP: run_scanner sets signal['paper_trade_id']=None when the paper trader "
    "REJECTS a signal (correlation / duplicate setup / loss budget), but send_discord "
    "never reads it: every new signal is rendered '[TAKE] = pinged + paper-traded' with a "
    "lot size. E2E 2026-09-27: 6 NZD signals posted, 5 rejected for correlation, so the "
    "user would place 5 correlated long-NZD orders (~$215 risk) by hand that the paper "
    "account never took."))
def test_signal_rejected_by_paper_trader_is_not_announced_as_paper_traded():
    base = {"direction": "long", "order_type": "limit", "entry_type": "E1",
            "entry_price": 0.5551, "stop_price": 0.5491, "targets": [0.5611, 0.5671, 0.5731],
            "current_price": 0.5659, "price_at_zone": False, "pending_order": True,
            "qualifier_scores": {"composite": 9.2}, "lot_size": 0.08, "units": 8000,
            "risk_usd_actual": 48.09, "risk_usd_target": 50.0, "trade_context": "standard"}
    taken = dict(base, symbol="NZDJPY=X", display_name="NZDJPY", paper_trade_id="P1",
                 setup_key="NZDJPY=X|long|88.134|87.242")
    rejected = dict(base, symbol="NZDUSD=X", display_name="NZDUSD", paper_trade_id=None,
                    setup_key="NZDUSD=X|long|0.55508|0.54907")
    scan = {"scan_time": "2026-09-27T12:53:52+00:00", "signals": [taken, rejected],
            "positions": [], "pending_orders": [], "trade_history": [], "errors": [],
            "watchlist_scanned": 41,
            "account": {"prop_firm": {"challenge_started_at": "2026-09-27T00:00:00+00:00"}}}
    ev = sd.compute_events(scan, {"challenge_started_at": "2026-09-27T00:00:00+00:00"})
    shown = [s for s in ev["new_signals"] if s["symbol"] == "NZDUSD=X"]
    if not shown:
        return                                      # not announced at all: acceptable
    text = "\n".join(m["content"] for m in sd.build_signals_messages(scan, shown)).lower()
    assert "not paper-traded" in text or "rejected" in text


@pytest.mark.xfail(strict=True, reason=(
    "CONTRACT GAP: run_scanner publishes cancellations as results['cancelled_this_run'] "
    "(events keyed 'position_id'), and get_trade_history() excludes CANCELLED orders, but "
    "send_discord.compute_events only looks for results['cancelled_orders'] keyed 'id' "
    "or a cancelled row in trade_history -- so the reason (drifted / expired / cancelled) "
    "never reaches the ORDERS CANCELLED line, which always reads 'cancelled'."))
def test_cancellation_reason_reaches_discord():
    trader = PaperTrader(CFG)
    pid = trader.submit_signal(_long_signal())
    prev = _discord_state_with_pending(trader)

    # price walks 3.2R away on the approach side -> E-05 drift cancel
    ev = trader.replay_bars("EURUSD=X", pd.DataFrame({
        "timestamp": pd.to_datetime(["2026-07-30T11:00Z"], utc=True),
        "open": [1.1100], "high": [1.1165], "low": [1.1095], "close": [1.1160]}))
    assert [c["close_reason"] for c in ev["cancelled"]] == ["drifted"]

    out = sd.compute_events(_payload(trader, ev), prev)
    assert [c["id"] for c in out["cancelled"]] == [pid]
    assert out["cancelled"][0].get("close_reason") == "drifted"
