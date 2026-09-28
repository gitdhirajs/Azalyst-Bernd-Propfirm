#!/usr/bin/env python3
"""
Send the latest scan_results.json to a Discord channel via webhook.

Usage:
    DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/... \
        python send_discord.py

    python send_discord.py --dry-run     # build the message but don't POST
    python send_discord.py --dry-run --input X.json --state Y.json --now 2026-09-27T21:40Z

The script reads:
    scan_results.json          (latest scan output -- required)
    discord_state.json         (last sent state -- created on first run)

The Discord message is a fixed-width text block styled to match the AZALYST
PAPER PORTFOLIO report format. We diff the current scan against the
previously-sent state to call out:
    NEW SIGNALS            -- orders to copy to FundingPips (one msg each + chart)
    FILLED / CLOSED        -- orders that filled / trades that closed since the last post
    ORDERS CANCELLED       -- resting orders the bot withdrew (cancel them at the broker)
    PORTFOLIO STATUS       -- equity, FP guardrails, open trades, pending orders

Posting cadence (2026-09-27, hourly runs -- see decide_post()):
    * post IMMEDIATELY when there is news: a new signal (with @ping), a fill,
      a closed trade, or a cancelled resting order;
    * otherwise post the account status at most once per UTC day, on the first
      run at or after 21:30 UTC (after the FX daily close);
    * also post on the first run, on a challenge reset and when the account
      first becomes breached; --always-send forces a post.
The scanner runs every hour, so without this gate the channel would get 24
identical status posts a day. Kill switch: BP_DISCORD_CADENCE=0 posts the
status on every run (fail open). AZALYST_DAILY_STATUS_UTC="HH:MM" moves the
daily status time.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

# A missing/broken charting stack must never kill the send: the chart is
# decoration, the account status and the order levels are what matter.
# (Before 2026-09-27 draw_chart imported mplfinance at module level, so an
# ImportError here aborted the whole Discord post.)
try:
    import draw_chart
except Exception as _chart_exc:  # pragma: no cover - depends on environment
    print(f"[discord] charts disabled: {_chart_exc}", file=sys.stderr)
    draw_chart = None

# Trade-management settings: the ONE reader shared with the paper trader and
# the charts (stop_loss.management in BP_config.yaml), so the alert describes
# what the paper trader actually does. Pure python + yaml; the fallback only
# guards a broken checkout.
try:
    from BP_management import resolve_management, scale_out_levels, fmt_r as _fmt_r
except Exception as _mg_exc:  # pragma: no cover - depends on environment
    print(f"[discord] management settings unavailable: {_mg_exc}", file=sys.stderr)
    resolve_management = None
    scale_out_levels = None

    def _fmt_r(r):
        return f"{r:g}"

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

# ── Posting cadence (hourly runs) ──────────────────────────────────────
# Daily status time (UTC) -- after the FX daily close (17:00 New York).
# Override with AZALYST_DAILY_STATUS_UTC="HH:MM".
DAILY_STATUS_DEFAULT = (21, 30)
# A setup keeps its "already announced" mark while it keeps being re-emitted;
# it is forgotten this many days after it was LAST seen (it can then re-post
# as a fresh setup). Pending orders live 14-30 days, so 30 covers them.
SIGNAL_MEMORY_DAYS = 30
# Cap on remembered order / closed-trade ids (keeps discord_state.json small).
ID_MEMORY_MAX = 500
STATE_VERSION = 2
# The status continues in follow-up messages instead of being cut (see _paginate).
MAX_STATUS_PAGES = 3
# Charts are shown inside embeds (image = attachment://<file>). Discord allows
# at most 10 embeds and 10 files per webhook message.
MAX_MESSAGE_IMAGES = 10
EMBED_LONG = 0x26A69A      # TradingView green: long / winning trade
EMBED_SHORT = 0xEF5350     # TradingView red:   short / losing trade
EMBED_NEUTRAL = 0x4E5058   # grey: scratch


# ───────────────────────────────────────────────────────────────────────
# Number / time formatting helpers
# ───────────────────────────────────────────────────────────────────────

LINE = "─" * 56          # 56 chars wide — fits Discord mobile cleanly
SECTION_SEP = "\n" + LINE + "\n"
MISSING = "-"            # printed for any missing / non-finite value (never "nan")


def _num(v) -> Optional[float]:
    """float(v) when it is a finite number, else None.

    NaN reaches this script for real: run_scanner's json_safe() passes float
    NaN through and json.load() reads it back, which is how the live alert
    printed "Now:nan" (a position whose last close was NaN)."""
    if isinstance(v, bool):
        return float(v)
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _int(v, default: int = 0) -> int:
    f = _num(v)
    return int(f) if f is not None else default


def fmt_money(v: float, sign: bool = False) -> str:
    """Format a USD number with thousand separators and 2 decimals.
    `sign=True` prefixes a + on positive numbers (use for PnL)."""
    v = _num(v)
    if v is None:
        return f"{MISSING:>13}"
    s = f"${abs(v):>12,.2f}"
    if sign:
        s = f"{'+' if v >= 0 else '-'}{s.lstrip('$').strip()}"
        s = f"${s:>12}"
    elif v < 0:
        s = "-" + s[1:]
    return s


def fmt_pct(v: float, sign: bool = True) -> str:
    v = _num(v)
    if v is None:
        return f"{MISSING:>8}"
    return f"{('+' if sign and v >= 0 else '')}{v:7.2f}%"


def fmt_price(v: float, width: int = 10) -> str:
    """Variable-precision price formatter (forex pairs need 5 decimals,
    indices need 2, crypto can need 4)."""
    v = _num(v)
    if v is None:
        return f"{MISSING:>{width}}"
    if v >= 1000:
        return f"{v:>{width},.2f}"
    if v >= 10:
        return f"{v:>{width},.3f}"
    return f"{v:>{width}.5f}"


def _px(v) -> str:
    """Compact price for the level lines (Entry/SL/TP): no padding, "-" for
    a missing or non-finite level."""
    return fmt_price(v).strip()


def fmt_qty(v, min_dp: int = 0, max_dp: int = 6) -> str:
    """Quantity with as many decimals as it needs (min_dp..max_dp).

    The old "{units:,.0f}" printed a 0.01-lot BTC order as "(units): 0" --
    rounding the only number the user types into the order ticket to zero.
    Whole numbers keep their thousands separators (100,000); fractional
    quantities keep their significant decimals (0.01, 0.005)."""
    f = _num(v)
    if f is None:
        return MISSING
    s = f"{f:,.{max_dp}f}"
    whole, _, frac = s.partition(".")
    frac = frac.rstrip("0")
    if len(frac) < min_dp:
        frac = frac + "0" * (min_dp - len(frac))
    return f"{whole}.{frac}" if frac else whole


def _signed_money(v) -> str:
    f = _num(v)
    if f is None:
        return MISSING
    return f"{'+' if f >= 0 else '-'}${abs(f):,.2f}"


def _signed_r(v) -> str:
    f = _num(v)
    if f is None:
        return MISSING
    return f"{f:+.2f}R"


def parse_utc(value, naive_is_local: bool = False) -> Optional[datetime]:
    """Parse an ISO timestamp to an aware UTC datetime (None if unparseable).

    Naive strings are ambiguous. Persisted fields (challenge_started_at,
    filled_at, close_time) are read as UTC -- the bot runs on a UTC GitHub
    runner, and reading them as the reader's local time is what produced
    "Day -1 since reset" when a naive IST value was compared on the runner.
    scan_time is written by this same run on this same machine, so it is
    read as local time (naive_is_local=True)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.astimezone() if naive_is_local else dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_when(value) -> str:
    dt = parse_utc(value)
    return dt.strftime("%d %b %H:%M UTC") if dt else MISSING


def challenge_day(started, now_utc: Optional[datetime] = None) -> Optional[int]:
    """UTC calendar days since the challenge (re)started; 0 on the start day.

    Clamped at 0: a start stamp that reads as slightly in the future (a naive
    local-time value from a machine east of UTC) must never show a negative
    day count."""
    st = parse_utc(started)
    if st is None:
        return None
    now_utc = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return max(0, (now_utc.date() - st.date()).days)


