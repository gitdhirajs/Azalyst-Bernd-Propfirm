"""Scale-out management (stop_loss.management: scale_out) -- user decision 2026-09-28:
"when 1r reach close 50% move to breakeven n then let 50% run till possible".

At +1R of the planned risk (from the planned entry) 50% of the original size
closes and the stop moves to breakeven (the fill price) from the NEXT bar. The
runner then trails in whole-R steps (+2R peak locks +1R, +3R locks +2R, ...)
and exits only on its stop, or at runner_target_r when set.

Run from the dashboard folder:
    python -m pytest tests -p no:cacheprovider -q
"""
import json
import os
import sys
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

os.environ.setdefault("BP_STATE_DIR", tempfile.mkdtemp(prefix="bp_state_scaleout_"))
os.environ.pop("DISCORD_WEBHOOK_URL", None)

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import BP_management as bm                                          # noqa: E402
import draw_chart                                                   # noqa: E402
import run_scanner as rs                                            # noqa: E402
import send_discord as sd                                           # noqa: E402
import scaleout_fixtures as fx                                      # noqa: E402
from BP_paper_trader import PaperTrader, TradeStatus                # noqa: E402
from test_paper_trader_replay import bars, cfg, hist, signal        # noqa: E402

UTC = timezone.utc
# EURUSD long: entry 1.1000, stop 1.0950 -> risk 0.0050 = $50 on 10,000 units.
# +1R 1.1050, +2R 1.1100, +3R 1.1150.


def so_cfg(**stop_kw):
    c = cfg()
    c["stop_loss"] = {"management": "scale_out", "scale_out_at_r": 1.0,
                      "scale_out_fraction": 0.5, "runner_trail": "r_steps",
                      "runner_target_r": None,
                      # ladder keys must be ignored in scale_out mode
                      "breakeven_at_half_target": True, "take_profit_target": 2}
    c["stop_loss"].update(stop_kw)
    return c


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in ("BP_BAR_REPLAY", "BP_PENDING_DISTANCE_RECHECK", "BP_STOP_ORDER_INVALIDATE",
              "BP_SETUP_KEY_DEDUP", "BP_TYPE_LADDERS"):
        monkeypatch.delenv(k, raising=False)

    def _boom(*a, **k):
        raise AssertionError("tests must never post to Discord")
    monkeypatch.setattr(sd.requests, "post", _boom)
    monkeypatch.setattr(sd, "_MIN_COMPOSITE_CACHE", 7.0)
    monkeypatch.setattr(sd, "_ALERT_COMPOSITE_CACHE", 5.5)


def filled_long(t, **kw):
    pid = t.submit_signal(signal(**kw))
    t.replay_bars("EURUSD=X", bars("2026-07-30T11:00Z", [(1.1005, 1.1008, 1.0998, 1.1003)]))
    assert t.positions[pid].status == TradeStatus.ACTIVE
    assert t.positions[pid].fill_price == pytest.approx(1.1000)
    return pid


def filled_short(t):
    pid = t.submit_signal(signal(direction="short", entry=1.1000, stop=1.1050,
                                 targets=(1.0950, 1.0900, 1.0850)))
    t.replay_bars("EURUSD=X", bars("2026-07-30T11:00Z", [(1.0995, 1.1002, 1.0992, 1.0997)]))
    assert t.positions[pid].status == TradeStatus.ACTIVE
    return pid


# ------------------------------------------------------------------ settings
def test_live_config_is_scale_out_by_default():
    live = yaml.safe_load((HERE / "BP_config.yaml").read_text(encoding="utf-8"))
    m = bm.management_settings(live)
    assert m == {"mode": "scale_out", "scale_out_at_r": 1.0, "scale_out_fraction": 0.5,
                 "runner_trail": "r_steps", "runner_target_r": None, "take_profit_target": 2,
                 "runner_blocks_new_entries": True}
    t = PaperTrader(live)
    assert t.scale_out and not t.fixed_bracket and not t.ladder


