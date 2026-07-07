#!/usr/bin/env python3
"""
Send the latest scan_results.json to a Discord channel via webhook.

Usage:
    DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/... \
        python send_discord.py

    python send_discord.py --dry-run     # build the message but don't POST

The script reads:
    ../data/scan_results.json          (latest scan output -- required)
    ../data/discord_state.json         (last sent state -- created on first run)

The Discord message is a single fixed-width text block styled to match
the AZALYST PAPER PORTFOLIO end-of-day report format. We diff the current
scan against the previously-sent state to call out:
    NEW SIGNALS THIS SCAN  -- entries the user should copy to Fundingpips
    CLOSED THIS SCAN       -- positions closed since the last message
    PORTFOLIO STATUS       -- always shown: equity, FP guardrails, open trades
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

# ── Paths ──────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT  = SCRIPT_DIR.parent

# Load DISCORD_WEBHOOK_URL / DISCORD_USER_ID from .secrets.bat so this script
# works whether it's invoked from scan_markets.bat (env preset) or directly.
def _load_secrets_from_bat() -> None:
    secrets_path = SCRIPT_DIR / ".secrets.bat"
    if not secrets_path.exists():
        return
    try:
        with open(secrets_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line.lower().startswith("set "):
                    continue
                _, _, kv = line.partition(" ")
                if "=" not in kv:
                    continue
                key, _, value = kv.partition("=")
                key, value = key.strip(), value.strip()
                if key and value and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        pass

_load_secrets_from_bat()

def _resolve_data_dir() -> Path:
    """Find scan_results.json regardless of which folder layout we're in.

    Priority:
      1. `AZALYST_DATA_DIR` env override (CI use).
      2. `<repo_root>/data/`         -- Azalyst Propfirm nested layout.
      3. `<script_dir>/`             -- Propfirm Trading Dashboard flat layout.
    """
    env_override = os.environ.get("AZALYST_DATA_DIR")
    if env_override:
        return Path(env_override)
    nested = REPO_ROOT / "data"
    if (nested / "scan_results.json").exists() or nested.exists():
        return nested
    return SCRIPT_DIR

DATA_DIR   = _resolve_data_dir()
# Profile-aware filenames: run_scanner.py sets AZALYST_STATE_SUFFIX (e.g.
# "_allcoins") so this reads the right profile's state. Empty suffix (the
# default FundingPips track) preserves the original filenames byte-for-byte.
_STATE_SUFFIX = os.environ.get("AZALYST_STATE_SUFFIX", "")
SCAN_FILE  = DATA_DIR / f"scan_results{_STATE_SUFFIX}.json"
STATE_FILE = DATA_DIR / f"discord_state{_STATE_SUFFIX}.json"

# Discord hard-limits a single message to 2000 chars (or 6000 in an embed
# description).  We stay well under by truncating the open-positions and
# track-record lists when needed.
DISCORD_MSG_LIMIT = 1900   # leave headroom for the code-block fence


# ───────────────────────────────────────────────────────────────────────
# Message-building helpers
# ───────────────────────────────────────────────────────────────────────

LINE = "─" * 56          # 56 chars wide — fits Discord mobile cleanly
SECTION_SEP = "\n" + LINE + "\n"


def fmt_money(v: float, sign: bool = False) -> str:
    """Format a USD number with thousand separators and 2 decimals.
    `sign=True` prefixes a + on positive numbers (use for PnL)."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "$        ?"
    s = f"${abs(v):>12,.2f}"
    if sign:
        s = f"{'+' if v >= 0 else '-'}{s.lstrip('$').strip()}"
        s = f"${s:>12}"
    elif v < 0:
        s = "-" + s[1:]
    return s


def fmt_pct(v: float, sign: bool = True) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "    ?%"
    return f"{('+' if sign and v >= 0 else '')}{v:7.2f}%"


