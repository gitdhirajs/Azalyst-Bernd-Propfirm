"""Migrate a paper_trader_state.json for a CODE revert of the scale-out deploy.

Why: since 2026-09-28 a scale-out +1R partial is credited to the account the
moment it happens (Position.booked_pnl; closed_pnl_total, balance and
daily_pnl include it), and _close_position later books only
realized_pnl - booked_pnl. Code from before that change (gitdhirajs/main before
the scale-out branch) does not know booked_pnl: it drops the field on load and
books the WHOLE realized_pnl -- partial included -- when the runner closes, so
the partial is counted twice.

The documented revert is config-only (`stop_loss.management: fixed`), which
keeps honouring booked_pnl and needs NO migration. Run this ONLY before a code
revert (git revert / checkout of older code) while any OPEN position has
booked_pnl != 0. It takes every open position's booked partial back out of the
account totals and sets booked_pnl = 0, so the old code books it exactly once,
at the runner's close:

    closed_pnl_total -= booked_pnl      (per open position)
    balance           = initial_balance + closed_pnl_total
    daily_pnl        -= booked_pnl      only when the partial fell in the
                                        state's current trading day
    booked_pnl        = 0

realized_pnl, partial_qty / partial_price and the trade history are untouched
(a CLOSED trade's booked_pnl already equals its realized_pnl and was booked
once). peak_balance is left alone: the old close restores the balance.

Usage (from the repo root):
    python research/unbook_partials.py                    # dry run, live state
    python research/unbook_partials.py --state PATH       # dry run, a copy
    python research/unbook_partials.py --state PATH --apply   # write (+ .bak)
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
DEFAULT_STATE = REPO / "Propfirm Trading Dashboard" / "paper_trader_state.json"


def _utc(v) -> Optional[datetime]:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def trading_day(when: datetime, reset_hour_utc: int = 22) -> str:
    """Same day key as BP_paper_trader.maybe_roll_day."""
    when = when.astimezone(timezone.utc)
    d = when.date() if when.hour < reset_hour_utc else when.date() + timedelta(days=1)
    return d.isoformat()


def unbook(state: Dict, reset_hour_utc: int = 22) -> Tuple[Dict, List[str]]:
    """Return (migrated copy of `state`, report lines). Idempotent: a second
    run finds booked_pnl == 0 everywhere and changes nothing."""
    st = json.loads(json.dumps(state))
    report: List[str] = []
    total = 0.0
    daily = 0.0
    for p in st.get("open_positions") or []:
        if str(p.get("status", "active")).lower() != "active":
            continue
        booked = float(p.get("booked_pnl") or 0.0)
        if booked == 0.0:
            continue
        total += booked
        pt = _utc(p.get("partial_time"))
        same_day = pt is not None and trading_day(pt, reset_hour_utc) == st.get("current_date")
        if same_day:
            daily += booked
        report.append(f"{p.get('symbol')} {p.get('id')}: booked_pnl {booked:+.2f} "
                      f"-> 0 (partial {p.get('partial_time')}"
                      f"{', today' if same_day else ''})")
        p["booked_pnl"] = 0.0
    if total:
        st["closed_pnl_total"] = float(st.get("closed_pnl_total") or 0.0) - total
        st["balance"] = float(st.get("initial_balance") or 0.0) + st["closed_pnl_total"]
        st["daily_pnl"] = float(st.get("daily_pnl") or 0.0) - daily
        report.append(f"closed_pnl_total {state.get('closed_pnl_total')} -> "
                      f"{st['closed_pnl_total']:.4f}; balance {state.get('balance')} -> "
                      f"{st['balance']:.4f}; daily_pnl {state.get('daily_pnl')} -> "
                      f"{st['daily_pnl']:.4f}")
    else:
        report.append("no open position has a booked partial: nothing to migrate")
    return st, report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--state", default=str(DEFAULT_STATE))
    ap.add_argument("--reset-hour", type=int, default=22,
                    help="prop_firm.daily_reset_hour_utc (default 22)")
    ap.add_argument("--apply", action="store_true", help="write the file (keeps a .bak)")
    a = ap.parse_args(argv)
    path = Path(a.state)
    state = json.loads(path.read_text(encoding="utf-8"))
    new, report = unbook(state, a.reset_hour)
    for line in report:
        print(line)
    if not a.apply:
        print("[dry-run] nothing written; add --apply to write")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    shutil.copy2(path, path.with_name(f"{path.name}.bak-unbook-{stamp}"))
    path.write_text(json.dumps(new, indent=2), encoding="utf-8")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