def test_settings_reader_defaults_and_bad_values():
    assert bm.management_settings({})["mode"] == "scale_out"
    assert bm.management_settings({"stop_loss": {"management": "FIXED"}})["mode"] == "fixed"
    m = bm.management_settings({"stop_loss": {"management": "bogus", "scale_out_fraction": 7,
                                              "runner_trail": "zones", "runner_target_r": "x"}})
    assert m["mode"] == "scale_out" and m["scale_out_fraction"] == 1.0
    assert m["runner_trail"] == "r_steps" and m["runner_target_r"] is None
    assert bm.management_settings(bm.management_settings({"stop_loss": {"management": "ladder"}}))[
        "mode"] == "ladder"


# ------------------------------------------------------------------ partial
def test_long_partial_at_1r_and_breakeven_from_next_bar():
    t = PaperTrader(so_cfg())
    pid = filled_long(t)
    # One bar reaches +1R and then trades back BELOW entry (still above the
    # original stop): the breakeven stop is not in force yet on this bar.
    ev = t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [(1.1003, 1.1055, 1.0990, 1.0995)]))
    p = t.positions[pid]
    assert p.status == TradeStatus.ACTIVE
    assert p.partial_taken and p.partial_price == pytest.approx(1.1050)
    assert p.partial_qty == pytest.approx(5000.0) and p.position_size == pytest.approx(5000.0)
    assert p.realized_pnl == pytest.approx(25.0)
    assert p.current_stop == pytest.approx(1.1000) and p.breakeven_triggered
    assert p.partial_time == datetime(2026, 7, 30, 12, tzinfo=UTC)
    (e,) = ev["partials"]
    assert e["event"] == "partial_close" and e["position_id"] == pid
    assert e["fraction"] == 0.5 and e["pnl"] == pytest.approx(25.0)
    assert e["r_booked"] == pytest.approx(0.5) and e["new_stop"] == pytest.approx(1.1000)
    assert e["new_stop_r"] == pytest.approx(0.0) and e["at"].startswith("2026-07-30T12:00")
    assert ev["closed"] == []
    # From the next bar the breakeven stop is live.
    ev = t.replay_bars("EURUSD=X", bars("2026-07-30T13:00Z", [(1.1010, 1.1020, 1.0998, 1.1001)]))
    c = hist(t, pid)
    assert c.close_reason == "breakeven" and c.close_price == pytest.approx(1.1000)
    assert c.realized_pnl == pytest.approx(25.0)
    assert c.trade_r_multiple == pytest.approx(0.5)            # +0.50R blended
    assert t.winning_trades == 1 and t.scratch_trades == 0 and t.losing_trades == 0
    assert t.balance == pytest.approx(5025.0)
    assert ev["closed"][0]["r_multiple"] == pytest.approx(0.5)


def test_short_partial_at_1r():
    t = PaperTrader(so_cfg())
    pid = filled_short(t)
    ev = t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [(1.0997, 1.1004, 1.0948, 1.0955)]))
    p = t.positions[pid]
    assert p.partial_taken and p.partial_price == pytest.approx(1.0950)
    assert p.current_stop == pytest.approx(1.1000)
    assert ev["partials"][0]["direction"] == "short"
    assert ev["partials"][0]["r_booked"] == pytest.approx(0.5)
    t.replay_bars("EURUSD=X", bars("2026-07-30T13:00Z", [(1.0960, 1.1003, 1.0955, 1.1001)]))
    c = hist(t, pid)
    assert c.close_reason == "breakeven" and c.trade_r_multiple == pytest.approx(0.5)


def test_stopped_before_the_partial_is_a_full_loss():
    t = PaperTrader(so_cfg())
    pid = filled_long(t)
    t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [
        (1.1003, 1.1030, 1.1000, 1.1028),    # half-T1: ignored in scale_out
        (1.1028, 1.1029, 1.0945, 1.0948),    # original stop
    ]))
    c = hist(t, pid)
    assert c.close_reason == "stop" and c.trade_r_multiple == pytest.approx(-1.0)
    assert not c.partial_taken and not c.breakeven_triggered


