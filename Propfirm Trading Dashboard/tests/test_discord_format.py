"""Display tests for send_discord.py (2026-09-27 fixes, defect 10 + O3):
never print nan, order types on pending orders, close_reason on closed lines,
fractional units, UTC "Day N since reset", PENDING Location line."""
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import send_discord as sd  # noqa: E402

NAN = float("nan")
NAN_RE = re.compile(r"\bnan\b", re.IGNORECASE)   # "financial" must not match


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("tests must never post to Discord")
    monkeypatch.setattr(sd.requests, "post", _boom)
    monkeypatch.setattr(sd, "_MIN_COMPOSITE_CACHE", 7.0)
    monkeypatch.setattr(sd, "_ALERT_COMPOSITE_CACHE", 5.5)


def utc(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def _account(start="2026-09-25T00:00:00+00:00", **pf):
    p = {"enabled": True, "account_size": 5000.0, "todays_loss": 0.0,
         "max_daily_loss_limit": 150.0, "daily_loss_remaining": 150.0,
         "total_loss": 0.0, "max_total_loss_limit": 300.0,
         "total_loss_remaining": 300.0, "breached": False,
         "profit_target_pct": 6.0, "target_equity": 5300.0,
         "progress_to_target_pct": 0.0, "challenge_started_at": start,
         "days_elapsed": -1}
    p.update(pf)
    return {"balance": 5000.0, "closed_pnl": 0.0, "open_pnl": 0.0,
            "total_trades": 0, "winning_trades": 0, "losing_trades": 0,
            "win_rate": None, "scratch_trades": 0, "avg_r": 0.0, "prop_firm": p}


# ── nan never printed ──────────────────────────────────────────────────────

def test_status_message_never_prints_nan():
    acct = _account(progress_to_target_pct=NAN, todays_loss=NAN)
    acct["balance"] = NAN
    acct["avg_r"] = NAN
    pos = {"id": "A", "symbol": "CL=F", "direction": "long", "entry_price": 70.0,
           "current_price": NAN, "unrealized_pnl": NAN, "r_multiple_open": NAN,
           "stop_price": 68.0, "current_stop": NAN, "targets": [72.0, NAN]}
    pend = {"id": "B", "symbol": "EURUSD=X", "direction": "short", "entry_price": NAN,
            "stop_price": 1.1, "targets": [], "distance_pct": NAN, "order_type": "stop"}
    hist = {"id": "C", "symbol": "GBPUSD=X", "direction": "long", "entry_price": 1.3,
            "stop_price": 1.29, "close_price": NAN, "realized_pnl": NAN,
            "r_multiple": NAN, "close_reason": "stop", "status": "closed"}
    scan = {"scan_time": "2026-09-27T10:17:00", "account": acct, "positions": [pos],
            "pending_orders": [pend], "trade_history": [hist], "signals": [],
            "watchlist_scanned": 66, "errors": []}
    msg = "\n".join(sd.build_status_messages(scan, [hist], fills=[pos], cancelled=[pend],
                                             now_utc=utc("2026-09-27T10:17:00")))
    assert not NAN_RE.search(msg), msg
    assert "Now:-" in msg
    assert "SELL-STOP" in msg          # pending order type survives the NaN entry


def test_long_status_paginates_instead_of_dropping_pending_orders():
    """2026-09-27: event blocks moved to the top pushed PENDING ORDERS past the
    1900-char cut and they were silently dropped. They must continue instead."""
    mk = lambda i, st: {"id": f"{st}{i}", "symbol": f"SYM{i}=X", "direction": "long",
                        "entry_price": 1.0 + i / 100, "stop_price": 0.99, "current_stop": 0.99,
                        "targets": [1.1, 1.2, 1.3], "order_type": "limit",
                        "current_price": 1.0, "unrealized_pnl": 1.0, "r_multiple_open": 0.1,
                        "close_price": 1.1, "realized_pnl": 5.0, "r_multiple": 0.5,
                        "close_reason": "T3", "status": st}
    scan = {"scan_time": "2026-09-27T21:17:00+00:00", "account": _account(),
            "positions": [mk(i, "active") for i in range(6)],
            "pending_orders": [mk(i, "pending") for i in range(8)],
            "trade_history": [mk(i, "closed") for i in range(5)],
            "signals": [], "watchlist_scanned": 66, "errors": []}
    pages = sd.build_status_messages(scan, scan["trade_history"],
                                     fills=scan["positions"][:6],
                                     cancelled=scan["pending_orders"][:6],
                                     now_utc=utc("2026-09-27T21:40:00"))
    assert 1 < len(pages) <= sd.MAX_STATUS_PAGES
    assert all(len(p) <= sd.DISCORD_MSG_LIMIT for p in pages)
    joined = "\n".join(pages)
    assert "PENDING ORDERS" in joined and "SYM7=X" in joined
    assert pages[1].startswith("```\n(continued 2/")


def test_signal_block_never_prints_nan():
    s = {"symbol": "CL=F", "direction": "long", "entry_price": 70.0, "stop_price": 68.0,
         "targets": [72.0, NAN, 76.0], "lot_size": 0.1, "units": NAN,
         "risk_usd_actual": NAN, "risk_amount": NAN, "current_price": NAN,
         "qualifier_scores": {"composite": NAN}}
    block = sd._format_signal_block(s, 7.0)
    assert not NAN_RE.search(block), block


@pytest.mark.parametrize("fn,arg", [(sd.fmt_price, NAN), (sd.fmt_money, NAN),
                                    (sd.fmt_pct, NAN), (sd._px, None), (sd._px, "x"),
                                    (sd.fmt_qty, NAN), (sd._signed_r, math.inf)])
def test_formatters_render_dash_for_missing(fn, arg):
    assert fn(arg).strip() == "-"


# ── order types ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("direction,ot,label", [
    ("long", "limit", "BUY-LIMIT"), ("long", "stop", "BUY-STOP"),
    ("short", "limit", "SELL-LIMIT"), ("short", "stop", "SELL-STOP"),
])
def test_pending_orders_show_order_type(direction, ot, label):
    p = {"id": "X", "symbol": "EURUSD=X", "direction": direction, "order_type": ot,
         "entry_price": 1.085, "stop_price": 1.08, "targets": [1.09]}
    block = sd.pending_orders_block([p])
    assert label in block
    assert "PENDING ORDERS" in block


