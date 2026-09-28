"""Regression tests for the 2026-09-28 scale-out review findings
(research/scaleout_fix_log.md). One test (or a small group) per finding.

Run from the dashboard folder:
    python -m pytest tests -p no:cacheprovider -q
"""
import copy
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

os.environ.setdefault("BP_STATE_DIR", tempfile.mkdtemp(prefix="bp_state_scaleout_fix_"))
os.environ.pop("DISCORD_WEBHOOK_URL", None)

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import BP_management as bm                                          # noqa: E402
import BP_paper_trader as bpt                                       # noqa: E402
import draw_chart                                                   # noqa: E402
import run_scanner as rs                                            # noqa: E402
import send_discord as sd                                           # noqa: E402
import scaleout_fixtures as fx                                      # noqa: E402
from BP_paper_trader import PaperTrader, TradeStatus                # noqa: E402
from test_paper_trader_replay import bars, cfg, hist, signal        # noqa: E402
from test_paper_trader_scale_out import (LIVE_NZDCHF, filled_long, so_cfg,  # noqa: E402
                                         _gbpnzd_open_runner, _gbpnzd_partial_event)

UTC = timezone.utc


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


# =================================================================== engine
# --- 1/7/10: the +1R partial is booked to the account when it happens ---------
@pytest.fixture
def july_clock(monkeypatch):
    """The daily-loss day only rolls FORWARD; pin the wall clock before the
    July 2026 test bars so bar time drives the day roll."""
    monkeypatch.setattr(bpt, "utcnow", lambda: datetime(2026, 7, 30, 0, 0, tzinfo=UTC))


def test_partial_is_booked_to_balance_and_daily_pnl_on_its_own_day(july_clock):
    t = PaperTrader(so_cfg())
    pid = filled_long(t)                                    # 2026-07-30 11:00
    t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [(1.1003, 1.1055, 1.1001, 1.1050)]))
    p = t.positions[pid]
    assert p.partial_taken and p.booked_pnl == pytest.approx(25.0)
    # Credited now, as FundingPips does for a partial close.
    assert t.balance == pytest.approx(5025.0)
    assert t.closed_pnl_total == pytest.approx(25.0)
    assert t.daily_pnl == pytest.approx(25.0)
    assert t.peak_balance == pytest.approx(5025.0)
    # Not counted as a closed trade yet.
    assert t.total_trades == 0 and t.winning_trades == 0
    # The open row's P&L no longer carries the booked half.
    assert t.get_open_positions()[0]["unrealized_pnl"] == pytest.approx(0.0)

    # The runner closes at breakeven on the NEXT trading day: that day's P&L
    # gets only the runner (0), not the partial again.
    t.replay_bars("EURUSD=X", bars("2026-07-31T12:00Z", [(1.1010, 1.1012, 1.0995, 1.0999)]))
    c = hist(t, pid)
    assert c.close_reason == "breakeven" and c.realized_pnl == pytest.approx(25.0)
    assert t.current_date == "2026-07-31"
    assert t.daily_pnl == pytest.approx(0.0)
    assert t.balance == pytest.approx(5025.0)              # no double count
    assert t.closed_pnl_total == pytest.approx(25.0)
    assert t.winning_trades == 1 and t.total_trades == 1
    assert c.trade_r_multiple == pytest.approx(0.5)


def test_gapped_runner_loss_lands_on_its_own_day_net_of_the_partial(july_clock):
    t = PaperTrader(so_cfg())
    pid = filled_long(t)
    t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [(1.1003, 1.1055, 1.1001, 1.1050)]))
    assert t.daily_pnl == pytest.approx(25.0)
    # Next day the runner gaps through breakeven: exits at the open 1.0940
    # (-0.0060 x 5,000 = -$30). The broker shows -$30 that day, not -$5.
    t.replay_bars("EURUSD=X", bars("2026-07-31T12:00Z", [(1.0940, 1.0945, 1.0930, 1.0935)]))
    c = hist(t, pid)
    assert c.close_reason == "breakeven" and c.realized_pnl == pytest.approx(-5.0)
    assert t.daily_pnl == pytest.approx(-30.0)
    assert t.balance == pytest.approx(4995.0)
    assert t.losing_trades == 1                              # whole trade lost $5


