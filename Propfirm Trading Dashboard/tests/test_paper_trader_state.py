"""State round-trip + fresh-challenge tests (2026-09-27).

Run from the dashboard folder:
    python -m pytest tests -p no:cacheprovider -q
"""
import json
import os
import sys
import tempfile
from dataclasses import asdict, fields
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

# Redirect run_scanner's state/log files BEFORE importing it, and make sure the
# import cannot pull the live webhook out of .secrets.bat.
_TMP_STATE = tempfile.mkdtemp(prefix="bp_state_test_")
os.environ["BP_STATE_DIR"] = _TMP_STATE
os.environ.pop("DISCORD_WEBHOOK_URL", None)

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import run_scanner as rs                                        # noqa: E402
import reset_challenge                                          # noqa: E402
from BP_paper_trader import PaperTrader, Position, TradeStatus  # noqa: E402

UTC = timezone.utc
CFG = {
    "prop_firm": {"enabled": True, "account_size": 5000.0, "max_daily_loss_usd": 150.0,
                  "max_total_loss_usd": 300.0},
    "risk": {"max_open_positions": 20, "correlation_check_enabled": False},
    "stop_loss": {"breakeven_at_half_target": True},
}


def _bars(start, rows):
    ts = pd.date_range(pd.Timestamp(start), periods=len(rows), freq="h", tz="UTC")
    o, h, l, c = zip(*rows)
    return pd.DataFrame({"timestamp": ts, "open": o, "high": h, "low": l, "close": c})


def _trader_with_activity():
    t = PaperTrader(CFG)
    t.challenge_started_at = datetime(2026, 9, 27, 0, 17, tzinfo=UTC).isoformat()
    base = {"direction": "long", "position_size": 10000.0, "risk_amount": 50.0,
            "income_strategy": "weekly", "signal_time": "2026-07-30T10:30:00Z",
            "trade_context": "counter_trend"}
    act = t.submit_signal({**base, "symbol": "EURUSD=X", "entry_price": 1.1, "stop_price": 1.095,
                           "targets": [1.105, 1.11, 1.115], "zone_id": "za"})
    stp = t.submit_signal({**base, "symbol": "GBPUSD=X", "entry_price": 1.3, "stop_price": 1.295,
                           "targets": [1.305, 1.31, 1.315], "zone_id": "zb", "order_type": "stop"})
    los = t.submit_signal({**base, "symbol": "AUDUSD=X", "entry_price": 0.66, "stop_price": 0.655,
                           "targets": [0.665, 0.67, 0.675], "zone_id": "zc"})
    t.replay_bars_multi({
        "EURUSD=X": _bars("2026-07-30T11:00Z", [(1.1005, 1.1030, 1.0998, 1.1020)]),  # fill; no BE credit on the fill bar
        "AUDUSD=X": _bars("2026-07-30T11:00Z", [(0.6610, 0.6612, 0.6540, 0.6560)]),  # fill + stop
    })
    t.replay_bars("EURUSD=X", _bars("2026-07-30T12:00Z", [(1.1020, 1.1030, 1.1010, 1.1025)]))
    return t, act, stp, los


def test_position_dict_round_trip_keeps_every_field():
    t, act, stp, los = _trader_with_activity()
    for pos in list(t.positions.values()) + t.trade_history:
        d = rs._position_to_dict(pos)
        json.dumps(d)                                   # must be JSON-serialisable
        back = rs._position_from_dict(json.loads(json.dumps(d)))
        for f in fields(Position):
            assert getattr(back, f.name) == getattr(pos, f.name), f.name
    a = t.positions[act]
    assert a.order_type == "limit" and a.fill_price == pytest.approx(1.1000)
    assert a.breakeven_triggered and a.last_priced_ts == datetime(2026, 7, 30, 13, tzinfo=UTC)
    assert t.positions[stp].order_type == "stop"