def order_label(p: Dict) -> str:
    """BUY-LIMIT / BUY-STOP / SELL-LIMIT / SELL-STOP for a signal or order.

    A limit fills when price comes back TO the zone (long: trades down to the
    entry); a stop fills only when price breaks THROUGH the entry in the trade
    direction (E3b: buy-stop above the hammer high). Treating the E3b stop as a
    limit booked fills exactly when the setup had failed (defect 4), so the
    alert must say which one to place. Payloads from before order_type existed
    fall back to entry_type (E3b = stop, everything else = limit)."""
    ot = str(p.get("order_type") or "").strip().lower()
    if ot not in ("limit", "stop"):
        ot = "stop" if str(p.get("entry_type") or "").upper() == "E3B" else "limit"
    side = "BUY" if str(p.get("direction", "")).lower() == "long" else "SELL"
    return f"{side}-{ot.upper()}"


def _order_fill_rule(label: str) -> str:
    return {
        "BUY-LIMIT":  "fills if price trades DOWN to entry",
        "SELL-LIMIT": "fills if price trades UP to entry",
        "BUY-STOP":   "fills only if price trades UP to entry",
        "SELL-STOP":  "fills only if price trades DOWN to entry",
    }.get(label, "")


def _reason(p: Dict) -> str:
    return str(p.get("close_reason") or "").strip() or MISSING


def _targets3(p: Dict) -> Tuple:
    """Return (T1, T2, T3) from a position/signal's targets list, padding with
    None when fewer than three targets exist."""
    t = list(p.get("targets", []) or [])
    t += [None, None, None]
    return t[0], t[1], t[2]


def _levels_line(p: Dict) -> str:
    t1, t2, t3 = _targets3(p)
    sl = p.get("current_stop", p.get("stop_price"))
    return f"         SL:{_px(sl)}   T1:{_px(t1)}  T2:{_px(t2)}  T3:{_px(t3)}"


# ── trade management (2026-09-28) ─────────────────────────────────────────

def _mgmt(scan: Optional[Dict] = None, s: Optional[Dict] = None,
          mgmt: Optional[Dict] = None) -> Dict:
    """Management settings for a message: an explicit dict, else what the
    signal / scan was produced under (run_scanner publishes results
    ['management']), else BP_config.yaml. Same reader as the paper trader."""
    cands = [mgmt, (s or {}).get("management") if isinstance(s, dict) else None,
             (scan or {}).get("management") if isinstance(scan, dict) else None]
    if resolve_management is not None:
        return resolve_management(*cands)
    for c in cands:
        if isinstance(c, dict) and c.get("mode"):
            return c
    return {"mode": "fixed"}


def _is_scale_out(m: Optional[Dict]) -> bool:
    return bool(m) and m.get("mode") == "scale_out"


def _frac_txt(f) -> str:
    f = _num(f)
    return f"{f * 100:g}%" if f is not None else MISSING


def _is_long(p: Dict) -> bool:
    return str(p.get("direction", "")).lower() == "long"


def _r_of(p: Dict, price) -> Optional[float]:
    """R of `price` from the planned entry, in units of the planned risk."""
    e, st, x = _num(p.get("entry_price")), _num(p.get("stop_price")), _num(price)
    if e is None or st is None or x is None or e == st:
        return None
    return (x - e) * (1.0 if _is_long(p) else -1.0) / abs(e - st)


def _stop_r_label(p: Dict, stop) -> str:
    """'breakeven' / '+1R locked' / '+0.37R' for a runner stop."""
    r = _r_of(p, stop)
    if r is None:
        return MISSING
    if abs(r) < 0.05:
        return "breakeven"
    if abs(r - round(r)) < 0.02:
        return f"{round(r):+d}R locked"
    return f"{r:+.2f}R"


def _scale_out_booked(p: Dict) -> Optional[Tuple[float, float, float]]:
    """(fraction closed, $ booked, R booked) of a partialled position/trade."""
    if not p.get("partial_taken"):
        return None
    pq, rem = _num(p.get("partial_qty")) or 0.0, _num(p.get("position_size")) or 0.0
    orig = pq + rem
    if orig <= 0:
        return None
    e, st = _num(p.get("entry_price")), _num(p.get("stop_price"))
    fill = _num(p.get("fill_price"))
    fill = fill if fill is not None else e
    px = _num(p.get("partial_price"))
    if e is None or st is None or px is None or fill is None or e == st:
        return None
    sign = 1.0 if _is_long(p) else -1.0
    usd = (px - fill) * sign * pq
    return pq / orig, usd, usd / (orig * abs(e - st))


def _runner_exit_text(p: Dict) -> str:
    reason = str(p.get("close_reason") or "").strip().lower()
    xr = _r_of(p, p.get("close_price"))
    if reason == "breakeven":
        return "runner breakeven"
    if reason == "trail":
        return f"runner stopped at {_stop_r_label(p, p.get('close_price'))}"
    if reason == "runner_target":
        return f"runner target {xr:+.0f}R" if xr is not None else "runner target"
    if xr is not None:
        return f"runner {reason or 'closed'} {xr:+.2f}R"
    return f"runner {reason or 'closed'}"


# ───────────────────────────────────────────────────────────────────────
# Message blocks
# ───────────────────────────────────────────────────────────────────────

def header_block(scan_time_iso: Optional[str], title: str = "STATUS") -> str:
    """Top of the message: title + timestamp."""
    ts = parse_utc(scan_time_iso, naive_is_local=True) or datetime.now(timezone.utc)
    return (
        f"AZALYST PROPFIRM SCANNER  —  {title}\n"
        f"{ts.strftime('%d %b %Y  %H:%M UTC')}\n"
    )


def account_block(account: Dict, now_utc: Optional[datetime] = None) -> str:
    """Equity, deposited capital, return %, and the FP Trading Objectives."""
    pf = account.get("prop_firm", {}) or {}
    equity = _num(account.get("balance"))
    initial = _num(pf.get("account_size"))
    if initial is None:
        initial = equity
    closed_pnl = _num(account.get("closed_pnl", account.get("total_pnl")))
    open_pnl = _num(account.get("open_pnl"))

    overall_return_pct = ((equity - initial) / initial * 100
                          if equity is not None and initial else None)

    def m(v, sign: bool = False) -> str:
        v = _num(v)
        if v is None:
            return f"{MISSING:>12}"
        prefix = ("+" if sign and v >= 0 else "-" if v < 0 else " ")
        return f"{prefix}${abs(v):>10,.2f}"

    def p(v) -> str:
        v = _num(v)
        if v is None:
            return f"{MISSING:>11}"
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
        status = "BREACHED" if pf.get("breached", False) else "ACTIVE"
        lines += [
            LINE,
            f"Daily Loss Used      : {m(pf.get('todays_loss'))}  /  "
            f"{m(pf.get('max_daily_loss_limit')).strip()}",
            f"Daily Loss Remaining : {m(pf.get('daily_loss_remaining'))}",
            f"Total Loss Used      : {m(pf.get('total_loss'))}  /  "
            f"{m(pf.get('max_total_loss_limit')).strip()}",
            f"Total Loss Remaining : {m(pf.get('total_loss_remaining'))}",
            f"Account Status       :{status:>12}",
        ]

        target_pct = _num(pf.get("profit_target_pct"))
        if target_pct:
            # Day count is computed HERE in UTC from challenge_started_at rather
            # than trusting days_elapsed: the paper trader computed that with a
            # naive local clock, which printed "Day -1 since reset" (defect 10).
            days = challenge_day(pf.get("challenge_started_at"), now_utc)
            if days is None and _num(pf.get("days_elapsed")) is not None:
                days = max(0, _int(pf.get("days_elapsed")))
            progress = _num(pf.get("progress_to_target_pct"))
            day_str = f"Day {days}" if days is not None else f"Day {MISSING}"
            progress_str = f"{progress:.1f}%" if progress is not None else MISSING
            lines += [
                LINE,
                f"Challenge Target     :{target_pct:>10.1f}%   "
                f"({m(pf.get('target_equity')).strip()})",
                f"Progress to Target   : {progress_str:>9}  ({day_str} since reset)",
            ]

    return "\n".join(lines)