def test_account_summary_shows_the_booked_partial():
    t = PaperTrader(so_cfg())
    filled_long(t)
    t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [(1.1003, 1.1055, 1.1001, 1.1050)]))
    a = t.get_account_summary()
    assert a["balance"] == pytest.approx(5025.0) and a["equity"] == pytest.approx(5025.0)
    assert a["closed_pnl"] == pytest.approx(25.0)
    assert a["prop_firm"]["current_equity"] == pytest.approx(5025.0)


def test_legacy_path_books_the_partial_too(monkeypatch):
    monkeypatch.setenv("BP_BAR_REPLAY", "0")
    t = PaperTrader(so_cfg())
    pid = t.submit_signal(signal(price_at_zone=True, pending_order=True))
    t.update_positions({"EURUSD=X": {"high": 1.1052, "low": 1.1001, "close": 1.1048}})
    assert t.positions[pid].partial_taken
    assert t.balance == pytest.approx(5025.0) and t.closed_pnl_total == pytest.approx(25.0)
    t.update_positions({"EURUSD=X": {"high": 1.1010, "low": 1.0990, "close": 1.0995}})
    assert t.balance == pytest.approx(5025.0) and t.total_trades == 1


def test_ladder_and_fixed_do_not_prebook():
    t = PaperTrader(cfg())                                   # ladder
    pid = t.submit_signal(signal())
    t.replay_bars("EURUSD=X", bars("2026-07-30T11:00Z", [(1.1005, 1.1008, 1.0998, 1.1003)]))
    t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [(1.1003, 1.1105, 1.1001, 1.1100)]))
    assert t.positions[pid].partial_taken and t.positions[pid].booked_pnl == 0.0
    assert t.balance == pytest.approx(5000.0)                # unchanged ladder behaviour


# --- 2: fill bar that already traded through +1R ----------------------------------
def test_fill_bar_through_l1_books_the_partial_at_the_level_not_the_next_open():
    t = PaperTrader(so_cfg())
    pid = t.submit_signal(signal())
    # Fills at 1.1000 and runs to +2.5R (1.1125) on the same bar.
    t.replay_bars("EURUSD=X", bars("2026-07-30T11:00Z", [(1.1005, 1.1126, 1.0995, 1.1125)]))
    p = t.positions[pid]
    assert p.status == TradeStatus.ACTIVE and not p.partial_taken
    assert p.fill_bar_extreme == pytest.approx(1.1126)
    ev = t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [(1.1125, 1.1125, 1.1040, 1.1045)]))
    p = t.positions[pid]
    # A take-profit resting at +1R would have filled AT 1.1050 on the fill bar.
    assert p.partial_price == pytest.approx(1.1050)
    assert ev["partials"][0]["pnl"] == pytest.approx(25.0)
    assert p.fill_bar_extreme is None                         # used once


def test_real_gap_after_a_quiet_fill_bar_still_gets_gap_credit():
    t = PaperTrader(so_cfg())
    pid = filled_long(t)                                     # fill bar high 1.1008
    t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [(1.1070, 1.1080, 1.1060, 1.1075)]))
    assert t.positions[pid].partial_price == pytest.approx(1.1070)


