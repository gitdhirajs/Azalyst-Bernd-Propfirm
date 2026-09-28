"""Render the scale-out sample outputs (2026-09-28) -- no network, no Discord post.

    python research/make_scaleout_samples.py

Writes research/scaleout_samples.txt and the charts in research/scaleout_charts/.

Sections 2-3 come from the REAL PaperTrader (live BP_config.yaml, $5,000
FundingPips account) replaying the GBPNZD fixture's daily bars
("Propfirm Trading Dashboard/tests/scaleout_fixtures.py"), so the account
figures (equity, realised P&L, daily P&L) are what the bot computes -- not
hand-typed. The scan payload is stamped the way run_scanner does it (live
price, unrealised P&L of the runner, open R).
"""
import copy
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / "Propfirm Trading Dashboard"
sys.path.insert(0, str(DASH))
sys.path.insert(0, str(DASH / "tests"))
os.environ.pop("DISCORD_WEBHOOK_URL", None)
os.environ.setdefault("BP_STATE_DIR", tempfile.mkdtemp(prefix="bp_samples_"))

import logging                          # noqa: E402
import pandas as pd                     # noqa: E402
import yaml                             # noqa: E402

logging.disable(logging.CRITICAL)

import BP_paper_trader as bpt           # noqa: E402
import draw_chart                       # noqa: E402
import run_scanner as rs                # noqa: E402
import send_discord as sd               # noqa: E402
import scaleout_fixtures as fx          # noqa: E402

OUT_TXT = ROOT / "research" / "scaleout_samples.txt"
OUT_DIR = ROOT / "research" / "scaleout_charts"
UTC = timezone.utc


def _no_post(*a, **k):
    raise RuntimeError("samples must never post to Discord")


def _day_bars(lo: int, hi: int) -> pd.DataFrame:
    rows = fx.daily_rows()[lo:hi + 1]
    return pd.DataFrame([{"timestamp": pd.Timestamp(r["timestamp"]), "open": r["open"],
                          "high": r["high"], "low": r["low"], "close": r["close"]}
                         for r in rows])


def _results(t, ev, price: float, scan_time: str) -> dict:
    """The scan_results payload the way run_scanner builds it."""
    acct = t.get_account_summary()
    op = t.get_open_positions()
    tot = 0.0
    for o in op:
        e = float(o["entry_price"])
        f = float(o["fill_price"] if o.get("fill_price") is not None else e)
        size = float(o["position_size"])
        risk = abs(e - float(o["stop_price"]))
        mv = (price - f) if o["direction"] == "long" else (f - price)
        o["display_name"] = "GBPNZD"
        o["current_price"] = price
        o["unrealized_pnl"] = round(mv * size, 2)
        o["r_multiple_open"] = round(mv / risk, 2) if risk > 0 else 0.0
        tot += o["unrealized_pnl"]
    acct["open_pnl"] = round(tot, 2)
    hist = t.get_trade_history(limit=100)
    for h in hist:
        h["display_name"] = "GBPNZD"
    res = {"scan_time": scan_time, "account": acct, "positions": op,
           "pending_orders": t.get_pending_orders(), "trade_history": hist, "signals": [],
           "fills": ev.get("fills", []), "closed_this_run": ev.get("closed", []),
           "cancelled_this_run": ev.get("cancelled", []),
           "partials_this_run": ev.get("partials", []), "management": t.management,
           "ohlcv_cache": fx.cache(), "ltf": "1d", "watchlist_scanned": 41, "errors": []}
    return json.loads(json.dumps(rs.json_safe(res)))


def _post(scan, prev, now, out, label):
    ev = sd.compute_events(scan, prev)
    reason = sd.decide_post(scan, prev, ev, now)
    out += ["", "=" * 70, f"{label}  (decide_post -> {reason!r})", "=" * 70]
    if reason:
        out += sd.build_status_messages(scan, ev["closed"], fills=ev["fills"],
                                        cancelled=ev["cancelled"], partials=ev["partials"],
                                        mode_change=ev.get("mode_change"),
                                        title=sd._TITLES[reason], now_utc=now)
    return sd.build_state(scan, prev, ev, now, posted=bool(reason)), ev