def test_bar_reaching_stop_and_l1_counts_the_stop():
    t = PaperTrader(so_cfg())
    pid = filled_long(t)
    ev = t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [(1.1003, 1.1060, 1.0940, 1.1000)]))
    c = hist(t, pid)
    assert c.close_reason == "stop" and c.trade_r_multiple == pytest.approx(-1.0)
    assert not c.partial_taken and ev["partials"] == []


def test_gap_through_l1_fills_the_partial_at_the_open():
    t = PaperTrader(so_cfg())
    pid = filled_long(t)
    t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [(1.1070, 1.1080, 1.1060, 1.1075)]))
    p = t.positions[pid]
    assert p.partial_price == pytest.approx(1.1070)
    assert p.realized_pnl == pytest.approx(0.0070 * 5000)


def test_fill_bar_gives_no_partial_credit():
    t = PaperTrader(so_cfg())
    pid = t.submit_signal(signal())
    # Fills (low 1.0998) and also trades to +1R and beyond on the same bar.
    ev = t.replay_bars("EURUSD=X", bars("2026-07-30T11:00Z", [(1.1010, 1.1060, 1.0998, 1.1055)]))
    p = t.positions[pid]
    assert p.status == TradeStatus.ACTIVE and not p.partial_taken
    assert p.runner_peak_r == 0.0 and ev["partials"] == []
    # The next bar that reaches +1R takes it.
    t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [(1.1055, 1.1056, 1.1040, 1.1045)]))
    assert t.positions[pid].partial_taken


# ------------------------------------------------------------------ runner
def test_runner_locks_at_2r_and_3r_and_exits_on_trail():
    t = PaperTrader(so_cfg())
    pid = filled_long(t)
    ev = t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [
        (1.1003, 1.1052, 1.1001, 1.1048),   # +1R: 50% off, BE from next bar
        (1.1048, 1.1105, 1.1040, 1.1100),   # peak 2.1R: lock +1R (1.1050) from next bar
        (1.1100, 1.1110, 1.1055, 1.1060),   # dips to 1.1055: lock not hit
        (1.1060, 1.1160, 1.1058, 1.1150),   # peak 3.2R: lock +2R (1.1100)
        (1.1150, 1.1152, 1.1095, 1.1098),   # hits the +2R lock
    ]))
    c = hist(t, pid)
    assert c.close_reason == "trail" and c.close_price == pytest.approx(1.1100)
    assert c.realized_pnl == pytest.approx(25.0 + 50.0)
    assert c.trade_r_multiple == pytest.approx(1.5)
    assert c.runner_peak_r == pytest.approx(3.2)
    kinds = [(e["event"], e.get("new_stop_r")) for e in ev["partials"]]
    assert kinds == [("partial_close", pytest.approx(0.0)), ("stop_moved", 1.0),
                     ("stop_moved", 2.0)]
    assert ev["partials"][1]["new_stop"] == pytest.approx(1.1050)


def test_lock_move_applies_from_the_next_bar_only():
    t = PaperTrader(so_cfg())
    pid = filled_long(t)
    t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [(1.1003, 1.1052, 1.1001, 1.1048)]))
    # Peak 2.2R and a dip to 1.1045 on the SAME bar: the +1R lock (1.1050) is
    # not in force yet, the breakeven stop (1.1000) is -> still open.
    t.replay_bars("EURUSD=X", bars("2026-07-30T13:00Z", [(1.1048, 1.1110, 1.1045, 1.1060)]))
    p = t.positions[pid]
    assert p.status == TradeStatus.ACTIVE and p.current_stop == pytest.approx(1.1050)
    t.replay_bars("EURUSD=X", bars("2026-07-30T14:00Z", [(1.1060, 1.1065, 1.1045, 1.1050)]))
    assert hist(t, pid).close_reason == "trail"


def test_same_bar_partial_and_2r_peak():
    t = PaperTrader(so_cfg())
    pid = filled_long(t)
    ev = t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [(1.1003, 1.1106, 1.1001, 1.1100)]))
    p = t.positions[pid]
    assert p.partial_taken and p.current_stop == pytest.approx(1.1050)   # +1R lock
    assert [e["event"] for e in ev["partials"]] == ["partial_close", "stop_moved"]