# --- 11: a gapped stop entry measures +1R from its fill --------------------------
def test_gapped_buy_stop_measures_l1_from_the_fill_and_never_books_a_loss():
    t = PaperTrader(so_cfg())
    pid = t.submit_signal(signal(order_type="stop", entry=1.1000, stop=1.0950))
    t.replay_bars("EURUSD=X", bars("2026-07-30T11:00Z", [
        (1.0990, 1.0995, 1.0985, 1.0990),
        (1.1075, 1.1080, 1.1070, 1.1075),     # buy-stop gaps: filled at 1.1075 (+1.5R)
        (1.1074, 1.1078, 1.1065, 1.1070),     # above planned +1R 1.1050: NOT a partial
    ]))
    p = t.positions[pid]
    assert p.fill_price == pytest.approx(1.1075) and not p.partial_taken
    ev = t.replay_bars("EURUSD=X", bars("2026-07-30T14:00Z", [(1.1070, 1.1130, 1.1068, 1.1120)]))
    p = t.positions[pid]
    (e,) = [x for x in ev["partials"] if x["event"] == "partial_close"]
    assert e["price"] == pytest.approx(1.1125)               # fill + 1R
    assert e["pnl"] == pytest.approx(25.0) and e["pnl"] > 0
    assert p.current_stop == pytest.approx(1.1075)           # breakeven = the fill


def test_gapped_sell_stop_mirror():
    t = PaperTrader(so_cfg())
    pid = t.submit_signal(signal(direction="short", order_type="stop", entry=1.1000,
                                 stop=1.1050, targets=(1.0950, 1.0900, 1.0850)))
    t.replay_bars("EURUSD=X", bars("2026-07-30T11:00Z", [
        (1.1010, 1.1015, 1.1005, 1.1010),
        (1.0925, 1.0930, 1.0920, 1.0925),     # sell-stop gaps: filled at 1.0925
        (1.0926, 1.0935, 1.0921, 1.0930),     # below planned +1R 1.0950: NOT a partial
    ]))
    assert not t.positions[pid].partial_taken
    ev = t.replay_bars("EURUSD=X", bars("2026-07-30T14:00Z", [(1.0930, 1.0932, 1.0870, 1.0880)]))
    (e,) = [x for x in ev["partials"] if x["event"] == "partial_close"]
    assert e["price"] == pytest.approx(1.0875) and e["pnl"] == pytest.approx(25.0)


# --- 3: runner and new entries ------------------------------------------------------
def _runner_at_be(**stop_kw):
    c = so_cfg(**stop_kw)
    c["risk"]["correlation_check_enabled"] = True
    t = PaperTrader(c)
    pid = filled_long(t)
    t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [(1.1003, 1.1055, 1.1001, 1.1050)]))
    assert t._is_derisked_runner(t.positions[pid])
    return t


def test_runner_still_blocks_a_correlated_entry_by_default(caplog):
    t = _runner_at_be()
    with caplog.at_level("INFO", logger="BP_paper_trader"):
        ok, why = t._check_activation_gates("GBPUSD=X", 50.0)
    assert not ok and "correlated" in why
    assert "blocked only by de-risked runner" in caplog.text


def test_runner_blocks_new_entries_false_lets_a_correlated_entry_in():
    t = _runner_at_be(runner_blocks_new_entries=False)
    ok, why = t._check_activation_gates("GBPUSD=X", 50.0)
    assert ok, why
    # ...and it does not count toward max_open_positions either.
    t.max_positions = 1
    assert t._check_activation_gates("AUDJPY=X", 50.0)[0]
    t2 = _runner_at_be()
    t2.max_positions = 1
    assert not t2._check_activation_gates("AUDJPY=X", 50.0)[0]


def test_unpartialled_position_is_never_a_runner():
    c = so_cfg(runner_blocks_new_entries=False)
    c["risk"]["correlation_check_enabled"] = True
    t = PaperTrader(c)
    filled_long(t)
    ok, why = t._check_activation_gates("GBPUSD=X", 10.0)
    assert not ok and "correlated" in why


def test_management_settings_reads_the_runner_flag():
    assert bm.management_settings({})["runner_blocks_new_entries"] is True
    assert bm.management_settings({"stop_loss": {"runner_blocks_new_entries": "false"}})[
        "runner_blocks_new_entries"] is False