def test_order_type_falls_back_to_entry_type():
    assert sd.order_label({"direction": "long", "entry_type": "E3b"}) == "BUY-STOP"
    assert sd.order_label({"direction": "short", "entry_type": "E1"}) == "SELL-LIMIT"
    assert sd.order_label({"direction": "long"}) == "BUY-LIMIT"


# ── close_reason ───────────────────────────────────────────────────────────

def test_close_reason_on_closed_and_track_record_lines():
    h = [{"id": "1", "symbol": "USDJPY=X", "direction": "short", "entry_price": 149.0,
          "stop_price": 150.0, "close_price": 150.0, "realized_pnl": -50.0,
          "r_multiple": -1.0, "close_reason": "stop"},
         {"id": "2", "symbol": "EURCHF=X", "direction": "long", "entry_price": 0.93,
          "stop_price": 0.92, "close_price": 0.93, "realized_pnl": 0.0,
          "r_multiple": 0.0, "close_reason": "breakeven"}]
    closed = sd.closed_block(h)
    track = sd.track_record_block(h)
    for text in (closed, track):
        lines = text.splitlines()
        assert any("USDJPY" in ln and ln.rstrip().endswith("stop") for ln in lines)
        assert any("EURCHF" in ln and ln.rstrip().endswith("breakeven") for ln in lines)
    assert re.search(r"-\$\s*50\.00", closed) and "-1.00R" in closed


def test_missing_close_reason_shows_dash():
    h = [{"id": "1", "symbol": "X", "direction": "long", "realized_pnl": 1.0,
          "r_multiple": 0.1}]
    assert sd.closed_block(h).splitlines()[1].rstrip().endswith("-")


