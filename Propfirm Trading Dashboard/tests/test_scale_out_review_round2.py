"""Regression tests for the second scale-out review round (2026-09-28,
research/scaleout_fix_log.md "Round 2"). One test (or a small group) per
finding. The gapped-stop-entry tests (major 1) live in
test_scale_out_review_fixes.py next to the round-1 tests they replace.

Run from the dashboard folder:
    python -m pytest tests -p no:cacheprovider -q
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

os.environ.setdefault("BP_STATE_DIR", tempfile.mkdtemp(prefix="bp_state_scaleout_r2_"))
os.environ.pop("DISCORD_WEBHOOK_URL", None)

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO / "research"))

import BP_management as bm                                          # noqa: E402
import BP_paper_trader as bpt                                       # noqa: E402
import draw_chart                                                   # noqa: E402
import reset_challenge                                              # noqa: E402
import run_scanner as rs                                            # noqa: E402
import send_discord as sd                                           # noqa: E402
import scaleout_fixtures as fx                                      # noqa: E402
import unbook_partials                                              # noqa: E402
from BP_paper_trader import PaperTrader, TradeStatus                # noqa: E402
from test_paper_trader_replay import bars, cfg, hist, signal        # noqa: E402
from test_paper_trader_scale_out import (LIVE_NZDCHF, filled_long, so_cfg,  # noqa: E402
                                         _gbpnzd_open_runner, _gbpnzd_partial_event)

UTC = timezone.utc
START = "2026-09-27T00:00:00+00:00"


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


def _scan(positions, partials=None, history=None, pending=None, management=None,
          signals=None, fills=None):
    s = {"scan_time": "2026-09-29T15:05:00+00:00", "signals": signals or [],
         "positions": positions, "pending_orders": pending or [],
         "trade_history": history or [],
         "account": {"prop_firm": {"challenge_started_at": START}}, "fills": fills or [],
         "partials_this_run": partials or []}
    if management is not None:
        s["management"] = management
    return s


def _prev(**kw):
    p = {"challenge_started_at": START, "open_position_ids_seen": ["P-GBPNZD"],
         "closed_ids_seen": [], "partial_events_seen": [], "runner_stops_seen": {},
         "last_status_date": "2026-09-29", "management_mode": "scale_out"}
    p.update(kw)
    return p


def _gbpnzd_single_open():
    return {"id": "P-SINGLE", "symbol": "GBPNZD=X", "display_name": "GBPNZD",
            "direction": "short", "status": "active", "entry_price": fx.ENTRY,
            "stop_price": fx.STOP, "current_stop": fx.STOP,
            "targets": [fx.L1, fx.R2, fx.R3], "fill_price": fx.ENTRY,
            "position_size": fx.SIZE, "management_mode": "scale_out",
            "scale_out_single": True}


# ====================================================== major 1: gapped stop entry
def test_fills_block_says_the_stop_order_gapped_past_1r():
    t = PaperTrader(so_cfg())
    pid = t.submit_signal(signal(order_type="stop", entry=1.1000, stop=1.0950))
    ev = t.replay_bars("EURUSD=X", bars("2026-07-30T11:00Z", [
        (1.0990, 1.0995, 1.0985, 1.0990), (1.1075, 1.1080, 1.1070, 1.1075)]))
    fill = dict(t.get_open_positions()[0], **ev["fills"][0])
    txt = sd.fills_block([fill], fx.SCALE_OUT)
    assert "stop order filled past +1R 1.10500" in txt
    assert "closed 50% at the fill 1.10750" in txt
    assert "set the runner's stop to breakeven 1.10750" in txt
    # The partial block explains the $0 partial too.
    ptxt = sd.partials_block(ev["partials"])
    assert "instantly marketable" in ptxt
    # A normal fill carries no such line.
    t2 = PaperTrader(so_cfg())
    filled_long(t2)
    assert "filled past" not in sd.fills_block(t2.get_open_positions(), fx.SCALE_OUT)


# ====================================================== major 2: ladder cadence
def _ladder_run_sequence(mode):
    c = so_cfg(management=mode)
    c["risk"]["correlation_check_enabled"] = False
    t = PaperTrader(c)
    E, R = 1.1000, 0.0050
    lv = lambda r: E + r * R                               # noqa: E731
    pid = filled_long(t)
    now = datetime(2026, 7, 30, 12, tzinfo=UTC)
    prev, reasons = {}, []
    for path in ([(0.2, 2.1, 0.1, 2.0)], [(2.0, 2.4, 1.9, 2.3)], [(2.3, 2.6, 2.2, 2.5)],
                 [(2.5, 2.8, 2.4, 2.7)]):
        df = pd.DataFrame([{"timestamp": now, "open": lv(o), "high": lv(h), "low": lv(l),
                            "close": lv(cl)} for (o, h, l, cl) in path])
        ev = t.replay_bars_multi({"EURUSD=X": df})
        now += timedelta(hours=1)
        sc = json.loads(json.dumps(rs.json_safe({
            "scan_time": (now + timedelta(minutes=5)).isoformat(),
            "account": t.get_account_summary(), "positions": t.get_open_positions(),
            "pending_orders": [], "trade_history": t.get_trade_history(), "signals": [],
            "fills": ev["fills"], "partials_this_run": ev["partials"],
            "management": t.management})))
        events = sd.compute_events(sc, prev)
        r = sd.decide_post(sc, prev, events, now + timedelta(minutes=5)) if prev else "first"
        reasons.append(r)
        prev = sd.build_state(sc, prev, events, now + timedelta(minutes=5), posted=bool(r))
    return t.positions[pid], reasons, prev


def test_ladder_trail_moves_never_post():
    p, reasons, prev = _ladder_run_sequence("ladder")
    assert p.partial_taken and p.current_stop > 1.1050      # the ladder trailed
    assert reasons[1:] == [None, None, None]
    assert prev["runner_stops_seen"] == {}                  # ladder runners not tracked


def test_backstop_reports_only_whole_r_scale_out_locks():
    runner = _gbpnzd_open_runner(stop=fx.R2)                # short: +2R lock
    runner["management_mode"] = "scale_out"
    ev = sd.compute_events(_scan([runner]), _prev(runner_stops_seen={"P-GBPNZD": fx.L1},
                                                  partial_events_seen=["P-GBPNZD|partial"]))
    assert [e["event"] for e in ev["partials"]] == ["stop_moved"]
    # a non-whole-R stop (ladder-style 1R trail) is not a scale-out lock
    odd = dict(runner, current_stop=fx.L1 - 0.3 * fx.RISK)
    ev = sd.compute_events(_scan([odd]), _prev(runner_stops_seen={"P-GBPNZD": fx.L1},
                                               partial_events_seen=["P-GBPNZD|partial"]))
    assert ev["partials"] == []
    # a ladder position is never reported, whatever its stop does
    lad = dict(runner, management_mode="ladder", partial_time=None, runner_peak_r=0)
    ev = sd.compute_events(_scan([lad]), _prev(runner_stops_seen={"P-GBPNZD": fx.L1},
                                               partial_events_seen=["P-GBPNZD|partial"]))
    assert ev["partials"] == []


# ====================================================== major 3: partial + runner close in one post
def _closed_runner(reason, close_px, stop):
    t = dict(_gbpnzd_open_runner(stop=stop), status="closed", close_reason=reason,
             close_price=close_px, management_mode="scale_out", realized_pnl=25.0)
    return t


def test_stop_move_and_close_in_one_post_says_close_order_b():
    closed = _closed_runner("trail", fx.L1, fx.L1)
    lock = {"event": "stop_moved", "position_id": "P-GBPNZD", "symbol": "GBPNZD=X",
            "direction": "short", "new_stop": fx.L1, "new_stop_r": 1.0,
            "at": "2026-09-29T14:00:00+00:00", "entry_price": fx.ENTRY, "stop_price": fx.STOP}
    ev = sd.compute_events(_scan([], partials=[lock], history=[closed]),
                           _prev(partial_events_seen=["P-GBPNZD|partial"]))
    txt = sd.partials_block(ev["partials"])
    assert "close order B (the runner) at market now" in txt
    assert "move the runner's stop" not in txt


def test_runner_closed_at_its_own_tp_needs_no_market_close():
    closed = _closed_runner("runner_target", fx.R3, fx.ENTRY)
    ev = sd.compute_events(_scan([], partials=[_gbpnzd_partial_event()], history=[closed]),
                           _prev())
    txt = sd.partials_block(ev["partials"])
    assert "order B's TP closed it" in txt and "at market" not in txt


# ====================================================== majors 4 / 8: mode-change notice
def _new_signal_order():
    sig = dict(fx.signal(), paper_trade_id="NEWORDER")
    order = dict(fx.signal(), id="NEWORDER", status="pending")
    return sig, order


def test_mode_change_never_lists_an_order_announced_in_the_same_post():
    sig, order = _new_signal_order()
    prev = _prev(open_position_ids_seen=[], management_mode="fixed")
    ev = sd.compute_events(_scan([], pending=[order], signals=[sig],
                                 management=fx.SCALE_OUT), prev)
    assert ev["new_signals"] and ev["mode_change"] is None
    # ... but an order announced before this run is listed
    old = dict(LIVE_NZDCHF, display_name="NZDCHF")
    prev = _prev(open_position_ids_seen=[], management_mode="fixed",
                 pending_orders_seen={old["id"]: {}})
    ev = sd.compute_events(_scan([], pending=[old, order], signals=[sig],
                                 management=fx.SCALE_OUT), prev)
    assert [o["id"] for o in ev["mode_change"]["orders"]] == [old["id"]]


def test_reset_state_records_the_mode_so_no_notice_follows(tmp_path):
    fresh = reset_challenge.fresh_discord_state(datetime.now(UTC))
    assert fresh["management_mode"] == bm.live_management()["mode"]
    sig, order = _new_signal_order()
    ev = sd.compute_events(_scan([], pending=[order], signals=[sig],
                                 management=bm.live_management()), fresh)
    assert ev["mode_change"] is None
    # the allcoins profile records its pinned 'fixed' mode
    base = bm.live_management()
    allc = reset_challenge._profile_config({"stop_loss": {"management": base["mode"]}},
                                           "_allcoins", tmp_path)
    assert reset_challenge.fresh_discord_state(datetime.now(UTC), allc)[
        "management_mode"] == "fixed"


# ====================================================== majors 5 / 9: mode-aware level lines
def test_pending_block_in_scale_out_has_no_t2_t3_and_says_how_to_place():
    pend = dict(LIVE_NZDCHF, display_name="NZDCHF")
    txt = sd.pending_orders_block([pend], fx.SCALE_OUT)
    assert "T2:" not in txt and "T3:" not in txt and "place as shown" not in txt
    assert "+1R(50%):0.46724" in txt and "runner: no TP, 1R trail" in txt
    assert "2 orders: A 50% TP +1R / B 50% no TP" in txt
    # fixed text unchanged
    ftxt = sd.pending_orders_block([pend], {"mode": "fixed"})
    assert "place as shown" in ftxt and "T2:0.46886" in ftxt


def test_open_and_filled_blocks_follow_the_trade_mode():
    runner = dict(_gbpnzd_open_runner(stop=fx.L1), management_mode="scale_out",
                  display_name="GBPNZD", current_price=fx.R2, unrealized_pnl=50.0 / 2 * 2)
    fresh = dict(fx.signal(), id="P2", status="active", fill_price=fx.ENTRY,
                 current_stop=fx.STOP, management_mode="scale_out", position_size=fx.SIZE,
                 current_price=fx.ENTRY, unrealized_pnl=0.0, r_multiple_open=0.0)
    txt = sd.open_positions_block([runner, fresh], fx.SCALE_OUT)
    assert "T1/T2/T3=targets" not in txt and "T2:" not in txt
    assert "+1R(50%):2.34538" in txt
    # runner row: $ labelled as the runner's, whole-trade R on its own line
    assert "runner +$50.00" in txt
    assert "Whole trade now: +1.50R (+$75.00 incl. booked)" in txt
    ftxt = sd.fills_block([fresh], fx.SCALE_OUT)
    assert "T2:" not in ftxt and "+1R(50%):2.34538" in ftxt
    # a position stamped fixed keeps its T-levels in a scale_out scan
    fixed_pos = dict(fresh, management_mode="fixed")
    assert "T2:2.34137" in sd.open_positions_block([fixed_pos], fx.SCALE_OUT)
    # fixed scan: byte-identical header and level line
    ftxt = sd.open_positions_block([dict(fresh, management_mode="fixed")], {"mode": "fixed"})
    assert "T1/T2/T3=targets" in ftxt and "SL:2.35340   T1:2.34538  T2:2.34137  T3:2.33736" in ftxt


# ====================================================== major 6: unsplittable lot
def test_unsplittable_lot_is_flagged_and_traded_as_one_order():
    assert bm.scale_out_unsplittable(0.01, fx.SCALE_OUT)
    assert not bm.scale_out_unsplittable(0.12, fx.SCALE_OUT)
    assert not bm.scale_out_unsplittable(0.01, {"mode": "fixed"})
    t = PaperTrader(so_cfg())
    pid = filled_long(t, scale_out_unsplittable=True)
    assert t.positions[pid].scale_out_single
    ev = t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [(1.1003, 1.1055, 1.1001, 1.1050)]))
    c = hist(t, pid)
    assert c.close_reason == "scale_out" and c.close_price == pytest.approx(1.1050)
    assert c.realized_pnl == pytest.approx(50.0) and not c.partial_taken
    assert ev["partials"] == []
    # Discord: one order, 100% at +1R, and a closed line that says so
    s = dict(fx.signal(), lot_size=0.01, units=1000, scale_out_unsplittable=True)
    txt = sd._format_signal_block(s, 7.0, fx.SCALE_OUT)
    assert "PLACE AS 1 ORDER: TP +1R 2.34538" in txt
    assert "Minimum lot: cannot split into 2 orders" in txt
    assert "100% at +1R; stop never moves" in txt
    assert "PLACE AS 2" not in txt and "Runner" not in txt and "B 0%" not in txt
    assert "+1R TP (100%)" in sd.closed_block(rs.json_safe(t.get_trade_history()))
    pend = dict(LIVE_NZDCHF, scale_out_single=True)
    assert "ONE order, TP +1R" in sd.pending_orders_block([pend], fx.SCALE_OUT)


def test_fraction_one_signal_text_is_a_single_take_profit():
    m = dict(fx.SCALE_OUT, scale_out_fraction=1.0)
    s = dict(fx.signal(), lot_size=0.12, units=12000)
    txt = sd._format_signal_block(s, 7.0, m)
    assert "PLACE AS 1 ORDER: TP +1R 2.34538" in txt and "Scale-out fraction is 100%" in txt
    assert "Runner 0%" not in txt and "B 0%" not in txt


def test_run_scanner_flags_the_minimum_lot(monkeypatch):
    # The flag is set right after lot sizing from the SAME helper the text uses.
    src = (HERE / "run_scanner.py").read_text(encoding="utf-8")
    assert 'if BP_scale_out_unsplittable(sz.lots, trader.management):' in src
    assert 's["scale_out_unsplittable"] = True' in src


def test_unsplittable_flag_survives_a_state_round_trip(monkeypatch, tmp_path):
    monkeypatch.setattr(rs, "PAPER_STATE_FILE", tmp_path / "state.json")
    t = PaperTrader(so_cfg())
    pid = t.submit_signal(signal(scale_out_unsplittable=True))
    rs.save_paper_trader_state(t)
    t2 = PaperTrader(so_cfg())
    rs.load_paper_trader_state(t2)
    assert t2.positions[pid].scale_out_single is True


# ====================================================== major 7: code rollback migration
def test_unbook_partials_lets_old_code_book_the_partial_once(monkeypatch, tmp_path):
    monkeypatch.setattr(bpt, "utcnow", lambda: datetime(2026, 7, 30, 0, 0, tzinfo=UTC))
    monkeypatch.setattr(rs, "PAPER_STATE_FILE", tmp_path / "state.json")
    t = PaperTrader(so_cfg())
    pid = filled_long(t)
    t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [(1.1003, 1.1055, 1.1001, 1.1050)]))
    assert t.balance == pytest.approx(5025.0)
    rs.save_paper_trader_state(t)
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))

    def old_code_close(st):
        # What pre-scale-out code does: it drops booked_pnl on load and books
        # the whole realized_pnl at the close.
        st = copy.deepcopy(st)
        for p in st["open_positions"]:
            p.pop("booked_pnl", None)
        (tmp_path / "state.json").write_text(json.dumps(st), encoding="utf-8")
        t2 = PaperTrader(so_cfg(management="fixed"))
        rs.load_paper_trader_state(t2)
        t2.replay_bars("EURUSD=X", bars("2026-07-30T13:00Z", [(1.1050, 1.1110, 1.1045, 1.1100)]))
        return t2

    # runner closes at T2 (+2R on half the size = +$50): trade = +$75
    assert old_code_close(state).balance == pytest.approx(5000 + 25 + 75)   # double count
    new, report = unbook_partials.unbook(state)
    assert new["balance"] == pytest.approx(5000.0) and new["closed_pnl_total"] == pytest.approx(0)
    assert new["daily_pnl"] == pytest.approx(0.0) and "today" in report[0]
    assert old_code_close(new).balance == pytest.approx(5000 + 75)          # once
    assert unbook_partials.unbook(new)[0] == new                            # idempotent


def test_unbook_partials_cli_dry_run_writes_nothing(tmp_path):
    st = {"balance": 5025.0, "initial_balance": 5000.0, "closed_pnl_total": 25.0,
          "daily_pnl": 25.0, "current_date": "2026-07-31",
          "open_positions": [{"id": "x", "symbol": "EURUSD=X", "status": "active",
                              "booked_pnl": 25.0, "partial_time": "2026-07-30T12:00:00+00:00"}]}
    f = tmp_path / "s.json"
    f.write_text(json.dumps(st), encoding="utf-8")
    out = subprocess.run([sys.executable, str(REPO / "research" / "unbook_partials.py"),
                          "--state", str(f)], capture_output=True, text=True)
    assert out.returncode == 0 and "[dry-run]" in out.stdout
    assert json.loads(f.read_text(encoding="utf-8")) == st
    new, _ = unbook_partials.unbook(st)
    assert new["daily_pnl"] == pytest.approx(25.0)      # partial was on an earlier day


# ====================================================== minor fixes
def test_gapped_breakeven_exit_is_labelled_truthfully():
    t = PaperTrader(so_cfg())
    pid = filled_long(t)
    t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [(1.1003, 1.1055, 1.1001, 1.1050),
                                                         (1.0970, 1.0975, 1.0960, 1.0965)]))
    c = hist(t, pid)
    assert c.close_reason == "breakeven_gap"
    txt = sd.closed_block(rs.json_safe(t.get_trade_history()))
    assert "runner gapped through breakeven, out at 1.09700 (-0.6R)" in txt
    assert "breakeven (gapped)" in txt
    # a clean breakeven exit is still 'breakeven'
    t2 = PaperTrader(so_cfg())
    p2 = filled_long(t2)
    t2.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [(1.1003, 1.1055, 1.1001, 1.1050),
                                                          (1.1010, 1.1012, 1.0990, 1.0995)]))
    assert hist(t2, p2).close_reason == "breakeven"


def test_ladder_breakeven_gap_keeps_the_old_reason(monkeypatch):
    t = PaperTrader(so_cfg(management="ladder"))
    pos = bpt.Position(id="L", symbol="EURUSD=X", direction=bpt.TradeDirection.LONG,
                       entry_price=1.1, stop_price=1.095, current_stop=1.1,
                       targets=[1.105, 1.11, 1.115], position_size=10000, risk_amount=50,
                       entry_time=datetime(2026, 7, 30, tzinfo=UTC), breakeven_triggered=True,
                       fill_price=1.1)
    assert t._stop_close_reason(pos) == "breakeven"
    assert t._stop_close_reason(pos, 1.097) == "breakeven_gap"   # only when asked (scale_out)


def test_result_chart_runner_label_keeps_its_sign(monkeypatch):
    seen = []
    monkeypatch.setattr(draw_chart._Canvas, "corner",
                        lambda self, text, *a, **k: seen.append(text))
    t = fx.closed_trade("trail")
    # the runner gapped through its +1R lock to below entry (short: above entry)
    t.update(current_stop=fx.L1, trail_stop_level=fx.L1, close_price=fx.ENTRY + 0.5 * fx.RISK,
             realized_pnl=12.5, pnl=12.5, r_multiple=0.25)
    path = draw_chart.generate_trade_result_chart(t, fx.cache(), timeframe="1d",
                                                  management=fx.SCALE_OUT)
    try:
        assert any("runner gapped lock -0.5R" in s for s in seen), seen
        assert not any("+0.5R lock" in s for s in seen)
    finally:
        if path and os.path.exists(path):
            os.remove(path)


def test_runner_exit_text_keeps_fractional_targets():
    tr = {"direction": "long", "entry_price": 1.1, "stop_price": 1.095, "partial_taken": True,
          "partial_qty": 5000, "position_size": 5000, "partial_price": 1.105,
          "close_price": 1.1075, "close_reason": "runner_target", "realized_pnl": 62.5,
          "r_multiple": 1.25, "management_mode": "scale_out"}
    assert "runner target +1.5R" in sd.closed_block([tr])


def test_invalid_settings_fall_back_to_fixed_loudly(caplog):
    for sl in ({"management": "fixd"},
               {"management": "scale_out", "runner_target_r": 0.5},
               {"management": "scale_out", "runner_target_r": 1.0},
               {"management": "scale_out", "scale_out_fraction": 0},
               {"management": "scale_out", "scale_out_at_r": -1},
               {"management": "scale_out", "scale_out_at_r": "abc"}):
        m = bm.management_settings({"stop_loss": sl})
        assert m["mode"] == "fixed" and m["errors"], sl
        assert PaperTrader({"stop_loss": sl}).fixed_bracket
    assert any(r.levelname == "ERROR" for r in caplog.records)
    ok = bm.management_settings({"stop_loss": {"management": "scale_out", "runner_target_r": 3}})
    assert ok["mode"] == "scale_out" and "errors" not in ok
    # the missing key still means scale_out (the 2026-09-28 default)
    assert bm.management_settings({})["mode"] == "scale_out"
    # the Discord footer shows the rejected setting
    scan = {"management": bm.management_settings({"stop_loss": {"management": "fixd"}}),
            "watchlist_scanned": 1, "errors": [], "signals": []}
    assert "[!] CONFIG: stop_loss.management='fixd'" in sd.footer_block(scan)


def test_ladder_partial_gets_no_scale_out_lines():
    lad = {"id": "L1", "symbol": "EURUSD=X", "direction": "long", "entry_price": 1.1,
           "stop_price": 1.09, "partial_taken": True, "partial_qty": 5000,
           "position_size": 5000, "partial_price": 1.12, "close_price": 1.13,
           "close_reason": "T3", "realized_pnl": 250.0, "r_multiple": 2.5,
           "management_mode": "ladder", "current_stop": 1.12, "targets": [1.11, 1.12, 1.13]}
    assert "= +" not in sd.closed_block([lad])
    otxt = sd.open_positions_block([dict(lad, status="active")], {"mode": "ladder"})
    assert "Booked" not in otxt and "Runner" not in otxt and "T2:1.12000" in otxt


def test_chart_subtitle_and_track_record_follow_the_runner_settings(monkeypatch):
    heads = []
    monkeypatch.setattr(draw_chart._Canvas, "header",
                        lambda self, title, colour, sub: heads.append(sub))
    for mg, want in ((dict(fx.SCALE_OUT, runner_trail="none"), "runner stop at BE"),
                     (dict(fx.SCALE_OUT, runner_target_r=3.0), "runner to +3R"),
                     (fx.SCALE_OUT, "runner trails")):
        path = draw_chart.generate_chart(fx.signal(), fx.cache(), management=mg)
        if path and os.path.exists(path):
            os.remove(path)
        assert want in heads[-1], heads[-1]
    path = draw_chart.generate_chart(dict(fx.signal(), scale_out_unsplittable=True),
                                     fx.cache(), management=fx.SCALE_OUT)
    if path and os.path.exists(path):
        os.remove(path)
    assert "100% off at +1R (one order)" in heads[-1]
    tr = sd.track_record_block([], dict(fx.SCALE_OUT, runner_trail="none"))
    assert "stop stays at breakeven" in tr and "1R steps" not in tr
    tr = sd.track_record_block([], dict(fx.SCALE_OUT, runner_target_r=3.0))
    assert "closes at +3R" in tr
    assert "Ladder:" in sd.track_record_block([], {"mode": "ladder"})
    assert sd.track_record_block([], {"mode": "fixed"}).endswith(
        "Each position closes at its stop or 100% at Target 2 (stop never moves).")


def test_signal_block_runner_target_below_2r_has_no_dangling_steps_line():
    m = dict(fx.SCALE_OUT, runner_target_r=1.5)
    txt = sd._format_signal_block(dict(fx.signal(), lot_size=0.12), 7.0, m)
    assert "trails in 1R steps:" not in txt
    assert "+1.5R runner TP : " in txt


def test_stop_moved_line_has_time_and_broker_instruction():
    e = {"event": "stop_moved", "position_id": "P-GBPNZD", "symbol": "GBPNZD=X",
         "direction": "short", "new_stop": fx.L1, "new_stop_r": 1.0,
         "at": "2026-09-29T14:00:00+00:00", "entry_price": fx.ENTRY, "stop_price": fx.STOP}
    txt = sd.partials_block([e])
    assert "29 Sep 14:00 UTC" in txt
    assert ">> Broker: move the runner's stop to 2.34538" in txt
    assert max(len(ln) for ln in txt.splitlines()) <= 60


def test_allcoins_profile_is_pinned_to_fixed():
    import yaml
    base = yaml.safe_load((HERE / "BP_config.yaml").read_text(encoding="utf-8"))
    ov = yaml.safe_load((HERE / "BP_config_allcoins.yaml").read_text(encoding="utf-8"))
    assert PaperTrader(rs._deep_merge(base, ov)).mode == "fixed"
    assert '"stop_loss": {"management": "fixed"}' in (HERE / "_gen_allcoins_config.py").read_text(
        encoding="utf-8")


def test_replay_trades_records_the_management_mode():
    sys.path.insert(0, str(HERE / "goldtest"))
    import replay_trades
    mode = replay_trades.replay_management_mode()
    assert mode == bm.live_management()["mode"]
    assert replay_trades.summarise([], "x")["management"] == mode


# ====================================================== follow-ups found while regenerating samples
def test_gapped_fill_breakeven_is_labelled_breakeven_not_plus_r():
    t = PaperTrader(so_cfg())
    t.submit_signal(signal(order_type="stop", entry=1.1000, stop=1.0950))
    t.replay_bars("EURUSD=X", bars("2026-07-30T11:00Z", [
        (1.0990, 1.0995, 1.0985, 1.0990), (1.1010, 1.1015, 1.1005, 1.1012),
        (1.1012, 1.1055, 1.1010, 1.1050)]))
    op = rs.json_safe(t.get_open_positions())
    txt = sd.open_positions_block(op, fx.SCALE_OUT)
    assert "stop 1.10100 = breakeven" in txt
    # the FILLED block shows the bracket as placed (the original stop)
    assert "SL:1.09500  +1R(50%):1.10500" in sd.fills_block(op, fx.SCALE_OUT)


def test_price_exactly_at_the_new_stop_is_not_past_it():
    assert sd._through_stop_line(True, 1.1, 1.1) == []
    assert sd._through_stop_line(True, 1.1, 1.0999)
    assert sd._through_stop_line(False, 1.1, 1.1001)


def test_closed_text_for_a_partial_taken_at_a_gapped_fill():
    tr = {"direction": "long", "entry_price": 1.1, "stop_price": 1.095, "fill_price": 1.1075,
          "partial_taken": True, "partial_qty": 5000, "position_size": 5000,
          "partial_price": 1.1075, "close_price": 1.1075, "close_reason": "breakeven",
          "realized_pnl": 0.0, "r_multiple": 0.0, "management_mode": "scale_out"}
    assert "50% at the fill (gapped past +1R), runner breakeven" in sd.closed_block([tr])


def test_unflagged_minimum_lot_never_prints_an_impossible_split():
    s = dict(fx.signal(), lot_size=0.01, units=1000)
    txt = sd._format_signal_block(s, 7.0, fx.SCALE_OUT)
    assert "PLACE AS 1 ORDER" in txt and "PLACE AS 2" not in txt


def test_runner_closed_lines_fit_a_phone():
    closed = _closed_runner("breakeven", fx.ENTRY, fx.ENTRY)
    ev = sd.compute_events(_scan([], partials=[_gbpnzd_partial_event()], history=[closed]),
                           _prev())
    assert max(len(ln) for ln in sd.partials_block(ev["partials"]).splitlines()) <= 60


def test_ladder_text_follows_its_breakeven_setting():
    lad_half = bm.management_settings({"stop_loss": {"management": "ladder"}})
    lad_t1 = bm.management_settings({"stop_loss": {"management": "ladder",
                                                   "breakeven_at_half_target": False}})
    assert "breakeven at half-way to T1" in sd._format_signal_block(fx.signal(), 7.0, lad_half)
    assert "breakeven at T1;" in sd._format_signal_block(fx.signal(), 7.0, lad_t1)
    assert "breakeven at T1," in sd.track_record_block([], lad_t1)
    # and the paper trader does the same thing
    assert PaperTrader({"stop_loss": {"management": "ladder",
                                      "breakeven_at_half_target": False}}).breakeven_at_half is False