# --- persistence of the new fields ---------------------------------------------------
def test_new_fields_survive_save_and_load(monkeypatch, tmp_path):
    monkeypatch.setattr(rs, "PAPER_STATE_FILE", tmp_path / "paper_trader_state.json")
    t = PaperTrader(so_cfg())
    pid = t.submit_signal(signal())
    t.replay_bars("EURUSD=X", bars("2026-07-30T11:00Z", [(1.1005, 1.1030, 1.0998, 1.1020)]))
    assert t.positions[pid].fill_bar_extreme == pytest.approx(1.1030)
    assert t.positions[pid].management_mode == "scale_out"
    rs.save_paper_trader_state(t)
    t2 = PaperTrader(so_cfg())
    rs.load_paper_trader_state(t2)
    p2 = t2.positions[pid]
    assert p2.fill_bar_extreme == pytest.approx(1.1030) and p2.management_mode == "scale_out"
    t2.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [(1.1020, 1.1055, 1.1015, 1.1050)]))
    assert t2.positions[pid].booked_pnl == pytest.approx(25.0)
    rs.save_paper_trader_state(t2)
    t3 = PaperTrader(so_cfg())
    rs.load_paper_trader_state(t3)
    assert t3.positions[pid].booked_pnl == pytest.approx(25.0)
    assert t3.balance == pytest.approx(5025.0)
    # Close after the reload: the partial is not booked a second time.
    t3.replay_bars("EURUSD=X", bars("2026-07-30T13:00Z", [(1.1010, 1.1012, 1.0995, 1.0999)]))
    assert t3.balance == pytest.approx(5025.0)


def test_old_record_without_the_new_fields_loads_with_safe_defaults():
    p = rs._position_from_dict(dict(LIVE_NZDCHF))
    assert p.booked_pnl == 0.0 and p.fill_bar_extreme is None and p.management_mode == ""


# =================================================================== Discord
START = "2026-09-27T00:00:00+00:00"


def _scan(positions, partials=None, history=None, pending=None, management=None):
    s = {"scan_time": "2026-09-29T15:05:00+00:00", "signals": [], "positions": positions,
         "pending_orders": pending or [], "trade_history": history or [],
         "account": {"prop_firm": {"challenge_started_at": START}}, "fills": [],
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


# --- 4: a late-reported partial never loosens the stop ------------------------------
def test_backstop_partial_is_ordered_before_the_lock_and_does_not_loosen_the_stop():
    lock = {"event": "stop_moved", "position_id": "P-GBPNZD", "symbol": "GBPNZD=X",
            "direction": "short", "price": fx.L1, "new_stop": fx.L1, "new_stop_r": 1.0,
            "at": "2026-09-29T15:00:00+00:00", "entry_price": fx.ENTRY, "stop_price": fx.STOP}
    scan = _scan([_gbpnzd_open_runner(stop=fx.L1)], partials=[lock])
    ev = sd.compute_events(scan, _prev())         # the partial's own post failed
    assert [e["event"] for e in ev["partials"]] == ["partial_close", "stop_moved"]
    txt = sd.partials_block(ev["partials"])
    assert "stop to breakeven" not in txt
    assert "stop since moved to 2.34538 (+1R locked)" in txt
    lines = txt.splitlines()
    last_stop = [ln for ln in lines if "stop" in ln][-1]
    assert "2.34538" in last_stop


# --- 5: upgrade run does not report ladder-era partials ------------------------------
def test_upgrade_run_ignores_ladder_era_partials():
    ladder = dict(_gbpnzd_open_runner(stop=fx.L1), partial_time=None, runner_peak_r=0.0,
                  partial_price=fx.R2)
    prev = _prev()
    del prev["runner_stops_seen"]
    ev = sd.compute_events(_scan([ladder]), prev)
    assert ev["partials"] == []
    # Same with the key present: a ladder partial is never a "+1R reached".
    ev = sd.compute_events(_scan([ladder]), _prev())
    assert ev["partials"] == []


def test_upgrade_run_skips_a_partial_already_covered_by_the_last_post():
    prev = _prev(last_sent_at="2026-09-29T14:30:00+00:00")
    del prev["runner_stops_seen"]
    ev = sd.compute_events(_scan([_gbpnzd_open_runner()]), prev)   # partial 14:00
    assert ev["partials"] == []
    prev["last_sent_at"] = "2026-09-29T13:30:00+00:00"
    ev = sd.compute_events(_scan([_gbpnzd_open_runner()]), prev)
    assert [e["event"] for e in ev["partials"]] == ["partial_close"]


def test_upgrade_run_on_a_real_ladder_state_posts_no_partial():
    state = json.loads((HERE / "paper_trader_state_allcoins.json").read_text(encoding="utf-8"))
    positions = [rs.json_safe(p) for p in state.get("open_positions", [])]
    assert any(p.get("partial_taken") for p in positions)
    prev = _prev(open_position_ids_seen=[p["id"] for p in positions])
    del prev["runner_stops_seen"]
    ev = sd.compute_events(_scan(positions), prev)
    assert ev["partials"] == []


# --- 6: partial and runner close in the same run ------------------------------------
def test_partial_and_close_in_one_run_does_not_say_move_the_stop():
    t = PaperTrader(so_cfg())
    pid = filled_long(t)
    ev = t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [
        (1.1003, 1.1055, 1.1000, 1.1052), (1.1052, 1.1053, 1.0995, 1.0998)]))
    th = t.get_trade_history()
    scan = {"scan_time": "2026-07-30T14:05:00+00:00", "signals": [], "positions": [],
            "pending_orders": [], "trade_history": th,
            "account": {"prop_firm": {"challenge_started_at": START}}, "fills": [],
            "partials_this_run": rs.json_safe(ev["partials"])}
    prev = _prev(open_position_ids_seen=[pid])
    out = sd.compute_events(json.loads(json.dumps(rs.json_safe(scan))), prev)
    assert out["partials"][0]["runner_closed"] is True
    txt = sd.partials_block(out["partials"])
    assert "runner 50% closed since (see CLOSED)" in txt
    assert "move the runner's stop" not in txt and "runner 50% open" not in txt


