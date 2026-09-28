"""Render the scale-out sample outputs (2026-09-28) -- no network, no Discord post.

    python research/make_scaleout_samples.py

Writes research/scaleout_samples.txt (Discord text for a new GBPNZD signal, a
+1R partial / runner stop move, and closed scale-out trades) and the charts in
research/scaleout_charts/. Uses the GBPNZD fixture in
"Propfirm Trading Dashboard/tests/scaleout_fixtures.py".
"""
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / "Propfirm Trading Dashboard"
sys.path.insert(0, str(DASH))
sys.path.insert(0, str(DASH / "tests"))
os.environ.pop("DISCORD_WEBHOOK_URL", None)

import draw_chart                       # noqa: E402
import send_discord as sd               # noqa: E402
import scaleout_fixtures as fx          # noqa: E402

OUT_TXT = ROOT / "research" / "scaleout_samples.txt"
OUT_DIR = ROOT / "research" / "scaleout_charts"


def _no_post(*a, **k):
    raise RuntimeError("samples must never post to Discord")


def main() -> int:
    sd.requests.post = _no_post
    sd._MIN_COMPOSITE_CACHE, sd._ALERT_COMPOSITE_CACHE = 7.0, 5.5
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    start = "2026-09-27T13:45:25+00:00"
    acct = {"balance": 5025.0, "closed_pnl": 25.0, "open_pnl": 0.0, "total_trades": 0,
            "winning_trades": 0, "losing_trades": 0, "win_rate": None, "scratch_trades": 0,
            "avg_r": 0.0,
            "prop_firm": {"enabled": True, "account_size": 5000.0,
                          "challenge_started_at": start, "profit_target_pct": 8.0,
                          "target_equity": 5400.0, "progress_to_target_pct": 6.3,
                          "todays_loss": 0.0, "max_daily_loss_limit": 150.0,
                          "daily_loss_remaining": 150.0, "total_loss": 0.0,
                          "max_total_loss_limit": 300.0, "total_loss_remaining": 300.0}}
    out = []

    # 1) NEW SIGNAL
    scan = {"scan_time": "2026-09-28T12:05:00+00:00", "management": fx.SCALE_OUT,
            "ohlcv_cache": fx.cache(), "ltf": "1d"}
    msgs = sd.build_signals_messages(scan, [fx.signal()])
    out += ["=" * 70, "1) NEW SIGNAL  (GBPNZD short, scale_out)", "=" * 70, msgs[0]["content"]]
    if msgs[0].get("image_path"):
        shutil.move(msgs[0]["image_path"], OUT_DIR / "signal_gbpnzd_short_scale_out.png")

    # fixed-mode chart for comparison (the 2026-09-27 look must be unchanged)
    p = draw_chart.generate_chart(fx.signal(), fx.cache(), asof=scan["scan_time"],
                                  management={"mode": "fixed"})
    if p:
        shutil.move(p, OUT_DIR / "signal_gbpnzd_short_fixed.png")

    # 2) +1R PARTIAL, then a runner lock
    half = fx.SIZE / 2
    runner = {"id": "P-GBPNZD", "symbol": "GBPNZD=X", "direction": "short",
              "status": "active", "entry_price": fx.ENTRY, "stop_price": fx.STOP,
              "current_stop": fx.ENTRY, "targets": [fx.L1, fx.R2, fx.R3],
              "fill_price": fx.ENTRY, "partial_taken": True, "partial_qty": half,
              "position_size": half, "partial_price": fx.L1,
              "partial_time": "2026-08-26T14:00:00+00:00", "realized_pnl": 25.0,
              "unrealized_pnl": 25.0, "current_price": 2.34470, "breakeven_triggered": True}
    partial = {"event": "partial_close", "position_id": "P-GBPNZD", "symbol": "GBPNZD=X",
               "direction": "short", "price": fx.L1, "fraction": 0.5, "pnl": 25.0,
               "r_booked": 0.5, "at_r": 1.0, "new_stop": fx.ENTRY, "new_stop_r": 0.0,
               "at": "2026-08-26T14:00:00+00:00", "entry_price": fx.ENTRY,
               "stop_price": fx.STOP}
    status_scan = {"scan_time": "2026-08-26T14:05:00+00:00", "management": fx.SCALE_OUT,
                   "signals": [], "positions": [runner], "pending_orders": [],
                   "trade_history": [], "account": acct, "fills": [],
                   "partials_this_run": [partial], "watchlist_scanned": 41, "errors": []}
    prev = {"challenge_started_at": start, "open_position_ids_seen": ["P-GBPNZD"],
            "closed_ids_seen": [], "partial_events_seen": [], "runner_stops_seen": {},
            "last_status_date": "2026-08-26"}
    now = datetime(2026, 8, 26, 14, 5, tzinfo=timezone.utc)
    ev = sd.compute_events(status_scan, prev)
    reason = sd.decide_post(status_scan, prev, ev, now)
    pages = sd.build_status_messages(status_scan, ev["closed"], fills=ev["fills"],
                                     cancelled=ev["cancelled"], partials=ev["partials"],
                                     title=sd._TITLES[reason], now_utc=now)
    out += ["", "=" * 70, f"2) +1R PARTIAL  (decide_post -> {reason!r})", "=" * 70] + pages

    lock = dict(partial, event="stop_moved", price=fx.L1, new_stop=fx.L1, new_stop_r=1.0,
                fraction=None, pnl=0.0, r_booked=0.0, at="2026-08-27T09:00:00+00:00")
    out += ["", "-- runner lock event (partials block alone) --", sd.partials_block([lock])]

    # 3) CLOSED scale-out trades
    closed = [fx.closed_trade("breakeven"), fx.closed_trade("trail")]
    acct_c = dict(acct, balance=5100.0, closed_pnl=100.0, total_trades=2, winning_trades=2,
                  win_rate=1.0, avg_r=1.0,
                  prop_firm=dict(acct["prop_firm"], progress_to_target_pct=25.0))
    closed_scan = dict(status_scan, positions=[], partials_this_run=[], trade_history=closed,
                       account=acct_c, scan_time="2026-09-05T10:05:00+00:00")
    pages = sd.build_status_messages(closed_scan, closed, title="TRADE UPDATE", now_utc=now)
    out += ["", "=" * 70, "3) CLOSED SCALE-OUT TRADES", "=" * 70] + pages
    for t in closed:
        p = draw_chart.generate_trade_result_chart(t, fx.cache(), timeframe="1d",
                                                   management=fx.SCALE_OUT)
        if p:
            shutil.move(p, OUT_DIR / f"closed_gbpnzd_short_{t['close_reason']}.png")

    OUT_TXT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {OUT_TXT} and {sorted(x.name for x in OUT_DIR.glob('*.png'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
