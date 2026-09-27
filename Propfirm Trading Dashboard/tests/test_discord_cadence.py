"""Posting-cadence tests for send_discord.py (hourly runs, 2026-09-27).

Rules under test (send_discord.decide_post / compute_events / build_state):
  * news (new signal, fill, close, cancelled resting order) posts immediately;
  * otherwise the account status posts at most once per UTC day, on the first
    run at/after 21:30 UTC;
  * first run, challenge reset and a breach transition post once;
  * a setup that keeps being re-emitted every hour is announced once.

Everything here is pure: no Discord call, no state file written.
"""
import copy
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import send_discord as sd  # noqa: E402


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """send_discord loads .secrets.bat at import; make any POST impossible."""
    def _boom(*a, **k):
        raise AssertionError("tests must never post to Discord")
    monkeypatch.setattr(sd.requests, "post", _boom)
    monkeypatch.setattr(sd, "_MIN_COMPOSITE_CACHE", 7.0)
    monkeypatch.setattr(sd, "_ALERT_COMPOSITE_CACHE", 5.5)
    monkeypatch.delenv("AZALYST_DAILY_STATUS_UTC", raising=False)


def utc(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


START = "2026-09-27T00:00:00+00:00"


def signal(sym="EURUSD=X", entry=1.085, stop=1.080, pid=None, comp=8.0,
           direction="long", order_type="limit"):
    return {
        "symbol": sym, "display_name": sym, "direction": direction,
        "entry_price": entry, "stop_price": stop,
        "targets": [entry + (entry - stop) * k for k in (1, 2, 3)],
        "order_type": order_type, "pending_order": True, "price_at_zone": False,
        "setup_key": f"{sym}|{direction}|{entry:.5g}|{stop:.5g}",
        "zone_id": f"z-{sym}", "paper_trade_id": pid,
        "qualifier_scores": {"composite": comp}, "lot_size": 0.5, "units": 50000,
        "risk_usd_actual": 50.0, "risk_usd_target": 50.0, "current_price": entry * 1.01,
    }


def order(pid, sym="EURUSD=X", status="pending", **kw):
    d = {"id": pid, "symbol": sym, "direction": "long", "entry_price": 1.085,
         "stop_price": 1.080, "current_stop": 1.080, "targets": [1.09, 1.095, 1.10],
         "order_type": "limit", "status": status}
    d.update(kw)
    return d


def scan(signals=(), positions=(), pending=(), history=(), fills=None,
         breached=False, start=START):
    s = {
        "scan_time": "2026-09-27T10:17:00+00:00",
        "watchlist_scanned": 66, "errors": [],
        "signals": list(signals), "positions": list(positions),
        "pending_orders": list(pending), "trade_history": list(history),
        "account": {"balance": 5000.0, "closed_pnl": 0.0, "open_pnl": 0.0,
                    "prop_firm": {"enabled": True, "account_size": 5000.0,
                                  "breached": breached, "profit_target_pct": 6.0,
                                  "challenge_started_at": start}},
    }
    if fills is not None:
        s["fills"] = fills
    return s


def run(sc, prev, now, always=False):
    """One scheduled run: returns (reason, events, next_state)."""
    ev = sd.compute_events(sc, prev)
    reason = sd.decide_post(sc, prev, ev, now, always_send=always)
    new_state = sd.build_state(sc, prev, ev, now, posted=reason is not None)
    return reason, ev, new_state


# ── baseline / quiet hours / daily status ─────────────────────────────────

def test_first_run_posts_baseline_then_quiet():
    sc = scan()
    reason, _, st = run(sc, {}, utc("2026-09-27T10:17:00"))
    assert reason == "first"
    reason2, _, _ = run(sc, st, utc("2026-09-27T11:17:00"))
    assert reason2 is None


def test_daily_status_once_after_2130_utc():
    sc = scan()
    _, _, st = run(sc, {}, utc("2026-09-27T09:17:00"))          # baseline
    assert run(sc, st, utc("2026-09-27T21:17:00"))[0] is None     # before 21:30
    reason, _, st = run(sc, st, utc("2026-09-27T21:31:00"))
    assert reason == "daily"
    assert st["last_status_date"] == "2026-09-27"
    assert run(sc, st, utc("2026-09-27T22:17:00"))[0] is None     # once per day
    assert run(sc, st, utc("2026-09-27T23:59:00"))[0] is None
    assert run(sc, st, utc("2026-09-28T00:17:00"))[0] is None     # new day, too early
    assert run(sc, st, utc("2026-09-28T21:40:00"))[0] == "daily"


def test_dropped_evening_runs_catch_up_same_day_only():
    sc = scan()
    _, _, st = run(sc, {}, utc("2026-09-27T09:17:00"))
    # 21:17 .. 23:17 runs all dropped; next run is 00:17 -> a NEW UTC day, not
    # due until 21:30 again (at most once per UTC day, never a morning repeat).
    assert run(sc, st, utc("2026-09-28T00:17:00"))[0] is None


def test_news_after_2130_counts_as_daily_status():
    sc0 = scan()
    _, _, st = run(sc0, {}, utc("2026-09-27T09:17:00"))
    sc1 = scan(signals=[signal(pid="P1")], pending=[order("P1")])
    reason, ev, st = run(sc1, st, utc("2026-09-27T21:45:00"))
    assert reason == "news" and len(ev["new_signals"]) == 1
    assert st["last_status_date"] == "2026-09-27"
    assert run(sc1, st, utc("2026-09-27T22:17:00"))[0] is None


def test_daily_time_env_override(monkeypatch):
    monkeypatch.setenv("AZALYST_DAILY_STATUS_UTC", "06:00")
    sc = scan()
    _, _, st = run(sc, {}, utc("2026-09-27T01:17:00"))
    assert run(sc, st, utc("2026-09-27T06:17:00"))[0] == "daily"


def test_always_send_forces_post():
    sc = scan()
    _, _, st = run(sc, {}, utc("2026-09-27T09:17:00"))
    assert run(sc, st, utc("2026-09-27T10:17:00"), always=True)[0] == "always"


# ── new signals ────────────────────────────────────────────────────────────

def test_reemitted_setup_is_announced_once_even_if_it_flickers():
    s = signal(pid="P1")
    _, _, st = run(scan(), {}, utc("2026-09-27T08:17:00"))
    reason, ev, st = run(scan(signals=[s], pending=[order("P1")]), st,
                         utc("2026-09-27T09:17:00"))
    assert reason == "news" and ev["new_signals"] == [s]
    # next hour the engine re-emits it; the paper trader rejects the duplicate
    again = dict(s, paper_trade_id=None)
    reason, ev, st = run(scan(signals=[again], pending=[order("P1")]), st,
                         utc("2026-09-27T10:17:00"))
    assert reason is None and ev["new_signals"] == []
    # it drops out for an hour, then comes back -> still not re-announced
    _, _, st = run(scan(pending=[order("P1")]), st, utc("2026-09-27T11:17:00"))
    reason, ev, _ = run(scan(signals=[again], pending=[order("P1")]), st,
                        utc("2026-09-27T12:17:00"))
    assert ev["new_signals"] == []


def test_resubmitted_order_for_same_setup_is_announced_again():
    s = signal(pid="P1")
    _, _, st = run(scan(signals=[s], pending=[order("P1")]), {}, utc("2026-09-27T09:17:00"))
    # P1 cancelled earlier; the paper trader places a NEW order P2 for the same setup
    s2 = dict(s, paper_trade_id="P2")
    reason, ev, _ = run(scan(signals=[s2], pending=[order("P2")]), st,
                        utc("2026-09-27T10:17:00"))
    assert reason == "news" and ev["new_signals"] == [s2]


def test_below_caution_bar_signal_is_not_news():
    _, _, st = run(scan(), {}, utc("2026-09-27T09:17:00"))
    low = signal(comp=4.0)
    reason, ev, _ = run(scan(signals=[low]), st, utc("2026-09-27T10:17:00"))
    assert ev["new_signals"] == [low]          # new, but held back
    assert sd.split_shown_signals(ev["new_signals"]) == ([], 1)
    assert reason is None


def test_legacy_state_is_migrated_without_reposting_old_zone():
    legacy = {"signal_ids_seen": ["z-EURUSD=X"], "open_position_ids_seen": [],
              "last_sent_at": "2026-09-25T05:07:45+00:00"}
    s = signal(pid=None)                     # same zone, no new order
    reason, ev, st = run(scan(signals=[s]), legacy, utc("2026-09-27T10:17:00"))
    assert ev["new_signals"] == [] and reason is None
    assert st["state_version"] == 2 and s["setup_key"] in st["signal_keys_seen"]


def test_legacy_state_new_order_still_announced():
    legacy = {"signal_ids_seen": ["z-EURUSD=X"], "open_position_ids_seen": []}
    s = signal(pid="P9")
    reason, ev, _ = run(scan(signals=[s], pending=[order("P9")]), legacy,
                        utc("2026-09-27T10:17:00"))
    assert reason == "news" and ev["new_signals"] == [s]


# ── fills / closes / cancellations ─────────────────────────────────────────

def _with_pending(pid="P1"):
    _, _, st = run(scan(signals=[signal(pid=pid)], pending=[order(pid)]), {},
                   utc("2026-09-27T09:17:00"))
    return st


def test_fill_from_scan_fills_key():
    st = _with_pending()
    pos = order("P1", status="active", filled_at="2026-09-27T13:00:00+00:00")
    sc = scan(positions=[pos], fills=[{"id": "P1", "filled_at": pos["filled_at"]}])
    reason, ev, st2 = run(sc, st, utc("2026-09-27T14:17:00"))
    assert reason == "news"
    assert [f["id"] for f in ev["fills"]] == ["P1"]
    assert ev["cancelled"] == [] and ev["closed"] == []
    # not reported twice
    assert run(scan(positions=[pos]), st2, utc("2026-09-27T15:17:00"))[1]["fills"] == []


def test_fill_detected_from_state_when_fills_key_missing():
    st = _with_pending()
    sc = scan(positions=[order("P1", status="active")])     # no "fills" key
    reason, ev, _ = run(sc, st, utc("2026-09-27T14:17:00"))
    assert reason == "news" and [f["id"] for f in ev["fills"]] == ["P1"]


def test_fill_given_as_bare_id():
    st = _with_pending()
    sc = scan(positions=[order("P1", status="active")], fills=["P1"])
    ev = sd.compute_events(sc, st)
    assert [f["id"] for f in ev["fills"]] == ["P1"]
    assert ev["fills"][0]["symbol"] == "EURUSD=X"


def test_fill_and_close_inside_one_replay_window():
    """Filled at 13:00 and stopped at 16:00 while runs were dropped: never seen
    ACTIVE, still reported as filled AND closed (legacy logic missed this)."""
    st = _with_pending()
    closed = order("P1", status="closed", close_reason="stop", realized_pnl=-50.0,
                   r_multiple=-1.0, close_price=1.080)
    reason, ev, _ = run(scan(history=[closed]), st, utc("2026-09-27T17:17:00"))
    assert reason == "news"
    assert [f["id"] for f in ev["fills"]] == ["P1"]
    assert [c["id"] for c in ev["closed"]] == ["P1"]
    assert ev["cancelled"] == []


def test_closed_trade_reported_once():
    st = _with_pending()
    _, _, st = run(scan(positions=[order("P1", status="active")]), st, utc("2026-09-27T12:17:00"))
    closed = order("P1", status="closed", close_reason="T3", realized_pnl=150.0, r_multiple=3.0)
    reason, ev, st = run(scan(history=[closed]), st, utc("2026-09-27T13:17:00"))
    assert reason == "news" and [c["id"] for c in ev["closed"]] == ["P1"]
    assert ev["fills"] == []
    reason, ev, _ = run(scan(history=[closed]), st, utc("2026-09-27T14:17:00"))
    assert reason is None and ev["closed"] == []


def test_cancelled_resting_order_is_news_with_details_from_state():
    st = _with_pending()
    reason, ev, _ = run(scan(), st, utc("2026-09-27T12:17:00"))
    assert reason == "news"
    assert len(ev["cancelled"]) == 1
    c = ev["cancelled"][0]
    assert c["id"] == "P1" and c["symbol"] == "EURUSD=X" and c["entry_price"] == 1.085


def test_cancelled_reason_taken_from_scan_when_available():
    st = _with_pending()
    sc = scan(history=[order("P1", status="cancelled", close_reason="drifted")])
    ev = sd.compute_events(sc, st)
    assert ev["fills"] == [] and ev["closed"] == []
    assert ev["cancelled"][0]["close_reason"] == "drifted"


# ── reset / breach ─────────────────────────────────────────────────────────

def test_challenge_reset_does_not_report_old_account_orders():
    st = _with_pending()
    sc = scan(start="2026-09-28T00:00:00+00:00")        # fresh $5k challenge
    reason, ev, st2 = run(sc, st, utc("2026-09-28T01:17:00"))
    assert reason == "reset"
    assert ev["cancelled"] == [] and ev["fills"] == [] and ev["closed"] == []
    assert st2["challenge_started_at"] == "2026-09-28T00:00:00+00:00"
    assert run(sc, st2, utc("2026-09-28T02:17:00"))[0] is None


def test_breach_posts_on_transition_only():
    _, _, st = run(scan(), {}, utc("2026-09-27T09:17:00"))
    reason, _, st = run(scan(breached=True), st, utc("2026-09-27T10:17:00"))
    assert reason == "breach"
    assert run(scan(breached=True), st, utc("2026-09-27T11:17:00"))[0] is None


def test_state_is_json_serialisable_and_bounded():
    import json
    st = {}
    for i in range(sd.ID_MEMORY_MAX + 50):
        hist = [order(f"H{i}", status="closed")]
        _, _, st = run(scan(history=hist), st, utc("2026-09-27T10:17:00"))
    json.dumps(st)
    assert len(st["closed_ids_seen"]) == sd.ID_MEMORY_MAX
    assert st["closed_ids_seen"][-1] == f"H{sd.ID_MEMORY_MAX + 49}"


def test_signal_memory_expires_after_it_stops_being_seen():
    s = signal(pid=None)
    _, _, st = run(scan(signals=[s]), {}, utc("2026-08-01T10:17:00"))
    # gone for > SIGNAL_MEMORY_DAYS, then it forms again -> announced again
    _, _, st = run(scan(), st, utc("2026-09-10T22:17:00"))
    assert s["setup_key"] not in st["signal_keys_seen"]
    ev = sd.compute_events(scan(signals=[s]), st)
    assert ev["new_signals"] == [s]


def test_dry_run_cli_does_not_write_state(tmp_path, capsys):
    import json
    inp = tmp_path / "scan.json"
    state = tmp_path / "state.json"
    inp.write_text(json.dumps(scan(signals=[signal(pid="P1")], pending=[order("P1")])))
    rc = sd.main(["--dry-run", "--input", str(inp), "--state", str(state),
                  "--now", "2026-09-27T21:40:00Z"])
    assert rc == 0
    assert not state.exists()
    out = capsys.readouterr().out
    assert "reason=first" in out and "NEW SIGNAL 1/1" in out


# ── live path (post_to_discord replaced by a recorder) ─────────────────────

def _live(monkeypatch, tmp_path, sc, now, ok=True):
    import json
    calls = []

    def fake_post(url, content, user_id=None, image_path=None, attempts=3):
        calls.append({"content": content, "user_id": user_id, "image": image_path})
        return ok
    monkeypatch.setattr(sd, "post_to_discord", fake_post)
    monkeypatch.setattr(sd.time, "sleep", lambda *_: None)
    inp = tmp_path / "scan.json"
    inp.write_text(json.dumps(sc))
    rc = sd.main(["--input", str(inp), "--state", str(tmp_path / "state.json"),
                  "--webhook-url", "https://example.invalid/hook", "--user-id", "42",
                  "--now", now])
    return rc, calls


def test_live_path_posts_status_then_pings_first_signal_only(monkeypatch, tmp_path):
    import json
    sc = scan(signals=[signal(pid="P1"), signal(sym="GBPUSD=X", entry=1.3, stop=1.29, pid="P2")],
              pending=[order("P1"), order("P2", sym="GBPUSD=X")])
    rc, calls = _live(monkeypatch, tmp_path, sc, "2026-09-27T10:17:00Z")
    assert rc == 0
    sig_calls = [c for c in calls if "NEW SIGNAL" in c["content"]]
    status_calls = [c for c in calls if "NEW SIGNAL" not in c["content"]]
    assert status_calls and all(c["user_id"] is None for c in status_calls)
    assert [c["user_id"] for c in sig_calls] == ["42", None]
    assert calls.index(sig_calls[0]) > calls.index(status_calls[-1])   # status first
    st = json.loads((tmp_path / "state.json").read_text())
    assert set(st["pending_orders_seen"]) == {"P1", "P2"}
    # the next quiet hour posts nothing
    rc, calls = _live(monkeypatch, tmp_path, sc, "2026-09-27T11:17:00Z")
    assert rc == 0 and calls == []


def test_failed_post_keeps_old_state_so_next_run_retries(monkeypatch, tmp_path):
    sc = scan(signals=[signal(pid="P1")], pending=[order("P1")])
    rc, _ = _live(monkeypatch, tmp_path, sc, "2026-09-27T10:17:00Z", ok=False)
    assert rc == 1 and not (tmp_path / "state.json").exists()
    rc, calls = _live(monkeypatch, tmp_path, sc, "2026-09-27T11:17:00Z")
    assert rc == 0 and any("NEW SIGNAL" in c["content"] for c in calls)


def test_kill_switch_cadence_off_posts_every_run(monkeypatch):
    sc = scan()
    _, _, st = run(sc, {}, utc("2026-09-27T09:17:00"))
    assert run(sc, st, utc("2026-09-27T10:17:00"))[0] is None
    monkeypatch.setenv("BP_DISCORD_CADENCE", "0")
    assert run(sc, st, utc("2026-09-27T10:17:00"))[0] == "always"