# --- a stop already through the market is flagged ------------------------------------
def test_stop_already_through_the_price_is_flagged():
    e = dict(_gbpnzd_partial_event(), current_price=fx.ENTRY + 0.0003,
             current_stop=fx.ENTRY)                       # short: price above BE
    txt = sd.partials_block([e])
    assert "is already past it" in txt and "close the runner at market" in txt
    e["current_price"] = fx.L1
    assert "already past" not in sd.partials_block([e])


# --- 8: how to mirror the scale-out at the broker ------------------------------------
def test_signal_block_tells_how_to_split_the_order():
    s = dict(fx.signal(), lot_size=0.12, units=12000)
    txt = sd._format_signal_block(s, 7.0, fx.SCALE_OUT)
    assert ">> PLACE AS 2 ORDERS (same entry + stop):" in txt
    assert "A 0.06 lots, TP +1R 2.34538" in txt
    assert "B 0.06 lots, no take-profit (runner)" in txt
    s2 = dict(s, lot_size=0.01)
    assert "Lot too small to split" in sd._format_signal_block(s2, 7.0, fx.SCALE_OUT)
    tgt = dict(fx.SCALE_OUT, runner_target_r=3.0)
    assert "B 0.06 lots, TP +3R 2.33736" in sd._format_signal_block(s, 7.0, tgt)
    # fixed / ladder text unchanged
    assert "PLACE AS 2 ORDERS" not in sd._format_signal_block(s, 7.0, {"mode": "fixed"})


def test_partial_block_is_an_instruction():
    txt = sd.partials_block([_gbpnzd_partial_event()])
    assert ">> Broker: close 50% unless order A's TP filled;" in txt
    assert "move the runner's stop to 2.34939" in txt
    assert max(len(ln) for ln in txt.splitlines()) <= 60