def test_runner_target_caps_the_runner():
    t = PaperTrader(so_cfg(runner_target_r=3.0))
    pid = filled_long(t)
    t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [
        (1.1003, 1.1052, 1.1001, 1.1048),
        (1.1048, 1.1155, 1.1040, 1.1150),   # +3R reached
    ]))
    c = hist(t, pid)
    assert c.close_reason == "runner_target" and c.close_price == pytest.approx(1.1150)
    assert c.trade_r_multiple == pytest.approx(0.5 + 1.5)


def test_runner_trail_none_rides_at_breakeven():
    t = PaperTrader(so_cfg(runner_trail="none"))
    pid = filled_long(t)
    ev = t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [
        (1.1003, 1.1052, 1.1001, 1.1048),
        (1.1048, 1.1170, 1.1040, 1.1160),   # +3.4R peak: no lock
        (1.1160, 1.1165, 1.0990, 1.1000),   # all the way back: breakeven
    ]))
    c = hist(t, pid)
    assert c.close_reason == "breakeven" and c.trade_r_multiple == pytest.approx(0.5)
    assert [e["event"] for e in ev["partials"]] == ["partial_close"]


def test_ladder_exits_do_not_fire_in_scale_out(monkeypatch):
    monkeypatch.setenv("BP_TYPE_LADDERS", "1")
    t = PaperTrader(so_cfg())
    pid = filled_long(t, trade_context="counter_trend")
    t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [
        (1.1003, 1.1027, 1.1001, 1.1020),   # half-T1: no breakeven
        (1.1020, 1.1105, 1.1015, 1.1100),   # T2: no counter-trend close, no 50% at T2
        (1.1100, 1.1160, 1.1090, 1.1150),   # T3: no close
    ]))
    p = t.positions[pid]
    assert p.status == TradeStatus.ACTIVE
    assert p.partial_price == pytest.approx(1.1050)       # the +1R partial only
    assert p.current_stop == pytest.approx(1.1100)        # +2R locked after the 3.2R peak


def test_zone_trailing_is_off_in_scale_out():
    t = PaperTrader(so_cfg())
    pid = filled_long(t)
    t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [(1.1003, 1.1052, 1.1001, 1.1048)]))
    t.apply_zone_trailing({"EURUSD=X": [{"zone_type": "demand", "proximal": 1.1040,
                                         "distal": 1.1030}]})
    assert t.positions[pid].current_stop == pytest.approx(1.1000)


# ------------------------------------------------------------------ risk gate
def test_activation_gate_counts_runner_at_breakeven_as_zero_risk():
    t = PaperTrader(so_cfg())
    pid = filled_long(t)
    ok, why = t._check_activation_gates("GBPUSD=X", 100.0)
    assert not ok and "daily loss" in why                    # 50 open + 100 new >= 150
    t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [(1.1003, 1.1052, 1.1001, 1.1048)]))
    assert t.positions[pid].breakeven_triggered
    ok, why = t._check_activation_gates("GBPUSD=X", 100.0)
    assert ok, why


# ------------------------------------------------------------------ legacy path
SEQ = [(1.1003, 1.1052, 1.1001, 1.1048), (1.1048, 1.1105, 1.1040, 1.1100),
       (1.1100, 1.1110, 1.1055, 1.1060), (1.1060, 1.1160, 1.1058, 1.1150),
       (1.1150, 1.1152, 1.1095, 1.1098)]


def test_legacy_single_bar_path_matches_replay(monkeypatch):
    t = PaperTrader(so_cfg())
    pid = filled_long(t)
    ev = t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", SEQ))
    rep = hist(t, pid)

    monkeypatch.setenv("BP_BAR_REPLAY", "0")
    t2 = PaperTrader(so_cfg())
    pid2 = t2.submit_signal(signal(price_at_zone=True, pending_order=True))
    assert t2.positions[pid2].status == TradeStatus.ACTIVE
    legacy_events = {"partials": []}
    closed = []
    for o, h, l, c in SEQ:
        closed += t2.update_positions({"EURUSD=X": {"open": o, "high": h, "low": l, "close": c,
                                                    "bid": c, "ask": c}}, events=legacy_events)
    leg = hist(t2, pid2)
    for k in ("close_reason", "close_price", "realized_pnl", "trade_r_multiple",
              "partial_price", "partial_qty", "runner_peak_r"):
        assert getattr(leg, k) == pytest.approx(getattr(rep, k)), k
    assert [(e["event"], e["new_stop"]) for e in legacy_events["partials"]] == \
        [(e["event"], e["new_stop"]) for e in ev["partials"]]
    assert closed[0]["close_reason"] == "trail" and closed[0]["r_multiple"] == pytest.approx(1.5)