def test_save_load_round_trip(monkeypatch, tmp_path):
    monkeypatch.setattr(rs, "PAPER_STATE_FILE", tmp_path / "paper_trader_state.json")
    t, act, stp, los = _trader_with_activity()
    rs.save_paper_trader_state(t)
    raw = json.loads((tmp_path / "paper_trader_state.json").read_text())
    assert raw["challenge_started_at"].endswith("+00:00")
    assert raw["saved_at"].endswith("+00:00")

    t2 = PaperTrader(CFG)
    rs.load_paper_trader_state(t2)
    assert set(t2.positions) == set(t.positions)
    for pid, pos in t.positions.items():
        assert asdict(t2.positions[pid]) == asdict(pos)
    assert [asdict(p) for p in t2.trade_history] == [asdict(p) for p in t.trade_history]
    closed = next(p for p in t2.trade_history if p.id == los)
    assert closed.close_reason == "stop" and closed.trade_context == "counter_trend"
    assert t2.balance == pytest.approx(t.balance)
    # Replay after reload continues from last_priced_ts, not from placement.
    assert t2.last_priced_ts("EURUSD=X") == datetime(2026, 7, 30, 13, tzinfo=UTC)


def test_legacy_state_record_loads_with_defaults():
    legacy = {
        "id": "abc", "symbol": "NZDUSD=X", "direction": "long", "entry_price": 0.5786,
        "stop_price": 0.5743, "current_stop": 0.5743, "targets": [0.5829, 0.5873, 0.5916],
        "position_size": 1000.0, "risk_amount": 4.33,
        "entry_time": "2026-09-17T05:03:24.335319", "status": "closed",
        "realized_pnl": -4.33, "close_time": "2026-09-18T04:54:44.256956",
        "close_price": 0.5743, "trade_r_multiple": -1.0, "income_strategy": "weekly",
        "some_future_key": 1,
    }
    p = rs._position_from_dict(legacy)
    assert p.entry_time == datetime(2026, 9, 17, 5, 3, 24, 335319, tzinfo=UTC)
    assert p.order_type == "limit" and p.setup_key == "" and p.placed_at is None
    assert p.close_reason == "" and p.trade_context == "standard"


def test_reset_challenge_on_a_copy(tmp_path):
    for name, payload in (("paper_trader_state.json", {"balance": 4995.67, "open_positions": [1]}),
                          ("discord_state.json", {"signal_ids_seen": ["x"]}),
                          ("scan_history.json", [{"scan_time": "t"}])):
        (tmp_path / name).write_text(json.dumps(payload))

    assert reset_challenge.main(["--state-dir", str(tmp_path), "--dry-run"]) == 0
    assert json.loads((tmp_path / "paper_trader_state.json").read_text())["balance"] == 4995.67

    assert reset_challenge.main(["--state-dir", str(tmp_path)]) == 0
    st = json.loads((tmp_path / "paper_trader_state.json").read_text())
    assert st["balance"] == st["initial_balance"] == st["peak_balance"] == 5000.0
    assert st["open_positions"] == [] and st["trade_history"] == [] and st["zone_memory"] == {}
    started = datetime.fromisoformat(st["challenge_started_at"])
    assert started.tzinfo is not None and started.utcoffset().total_seconds() == 0
    assert json.loads((tmp_path / "discord_state.json").read_text())["signal_ids_seen"] == []
    assert json.loads((tmp_path / "scan_history.json").read_text()) == []
    assert len(list(tmp_path.glob("*.bak-*"))) == 3

    # The fresh file loads into a trader cleanly and reports Day 0.
    t = PaperTrader(CFG)
    old = rs.PAPER_STATE_FILE
    try:
        rs.PAPER_STATE_FILE = tmp_path / "paper_trader_state.json"
        rs.load_paper_trader_state(t)
    finally:
        rs.PAPER_STATE_FILE = old
    s = t.get_account_summary()
    assert s["balance"] == 5000.0 and s["prop_firm"]["days_elapsed"] == 0
    assert t.positions == {} and t.trade_history == []