def stats_block(account: Dict, positions: List[Dict], history: List[Dict]) -> str:
    """Open count, closed count, win rate, W/L, avg R."""
    open_n = len(positions)
    closed_n = _int(account.get("total_trades"))
    win = _int(account.get("winning_trades"))
    loss = _int(account.get("losing_trades"))
    # E-04: win_rate is None until at least one trade is decided (win or loss).
    _wr = _num(account.get("win_rate"))
    _scratch = _int(account.get("scratch_trades"))
    win_rate_str = (f"{_wr * 100:.1f}%" if _wr is not None
                    else f"n/a ({_scratch} scratch{'' if _scratch == 1 else 'es'})")
    avg_r = _num(account.get("avg_r", account.get("avg_r_per_trade")))
    avg_r_str = f"{avg_r:+.2f}R" if avg_r is not None else MISSING

    return "\n".join([
        f"Open Positions       : {open_n:>15}",
        f"Closed Trades        : {closed_n:>15}",
        f"Win Rate             : {win_rate_str:>15}",
        f"Winners / Losers     : {f'{win} / {loss}':>15}",
        f"Avg R per Trade      : {avg_r_str:>15}",
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
    f = _num(qs.get("composite", s.get("composite", 0)))
    return f if f is not None else 0.0


def signal_verdict(s: Dict) -> Tuple[str, str]:
    """Return (verdict_label, location_note).

    2026-08-14: user wants every signal traded, none skipped or downgraded --
    the composite-score gate (TAKE/CAUTION/SKIP tiers) is removed. Every
    signal is [TAKE]; counter-trend / opposing-zone context is kept as an
    informational note only, it no longer changes the verdict.

    2026-09-27: every new signal is a RESTING order. The paper trader no
    longer fills at signal time (fills are replayed from completed 1h bars),
    because "AT ZONE" signals used to be booked as an immediate fill at an
    entry price the market was no longer at -- 6 of 8 losing setups were
    opened that way. price_at_zone is kept as display-only information."""
    comp = _composite_of(s)
    ctx = s.get("trade_context", "standard")
    speed_bump = bool(s.get("speed_bump_warning"))
    at_zone = bool(s.get("price_at_zone"))

    notes = []
    if ctx == "counter_trend":
        notes.append("counter-trend, half size")
    if speed_bump:
        notes.append("opposing zone in path")

    label = f"[TAKE]  composite {comp:.1f}/10"
    if notes:
        label += "  (" + "; ".join(notes) + ")"

    zone_note = "price already at the zone" if at_zone else "price not at the zone yet"
    loc = f"PENDING - resting order; {zone_note}"
    return label, loc


def _signal_verdict_header() -> List[str]:
    return [
        "NEW SIGNALS THIS SCAN",
        "  [TAKE] = pinged + paper-traded. No signal is skipped or downgraded.",
        "",
    ]


def _format_signal_block(s: Dict, take_bar: float, mgmt: Optional[Dict] = None) -> str:
    """Render ONE signal's full block (entry/SL/TP1-3 + risk + R:R + bias).

    Kept as a standalone, never-split unit so callers can truncate on whole
    blocks instead of a raw character offset -- cutting mid-line (e.g. inside
    the "Risk (actual)" line) produced garbled, half-written output."""
    sym  = s.get("display_name") or s.get("symbol", "?")
    dir_ = str(s.get("direction", "?")).upper()
    entry = _num(s.get("entry_price"))
    stop  = _num(s.get("stop_price"))
    targets = [_num(t) for t in (s.get("targets") or [])]
    risk_amt = _num(s.get("risk_amount")) or 0.0
    risk_r = abs(entry - stop) if entry is not None and stop is not None else 0.0
    t2 = targets[1] if len(targets) > 1 else None
    rr_t2 = abs((t2 - entry) / risk_r) if (t2 is not None and risk_r) else None
    composite = _composite_of(s)
    lot_size = _num(s.get("lot_size"))
    units = _num(s.get("units"))
    _ra = _num(s.get("risk_usd_actual"))
    risk_actual = _ra if _ra else risk_amt
    spec_verified = s.get("spec_verified", True)
    label = order_label(s)
    out = [f"  {sym:14s}  {dir_:5s}"]
    _v_label, _v_loc = signal_verdict(s)
    out.append(f"    >> VERDICT     : {_v_label}")
    out.append(f"    Order          : {label} at entry ({_order_fill_rule(label)})")
    if _v_loc:
        out.append(f"    Location       : {_v_loc}")
    _now = _num(s.get("current_price"))
    if _now is not None:
        out.append(f"    Price now      : {fmt_price(_now, 12)}")
    m = _mgmt(s=s, mgmt=mgmt)
    lv = None
    if _is_scale_out(m) and scale_out_levels is not None and entry is not None \
            and stop is not None:
        lv = scale_out_levels(entry, stop, dir_ == "LONG", m)
    out.append(f"    Entry          : {fmt_price(entry, 12)}")
    out.append(f"    Stop Loss      : {fmt_price(stop, 12)}")
    if lv:
        # scale_out (2026-09-28): the engine's 1R/2R/3R targets are not
        # take-profits any more. Show what the paper trader will actually do.
        r1 = _fmt_r(lv["l1_r"])
        lab = f"+{r1}R close {_frac_txt(lv['fraction'])}"
        out.append(f"    {lab:15s}: {fmt_price(lv['l1'], 12)}  stop -> BE")
        for peak_r, peak_px, lock_r, _lock_px in lv["locks"]:
            lab = f"+{_fmt_r(peak_r)}R runner"
            out.append(f"    {lab:15s}: {fmt_price(peak_px, 12)}  stop -> +{_fmt_r(lock_r)}R")
        if lv["runner_target"] is not None:
            lab = f"+{_fmt_r(lv['runner_target_r'])}R runner TP"
            out.append(f"    {lab:15s}: {fmt_price(lv['runner_target'], 12)}  close the rest")
    else:
        for i, t in enumerate(targets[:3], 1):
            out.append(f"    Target {i} ({i}R)  : {fmt_price(t, 12)}")
    # The number to type into FundingPips. Shown prominently.
    if lot_size:
        out.append(f"    >> LOT SIZE    : {fmt_qty(lot_size, min_dp=2):>12} lots")
        if units is not None:
            out.append(f"       (units)     : {fmt_qty(units):>12}")
        _rt = _num(s.get("risk_usd_target")) or risk_actual
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
            out.append(f"        {str(note)[:48]}")
    if lv:
        out.extend(_scale_out_management_lines(lv, m))
    else:
        out.append(f"    R:R (to T2)    : " + (f"1:{rr_t2:>5.2f}" if rr_t2 is not None else MISSING))
        out.append("    >> MANAGEMENT  : stop never moves; close 100% at Target 2")
    if composite:
        out.append(f"    Composite      : {float(composite):>5.2f} / 10")
    return "\n".join(out)


def _scale_out_management_lines(lv: Dict, m: Dict) -> List[str]:
    """The truthful R:R + management lines of a scale_out signal."""
    r1 = _fmt_r(lv["l1_r"])
    frac, rest = _frac_txt(lv["fraction"]), _frac_txt(1.0 - lv["fraction"])
    runner = ("runner open" if lv["runner_target"] is None
              else f"runner to +{_fmt_r(lv['runner_target_r'])}R")
    out = [f"    First take     : +{r1}R on {frac}; {runner}",
           "    >> MANAGEMENT  (scale-out):",
           f"       At +{r1}R: {_px(lv['l1'])} close {frac} + stop to breakeven"]
    if m.get("runner_trail") == "r_steps":
        steps = ", ".join(f"+{_fmt_r(a)}R -> stop +{_fmt_r(c)}R" for a, _b, c, _d in lv["locks"])
        out.append(f"       Runner {rest} trails in 1R steps:")
        if steps:
            out.append(f"       {steps}, ...")
    else:
        out.append(f"       Runner {rest} stays at breakeven (no trail)")
    if lv["runner_target"] is None:
        out.append("       No runner take-profit: it exits on its stop.")
    else:
        out.append(f"       Runner closes at +{_fmt_r(lv['runner_target_r'])}R "
                   f"{_px(lv['runner_target'])}")
    out.append("       Move the stop at the broker when the bot says so.")
    return out


def new_signals_block(new_signals: List[Dict], mgmt: Optional[Dict] = None) -> str:
    """One block per signal. Show entry/SL/TP1/T2/T3 + risk + R:R + bias."""
    if not new_signals:
        return ""
    _take_bar = _load_min_composite()
    header = _signal_verdict_header()
    body = "\n\n".join(_format_signal_block(s, _take_bar, mgmt) for s in new_signals)
    return "\n".join(header) + "\n" + body


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
        dir_ = str(s.get("direction", "?")).upper()
        label, _ = signal_verdict(s)
        out.append(f"  {sym:14s} {dir_:5s}  {label}")
    if len(below) > 8:
        out.append(f"  ... and {len(below) - 8} more")
    return "\n".join(out)


def open_positions_block(positions: List[Dict]) -> str:
    """Open paper positions, 2 lines each so Entry/SL/T1/T2/T3 all fit even on
    mobile. Line 1 = live status (entry, now, PnL, R); line 2 = the levels so
    you can still manage/place the trade if you missed the original alert."""
    if not positions:
        return "OPEN POSITIONS\n  (none)"
    out = ["OPEN POSITIONS   (E=entry  Now=live  SL=stop  T1/T2/T3=targets)"]
    for i, p in enumerate(positions[:6], 1):   # cap rows for message length
        sym  = (p.get("display_name") or p.get("symbol", "?"))[:10]
        dir_ = str(p.get("direction", "?")).upper()
        entry = p.get("entry_price")
        # No fallback to entry: a missing live price must read "-", not a
        # plausible-looking number (and a NaN one used to print "Now:nan").
        now   = p.get("current_price")
        pnl   = p.get("unrealized_pnl", p.get("realized_pnl"))
        r_mult = p.get("r_multiple_open", p.get("trade_r_multiple"))
        out.append(
            f"  T{i:04d} {sym:10s} {dir_:5s} E:{_px(entry)}  Now:{_px(now)}  "
            f"{_signed_money(pnl)}  {_signed_r(r_mult)}"
        )
        out.append(_levels_line(p))
        booked = _scale_out_booked(p)
        if booked:
            frac, usd, rb = booked
            out.append(f"         Booked {_frac_txt(frac)} at {_px(p.get('partial_price'))}: "
                       f"{_signed_money(usd)} ({_signed_r(rb)})")
            out.append(f"         Runner {_frac_txt(1.0 - frac)} open, stop "
                       f"{_px(p.get('current_stop'))} = {_stop_r_label(p, p.get('current_stop'))}")
    if len(positions) > 6:
        out.append(f"  ... and {len(positions) - 6} more open")
    return "\n".join(out)


def pending_orders_block(pending: List[Dict]) -> str:
    """Resting PENDING orders (not filled yet). Shown with the order type and
    full Entry/SL/T1/T2/T3 so a missed signal can still be placed on
    FundingPips. These are NOT open trades and carry no risk until price
    trades to the entry (down/up to a limit, through a stop)."""
    if not pending:
        return ""
    out = ["PENDING ORDERS   (not filled yet -- place as shown)"]
    for p in pending[:8]:
        sym  = (p.get("display_name") or p.get("symbol", "?"))[:10]
        label = order_label(p)
        entry = p.get("entry_price")
        dist = _num(p.get("distance_pct"))
        dist_s = f"  ({dist:.2f}% away)" if dist is not None else ""
        out.append(f"  {sym:10s} {label:10s} E:{_px(entry)}{dist_s}")
        out.append(_levels_line(p))
    if len(pending) > 8:
        out.append(f"  ... and {len(pending) - 8} more pending")
    return "\n".join(out)


def fills_block(fills: List[Dict]) -> str:
    """Resting orders that FILLED since the last post (pending -> open trade)."""
    if not fills:
        return ""
    out = ["FILLED SINCE LAST UPDATE   (pending order -> open trade)"]
    for p in fills[:6]:
        sym = (p.get("display_name") or p.get("symbol", "?"))[:10]
        dir_ = str(p.get("direction", "?")).upper()
        price = p.get("fill_price", p.get("entry_price"))
        when = p.get("filled_at") or p.get("fill_time") or p.get("entry_time")
        out.append(f"  {sym:10s} {dir_:5s} {order_label(p):10s} "
                   f"@ {_px(price)}  {fmt_when(when)}")
        out.append(_levels_line(p))
    if len(fills) > 6:
        out.append(f"  ... and {len(fills) - 6} more filled")
    return "\n".join(out)


def partials_block(partials: List[Dict]) -> str:
    """Scale-out partial closes at +1R and runner stop moves since the last
    post (2026-09-28). The user mirrors the paper trades by hand, so every stop
    move has to be repeated at the broker."""
    if not partials:
        return ""
    out = ["PARTIAL CLOSES / STOP MOVES   (move the stop at the broker)"]
    for e in partials[:8]:
        sym = (e.get("display_name") or e.get("symbol", "?"))[:10]
        dir_ = str(e.get("direction", "?")).upper()
        if e.get("event") == "partial_close":
            at_r = _num(e.get("at_r"))
            if at_r is None:
                at_r = _r_of(e, e.get("price"))
            r_txt = f"+{_fmt_r(round(at_r, 2))}R" if at_r is not None else "Target"
            frac = _num(e.get("fraction"))
            out.append(f"  {sym:10s} {dir_:5s}  {r_txt} reached: closed {_frac_txt(frac)} "
                       f"at {_px(e.get('price'))}")
            out.append(f"    {_signed_money(e.get('pnl'))}, {_signed_r(e.get('r_booked'))} booked"
                       f"  {fmt_when(e.get('at'))}")
            rest = _frac_txt(1.0 - frac) if frac is not None else "rest"
            out.append(f"    stop to breakeven {_px(e.get('new_stop'))}, runner {rest} open")
        else:
            nr = _num(e.get("new_stop_r"))
            lock = (f"{nr:+.0f}R locked" if nr is not None and abs(nr - round(nr)) < 0.02
                    else (f"{nr:+.2f}R" if nr is not None else MISSING))
            out.append(f"  {sym:10s} {dir_:5s}  runner stop -> {_px(e.get('new_stop'))} ({lock})")
    if len(partials) > 8:
        out.append(f"  ... and {len(partials) - 8} more")
    return "\n".join(out)


def cancelled_block(cancelled: List[Dict]) -> str:
    """Resting orders the bot withdrew without a fill (expired / drifted /
    cancelled). The user copies orders to FundingPips by hand, so a silently
    vanished order would stay live at the broker and could fill there as a
    trade the bot no longer tracks."""
    if not cancelled:
        return ""
    out = ["ORDERS CANCELLED   (cancel these at the broker too)"]
    for p in cancelled[:6]:
        sym = (p.get("display_name") or p.get("symbol", "?"))[:10]
        reason = str(p.get("close_reason") or "").strip() or "cancelled"
        out.append(f"  {sym:10s} {order_label(p):10s} E:{_px(p.get('entry_price'))}  {reason}")
    if len(cancelled) > 6:
        out.append(f"  ... and {len(cancelled) - 6} more cancelled")
    return "\n".join(out)


def closed_block(closed_this_scan: List[Dict]) -> str:
    """Trades closed since the last Discord message."""
    if not closed_this_scan:
        return ""
    out = ["CLOSED SINCE LAST UPDATE"]
    for p in closed_this_scan[:6]:
        sym = (p.get("display_name") or p.get("symbol", "?"))[:10]
        dir_ = str(p.get("direction", "?")).upper()
        pnl = _num(p.get("realized_pnl"))
        pnl_s = (f"{('+' if pnl >= 0 else '-')}${abs(pnl):>8,.2f}"
                 if pnl is not None else f"{MISSING:>10}")
        # E-01 (2026-08-26): get_trade_history() renames trade_r_multiple ->
        # r_multiple, so the old read always returned 0 and every close --
        # including real losses -- printed "+0.00R". Fall back to the raw
        # dataclass key for callers that pass unserialised Position dicts.
        r_mult = _num(p.get("r_multiple", p.get("trade_r_multiple")))
        r_s = f"{r_mult:+5.2f}R" if r_mult is not None else f"{MISSING:>6}"
        out.append(
            f"  {sym:10s}  {dir_:5s}  {pnl_s}  {r_s}  {_reason(p)}"
        )
        booked = _scale_out_booked(p)
        if booked:
            # Blended scale-out result, e.g. "+0.50R: 50% at +1R, runner breakeven".
            pr = _r_of(p, p.get("partial_price"))
            pr_s = f"{pr:+.0f}R" if pr is not None and abs(pr - round(pr)) < 0.02 else (
                f"{pr:+.2f}R" if pr is not None else MISSING)
            tot = f"{r_mult:+.2f}R" if r_mult is not None else MISSING
            out.append(f"      = {tot}: {_frac_txt(booked[0])} at {pr_s}, {_runner_exit_text(p)}")
    return "\n".join(out)


def track_record_block(history: List[Dict], mgmt: Optional[Dict] = None) -> str:
    if not history:
        m = _mgmt(mgmt=mgmt)
        if _is_scale_out(m):
            how = (f"  {_frac_txt(m.get('scale_out_fraction'))} closes at "
                   f"+{_fmt_r(m.get('scale_out_at_r') or 1.0)}R (stop to breakeven);\n"
                   "  the runner exits on its stop (trails in 1R steps).")
        else:
            how = "  Each position closes at its stop or 100% at Target 2 (stop never moves)."
        return (
            "TRACK RECORD\n"
            "  No completed trades yet. Building track record.\n"
            + how
        )
    out = ["TRACK RECORD (last 5 trades)   (E=entry  SL=stop  X=exit)"]
    for p in history[-5:][::-1]:
        sym = (p.get("display_name") or p.get("symbol", "?"))[:10]
        dir_ = str(p.get("direction", "?")).upper()
        entry = p.get("entry_price")
        sl    = p.get("stop_price")
        close = p.get("close_price")
        # E-01 (2026-08-26): see closed_block.
        r_mult = p.get("r_multiple", p.get("trade_r_multiple"))
        out.append(
            f"  {sym:10s} {dir_:5s} E:{_px(entry)} SL:{_px(sl)} X:{_px(close)}  "
            f"{_signed_money(p.get('realized_pnl'))} {_signed_r(r_mult)}  {_reason(p)}"
        )
    return "\n".join(out)


def footer_block(scan: Dict) -> str:
    n = _int(scan.get("watchlist_scanned"))
    err = len(scan.get("errors") or [])
    h, m = _daily_status_time()
    base = (
        "Azalyst Propfirm  |  Simulated paper trades.  Not financial advice.\n"
        f"{n} symbols scanned  •  {err} errors  •  next scan in ~1h\n"
        f"Quiet hours post nothing; status posts daily after {h:02d}:{m:02d} UTC."
    )
    # Note how many setups were below the quality bar (not alerted this scan).
    minc = _load_min_composite()
    below = [s for s in (scan.get("signals") or []) if _composite_of(s) < minc]
    if below:
        base += (f"\n{len(below)} setup(s) below your quality bar "
                 f"(composite < {minc:g}) were not alerted.")
    return base


# ───────────────────────────────────────────────────────────────────────
# State + diff vs last sent
# ───────────────────────────────────────────────────────────────────────

def _daily_status_time() -> Tuple[int, int]:
    raw = os.environ.get("AZALYST_DAILY_STATUS_UTC", "")
    try:
        hh, mm = raw.split(":")
        h, m = int(hh), int(mm)
        if 0 <= h < 24 and 0 <= m < 60:
            return h, m
    except ValueError:
        pass
    return DAILY_STATUS_DEFAULT


def _daily_due_at(now_utc: datetime) -> datetime:
    h, m = _daily_status_time()
    return now_utc.astimezone(timezone.utc).replace(hour=h, minute=m, second=0, microsecond=0)


def load_state(path: Optional[Path] = None) -> Dict:
    """Previous discord state; {} when there is none (first run)."""
    path = Path(path) if path else STATE_FILE
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def write_state(state: Dict, path: Optional[Path] = None) -> None:
    path = Path(path) if path else STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def _signal_key(s: Dict) -> str:
    """Identity of a setup. setup_key = symbol|direction|entry|stop (engine
    contract 2026-09-27); older payloads fall back to zone_id / symbol. The
    zone_id alone is not enough: it hashed the leg-out bar timestamp and
    changed daily while that bar was still forming (defect 9)."""
    return str(s.get("setup_key") or s.get("signal_id") or s.get("zone_id")
               or s.get("symbol") or "")


def _legacy_signal_id(s: Dict) -> str:
    return str(s.get("signal_id") or s.get("zone_id") or s.get("symbol") or "")


def _status(p: Dict) -> str:
    return str(p.get("status") or "").lower()


def _challenge_start(scan: Dict) -> Optional[str]:
    pf = (scan.get("account") or {}).get("prop_firm") or {}
    v = pf.get("challenge_started_at")
    return str(v) if v else None


def _compact_order(p: Dict) -> Dict:
    """What we remember about a resting order, so a later cancellation can be
    reported with its symbol/levels even though it is gone from the scan."""
    keep = ("symbol", "display_name", "direction", "entry_price", "stop_price",
            "order_type", "entry_type", "placed_at")
    return {k: p.get(k) for k in keep if p.get(k) is not None}


def _pending_seen(prev: Dict) -> Dict[str, Dict]:
    raw = prev.get("pending_orders_seen")
    if isinstance(raw, dict):
        return {str(k): (v if isinstance(v, dict) else {}) for k, v in raw.items()}
    return {}


def split_shown_signals(new_signals: List[Dict]) -> Tuple[List[Dict], int]:
    """(signals to show, count held back below the CAUTION composite bar)."""
    alert = _load_alert_composite()
    shown = [s for s in new_signals if _composite_of(s) >= alert]
    return shown, len(new_signals) - len(shown)


def compute_events(scan: Dict, prev: Dict) -> Dict:
    """Diff this scan against the last saved state.

    Returns dict(new_signals, fills, closed, cancelled, reset). Everything is
    derived from ids so it survives dropped runs: whatever changed since the
    last SAVED state is reported, however many hourly runs that spans (the
    state is only saved after a successful post)."""
    signals   = scan.get("signals") or []
    positions = scan.get("positions") or []
    pending   = scan.get("pending_orders") or []
    history   = [h for h in (scan.get("trade_history") or []) if isinstance(h, dict)]
    pos_by_id  = {p["id"]: p for p in positions if p.get("id")}
    pend_ids   = {p["id"] for p in pending if p.get("id")}
    hist_by_id = {h["id"]: h for h in history if h.get("id")}

    # A new challenge (paper account reset) makes every remembered order /
    # position id meaningless -- do not report the old account's orders as
    # "cancelled" or its positions as closed.
    start = _challenge_start(scan)
    prev_start = prev.get("challenge_started_at")
    reset = bool(prev and prev_start and start and str(prev_start) != start)
    ids_prev = {} if reset else prev

    prev_open = set(ids_prev.get("open_position_ids_seen") or [])
    prev_pend = _pending_seen(ids_prev)
    announced = set(prev.get("order_ids_seen") or [])

    # ── new signals ────────────────────────────────────────────────────
    key_mem = prev.get("signal_keys_seen")
    legacy_ids = set(prev.get("signal_ids_seen") or []) if not isinstance(key_mem, dict) else set()
    key_mem = key_mem if isinstance(key_mem, dict) else {}
    new_signals, seen_now = [], set()
    for s in signals:
        k = _signal_key(s)
        tid = s.get("paper_trade_id")
        seen = (k in key_mem or k in seen_now
                or (legacy_ids and _legacy_signal_id(s) in legacy_ids))
        # A setup keeps being re-emitted every hour while its zone is valid, so
        # the key alone decides "already announced". The exception is a NEW
        # paper order for it (e.g. re-submitted after the old one was
        # cancelled): that is a fresh order the user has to place again.
        new_order = bool(tid) and tid not in announced and tid not in prev_open \
            and tid not in prev_pend
        if not seen or new_order:
            new_signals.append(s)
        seen_now.add(k)

    # ── fills (pending -> active) ──────────────────────────────────────
    fills: Dict[str, Dict] = {}
    for f in scan.get("fills") or []:
        if isinstance(f, dict):
            fid = f.get("id") or f.get("position_id")
            base = dict(pos_by_id.get(fid) or hist_by_id.get(fid) or {})
            base.update({k: v for k, v in f.items() if v is not None})
        else:
            fid = f
            base = dict(pos_by_id.get(fid) or hist_by_id.get(fid) or {"id": fid})
        if fid and fid not in prev_open:
            fills[str(fid)] = base
    # Backstop from state: an order last seen PENDING that is now ACTIVE, or
    # already CLOSED (filled and stopped/targeted inside one replay window),
    # filled in between -- even if this run's "fills" key is missing or the
    # previous run's post failed before its state was saved.
    for pid in prev_pend:
        if pid in fills:
            continue
        if pid in pos_by_id:
            fills[pid] = dict(pos_by_id[pid])
        elif pid in hist_by_id and _status(hist_by_id[pid]) != "cancelled":
            fills[pid] = dict(hist_by_id[pid])

    # ── closed trades ──────────────────────────────────────────────────
    closed_seen = prev.get("closed_ids_seen")
    if isinstance(closed_seen, list):
        cs = set(closed_seen)
        closed = [h for h in history
                  if h.get("id") and h["id"] not in cs and _status(h) != "cancelled"]
    else:
        # Legacy state (before 2026-09-27): a close was a previously-open id
        # that is gone. That misses a trade that filled AND closed between two
        # posts (never seen open) -- possible now that fills are replayed from
        # 1h bars -- hence closed_ids_seen above.
        gone = prev_open - set(pos_by_id)
        closed = [h for h in history if h.get("id") in gone]

    # ── cancelled resting orders ───────────────────────────────────────
    cancel_info = {}
    for c in (scan.get("cancelled_orders") or []):
        if isinstance(c, dict) and c.get("id"):
            cancel_info[c["id"]] = c
    cancelled = []
    for pid, info in prev_pend.items():
        if pid in pend_ids or pid in pos_by_id or pid in fills:
            continue
        rec = dict(info)
        rec["id"] = pid
        extra = cancel_info.get(pid) or hist_by_id.get(pid)
        if extra:
            rec.update({k: v for k, v in extra.items() if v is not None})
        cancelled.append(rec)

    partials = _partial_events(scan, ids_prev, pos_by_id, hist_by_id)

    return {
        "new_signals": new_signals,
        "fills": list(fills.values()),
        "closed": closed,
        "cancelled": cancelled,
        "partials": partials,
        "reset": reset,
    }


def _partial_key(e: Dict) -> str:
    pid = str(e.get("position_id") or e.get("id") or "")
    if e.get("event") == "partial_close":
        return f"{pid}|partial"
    st = _num(e.get("new_stop"))
    return f"{pid}|stop|{st:.10g}" if st is not None else f"{pid}|stop|?"


def _partial_events(scan: Dict, prev: Dict, pos_by_id: Dict, hist_by_id: Dict) -> List[Dict]:
    """Scale-out partial closes and runner stop moves to report (2026-09-28).

    Primary source: this run's results['partials_this_run']. Backstop from the
    open positions vs the last SAVED state (partial_events_seen /
    runner_stops_seen), so a partial or a lock is still reported when the run
    that produced it failed to post. Each event carries '_key' for build_state."""
    seen = set(prev.get("partial_events_seen") or [])
    runner_prev = prev.get("runner_stops_seen")
    runner_prev = runner_prev if isinstance(runner_prev, dict) else {}
    out: List[Dict] = []
    keys = set()

    def _add(rec: Dict) -> None:
        k = _partial_key(rec)
        if k in seen or k in keys:
            return
        rec["_key"] = k
        keys.add(k)
        out.append(rec)

    for e in scan.get("partials_this_run") or []:
        if not isinstance(e, dict):
            continue
        pid = e.get("position_id") or e.get("id")
        base = pos_by_id.get(pid) or hist_by_id.get(pid) or {}
        rec = {k: base.get(k) for k in ("display_name", "entry_price", "stop_price",
                                         "fill_price") if base.get(k) is not None}
        rec.update({k: v for k, v in e.items() if v is not None})
        _add(rec)

    for pid, p in pos_by_id.items():
        if not p.get("partial_taken"):
            continue
        booked = _scale_out_booked(p)
        if pid not in runner_prev and f"{pid}|partial" not in seen and booked:
            _add({"event": "partial_close", "position_id": pid, "symbol": p.get("symbol"),
                  "display_name": p.get("display_name"), "direction": p.get("direction"),
                  "entry_price": p.get("entry_price"), "stop_price": p.get("stop_price"),
                  "price": p.get("partial_price"), "fraction": booked[0], "pnl": booked[1],
                  "r_booked": booked[2], "new_stop": p.get("fill_price") or p.get("entry_price"),
                  "at": p.get("partial_time")})
        prev_stop, cur = _num(runner_prev.get(pid)), _num(p.get("current_stop"))
        if prev_stop is None or cur is None:
            continue
        tighter = cur > prev_stop if _is_long(p) else cur < prev_stop
        if tighter:
            _add({"event": "stop_moved", "position_id": pid, "symbol": p.get("symbol"),
                  "display_name": p.get("display_name"), "direction": p.get("direction"),
                  "entry_price": p.get("entry_price"), "stop_price": p.get("stop_price"),
                  "price": cur, "new_stop": cur, "new_stop_r": _r_of(p, cur)})
    return out


def diff(scan: Dict, prev_state: Dict) -> Tuple[List[Dict], List[Dict]]:
    """Return (new_signals_this_scan, closed_this_scan). Kept for callers of
    the pre-2026-09-27 API; compute_events() carries fills/cancellations too."""
    ev = compute_events(scan, prev_state)
    return ev["new_signals"], ev["closed"]


def decide_post(scan: Dict, prev: Dict, events: Dict, now_utc: datetime,
                always_send: bool = False) -> Optional[str]:
    """Why to post this run, or None to stay quiet.

    Hourly runs (2026-09-27): news posts immediately; the plain account status
    posts at most once per UTC day, on the first run at/after the daily status
    time (21:30 UTC -- after the FX daily close). Order of precedence only
    changes the message title."""
    if not prev:
        return "first"
    if events.get("reset"):
        return "reset"
    shown, _ = split_shown_signals(events.get("new_signals") or [])
    if (shown or events.get("fills") or events.get("closed") or events.get("cancelled")
            or events.get("partials")):
        return "news"
    breached = bool(((scan.get("account") or {}).get("prop_firm") or {}).get("breached"))
    if breached and not prev.get("breached"):
        return "breach"
    today = now_utc.astimezone(timezone.utc).date().isoformat()
    if now_utc >= _daily_due_at(now_utc) and prev.get("last_status_date") != today:
        return "daily"
    # Kill switch BP_DISCORD_CADENCE=0: fail open -- post the status on EVERY
    # run, in case this gating ever suppresses something it should not.
    if always_send or os.environ.get("BP_DISCORD_CADENCE", "1") == "0":
        return "always"
    return None


def _dedupe_tail(items: List, cap: int) -> List:
    seen, out = set(), []
    for x in reversed(items):
        if x is None or x in seen:
            continue
        seen.add(x)
        out.append(x)
    return list(reversed(out))[-cap:]


def build_state(scan: Dict, prev: Dict, events: Dict, now_utc: datetime,
                posted: bool) -> Dict:
    """The discord_state.json to save after this run."""
    today = now_utc.astimezone(timezone.utc).date()
    signals   = scan.get("signals") or []
    positions = scan.get("positions") or []
    pending   = scan.get("pending_orders") or []
    history   = scan.get("trade_history") or []

    # Rolling setup memory, keyed by the date a setup was LAST seen (date, not
    # time, so the file only changes once a day for a persisting signal).
    mem = dict(prev.get("signal_keys_seen") or {}) if isinstance(
        prev.get("signal_keys_seen"), dict) else {}
    cutoff = today - timedelta(days=SIGNAL_MEMORY_DAYS)
    kept = {}
    for k, d in mem.items():
        try:
            if date.fromisoformat(str(d)) >= cutoff:
                kept[k] = d
        except ValueError:
            continue
    for s in signals:
        k = _signal_key(s)
        if k:
            kept[k] = today.isoformat()

    order_ids = list(prev.get("order_ids_seen") or [])
    order_ids += [p.get("id") for p in pending] + [p.get("id") for p in positions]
    order_ids += [s.get("paper_trade_id") for s in signals]
    closed_ids = list(prev.get("closed_ids_seen") or [])
    closed_ids += [h.get("id") for h in history if isinstance(h, dict)]
    # Scale-out (2026-09-28): partial/stop-move events already reported, and the
    # runner stop of every partialled open position (backstop in compute_events).
    partial_keys = [] if events.get("reset") else list(prev.get("partial_events_seen") or [])
    partial_keys += [e.get("_key") or _partial_key(e) for e in (events.get("partials") or [])]
    runner_stops = {p["id"]: p.get("current_stop") for p in positions
                    if isinstance(p, dict) and p.get("id") and p.get("partial_taken")}

    last_status_date = prev.get("last_status_date")
    if posted and now_utc >= _daily_due_at(now_utc):
        # A status posted after the daily time (for whatever reason) IS today's
        # daily status -- don't post a second one an hour later.
        last_status_date = today.isoformat()

    return {
        "state_version": STATE_VERSION,
        "challenge_started_at": _challenge_start(scan),
        "breached": bool(((scan.get("account") or {}).get("prop_firm") or {}).get("breached")),
        "signal_keys_seen": kept,
        "order_ids_seen": _dedupe_tail(order_ids, ID_MEMORY_MAX),
        "pending_orders_seen": {p["id"]: _compact_order(p) for p in pending if p.get("id")},
        "open_position_ids_seen": [p.get("id") for p in positions if p.get("id")],
        "closed_ids_seen": _dedupe_tail(closed_ids, ID_MEMORY_MAX),
        "partial_events_seen": _dedupe_tail(partial_keys, ID_MEMORY_MAX),
        "runner_stops_seen": runner_stops,
        "last_status_date": last_status_date,
        "last_sent_at": now_utc.isoformat() if posted else prev.get("last_sent_at"),
    }


# ───────────────────────────────────────────────────────────────────────
# Build the full message
# ───────────────────────────────────────────────────────────────────────

_TITLES = {
    "first":  "SYSTEM ONLINE",
    "reset":  "NEW CHALLENGE STARTED",
    "news":   "TRADE UPDATE",
    "breach": "ACCOUNT BREACHED",
    "daily":  "DAILY STATUS (after FX close)",
    "always": "STATUS",
}


def _wrap(body: str) -> str:
    """Wrap a plain body in a fenced code block for Discord monospace rendering."""
    return f"```\n{body.strip()}\n```"


def _assemble(blocks: List[str]) -> str:
    """Assemble in priority order, stopping on WHOLE-block boundaries before the
    2000-char limit (never a mid-line cut). Blocks are ordered most-important
    first so if anything is dropped it's the low-value tail (track record,
    footer), not your live risk."""
    blocks = [b for b in blocks if b]
    body, dropped = "", 0
    for i, blk in enumerate(blocks):
        candidate = (body + SECTION_SEP + blk) if body else blk
        if body and len(candidate) > DISCORD_MSG_LIMIT:
            dropped = len(blocks) - i
            break
        body = candidate
    body = body.strip()
    if dropped:
        note = "\n(+ more; trimmed to fit Discord's 2000-char limit)"
        if len(body) + len(note) <= DISCORD_MSG_LIMIT:
            body += note
    return _wrap(body)


def _cut_lines(text: str, limit: int) -> str:
    """Cut an oversize block on a line boundary (never mid-line)."""
    out = ""
    for ln in text.splitlines():
        if len(out) + len(ln) + 1 > limit:
            return out + "... (truncated)"
        out += ln + "\n"
    return out.rstrip("\n")


def _paginate(blocks: List[str], max_pages: int = MAX_STATUS_PAGES) -> List[str]:
    """Split blocks into Discord-sized messages on WHOLE-block boundaries.

    The single-message status used to DROP whatever did not fit. With the
    FILLED / CLOSED / CANCELLED blocks at the top (2026-09-27) a normal day
    pushed the PENDING ORDERS -- the levels the user copies to the broker --
    off the end. Overflow now continues in a follow-up message instead."""
    limit = DISCORD_MSG_LIMIT - 40            # room for the "(continued i/n)" line
    blocks = [b if len(b) <= limit else _cut_lines(b, limit) for b in blocks if b]
    pages, body = [], ""
    for blk in blocks:
        candidate = (body + SECTION_SEP + blk) if body else blk
        if body and len(candidate) > limit:
            pages.append(body.strip())
            body = blk
        else:
            body = candidate
    if body.strip():
        pages.append(body.strip())
    if len(pages) > max_pages:
        pages = pages[:max_pages]
        note = "\n(+ more; trimmed to fit Discord's message limit)"
        if len(pages[-1]) + len(note) <= DISCORD_MSG_LIMIT:
            pages[-1] += note
    n = len(pages)
    return [_wrap(p if i == 0 else f"(continued {i + 1}/{n})\n{p}")
            for i, p in enumerate(pages)]


def build_status_messages(scan: Dict, closed_trades: List[Dict],
                          fills: Optional[List[Dict]] = None,
                          cancelled: Optional[List[Dict]] = None,
                          title: str = "STATUS",
                          now_utc: Optional[datetime] = None,
                          partials: Optional[List[Dict]] = None) -> List[str]:
    """Portfolio status: header + what changed (FILLED / CLOSED / CANCELLED)
    + account + stats + OPEN + PENDING + TRACK RECORD, as 1..3 messages.

    The change blocks come right after the header: they are the reason this
    message exists, so they must never be the part cut for length."""
    blocks: List[str] = [header_block(scan.get("scan_time"), title)]
    blocks.append(fills_block(fills or []))
    blocks.append(partials_block(partials or []))
    blocks.append(closed_block(closed_trades or []))
    blocks.append(cancelled_block(cancelled or []))
    blocks.append(account_block(scan.get("account") or {}, now_utc))
    blocks.append(stats_block(
        scan.get("account") or {},
        scan.get("positions") or [],
        scan.get("trade_history") or [],
    ))
    blocks.append(open_positions_block(scan.get("positions") or []))
    blocks.append(pending_orders_block(scan.get("pending_orders") or []))
    blocks.append(track_record_block(scan.get("trade_history") or [], _mgmt(scan)))
    blocks.append(below_bar_block(scan))
    blocks.append(footer_block(scan))
    return _paginate(blocks)


def build_status_message(scan: Dict, closed_trades: List[Dict], **kw) -> str:
    """First status page only (pre-2026-09-27 single-message API)."""
    return build_status_messages(scan, closed_trades, **kw)[0]


def build_signals_messages(scan: Dict, new_signals: List[Dict]) -> List[Dict]:
    if not new_signals:
        return []
    ts_line = header_block(scan.get("scan_time")).splitlines()[1]
    take_bar = _load_min_composite()
    header = "\n".join(_signal_verdict_header())
    messages: List[Dict] = []
    ohlcv_cache = scan.get("ohlcv_cache", {}) or {}
    total = len(new_signals)
    for i, s in enumerate(new_signals, 1):
        m = _mgmt(scan, s)
        block = _format_signal_block(s, take_bar, m)
        body = (f"AZALYST PROPFIRM SCANNER  —  NEW SIGNAL {i}/{total}\n{ts_line}"
                + SECTION_SEP + header + "\n\n" + block).strip()
        # A single pathological block must never exceed Discord's limit, or the
        # webhook rejects it and nothing is posted for that signal.
        wrapped = _wrap(body)
        if len(wrapped) > DISCORD_MSG_LIMIT:
            wrapped = _wrap(body[: DISCORD_MSG_LIMIT - 40] + "\n... (truncated)")
        # One message per signal with its chart shown in an embed (None when the
        # chart cannot be drawn; the message is then sent as text only).
        img_path = None
        if draw_chart is not None:
            try:
                img_path = draw_chart.generate_chart(s, ohlcv_cache, asof=scan.get("scan_time"),
                                                     management=m)
            except Exception as exc:   # generate_chart should not raise; belt and braces
                print(f"[discord] chart failed for {s.get('symbol')}: {exc}", file=sys.stderr)
                img_path = None
        images = []
        if img_path:
            is_long = str(s.get("direction", "")).lower() == "long"
            name = s.get("display_name") or s.get("symbol", "?")
            images.append({
                "path": img_path,
                "color": EMBED_LONG if is_long else EMBED_SHORT,
                "title": f"{name} {'LONG' if is_long else 'SHORT'} · "
                         f"{order_label(s)} @ {_px(s.get('entry_price'))}",
            })
        # image_path kept for older callers; `images` carries the embed spec.
        messages.append({"content": wrapped, "image_path": img_path, "images": images})
    return messages


def build_result_images(scan: Dict, closed_trades: List[Dict],
                        limit: int = MAX_MESSAGE_IMAGES) -> List[Dict]:
    """Result charts (fill -> exit, R and $ badge) for the trades reported in
    this post's CLOSED block, as embed image specs, at most `limit`.

    A closed-trade record from an event list can lack the levels the chart
    needs (stop / targets / fill time); those are filled in from the matching
    trade_history record by id. A chart that cannot be drawn is skipped."""
    if draw_chart is None or not closed_trades:
        return []
    cache = scan.get("ohlcv_cache") or {}
    hist = {h.get("id"): h for h in (scan.get("trade_history") or [])
            if isinstance(h, dict) and h.get("id")}
    out: List[Dict] = []
    for t in closed_trades:
        if len(out) >= limit:
            break
        if not isinstance(t, dict):
            continue
        rec = dict(hist.get(t.get("id") or t.get("position_id")) or {})
        rec.update({k: v for k, v in t.items() if v is not None})
        try:
            path = draw_chart.generate_trade_result_chart(rec, cache, timeframe=scan.get("ltf"),
                                                          management=_mgmt(scan))
        except Exception as exc:   # should not raise; belt and braces
            print(f"[discord] result chart failed for {rec.get('symbol')}: {exc}",
                  file=sys.stderr)
            path = None
        if not path:
            continue
        r = _num(rec.get("r_multiple", rec.get("trade_r_multiple")))
        pnl = _num(rec.get("realized_pnl", rec.get("pnl")))
        good = pnl if pnl else (r or 0.0)
        name = rec.get("display_name") or rec.get("symbol", "?")
        out.append({
            "path": path,
            "color": EMBED_LONG if good > 0 else (EMBED_SHORT if good < 0 else EMBED_NEUTRAL),
            "title": f"{name} {str(rec.get('direction', '?')).upper()} closed  "
                     f"{_signed_r(r)}  {_signed_money(pnl)}",
        })
    return out


def build_message(scan: Dict, new_signals: List[Dict], closed_trades: List[Dict]) -> str:
    """Legacy single-message builder (status + signals in one message).

    Live sends use build_status_message + build_signals_messages instead so
    open-position state never gets truncated when there are many new signals.
    """
    blocks: List[str] = [header_block(scan.get("scan_time"))]
    blocks.append(account_block(scan.get("account") or {}))
    blocks.append(stats_block(
        scan.get("account") or {},
        scan.get("positions") or [],
        scan.get("trade_history") or [],
    ))
    blocks.append(closed_block(closed_trades or []))
    blocks.append(open_positions_block(scan.get("positions") or []))
    blocks.append(pending_orders_block(scan.get("pending_orders") or []))
    blocks.append(track_record_block(scan.get("trade_history") or [], _mgmt(scan)))
    blocks.append(new_signals_block(new_signals, _mgmt(scan)))
    blocks.append(below_bar_block(scan))
    blocks.append(footer_block(scan))
    return _assemble(blocks)


# ───────────────────────────────────────────────────────────────────────
# POST to Discord
# ───────────────────────────────────────────────────────────────────────

def post_to_discord(webhook_url: str, content: str,
                    user_id: Optional[str] = None,
                    image_path: Optional[str] = None,
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
            if image_path and os.path.exists(image_path):
                with open(image_path, 'rb') as f:
                    r = requests.post(webhook_url, data={'payload_json': json.dumps(payload)}, files={'file': (os.path.basename(image_path), f)}, timeout=30)
            else:
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


def _cleanup_images(messages: List[Dict]) -> None:
    for m in messages:
        p = m.get("image_path")
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass


# ───────────────────────────────────────────────────────────────────────
# Main
# ───────────────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Send scan_results.json summary to Discord")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the message(s); don't POST and don't write the state file")
    ap.add_argument("--webhook-url", default=os.environ.get("DISCORD_WEBHOOK_URL"),
                    help="Discord webhook URL (defaults to env DISCORD_WEBHOOK_URL)")
    ap.add_argument("--user-id", default=os.environ.get("DISCORD_USER_ID"),
                    help="Discord user snowflake ID to @ping on new-signal messages "
                         "(defaults to env DISCORD_USER_ID). Omit to disable pings.")
    ap.add_argument("--always-send", action="store_true",
                    help="send the portfolio update even if nothing changed since last message")
    ap.add_argument("--input", default=None,
                    help=f"scan results JSON to read (default {SCAN_FILE})")
    ap.add_argument("--state", default=None,
                    help=f"discord state JSON (default {STATE_FILE})")
    ap.add_argument("--now", default=None,
                    help="pretend the current time is this ISO timestamp (UTC if naive); "
                         "for testing the posting cadence")
    args = ap.parse_args(argv)

    scan_file = Path(args.input) if args.input else SCAN_FILE
    state_file = Path(args.state) if args.state else STATE_FILE
    now_utc = parse_utc(args.now) if args.now else datetime.now(timezone.utc)
    if now_utc is None:
        print(f"[discord] --now {args.now!r} is not an ISO timestamp", file=sys.stderr)
        return 2

    if not scan_file.exists():
        print(f"[discord] No scan results at {scan_file}; nothing to send.", file=sys.stderr)
        return 0  # not an error -- workflow may have no fresh output

    with open(scan_file, "r", encoding="utf-8") as f:
        scan = json.load(f)

    prev_state = load_state(state_file)
    events = compute_events(scan, prev_state)

    # Composite show-bar: signals below min_composite_to_alert are held back
    # (FYI count only, in the SKIPPED block); everything at/above it posts.
    new_signals, hidden = split_shown_signals(events["new_signals"])
    if hidden:
        print(f"[discord] {hidden} new signal(s) below composite "
              f"{_load_alert_composite():g} held back (not shown).")

    reason = decide_post(scan, prev_state, events, now_utc, always_send=args.always_send)
    breached = bool(((scan.get("account") or {}).get("prop_firm") or {}).get("breached"))

    if reason is None:
        print(f"[discord] Nothing new (no signal / fill / partial / close / cancellation) and the "
              f"daily status is not due ({now_utc.strftime('%Y-%m-%d %H:%M UTC')}); skipping.")
        if not args.dry_run and args.webhook_url:
            # Keep the setup memory fresh even on quiet runs (content is date
            # granular, so this rarely changes the file).
            write_state(build_state(scan, prev_state, events, now_utc, posted=False), state_file)
        return 0

    status_msgs = build_status_messages(
        scan, events["closed"], fills=events["fills"], cancelled=events["cancelled"],
        title=_TITLES.get(reason, "STATUS"), now_utc=now_utc,
        partials=events.get("partials"))
    signals_msgs = build_signals_messages(scan, new_signals) if new_signals else []

    if args.dry_run:
        # Reconfigure stdout to UTF-8 so the box-drawing chars render on
        # Windows consoles (default cp1252) without crashing.
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
        print(f"[discord] dry-run: would post (reason={reason}) at "
              f"{now_utc.strftime('%Y-%m-%d %H:%M UTC')}: {len(status_msgs)} status + "
              f"{len(signals_msgs)} signal message(s); fills={len(events['fills'])} "
              f"closed={len(events['closed'])} cancelled={len(events['cancelled'])} "
              f"partials={len(events.get('partials') or [])}")
        for i, m in enumerate(status_msgs, 1):
            print(f"\n--- STATUS MESSAGE {i}/{len(status_msgs)} ---\n")
            print(m)
        for i, m in enumerate(signals_msgs, 1):
            print(f"\n--- SIGNALS MESSAGE {i}/{len(signals_msgs)} ---\n")
            print(m["content"])
            if m.get("image_path"):
                print(f"[Chart Image attached: {m['image_path']}]")
        return 0

    if not args.webhook_url:
        _cleanup_images(signals_msgs)
        print("[discord] No webhook URL configured (env DISCORD_WEBHOOK_URL); skipping.",
              file=sys.stderr)
        return 0  # not an error -- some users may opt out of Discord

    try:
        # Portfolio status first (silent -- no @ping), 1..3 messages. It ALWAYS
        # includes the open-positions table so the user sees running-trade state
        # even when there are many new signals queued below.
        for i, m in enumerate(status_msgs):
            if not post_to_discord(args.webhook_url, m, user_id=None):
                print(f"[discord] Status message {i + 1}/{len(status_msgs)} failed.",
                      file=sys.stderr)
                return 1
            time.sleep(0.6)

        # New signals: one message each (with its chart), @ping on the FIRST
        # only so a busy scan pings once, not once per signal.
        for i, m in enumerate(signals_msgs):
            ping_user_id = args.user_id if i == 0 else None
            if not post_to_discord(args.webhook_url, m["content"], user_id=ping_user_id,
                                   image_path=m.get("image_path")):
                print(f"[discord] Signals message {i + 1}/{len(signals_msgs)} failed.",
                      file=sys.stderr)
                return 1
            if i + 1 < len(signals_msgs):
                time.sleep(0.6)
    finally:
        _cleanup_images(signals_msgs)

    write_state(build_state(scan, prev_state, events, now_utc, posted=True), state_file)
    sent_chars = sum(len(m) for m in status_msgs) + sum(len(m["content"]) for m in signals_msgs)
    print(f"[discord] Sent {len(status_msgs) + len(signals_msgs)} msg(s), {sent_chars} chars total. "
          f"reason={reason} new_signals={len(new_signals)} fills={len(events['fills'])} "
          f"closed={len(events['closed'])} cancelled={len(events['cancelled'])} "
          f"breached={breached}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