def test_legacy_path_without_events_arg_still_works(monkeypatch):
    monkeypatch.setenv("BP_BAR_REPLAY", "0")
    t = PaperTrader(so_cfg())
    pid = t.submit_signal(signal(price_at_zone=True, pending_order=True))
    t.update_positions({"EURUSD=X": {"high": 1.1052, "low": 1.1001, "close": 1.1048}})
    assert t.positions[pid].partial_taken


# ------------------------------------------------------------------ persistence
def test_state_round_trip_keeps_scale_out_fields(monkeypatch, tmp_path):
    monkeypatch.setattr(rs, "PAPER_STATE_FILE", tmp_path / "paper_trader_state.json")
    t = PaperTrader(so_cfg())
    pid = filled_long(t)
    t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", SEQ[:2]))
    rs.save_paper_trader_state(t)
    raw = json.loads((tmp_path / "paper_trader_state.json").read_text())
    rec = raw["open_positions"][0]
    assert rec["partial_time"].endswith("+00:00") and rec["runner_peak_r"] == pytest.approx(2.1)

    t2 = PaperTrader(so_cfg())
    rs.load_paper_trader_state(t2)
    assert asdict(t2.positions[pid]) == asdict(t.positions[pid])
    # ...and it continues correctly after the reload.
    t2.replay_bars("EURUSD=X", bars("2026-07-30T14:00Z", SEQ[2:]))
    c = hist(t2, pid)
    assert c.close_reason == "trail" and c.trade_r_multiple == pytest.approx(1.5)


def test_old_state_record_without_new_fields_loads():
    old = {"id": "abc", "symbol": "EURUSD=X", "direction": "long", "entry_price": 1.1,
           "stop_price": 1.095, "current_stop": 1.095, "targets": [1.105, 1.11, 1.115],
           "position_size": 10000.0, "risk_amount": 50.0, "status": "active",
           "entry_time": "2026-07-30T11:00:00+00:00", "fill_price": 1.1,
           "last_priced_ts": "2026-07-30T12:00:00+00:00"}
    p = rs._position_from_dict(old)
    assert p.runner_peak_r == 0.0 and p.partial_time is None and not p.partial_taken
    t = PaperTrader(so_cfg())
    t.positions[p.id] = p
    t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [(1.1003, 1.1052, 1.1001, 1.1048)]))
    assert t.positions["abc"].partial_taken


LIVE_NZDCHF = {
    "id": "eb9cb892-2ec", "symbol": "NZDCHF=X", "direction": "long",
    "entry_price": 0.46562, "stop_price": 0.464, "current_stop": 0.464,
    "targets": [0.46724, 0.46886, 0.47048], "position_size": 14487.504541,
    "risk_amount": 23.47, "entry_time": "2026-09-27T18:28:50.251264+00:00",
    "status": "pending", "realized_pnl": 0.0, "partial_taken": False, "partial_qty": 0.0,
    "partial_price": 0.0, "breakeven_triggered": False, "trail_stop_level": None,
    "zone_id": "7595091cbf", "close_time": None, "close_price": None,
    "trade_r_multiple": 0.0, "close_reason": "", "notes": "", "income_strategy": "weekly",
    "trade_context": "counter_trend", "placed_at": "2026-09-27T18:28:50.251264+00:00",
    "filled_at": None, "last_priced_ts": "2026-09-28T00:00:00+00:00",
    "order_type": "limit", "setup_key": "NZDCHF=X|long|0.46562|0.464", "fill_price": None,
}