def test_mode_change_notice_for_the_live_nzdchf_order():
    pend = dict(LIVE_NZDCHF, display_name="NZDCHF")
    # The live discord_state.json (written by the 'fixed' bot) in this checkout.
    live_file = HERE / "discord_state.json"
    live_prev = (json.loads(live_file.read_text(encoding="utf-8"))
                 if live_file.exists() else None)
    if live_prev is not None and pend["id"] not in (live_prev.get("pending_orders_seen") or {}):
        live_prev = None                                  # live state moved on
    prev = _prev(open_position_ids_seen=[], pending_orders_seen={pend["id"]: {}})
    del prev["management_mode"]                          # state written by the fixed bot
    for p in [prev] + ([live_prev] if live_prev else []):
        scan = _scan([], pending=[pend], management=fx.SCALE_OUT)
        if live_prev is p:
            scan["account"]["prop_firm"]["challenge_started_at"] = p.get("challenge_started_at")
        ev = sd.compute_events(scan, p)
        assert ev["mode_change"] and ev["mode_change"]["new"] == "scale_out"
        now = datetime(2026, 9, 29, 15, 5, tzinfo=UTC)
        assert sd.decide_post(scan, p, ev, now) == "news"
        body = "\n".join(sd.build_status_messages(scan, [], partials=[], title="TRADE UPDATE",
                                                  mode_change=ev["mode_change"], now_utc=now))
        assert "MANAGEMENT CHANGED: earlier alerts -> scale-out" in body
        assert "NZDCHF" in body and "remove its old take-profit; at +1R 0.46724" in body
        st = sd.build_state(scan, p, ev, now, posted=True)
        assert st["management_mode"] == "scale_out"
        ev2 = sd.compute_events(scan, st)
        assert ev2["mode_change"] is None                   # one time only
    # no orders -> no notice; a failed post keeps the old mode in state
    ev = sd.compute_events(_scan([], management=fx.SCALE_OUT), prev)
    assert ev["mode_change"] is None
    st = sd.build_state(_scan([], management=fx.SCALE_OUT), prev, ev,
                        datetime(2026, 9, 29, 15, 5, tzinfo=UTC), posted=False)
    assert st.get("management_mode") is None


def test_scan_without_management_never_triggers_the_notice():
    prev = _prev()
    del prev["management_mode"]
    ev = sd.compute_events(_scan([_gbpnzd_open_runner()]), prev)
    assert ev["mode_change"] is None


# --- 9: result chart drawn in the trade's own mode -----------------------------------
def test_trade_mode_inference():
    assert bm.trade_mode({"management_mode": "fixed"}) == "fixed"
    assert bm.trade_mode({"partial_taken": True, "partial_time": "2026-09-29T14:00:00Z"}) \
        == "scale_out"
    assert bm.trade_mode({"runner_peak_r": 2.1}) == "scale_out"
    assert bm.trade_mode({"partial_taken": True}) == "ladder"
    assert bm.trade_mode({}) is None
    m = bm.trade_management(fx.closed_trade("trail"), {"mode": "fixed"})
    assert m["mode"] == "scale_out" and m["scale_out_fraction"] == 0.5


def test_result_images_use_the_trade_mode_not_the_config(monkeypatch):
    seen = []

    def fake(trade, cache, timeframe=None, management=None):
        seen.append((management or {}).get("mode"))
        return None
    monkeypatch.setattr(sd.draw_chart, "generate_trade_result_chart", fake)
    so_trade = dict(fx.closed_trade("trail"), id="A")
    ladder_trade = dict(fx.closed_trade("trail"), id="B", partial_time=None,
                        runner_peak_r=0.0, management_mode="")
    scan = {"management": {"mode": "fixed"}, "ohlcv_cache": fx.cache(), "trade_history": []}
    sd.build_result_images(scan, [so_trade])
    scan["management"] = fx.SCALE_OUT
    sd.build_result_images(scan, [ladder_trade])
    assert seen == ["scale_out", "ladder"]


def test_result_chart_marks_the_partial_even_when_config_is_fixed(tmp_path):
    t = fx.closed_trade("trail")
    assert draw_chart._trade_management(t, {"mode": "fixed"})["mode"] == "scale_out"
    path = draw_chart.generate_trade_result_chart(t, fx.cache(), timeframe="1d",
                                                  management={"mode": "fixed"})
    try:
        assert path and os.path.getsize(path) > 5000
    finally:
        if path and os.path.exists(path):
            os.remove(path)