def main() -> int:
    sd.requests.post = _no_post
    sd._MIN_COMPOSITE_CACHE, sd._ALERT_COMPOSITE_CACHE = 7.0, 5.5
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.glob("*.png"):
        old.unlink()
    out = []

    # 1) NEW SIGNAL ----------------------------------------------------------
    scan = {"scan_time": "2026-09-28T12:05:00+00:00", "management": fx.SCALE_OUT,
            "ohlcv_cache": fx.cache(), "ltf": "1d"}
    msgs = sd.build_signals_messages(scan, [fx.signal()])
    out += ["=" * 70, "1) NEW SIGNAL  (GBPNZD short, scale_out)", "=" * 70, msgs[0]["content"]]
    if msgs[0].get("image_path"):
        shutil.move(msgs[0]["image_path"], OUT_DIR / "signal_gbpnzd_short_scale_out.png")
    p = draw_chart.generate_chart(fx.signal(), fx.cache(), asof=scan["scan_time"],
                                  management={"mode": "fixed"})
    if p:
        shutil.move(p, OUT_DIR / "signal_gbpnzd_short_fixed.png")

    # 2-3) The REAL paper trader on the fixture's daily bars -----------------
    live = yaml.safe_load((DASH / "BP_config.yaml").read_text(encoding="utf-8"))
    live.setdefault("risk", {})["correlation_check_enabled"] = False
    day = lambda i: fx.T0 + pd.Timedelta(days=i)         # noqa: E731
    bpt.utcnow = lambda: day(79).to_pydatetime()
    t = bpt.PaperTrader(copy.deepcopy(live))
    t.challenge_started_at = "2026-08-19T00:00:00+00:00"
    sig = dict(fx.signal(), signal_time=str(day(79)))
    pid = t.submit_signal(sig)
    prev = {}
    one_day = timedelta(days=1)

    def run(lo, hi, label):
        nonlocal prev
        bpt.utcnow = lambda: (day(hi) + pd.Timedelta(hours=23)).to_pydatetime()
        ev = t.replay_bars_multi({"GBPNZD=X": _day_bars(lo, hi)}, bar_interval=one_day)
        price = float(fx.daily_rows()[hi]["close"])
        now = (day(hi + 1) + pd.Timedelta(hours=0, minutes=5)).to_pydatetime()
        scan_ = _results(t, ev, price, now.isoformat())
        prev, ev2 = _post(scan_, prev, now, out, label)
        return ev, scan_

    out.append("")
    out.append("(sections 2a-2c: the real PaperTrader, live config, replaying daily bars)")
    run(80, 82, "2a) FILL (the sell-limit fills)")
    ev_p, scan_p = run(83, 86, "2b) +1R PARTIAL: 50% closed + stop to breakeven")
    lock = {"event": "stop_moved", "position_id": pid, "symbol": "GBPNZD=X",
            "display_name": "GBPNZD", "direction": "short", "price": fx.R2 + fx.RISK,
            "new_stop": fx.L1, "new_stop_r": 1.0, "entry_price": fx.ENTRY,
            "stop_price": fx.STOP, "at": "2026-08-27T09:00:00+00:00"}
    out += ["", "-- a runner lock at a +2R peak (partials block alone) --",
            sd.partials_block([lock])]
    ev_c, scan_c = run(87, 89, "3) CLOSED: the runner is stopped at breakeven")

    a = t.get_account_summary()
    out += ["", f"(real trader after the close: balance {a['balance']:.2f}, closed_pnl "
                f"{a['closed_pnl']:.2f}, wins {a['winning_trades']}, "
                f"R {t.trade_history[-1].trade_r_multiple:+.2f})"]

    # Result charts: the real breakeven trade, and the fixture trail trade --
    # the trail one drawn with the config set to 'fixed' (it must still show
    # the scale-out partial: a trade is drawn in the mode it ran under).
    real = dict(t.get_trade_history()[-1], display_name="GBPNZD")
    p = draw_chart.generate_trade_result_chart(json.loads(json.dumps(rs.json_safe(real))),
                                               fx.cache(), timeframe="1d")
    if p:
        shutil.move(p, OUT_DIR / "closed_gbpnzd_short_breakeven_real_trader.png")
    for kind in ("breakeven", "trail"):
        p = draw_chart.generate_trade_result_chart(fx.closed_trade(kind), fx.cache(),
                                                   timeframe="1d", management=fx.SCALE_OUT)
        if p:
            shutil.move(p, OUT_DIR / f"closed_gbpnzd_short_{kind}.png")
    p = draw_chart.generate_trade_result_chart(fx.closed_trade("trail"), fx.cache(),
                                               timeframe="1d", management={"mode": "fixed"})
    if p:
        shutil.move(p, OUT_DIR / "closed_gbpnzd_short_trail_config_fixed.png")

    # 4) One-time notice for the live NZDCHF order announced under 'fixed' ---
    from test_paper_trader_scale_out import LIVE_NZDCHF
    pend = dict(LIVE_NZDCHF, display_name="NZDCHF")
    start = "2026-09-27T13:45:25+00:00"
    scan4 = {"scan_time": "2026-09-28T12:05:00+00:00", "management": fx.SCALE_OUT,
             "signals": [], "positions": [], "pending_orders": [pend], "trade_history": [],
             "account": None,
             "fills": [], "partials_this_run": [], "watchlist_scanned": 41, "errors": []}
    bpt.utcnow = lambda: datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    t4 = bpt.PaperTrader(copy.deepcopy(live))
    t4.challenge_started_at = start
    scan4["account"] = json.loads(json.dumps(rs.json_safe(t4.get_account_summary())))
    prev4 = {"challenge_started_at": start, "open_position_ids_seen": [],
             "pending_orders_seen": {pend["id"]: {}}, "order_ids_seen": [pend["id"]],
             "closed_ids_seen": [], "last_status_date": "2026-09-28"}
    _post(scan4, prev4, datetime(2026, 9, 28, 12, 5, tzinfo=UTC), out,
          "4) FIRST RUN AFTER DEPLOY: management notice (live NZDCHF order)")

    OUT_TXT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {OUT_TXT} and {sorted(x.name for x in OUT_DIR.glob('*.png'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