def test_live_nzdchf_pending_order_loads_and_runs_under_scale_out(monkeypatch, tmp_path):
    state = {"balance": 5000.0, "initial_balance": 5000.0, "closed_pnl_total": 0.0,
             "current_date": "2026-09-28", "account_blown": False,
             "challenge_started_at": "2026-09-27T13:45:25.355334+00:00",
             "open_positions": [LIVE_NZDCHF], "trade_history": [], "zone_memory": {}}
    (tmp_path / "paper_trader_state.json").write_text(json.dumps(state))
    monkeypatch.setattr(rs, "PAPER_STATE_FILE", tmp_path / "paper_trader_state.json")
    live = yaml.safe_load((HERE / "BP_config.yaml").read_text(encoding="utf-8"))
    t = PaperTrader(live)
    rs.load_paper_trader_state(t)
    p = t.positions["eb9cb892-2ec"]
    assert p.status == TradeStatus.PENDING and p.runner_peak_r == 0.0
    assert p.trade_context == "counter_trend" and t.scale_out
    # risk 0.00162: +1R = 0.46724, +2R = 0.46886.
    ev = t.replay_bars("NZDCHF=X", bars("2026-09-28T00:00Z", [
        (0.4660, 0.4661, 0.4655, 0.4657),     # fill at 0.46562
        (0.4657, 0.4673, 0.4656, 0.4671),     # +1R: 50% off, stop -> 0.46562
        (0.4671, 0.4690, 0.4668, 0.4688),     # +2.0R peak: lock +1R
    ]))
    assert len(ev["fills"]) == 1
    p = t.positions["eb9cb892-2ec"]
    assert p.partial_taken and p.partial_price == pytest.approx(0.46724)
    assert p.current_stop == pytest.approx(0.46724)
    assert [e["event"] for e in ev["partials"]] == ["partial_close", "stop_moved"]


def test_scan_history_and_results_carry_partials(monkeypatch, tmp_path):
    monkeypatch.setattr(rs, "SCAN_RESULTS_FILE", tmp_path / "scan_results.json")
    monkeypatch.setattr(rs, "SCAN_HISTORY_FILE", tmp_path / "scan_history.json")
    t = PaperTrader(so_cfg())
    filled_long(t)
    ev = t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [(1.1003, 1.1052, 1.1001, 1.1048)]))
    res = {"scan_time": "2026-07-30T13:05:00+00:00", "strategy": "weekly",
           "watchlist_scanned": 1, "signals_found": 0, "auto_traded": 0, "signals": [],
           "account": t.get_account_summary(), "fills": [], "closed_this_run": [],
           "partials_this_run": rs.json_safe(ev["partials"]),
           "management": rs.json_safe(t.management)}
    rs.save_results(res)
    h = json.loads((tmp_path / "scan_history.json").read_text())
    assert h[-1]["partials"][0]["event"] == "partial_close"
    assert h[-1]["partials"][0]["r_booked"] == pytest.approx(0.5)


# ------------------------------------------------------------------ Discord
def _gbpnzd_partial_event():
    return {"event": "partial_close", "position_id": "P-GBPNZD", "symbol": "GBPNZD=X",
            "direction": "short", "price": fx.L1, "fraction": 0.5, "pnl": 25.0,
            "r_booked": 0.5, "at_r": 1.0, "new_stop": fx.ENTRY, "new_stop_r": 0.0,
            "at": "2026-09-29T14:00:00+00:00", "entry_price": fx.ENTRY, "stop_price": fx.STOP}


def _gbpnzd_open_runner(stop=fx.ENTRY):
    half = fx.SIZE / 2
    return {"id": "P-GBPNZD", "symbol": "GBPNZD=X", "direction": "short", "status": "active",
            "entry_price": fx.ENTRY, "stop_price": fx.STOP, "current_stop": stop,
            "targets": [fx.L1, fx.R2, fx.R3], "fill_price": fx.ENTRY,
            "partial_taken": True, "partial_qty": half, "position_size": half,
            "partial_price": fx.L1, "partial_time": "2026-09-29T14:00:00+00:00",
            "realized_pnl": 25.0, "unrealized_pnl": 25.0, "breakeven_triggered": True}


