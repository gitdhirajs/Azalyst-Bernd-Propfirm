"""
Start a fresh prop-firm challenge: reset the paper account and its message /
history state.

Writes (in --state-dir, default this folder):
  paper_trader_state.json  $account_size from BP_config.yaml prop_firm (5,000),
                           challenge_started_at = now UTC, no positions, no
                           trade history, no zone memory, peak = balance.
  discord_state.json       nothing seen yet, so the first message after the
                           reset lists everything as new.
  scan_history.json        empty list.

Each existing file is copied to <name>.bak-<UTC timestamp> first (skip with
--no-backup). --dry-run prints what would be written and touches nothing.

2026-09-27: added for the redeploy that follows the execution-layer audit
(bar replay, no fill at signal time, 1% sizing). The old account's numbers were
produced by the defective pricing path, so the challenge restarts clean instead
of carrying them forward. Also fixes "Day -1 since reset": the old manual reset
wrote challenge_started_at in naive IST local time; this writes aware UTC.

Usage:
    python reset_challenge.py --dry-run
    python reset_challenge.py                       # this folder (live state!)
    python reset_challenge.py --state-dir C:/tmp/x  # a copy
    python reset_challenge.py --suffix _allcoins    # another profile's files
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent


def fresh_paper_state(config: Dict, now: datetime) -> Dict:
    """Initial paper_trader_state.json, in the shape load_paper_trader_state reads."""
    prop = config.get("prop_firm", {}) or {}
    risk = config.get("risk", {}) or {}
    if prop.get("enabled"):
        balance = float(prop.get("account_size", 5000.0))
    else:
        balance = float(risk.get("account_balance", 5000.0))
    return {
        "balance":               balance,
        "initial_balance":       balance,
        "closed_pnl_total":      0.0,
        "total_trades":          0,
        "winning_trades":        0,
        "losing_trades":         0,
        "scratch_trades":        0,
        "peak_balance":          balance,
        "max_drawdown_pct":      0.0,
        "daily_pnl":             0.0,
        "daily_trades":          0,
        "today_starting_equity": balance,
        # None: the trader's first maybe_roll_day() stamps the current day.
        "current_date":          None,
        "account_blown":         False,
        "zone_memory":           {},
        "challenge_started_at":  now.isoformat(),
        "open_positions":        [],
        "trade_history":         [],
        "saved_at":              now.isoformat(),
    }


def fresh_discord_state(now: datetime) -> Dict:
    """Initial discord_state.json (the shape send_discord.load_state defaults to)."""
    return {
        "signal_ids_seen":        [],
        "open_position_ids_seen": [],
        "last_sent_at":           None,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--state-dir", default=str(SCRIPT_DIR),
                    help="folder holding the state files (default: this folder)")
    ap.add_argument("--suffix", default="",
                    help="profile suffix, e.g. _allcoins (default: FundingPips files)")
    ap.add_argument("--config", default=str(SCRIPT_DIR / "BP_config.yaml"),
                    help="config to read prop_firm.account_size from")
    ap.add_argument("--dry-run", action="store_true", help="print, write nothing")
    ap.add_argument("--no-backup", action="store_true", help="do not keep .bak copies")
    args = ap.parse_args(argv)

    state_dir = Path(args.state_dir).resolve()
    if not state_dir.is_dir():
        print(f"ERROR: state dir not found: {state_dir}")
        return 1
    with open(args.config, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    now = datetime.now(timezone.utc)
    outputs = {
        state_dir / f"paper_trader_state{args.suffix}.json": fresh_paper_state(config, now),
        state_dir / f"discord_state{args.suffix}.json":      fresh_discord_state(now),
        state_dir / f"scan_history{args.suffix}.json":       [],
    }

    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    for path, payload in outputs.items():
        exists = path.exists()
        if args.dry_run:
            print(f"[dry-run] would {'overwrite' if exists else 'create'} {path}")
            print(json.dumps(payload, indent=2)[:600])
            continue
        if exists and not args.no_backup:
            bak = path.with_name(f"{path.name}.bak-{stamp}")
            shutil.copy2(path, bak)
            print(f"backup   {bak}")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"wrote    {path}")

    if not args.dry_run:
        bal = outputs[state_dir / f"paper_trader_state{args.suffix}.json"]["balance"]
        print(f"Fresh challenge: ${bal:,.2f}, started {now.isoformat()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