def fmt_price(v: float, width: int = 10) -> str:
    """Variable-precision price formatter (forex pairs need 5 decimals,
    indices need 2, crypto can need 4)."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return f"{'?':>{width}}"
    if v >= 1000:
        return f"{v:>{width},.2f}"
    if v >= 10:
        return f"{v:>{width},.3f}"
    return f"{v:>{width}.5f}"


def header_block(scan_time_iso: Optional[str]) -> str:
    """Top of the message: title + timestamp."""
    if scan_time_iso:
        try:
            ts = datetime.fromisoformat(scan_time_iso.replace("Z", "+00:00"))
        except ValueError:
            ts = datetime.now(timezone.utc)
    else:
        ts = datetime.now(timezone.utc)
    return (
        "AZALYST PROPFIRM SCANNER  —  4-HOUR UPDATE\n"
        f"{ts.strftime('%d %b %Y  %H:%M UTC')}\n"
    )


def account_block(account: Dict) -> str:
    """Equity, deposited capital, return %, and the FP Trading Objectives."""
    pf = account.get("prop_firm", {}) or {}
    equity = float(account.get("balance", 0))
    initial = float(pf.get("account_size", equity))
    closed_pnl = float(account.get("closed_pnl", account.get("total_pnl", 0)))
    open_pnl = float(account.get("open_pnl", 0))

    overall_return_pct = ((equity - initial) / initial * 100) if initial else 0.0

    def m(v: float, sign: bool = False) -> str:
        try:
            v = float(v)
        except (TypeError, ValueError):
            return "$        ?"
        prefix = ("+" if sign and v >= 0 else "-" if v < 0 else " ")
        return f"{prefix}${abs(v):>10,.2f}"

    def p(v: float) -> str:
        return f"{('+' if v >= 0 else '-')}{abs(v):>9.2f}%"

    lines = [
        f"Account Equity       : {m(equity)}",
        f"Account Size         : {m(initial)}",
        f"Overall Return       : {p(overall_return_pct)}",
        LINE,
        f"Realised PnL (total) : {m(closed_pnl, sign=True)}",
        f"Unrealised PnL       : {m(open_pnl, sign=True)}",
    ]

    if pf.get("enabled"):
        daily_used = float(pf.get("todays_loss", 0))
        daily_limit = float(pf.get("max_daily_loss_limit", 0))
        daily_rem = float(pf.get("daily_loss_remaining", 0))
        total_used = float(pf.get("total_loss", 0))
        total_limit = float(pf.get("max_total_loss_limit", 0))
        total_rem = float(pf.get("total_loss_remaining", 0))
        breached = pf.get("breached", False)
        status = "BREACHED" if breached else "ACTIVE"
        lines += [
            LINE,
            f"Daily Loss Used      : {m(daily_used)}  /  {m(daily_limit).strip()}",
            f"Daily Loss Remaining : {m(daily_rem)}",
            f"Total Loss Used      : {m(total_used)}  /  {m(total_limit).strip()}",
            f"Total Loss Remaining : {m(total_rem)}",
            f"Account Status       :{status:>12}",
        ]

        target_pct = pf.get("profit_target_pct")
        if target_pct:
            days = pf.get("days_elapsed")
            progress = pf.get("progress_to_target_pct")
            target_equity = pf.get("target_equity", 0)
            day_str = f"Day {days}" if days is not None else "Day ?"
            progress_str = f"{progress:.1f}%" if progress is not None else "?%"
            lines += [
                LINE,
                f"Challenge Target     :{target_pct:>10.1f}%   ({m(target_equity).strip()})",
                f"Progress to Target   : {progress_str:>9}  ({day_str} since reset)",
            ]

    return "\n".join(lines)


def stats_block(account: Dict, positions: List[Dict], history: List[Dict]) -> str:
    """Open count, closed count, win rate, W/L, avg R."""
    open_n = len(positions)
    closed_n = int(account.get("total_trades", 0))
    win = int(account.get("winning_trades", 0))
    loss = int(account.get("losing_trades", 0))
    win_rate_pct = float(account.get("win_rate", 0)) * 100
    avg_r = float(account.get("avg_r", account.get("avg_r_per_trade", 0)))

    return "\n".join([
        f"Open Positions       : {open_n:>15}",
        f"Closed Trades        : {closed_n:>15}",
        f"Win Rate             : {win_rate_pct:>14.1f}%",
        f"Winners / Losers     : {f'{win} / {loss}':>15}",
        f"Avg R per Trade      : {avg_r:+14.2f}R",
    ])


# ───────────────────────────────────────────────────────────────────────
# Signal quality: skip/take verdict + composite filter
# ───────────────────────────────────────────────────────────────────────

_MIN_COMPOSITE_CACHE: Optional[float] = None


def _load_min_composite() -> float:
    """Minimum zone composite for a signal to be POSTED / @pinged. Read from
    BP_config.yaml `alerts.min_composite_to_post` (fallback 7.0); env
    AZALYST_MIN_COMPOSITE overrides. Below this a setup is not alerted --
    only high-quality zones ping you."""
    global _MIN_COMPOSITE_CACHE
    if _MIN_COMPOSITE_CACHE is not None:
        return _MIN_COMPOSITE_CACHE
    val = 7.0
    env = os.environ.get("AZALYST_MIN_COMPOSITE")
    if env:
        try:
            val = float(env)
        except ValueError:
            pass
    else:
        try:
            import yaml
            with open(SCRIPT_DIR / "BP_config.yaml", "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            val = float((cfg.get("alerts") or {}).get("min_composite_to_post", 7.0))
        except Exception:
            val = 7.0
    _MIN_COMPOSITE_CACHE = val
    return val


_ALERT_COMPOSITE_CACHE: Optional[float] = None


def _load_alert_composite() -> float:
    """Minimum zone composite for a signal to be SHOWN in Discord (the CAUTION
    band). Signals in [this, min_composite_to_post) are displayed with a
    [CAUTION] tag but are NOT @pinged and NOT paper-traded. Read from
    BP_config.yaml `alerts.min_composite_to_alert` (fallback 5.5)."""
    global _ALERT_COMPOSITE_CACHE
    if _ALERT_COMPOSITE_CACHE is not None:
        return _ALERT_COMPOSITE_CACHE
    val = 5.5
    try:
        import yaml
        with open(SCRIPT_DIR / "BP_config.yaml", "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        val = float((cfg.get("alerts") or {}).get("min_composite_to_alert", 5.5))
    except Exception:
        val = 5.5
    # Never let the show bar exceed the take bar.
    val = min(val, _load_min_composite())
    _ALERT_COMPOSITE_CACHE = val
    return val


def _composite_of(s: Dict) -> float:
    """Zone composite score (0-10) for a signal, from qualifier_scores."""
    qs = s.get("qualifier_scores") or {}
    try:
        return float(qs.get("composite", s.get("composite", 0)) or 0)
    except (TypeError, ValueError):
        return 0.0


def signal_verdict(s: Dict) -> Tuple[str, str]:
    """Return (verdict_label, location_note) so every alert carries an
    explicit skip-or-take call.

    verdict = [TAKE] (composite >= 7, clean) / [CAUTION] (5.5-7, or
    counter-trend, or an opposing zone in the path) / [SKIP] (< 5.5).
    location = whether price is AT the zone now, or the order is PENDING."""
    comp = _composite_of(s)
    ctx = s.get("trade_context", "standard")
    speed_bump = bool(s.get("speed_bump_warning"))
    at_zone = bool(s.get("price_at_zone"))
    pending = bool(s.get("pending_order"))

    tier = "TAKE" if comp >= 7.0 else ("CAUTION" if comp >= 5.5 else "SKIP")
    notes = []
    if ctx == "counter_trend":
        notes.append("counter-trend, half size")
        if tier == "TAKE":
            tier = "CAUTION"
    if speed_bump:
        notes.append("opposing zone in path")
        if tier == "TAKE":
            tier = "CAUTION"

    label = f"[{tier}]  composite {comp:.1f}/10"
    if notes:
        label += "  (" + "; ".join(notes) + ")"

    if pending and not at_zone:
        side = "buy" if str(s.get("direction", "")).lower() == "long" else "sell"
        loc = f"PENDING - set a {side} limit at entry; price not at the zone yet"
    elif at_zone:
        loc = "AT ZONE - price is in the zone now"
    else:
        loc = ""
    return label, loc


def new_signals_block(new_signals: List[Dict]) -> str:
    """One block per signal. Show entry/SL/TP1/T2/T3 + risk + R:R + bias."""
    if not new_signals:
        return ""
    _take_bar = _load_min_composite()
    out = [
        "NEW SIGNALS THIS SCAN",
        f"  [TAKE] = pinged + paper-traded at 1% | "
        f"[CAUTION] = pinged + paper-traded at MIN lot (composite < {_take_bar:g})",
        "",
    ]
    for s in new_signals:
        sym  = s.get("display_name") or s.get("symbol", "?")
        dir_ = s.get("direction", "?").upper()
        entry = s.get("entry_price")
        stop  = s.get("stop_price")
        targets = s.get("targets", []) or []
        risk_amt = float(s.get("risk_amount", 0))
        risk_r = abs(float(entry) - float(stop)) if entry and stop else 0
        rr_t2 = abs((targets[1] - entry) / risk_r) if len(targets) > 1 and risk_r else 0
        composite = _composite_of(s)
        lot_size = s.get("lot_size")
        units = s.get("units")
        risk_actual = float(s.get("risk_usd_actual", risk_amt) or risk_amt)
        spec_verified = s.get("spec_verified", True)
        out.append(f"  {sym:14s}  {dir_:5s}")
        _v_label, _v_loc = signal_verdict(s)
        out.append(f"    >> VERDICT     : {_v_label}")
        if composite < _take_bar:
            out.append(f"    (!) CAUTION    : low conviction -- paper-traded at MIN "
                       f"lot only (not the full 1%; composite {composite:.1f} < {_take_bar:g})")
        if _v_loc:
            out.append(f"    Location       : {_v_loc}")
        out.append(f"    Entry          : {fmt_price(entry, 12)}")
        out.append(f"    Stop Loss      : {fmt_price(stop, 12)}")
        for i, t in enumerate(targets[:3], 1):
            out.append(f"    Target {i} ({i}R)   : {fmt_price(t, 12)}")
        # The number to type into FundingPips. Shown prominently.
        if lot_size:
            out.append(f"    >> LOT SIZE    : {lot_size:>12,.2f} lots")
            if units:
                out.append(f"       (units)     : {units:>12,.0f}")
            _rt = float(s.get("risk_usd_target", risk_actual) or risk_actual)
            _pct = (risk_actual / _rt) if _rt else 1.0   # risk_usd_target IS 1% of the static account
            out.append(f"    Risk (actual)  : {fmt_money(risk_actual)}  (~{_pct:.2f}% of account)")
            # Hard guard: if lot rounding pushed the ACTUAL dollar risk materially
            # above the 1% target, the printed lot is oversized for the $150/$300
            # caps -- surface it loudly rather than let it be placed silently.
            if _rt and risk_actual > _rt * 1.10:
                out.append(f"    [!!] RISK MISMATCH -- lot risks {fmt_money(risk_actual)} "
                           f"(~{_pct:.2f}% of account) vs {fmt_money(_rt)} target.")
                out.append(f"         DO NOT place as-is; use platform Risk Mode = 1% + the Stop.")
            out.append(f"    >> EXACT 1%    : set platform Risk Mode = 1% + the Stop")
            out.append(f"       Loss above; that lot IS your 1% (this is a cross-check).")
            if not spec_verified:
                out.append(f"    [!] CONFIRM contract size on the FundingPips")
                out.append(f"        order ticket before entering this size.")
        else:
            out.append(f"    Risk           : {fmt_money(risk_amt)}")
            out.append(f"    [!] LOT SIZE UNAVAILABLE -- do not size off this alert")
            note = s.get("sizing_note")
            if note:
                out.append(f"        {note[:48]}")
        out.append(f"    R:R (to T2)    : 1:{rr_t2:>5.2f}")
        if composite:
            out.append(f"    Composite      : {float(composite):>5.2f} / 10")
        out.append("")
    return "\n".join(out).rstrip()


def below_bar_block(scan: Dict) -> str:
    """FYI list of SKIP setups below even the CAUTION show-bar this scan.

    CAUTION signals (>= min_composite_to_alert) are shown in the main NEW
    SIGNALS block; this block is only the sub-caution SKIPs, so the user can
    see what was filtered out entirely without it ever pinging or trading."""
    minc = _load_alert_composite()
    below = [s for s in (scan.get("signals") or []) if _composite_of(s) < minc]
    if not below:
        return ""
    out = [f"SKIPPED  (composite < {minc:g}, below the CAUTION bar -- not shown above)"]
    for s in below[:8]:
        sym = (s.get("display_name") or s.get("symbol", "?"))[:14]
        dir_ = s.get("direction", "?").upper()
        label, _ = signal_verdict(s)
        out.append(f"  {sym:14s} {dir_:5s}  {label}")
    if len(below) > 8:
        out.append(f"  ... and {len(below) - 8} more")
    return "\n".join(out)


def open_positions_block(positions: List[Dict]) -> str:
    """Aligned table of open paper positions."""
    if not positions:
        return "OPEN POSITIONS\n  (none)"
    out = [
        "OPEN POSITIONS",
        "  ID      TICKER       DIR    ENTRY      NOW        PnL          R     ",
        "  " + "─" * 70,
    ]
    for i, p in enumerate(positions[:8], 1):  # cap at 8 rows for message length
        sym  = (p.get("display_name") or p.get("symbol", "?"))[:10]
        dir_ = p.get("direction", "?").upper()
        entry = p.get("entry_price", 0)
        now   = p.get("current_price", entry)
        pnl   = float(p.get("unrealized_pnl", p.get("realized_pnl", 0)))
        r_mult = float(p.get("r_multiple_open", p.get("trade_r_multiple", 0)))
        days = p.get("days_held")
        days_s = (f"{int(days)}d" if days is not None else "")
        out.append(
            f"  T{i:04d}  {sym:10s}  {dir_:5s}  "
            f"{fmt_price(entry, 9):>9}  {fmt_price(now, 9):>9}  "
            f"{('+' if pnl >= 0 else '-')}${abs(pnl):>8,.2f}  "
            f"{r_mult:+5.2f}R  {days_s}"
        )
    if len(positions) > 8:
        out.append(f"  ... and {len(positions) - 8} more")
    return "\n".join(out)


def closed_block(closed_this_scan: List[Dict]) -> str:
    """Trades closed since the last Discord message."""
    if not closed_this_scan:
        return ""
    out = ["CLOSED THIS SCAN"]
    for p in closed_this_scan[:6]:
        sym = (p.get("display_name") or p.get("symbol", "?"))[:10]
        dir_ = p.get("direction", "?").upper()
        pnl = float(p.get("realized_pnl", 0))
        r_mult = float(p.get("trade_r_multiple", 0))
        reason = p.get("close_reason", "")
        out.append(
            f"  {sym:10s}  {dir_:5s}  "
            f"{('+' if pnl >= 0 else '-')}${abs(pnl):>8,.2f}  "
            f"{r_mult:+5.2f}R  {reason}"
        )
    return "\n".join(out)


def track_record_block(history: List[Dict]) -> str:
    if not history:
        return (
            "TRACK RECORD\n"
            "  No completed trades yet. Building track record.\n"
            "  Positions close on T1/T2/T3, stop-loss, or trailing exit."
        )
    out = ["TRACK RECORD (last 5 trades)"]
    for p in history[-5:][::-1]:
        sym = (p.get("display_name") or p.get("symbol", "?"))[:10]
        dir_ = p.get("direction", "?").upper()
        pnl = float(p.get("realized_pnl", 0))
        r_mult = float(p.get("trade_r_multiple", 0))
        reason = p.get("close_reason", "")
        out.append(
            f"  {sym:10s}  {dir_:5s}  "
            f"{('+' if pnl >= 0 else '-')}${abs(pnl):>8,.2f}  "
            f"{r_mult:+5.2f}R  {reason}"
        )
    return "\n".join(out)


def footer_block(scan: Dict) -> str:
    n = int(scan.get("watchlist_scanned", 0))
    err = len(scan.get("errors", []))
    base = (
        "Azalyst Propfirm  |  Simulated paper trades.  Not financial advice.\n"
        f"{n} symbols scanned  •  {err} errors  •  next scan in ~4h"
    )
    # Note how many setups were below the quality bar (not alerted this scan).
    minc = _load_min_composite()
    below = [s for s in (scan.get("signals") or []) if _composite_of(s) < minc]
    if below:
        base += (f"\n{len(below)} setup(s) below your quality bar "
                 f"(composite < {minc:g}) were not alerted.")
    return base


# ───────────────────────────────────────────────────────────────────────
# Diff vs last sent
# ───────────────────────────────────────────────────────────────────────

def load_state() -> Dict:
    if not STATE_FILE.exists():
        return {"signal_ids_seen": [], "open_position_ids_seen": []}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"signal_ids_seen": [], "open_position_ids_seen": []}


def save_state(scan: Dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "signal_ids_seen": [
            s.get("signal_id") or s.get("paper_trade_id") or s.get("symbol")
            for s in (scan.get("signals") or [])
        ],
        "open_position_ids_seen": [
            p.get("id") for p in (scan.get("positions") or [])
        ],
        "last_sent_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def diff(scan: Dict, prev_state: Dict) -> Tuple[List[Dict], List[Dict]]:
    """Return (new_signals_this_scan, closed_this_scan)."""
    seen_signal_ids = set(prev_state.get("signal_ids_seen") or [])
    new_signals = []
    for s in scan.get("signals") or []:
        sid = s.get("signal_id") or s.get("paper_trade_id") or s.get("symbol")
        if sid not in seen_signal_ids:
            new_signals.append(s)

    seen_position_ids = set(prev_state.get("open_position_ids_seen") or [])
    current_position_ids = {p.get("id") for p in (scan.get("positions") or [])}
    closed_ids = seen_position_ids - current_position_ids
    closed = [
        h for h in (scan.get("trade_history") or [])
        if h.get("id") in closed_ids
    ]
    return new_signals, closed


# ───────────────────────────────────────────────────────────────────────
# Build the full message
# ───────────────────────────────────────────────────────────────────────

def _wrap(body: str) -> str:
    """Wrap a plain body in a fenced code block for Discord monospace rendering."""
    return f"```\n{body.strip()}\n```"


def build_status_message(scan: Dict, closed_trades: List[Dict]) -> str:
    """Portfolio status: header + account + stats + CLOSED + OPEN + TRACK RECORD.

    This is the 'what's happening with my running trades' message. Always
    sent first so the user sees open-position state even when new signals
    would otherwise push it out via truncation.
    """
    blocks: List[str] = [header_block(scan.get("scan_time"))]
    blocks.append(account_block(scan.get("account") or {}))
    blocks.append(stats_block(
        scan.get("account") or {},
        scan.get("positions") or [],
        scan.get("trade_history") or [],
    ))
    if closed_trades:
        blocks.append(closed_block(closed_trades))
    blocks.append(open_positions_block(scan.get("positions") or []))
    blocks.append(track_record_block(scan.get("trade_history") or []))
    below_bar = below_bar_block(scan)
    if below_bar:
        blocks.append(below_bar)
    blocks.append(footer_block(scan))

    body = SECTION_SEP.join(b for b in blocks if b).strip()
    if len(body) > DISCORD_MSG_LIMIT:
        body = body[:DISCORD_MSG_LIMIT - 30] + "\n... (truncated)"
    return _wrap(body)


def build_signals_message(scan: Dict, new_signals: List[Dict]) -> str:
    """New-signals-only message. Sent as a separate follow-up so it gets
    its own @ping and never crowds out the portfolio status block above."""
    ts_line = header_block(scan.get("scan_time")).splitlines()[1]
    blocks = [f"AZALYST PROPFIRM SCANNER  —  NEW SIGNALS\n{ts_line}"]
    blocks.append(new_signals_block(new_signals))
    body = SECTION_SEP.join(b for b in blocks if b).strip()
    if len(body) > DISCORD_MSG_LIMIT:
        body = body[:DISCORD_MSG_LIMIT - 30] + "\n... (truncated -- see dashboard for full list)"
    return _wrap(body)


def build_message(scan: Dict, new_signals: List[Dict], closed_trades: List[Dict]) -> str:
    """Legacy single-message builder (kept for --dry-run preview).

    Live sends use build_status_message + build_signals_message instead so
    open-position state never gets truncated when there are many new signals.
    """
    blocks: List[str] = [header_block(scan.get("scan_time"))]
    blocks.append(account_block(scan.get("account") or {}))
    blocks.append(stats_block(
        scan.get("account") or {},
        scan.get("positions") or [],
        scan.get("trade_history") or [],
    ))
    if closed_trades:
        blocks.append(closed_block(closed_trades))
    blocks.append(open_positions_block(scan.get("positions") or []))
    blocks.append(track_record_block(scan.get("trade_history") or []))
    if new_signals:
        blocks.append(new_signals_block(new_signals))
    below_bar = below_bar_block(scan)
    if below_bar:
        blocks.append(below_bar)
    blocks.append(footer_block(scan))

    body = SECTION_SEP.join(b for b in blocks if b).strip()
    if len(body) > DISCORD_MSG_LIMIT:
        body = body[:DISCORD_MSG_LIMIT - 30] + "\n... (truncated)"
    return _wrap(body)


# ───────────────────────────────────────────────────────────────────────
# POST to Discord
# ───────────────────────────────────────────────────────────────────────

def post_to_discord(webhook_url: str, content: str,
                    user_id: Optional[str] = None,
                    attempts: int = 3) -> bool:
    """POST a message to a Discord webhook.

    `user_id` is an optional Discord user-snowflake (numeric string). When
    provided, the message is prefixed with `<@USER_ID>` and `allowed_mentions`
    explicitly grants user-ping permission so the user actually gets a
    desktop/mobile notification (webhook messages don't ping by default).
    """
    if user_id:
        # Prepend the mention OUTSIDE the code-block fence so Discord parses
        # it as a real ping rather than literal text.
        content = f"<@{user_id}>\n{content}"

    payload: Dict = {
        "content": content,
        "username": "Azalyst Propfirm",
    }
    if user_id:
        payload["allowed_mentions"] = {"users": [str(user_id)]}

    for i in range(1, attempts + 1):
        try:
            r = requests.post(webhook_url, json=payload, timeout=20)
            if r.status_code in (200, 204):
                return True
            # 429 = rate-limit; honour Retry-After
            if r.status_code == 429:
                wait = float(r.headers.get("Retry-After", "5"))
                print(f"[discord] 429 rate-limited; waiting {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"[discord] HTTP {r.status_code}: {r.text[:200]}", file=sys.stderr)
        except requests.RequestException as exc:
            print(f"[discord] attempt {i} failed: {exc}", file=sys.stderr)
        time.sleep(2 * i)
    return False


# ───────────────────────────────────────────────────────────────────────
# Main
# ───────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Send scan_results.json summary to Discord")
    ap.add_argument("--dry-run", action="store_true", help="print the message; don't POST")
    ap.add_argument("--webhook-url", default=os.environ.get("DISCORD_WEBHOOK_URL"),
                    help="Discord webhook URL (defaults to env DISCORD_WEBHOOK_URL)")
    ap.add_argument("--user-id", default=os.environ.get("DISCORD_USER_ID"),
                    help="Discord user snowflake ID to @ping on every message "
                         "(defaults to env DISCORD_USER_ID). Omit to disable pings.")
    ap.add_argument("--always-send", action="store_true",
                    help="send the portfolio update even if nothing changed since last message")
    args = ap.parse_args()

    if not SCAN_FILE.exists():
        print(f"[discord] No scan_results.json at {SCAN_FILE}; nothing to send.", file=sys.stderr)
        return 0  # not an error -- workflow may have no fresh output

    with open(SCAN_FILE, "r", encoding="utf-8") as f:
        scan = json.load(f)

    prev_state = load_state()
    new_signals, closed_trades = diff(scan, prev_state)

    # Two-tier quality filter:
    #   * TAKE  (composite >= min_composite_to_post): shown + @pinged (+ paper-
    #     traded by the scanner). Actionable.
    #   * CAUTION (min_composite_to_alert <= composite < post): SHOWN in Discord
    #     with its [CAUTION] tag for awareness, but NOT @pinged and NOT traded.
    #   * SKIP (below alert bar): held back (FYI count only).
    _take_comp = _load_min_composite()
    _alert_comp = _load_alert_composite()
    _all_new = new_signals
    new_signals = [s for s in _all_new if _composite_of(s) >= _alert_comp]   # shown (take+caution)
    _take_new = [s for s in new_signals if _composite_of(s) >= _take_comp]   # ping-worthy (take)
    _caution_new = [s for s in new_signals if _composite_of(s) < _take_comp]
    _hidden = len(_all_new) - len(new_signals)
    if _hidden:
        print(f"[discord] {_hidden} new signal(s) below composite {_alert_comp:g} "
              f"held back (not shown).")
    if _caution_new:
        print(f"[discord] {len(_caution_new)} CAUTION signal(s) shown + pinged + "
              f"paper-traded at MIN lot.")

    has_news = bool(new_signals or closed_trades)
    breached = (scan.get("account") or {}).get("prop_firm", {}).get("breached", False)

    # Skip the send if there's nothing actionable AND nothing breached AND
    # the user didn't pass --always-send.  The first call after fresh state
    # always sends so the channel sees a "system online" baseline.
    first_send = not STATE_FILE.exists()
    if not has_news and not breached and not args.always_send and not first_send:
        print("[discord] No new signals or closed trades since last message; skipping.")
        return 0

    status_msg = build_status_message(scan, closed_trades)
    signals_msg = build_signals_message(scan, new_signals) if new_signals else None

    if args.dry_run:
        # Reconfigure stdout to UTF-8 so the box-drawing chars render on
        # Windows consoles (default cp1252) without crashing.
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
        print(status_msg)
        if signals_msg:
            print("\n--- FOLLOW-UP MESSAGE ---\n")
            print(signals_msg)
        return 0

    if not args.webhook_url:
        print("[discord] No webhook URL configured (env DISCORD_WEBHOOK_URL); skipping.",
              file=sys.stderr)
        return 0  # not an error -- some users may opt out of Discord

    # Send portfolio status first (silent -- no @ping for hourly updates).
    # This block ALWAYS includes the open-positions table so the user sees
    # running-trade state even when there are many new signals queued below.
    ok_status = post_to_discord(args.webhook_url, status_msg, user_id=None)
    if not ok_status:
        print("[discord] Status message failed.", file=sys.stderr)
        return 1

    # New signals come as a separate follow-up message with an @ping. Both TAKE
    # and CAUTION signals ping the user (CAUTION is paper-traded at min lot, but
    # the user still wants a heads-up on it). Only SKIP (below the alert bar) is
    # silent -- those never reach `new_signals`.
    ok_signals = True
    if signals_msg:
        ping_user_id = args.user_id
        ok_signals = post_to_discord(args.webhook_url, signals_msg, user_id=ping_user_id)
        if not ok_signals:
            print("[discord] Signals follow-up failed.", file=sys.stderr)
            return 1

    save_state(scan)
    sent_chars = len(status_msg) + (len(signals_msg) if signals_msg else 0)
    print(f"[discord] Sent {1 if not signals_msg else 2} msg(s), {sent_chars} chars total. "
          f"new_signals={len(new_signals)}  closed={len(closed_trades)}  breached={breached}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