def test_discord_partial_and_stop_move_block_text():
    lock = dict(_gbpnzd_partial_event(), event="stop_moved", price=fx.L1, new_stop=fx.L1,
                new_stop_r=1.0, fraction=None, pnl=0.0)
    txt = sd.partials_block([_gbpnzd_partial_event(), lock])
    assert "GBPNZD=X   SHORT  +1R reached: closed 50% at 2.34538" in txt
    assert "+$25.00, +0.50R booked" in txt
    assert "stop to breakeven 2.34939, runner 50% open" in txt
    assert "runner stop -> 2.34538 (+1R locked)" in txt
    assert max(len(ln) for ln in txt.splitlines()) <= 60


def test_partial_event_makes_the_run_post_and_is_reported_once():
    start = "2026-09-27T00:00:00+00:00"
    acct = {"prop_firm": {"challenge_started_at": start}}
    runner = _gbpnzd_open_runner()
    scan = {"scan_time": "2026-09-29T14:05:00+00:00", "signals": [], "positions": [runner],
            "pending_orders": [], "trade_history": [], "account": acct, "fills": [],
            "partials_this_run": [_gbpnzd_partial_event()]}
    prev = {"challenge_started_at": start, "open_position_ids_seen": ["P-GBPNZD"],
            "closed_ids_seen": [], "partial_events_seen": [], "runner_stops_seen": {},
            "last_status_date": "2026-09-29"}
    now = datetime(2026, 9, 29, 14, 5, tzinfo=UTC)
    ev = sd.compute_events(scan, prev)
    assert [e["event"] for e in ev["partials"]] == ["partial_close"]
    assert sd.decide_post(scan, prev, ev, now) == "news"
    msgs = sd.build_status_messages(scan, ev["closed"], fills=ev["fills"],
                                    cancelled=ev["cancelled"], partials=ev["partials"],
                                    title="TRADE UPDATE", now_utc=now)
    body = "\n".join(msgs)
    assert "PARTIAL CLOSES / STOP MOVES" in body
    assert "Booked 50% at 2.34538: +$25.00 (+0.50R)" in body
    assert "Runner 50% open, stop 2.34939 = breakeven" in body

    st = sd.build_state(scan, prev, ev, now, posted=True)
    assert "P-GBPNZD|partial" in st["partial_events_seen"]
    assert st["runner_stops_seen"] == {"P-GBPNZD": fx.ENTRY}
    # The next hourly run re-publishes nothing new -> quiet.
    scan2 = dict(scan, partials_this_run=[])
    ev2 = sd.compute_events(scan2, st)
    assert ev2["partials"] == [] and sd.decide_post(scan2, st, ev2, now) is None
    # A lock that happened in a run whose post failed is recovered from state.
    scan3 = dict(scan2, positions=[_gbpnzd_open_runner(stop=fx.L1)])
    ev3 = sd.compute_events(scan3, st)
    assert [(e["event"], e["new_stop"]) for e in ev3["partials"]] == [("stop_moved", fx.L1)]
    assert "runner stop -> 2.34538 (+1R locked)" in sd.partials_block(ev3["partials"])


def test_partial_backstop_when_the_posting_run_failed():
    start = "2026-09-27T00:00:00+00:00"
    scan = {"signals": [], "positions": [_gbpnzd_open_runner()], "pending_orders": [],
            "trade_history": [], "account": {"prop_firm": {"challenge_started_at": start}}}
    prev = {"challenge_started_at": start, "open_position_ids_seen": ["P-GBPNZD"],
            "closed_ids_seen": []}
    ev = sd.compute_events(scan, prev)
    (e,) = ev["partials"]
    assert e["event"] == "partial_close" and e["pnl"] == pytest.approx(25.0)
    assert e["r_booked"] == pytest.approx(0.5)


def test_closed_block_shows_the_blended_result():
    txt = sd.closed_block([fx.closed_trade("breakeven"), fx.closed_trade("trail")])
    assert "= +0.50R: 50% at +1R, runner breakeven" in txt
    assert "= +1.50R: 50% at +1R, runner stopped at +2R locked" in txt