# ── units / lots ───────────────────────────────────────────────────────────

def test_fractional_units_keep_decimals():
    s = {"symbol": "BTC-USD", "direction": "long", "entry_price": 60000.0,
         "stop_price": 58000.0, "targets": [62000.0, 64000.0, 66000.0],
         "lot_size": 0.01, "units": 0.01, "risk_usd_actual": 20.0,
         "risk_usd_target": 50.0, "qualifier_scores": {"composite": 8.0}}
    block = sd._format_signal_block(s, 7.0)
    units_line = next(ln for ln in block.splitlines() if "(units)" in ln)
    assert units_line.split(":")[1].strip() == "0.01"
    lot_line = next(ln for ln in block.splitlines() if "LOT SIZE" in ln)
    assert "0.01 lots" in lot_line


@pytest.mark.parametrize("v,min_dp,out", [
    (100000, 0, "100,000"), (0.01, 0, "0.01"), (0.005, 2, "0.005"),
    (1, 2, "1.00"), (1234.5, 0, "1,234.5"), (2.5, 2, "2.50"),
])
def test_fmt_qty(v, min_dp, out):
    assert sd.fmt_qty(v, min_dp=min_dp) == out


# ── Day N since reset (UTC) ────────────────────────────────────────────────

@pytest.mark.parametrize("start,now,day", [
    ("2026-09-25T10:00:00", "2026-09-27T12:00:00", 2),            # naive = UTC
    ("2026-09-25T10:00:00+00:00", "2026-09-27T12:00:00", 2),      # aware
    ("2026-09-28T01:00:00+05:30", "2026-09-27T20:00:00", 0),      # IST aware, same UTC day
    # naive IST stamp that reads as later than "now" in UTC -> never negative
    ("2026-09-27T23:00:00", "2026-09-27T20:00:00", 0),
    ("2026-09-27T00:00:00Z", "2026-09-27T23:59:00", 0),
    ("2026-09-27T00:00:00Z", "2026-09-28T00:01:00", 1),
])
def test_challenge_day_utc(start, now, day):
    assert sd.challenge_day(start, utc(now)) == day


def test_account_block_uses_utc_day_not_days_elapsed():
    acct = _account(start="2026-09-25T05:00:00", days_elapsed=-1)
    text = sd.account_block(acct, utc("2026-09-27T12:00:00"))
    assert "(Day 2 since reset)" in text
    assert "Day -1" not in text


# ── signal Location line ───────────────────────────────────────────────────

def _sig(**kw):
    s = {"symbol": "NZDUSD=X", "direction": "long", "entry_price": 0.59,
         "stop_price": 0.585, "targets": [0.595, 0.6, 0.605], "lot_size": 1.0,
         "units": 100000, "risk_usd_actual": 50.0, "risk_usd_target": 50.0,
         "qualifier_scores": {"composite": 8.0}, "pending_order": True}
    s.update(kw)
    return s


def test_location_line_pending_and_at_zone():
    block = sd._format_signal_block(_sig(price_at_zone=True, order_type="limit",
                                         current_price=0.5905), 7.0)
    loc = next(ln for ln in block.splitlines() if "Location" in ln)
    assert "PENDING - resting order" in loc and "already at the zone" in loc
    assert "BUY-LIMIT" in block
    assert "Price now" in block


def test_location_line_pending_not_at_zone_stop_order():
    block = sd._format_signal_block(_sig(price_at_zone=False, order_type="stop"), 7.0)
    loc = next(ln for ln in block.splitlines() if "Location" in ln)
    assert "PENDING - resting order" in loc and "not at the zone" in loc
    order_line = next(ln for ln in block.splitlines() if "Order" in ln)
    assert "BUY-STOP" in order_line and "UP to entry" in order_line
    assert "AT ZONE" not in block


def test_header_is_utc():
    h = sd.header_block("2026-09-27T21:40:00+00:00", "DAILY STATUS")
    assert "27 Sep 2026  21:40 UTC" in h and "DAILY STATUS" in h