def test_scale_out_signal_block_text():
    s = fx.signal()
    txt = sd._format_signal_block(s, 7.0, fx.SCALE_OUT)
    assert "At +1R: 2.34538 close 50% + stop to breakeven" in txt
    assert "+1R close 50%  :      2.34538  stop -> BE" in txt
    assert "+2R runner     :      2.34137  stop -> +1R" in txt
    assert "+3R runner     :      2.33736  stop -> +2R" in txt
    assert "+2R -> stop +1R, +3R -> stop +2R" in txt
    assert "First take     : +1R on 50%; runner open" in txt
    assert "R:R (to T2)" not in txt and "close 100% at Target 2" not in txt
    assert "Target 2 (2R)" not in txt
    new_lines = [ln for ln in txt.splitlines()
                 if "runner" in ln.lower() or "+1R" in ln or "MANAGEMENT" in ln
                 or "broker" in ln or "First take" in ln]
    assert len(new_lines) >= 8 and max(len(ln) for ln in new_lines) <= 56


def test_signal_block_text_is_unchanged_for_fixed_and_ladder():
    s = fx.signal()
    for mode in ("fixed", "ladder"):
        txt = sd._format_signal_block(s, 7.0, {"mode": mode})
        assert "R:R (to T2)    : 1: 2.00" in txt
        assert ">> MANAGEMENT  : stop never moves; close 100% at Target 2" in txt
        assert "Target 2 (2R)  :      2.34137" in txt
        assert "+1R close" not in txt


def test_signal_messages_use_the_scan_management(monkeypatch):
    seen = {}

    def fake_chart(sig, cache, asof=None, management=None):
        seen["mode"] = (management or {}).get("mode")
        return None
    monkeypatch.setattr(sd.draw_chart, "generate_chart", fake_chart)
    scan = {"scan_time": "2026-09-28T12:00:00+00:00", "management": {"mode": "fixed"},
            "ohlcv_cache": {}}
    msgs = sd.build_signals_messages(scan, [fx.signal()])
    assert "close 100% at Target 2" in msgs[0]["content"] and seen["mode"] == "fixed"
    scan["management"] = fx.SCALE_OUT
    msgs = sd.build_signals_messages(scan, [fx.signal()])
    assert "At +1R: 2.34538 close 50%" in msgs[0]["content"] and seen["mode"] == "scale_out"


def test_track_record_empty_text_follows_the_mode():
    assert "50% closes at +1R" in sd.track_record_block([], fx.SCALE_OUT)
    assert "100% at Target 2" in sd.track_record_block([], {"mode": "fixed"})


# ------------------------------------------------------------------ charts
def _check_png(path):
    try:
        assert path is not None and os.path.exists(path) and os.path.getsize(path) > 5000
        with open(path, "rb") as f:
            assert f.read(8) == b"\x89PNG\r\n\x1a\n"
    finally:
        if path and os.path.exists(path):
            os.remove(path)


def test_scale_out_signal_chart_png_gbpnzd_short():
    _check_png(draw_chart.generate_chart(fx.signal(), fx.cache(),
                                         asof="2026-09-28T12:00:00+00:00",
                                         management=fx.SCALE_OUT))


def test_scale_out_result_chart_png():
    for kind in ("breakeven", "trail"):
        _check_png(draw_chart.generate_trade_result_chart(fx.closed_trade(kind), fx.cache(),
                                                          timeframe="1d",
                                                          management=fx.SCALE_OUT))


def test_fixed_chart_still_draws_and_charts_never_raise():
    _check_png(draw_chart.generate_chart(fx.signal(), fx.cache(), management={"mode": "fixed"}))
    bad = dict(fx.closed_trade(), partial_price="x", partial_qty=None)
    p = draw_chart.generate_trade_result_chart(bad, fx.cache(), management=fx.SCALE_OUT)
    if p:
        os.remove(p)
    assert draw_chart.generate_chart({"symbol": "GBPNZD=X"}, fx.cache(),
                                     management=fx.SCALE_OUT) is None
