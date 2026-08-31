#!/usr/bin/env python3
"""Bar-by-bar trade-OUTCOME replay through BP_paper_trader.PaperTrader.

WHY THIS EXISTS
    Neither existing harness can measure whether a change makes or loses money.
      * run_goldtest.py scores Stage-1 direction only. Paper-trader config
        cannot move that number at all.
      * run_forward_test.py never instantiates PaperTrader -- it only asks
        whether T1 or the stop is hit first. No breakeven, no partials, no
        trailing, no close_reason.
    This drives the REAL PaperTrader over pinned historical bars, so
    breakeven / partial / trailing behaviour is the thing under test.

DETERMINISM
    Bars come only from ohlcv_snapshot/*.csv (pinned). No network, ever.
    PaperTrader calls datetime.now() in five places -- entry_time, close_time,
    the pending age-expiry clock, the E-05 drift check and maybe_roll_day. Left
    alone, a replay runs at wall-clock "now", so every order is 0 days old and
    the age-expiry path silently never fires. We patch the module-level
    `datetime` with a clock that returns the CURRENT BAR's timestamp.
    (maybe_roll_day re-imports datetime locally and is therefore NOT patched --
    see LIMITATIONS.)

ISOLATION
    Default is one PaperTrader per signal. Portfolio gates -- max_positions,
    the daily/total loss budget, the correlation cap -- would otherwise silently
    drop trades from one arm of an A/B and not the other, and an A/B whose arms
    contain different trades measures attrition, not the flag.

USAGE
    python replay_trades.py --from-goldtest "nocyc?.json" --ab
    python replay_trades.py --signals-file mysignals.json --arm be_half=1

LIMITATIONS -- read before quoting any number this prints
 1. INTRA-BAR PATH IS UNKNOWABLE. update_positions() arms the half-target
    breakeven from the bar's HIGH and then tests the stop against the same
    bar's LOW. On a bar that touches both, the BE always wins, because it is
    checked first. Reality depends on the order the two levels were touched
    inside that bar, which daily bars do not record. Every such trade is
    counted and reported as `path_ambiguous`. A result whose sign depends on
    those trades is not a result.
 2. maybe_roll_day() uses the wall clock, so the whole replay counts as one
    trading day. Irrelevant while prop_firm is disabled (the default here),
    which is why it is disabled.
 3. Fills are optimistic in the usual backtest way: a limit fills at its exact
    level with no slippage, spread or commission.
 4. A signal is replayed as a RESTING LIMIT. If price never trades to the
    entry within the horizon the trade is NO_FILL, not a loss.
 5. The horizon is capped by the pinned data. Every pinned CSV is truncated at
    the call date it was fetched for, so the furthest any replay can run is the
    latest pin for that symbol. Reported per trade as `bars_available`.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import pandas as pd                                          # noqa: E402
import BP_paper_trader as pt                                 # noqa: E402
from BP_paper_trader import PaperTrader, TradeStatus         # noqa: E402

SNAP_DIR = ROOT / "ohlcv_snapshot"
RISK_PER_TRADE = 1000.0          # $ risked per trade, so P&L is comparable across symbols


# ---------------------------------------------------------------- fake clock
class _ClockMeta(type):
    """Falls through to the real `datetime` for everything except now().

    Needed as a metaclass, not a plain __getattr__: BP_paper_trader reaches for
    `datetime.fromisoformat` at :772, and that is a CLASS attribute lookup, which
    an instance-level __getattr__ would never see.
    """

    def __getattr__(cls, item):
        return getattr(datetime, item)


class _Clock(metaclass=_ClockMeta):
    """Stands in for `datetime` inside BP_paper_trader for the length of a replay."""
    current = datetime(2000, 1, 1)

    @classmethod
    def now(cls, tz=None):
        return cls.current


def _install_clock():
    """Swap the module-level `datetime` name. Returns the original for restore."""
    original = pt.datetime
    pt.datetime = _Clock
    return original


# ------------------------------------------------------------------ bar data
_BARS_CACHE: Dict[str, Optional[pd.DataFrame]] = {}


_DATE_WINDOW = re.compile(r"__(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})__primary\.csv$")


def load_forward_bars(symbol: str, interval: str = "1d") -> Optional[pd.DataFrame]:
    """Pinned series for `symbol` that reaches furthest forward in time.

    Two kinds of pin exist, and the difference decides the replay horizon:
      * date-windowed (`SYM__1d__2013-05-22_2023-05-20__primary.csv`) -- written
        by run_goldtest, TRUNCATED at the call date it was fetched for. Useless
        as a forward source for a signal on or after that date.
      * period-keyed (`SYM__1d__5y__primary.csv`) -- written by a period fetch,
        running up to whenever it was pinned. Much longer forward reach.
    Period-keyed wins; date-windowed is the fallback, latest end first.
    """
    key = symbol + "|" + interval
    if key in _BARS_CACHE:
        return _BARS_CACHE[key]

    period_keyed, dated = [], []
    for path in SNAP_DIR.glob(symbol + "__" + interval + "__*__primary.csv"):
        m = _DATE_WINDOW.search(path.name)
        if m:
            dated.append((m.group(2), path))
        else:
            period_keyed.append(path)
    dated.sort(reverse=True)
    candidates = sorted(period_keyed) + [p for _, p in dated]
    if not candidates:
        _BARS_CACHE[key] = None
        return None
    best = candidates[0]
    df = pd.read_csv(best)
    ts = pd.to_datetime(df["timestamp"])
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_localize(None)
    df["timestamp"] = ts
    df = df.sort_values("timestamp").reset_index(drop=True)
    _BARS_CACHE[key] = df
    return df


# -------------------------------------------------------------------- config
_LIVE_CFG: Optional[Dict] = None


def _live_config() -> Dict:
    """The real BP_config.yaml. Loaded once.

    Not optional: `entry_distance` drives the E-05 pending-drift cancel, and its
    per-strategy caps differ from the in-code fallbacks (monthly is 5R/25% in the
    file, 3R/15% in code). Running the replay on the fallbacks silently cancelled
    a monthly order that the live config would have kept resting.
    """
    global _LIVE_CFG
    if _LIVE_CFG is None:
        import yaml
        with open(ROOT / "BP_config.yaml", encoding="utf-8") as fh:
            _LIVE_CFG = yaml.safe_load(fh) or {}
    return _LIVE_CFG


def replay_config(be_half: bool) -> Dict:
    """Live config for anything that shapes a trade; guardrails forced OFF.

    Prop-firm limits, the position cap and the correlation cap would otherwise
    drop trades from one arm of an A/B and not the other, so an A/B would be
    measuring attrition instead of the flag.
    """
    live = _live_config()
    risk = dict(live.get("risk") or {})
    risk.update({
        "account_balance": 1_000_000.0,
        "max_open_positions": 999,
        "max_daily_loss_pct": 100.0,
        "max_total_loss_pct": 100.0,
        "correlation_check_enabled": False,
    })
    stop = dict(live.get("stop_loss") or {})
    stop["breakeven_at_half_target"] = be_half
    return {
        "risk": risk,
        "stop_loss": stop,
        "prop_firm": {"enabled": False},
        "entry_distance": live.get("entry_distance") or {},
        "correlation_groups": live.get("correlation_groups") or {},
    }


# ------------------------------------------------------------------- signals
@dataclass
class Signal:
    symbol: str
    direction: str
    entry: float
    stop: float
    targets: List[float]
    call_date: datetime
    income_strategy: str
    source: str = ""

    @property
    def risk_per_unit(self) -> float:
        return abs(self.entry - self.stop)


def signals_from_goldtest(pattern: str) -> List[Signal]:
    out: List[Signal] = []
    seen = set()
    files = sorted(glob.glob(pattern)) or sorted(glob.glob(str(HERE / pattern)))
    for f in files:
        for case in json.load(open(f, encoding="utf-8")).get("results", []):
            sysd = case.get("system") or {}
            if not sysd.get("entry_price"):
                continue
            key = (case["symbol"], case["call_date"][:10], sysd["entry_price"])
            if key in seen:
                continue
            seen.add(key)
            out.append(Signal(
                symbol=case["symbol"],
                direction=sysd["direction"],
                entry=float(sysd["entry_price"]),
                stop=float(sysd["stop_price"]),
                targets=[float(t) for t in sysd["targets"]],
                call_date=datetime.fromisoformat(case["call_date"][:10]),
                income_strategy=case.get("strategy") or "weekly",
                source=os.path.basename(f),
            ))
    return sorted(out, key=lambda s: (s.call_date, s.symbol))


# -------------------------------------------------------------------- replay
def replay_one(sig: Signal, be_half: bool, horizon_bars: int = 180) -> Dict:
    """Drive one signal through its own PaperTrader. Returns a result row."""
    row: Dict = {
        "symbol": sig.symbol, "call_date": sig.call_date.date().isoformat(),
        "direction": sig.direction, "entry": sig.entry, "stop": sig.stop,
        "targets": sig.targets, "strategy": sig.income_strategy,
        "outcome": None, "close_reason": None, "r": None, "pnl": None,
        "max_fav_r": None, "reached_1r": None, "bars_held": 0,
        "path_ambiguous": False, "bars_available": 0, "skip_reason": None,
        "filled_at": None,
    }

    if sig.risk_per_unit <= 0:
        row["outcome"] = "DEGENERATE"
        row["skip_reason"] = "entry == stop, risk per unit is zero"
        return row

    bars = load_forward_bars(sig.symbol)
    if bars is None:
        row["outcome"] = "NO_DATA"
        row["skip_reason"] = "no pinned 1d snapshot for " + sig.symbol
        return row

    fwd = bars[bars["timestamp"] > sig.call_date].head(horizon_bars).reset_index(drop=True)
    row["bars_available"] = len(fwd)
    if fwd.empty:
        row["outcome"] = "NO_DATA"
        row["skip_reason"] = "pinned series ends at or before the call date"
        return row

    original = _install_clock()
    try:
        _Clock.current = sig.call_date
        trader = PaperTrader(replay_config(be_half))
        size = RISK_PER_TRADE / sig.risk_per_unit
        pos_id = trader.submit_signal({
            "symbol": sig.symbol, "direction": sig.direction,
            "entry_price": sig.entry, "stop_price": sig.stop, "targets": sig.targets,
            "position_size": size, "risk_amount": RISK_PER_TRADE,
            "pending_order": True, "price_at_zone": False,
            "zone_id": "replay::" + sig.symbol + "::" + sig.call_date.date().isoformat(),
            "income_strategy": sig.income_strategy,
        })
        if pos_id is None:
            row["outcome"] = "REJECTED"
            row["skip_reason"] = "submit_signal returned None"
            return row

        halfway = (sig.entry + sig.targets[0]) / 2.0 if sig.targets else None
        best_r = 0.0
        filled_at = None

        for _, bar in fwd.iterrows():
            _Clock.current = bar["timestamp"].to_pydatetime()
            high, low, close = float(bar["high"]), float(bar["low"]), float(bar["close"])
            prices = {sig.symbol: {"bid": close, "ask": close, "close": close,
                                   "high": high, "low": low}}

            pos = trader.positions.get(pos_id)
            if pos is not None and pos.status == TradeStatus.ACTIVE:
                row["bars_held"] += 1
                if sig.direction == "long":
                    best_r = max(best_r, (high - sig.entry) / sig.risk_per_unit)
                    touch_be = halfway is not None and high >= halfway
                    revisits_entry = low <= sig.entry
                    touch_stop = low <= pos.current_stop
                else:
                    best_r = max(best_r, (sig.entry - low) / sig.risk_per_unit)
                    touch_be = halfway is not None and low <= halfway
                    revisits_entry = high >= sig.entry
                    touch_stop = high >= pos.current_stop
                # LIMITATION 1. The comparison that matters is against ENTRY, not
                # against the stop currently on the position. On the bar that arms
                # the half-target BE, the stop is still the ORIGINAL one when the
                # bar opens; it only becomes `entry` because update_positions arms
                # BE first and tests the stop afterwards, within the same bar.
                # So a bar that reaches halfway AND trades back to entry decides
                # the trade purely by intra-bar ordering:
                #   down-to-entry first  -> BE not yet armed, original stop still
                #                           in force, trade survives
                #   up-to-halfway first  -> BE armed, trade scratches at 0R
                # Daily bars do not record which happened.
                if not pos.breakeven_triggered and touch_be and (revisits_entry or touch_stop):
                    row["path_ambiguous"] = True

            # update BEFORE check_pending_fills: PaperTrader documents that a
            # freshly filled limit must not be stop/target-tested on its own bar
            trader.update_positions(prices)
            newly = trader.check_pending_fills(prices)
            if newly and filled_at is None:
                filled_at = bar["timestamp"]

            if pos_id not in trader.positions:
                break

        row["max_fav_r"] = round(best_r, 4)
        row["reached_1r"] = bool(best_r >= 1.0)
        if filled_at is not None:
            row["filled_at"] = filled_at.date().isoformat()

        hist = {p.id: p for p in trader.trade_history}
        pos = trader.positions.get(pos_id) or hist.get(pos_id)
        if pos is None:
            row["outcome"] = "LOST"                       # should be unreachable
        elif pos.status == TradeStatus.PENDING:
            row["outcome"] = "NO_FILL"
        elif pos.status == TradeStatus.CANCELLED:
            row["outcome"] = "CANCELLED"
            row["close_reason"] = pos.close_reason or "expired_or_drifted"
        elif pos.status == TradeStatus.ACTIVE:
            row["outcome"] = "STILL_OPEN"
            row["r"] = round(best_r, 4)
        else:
            row["outcome"] = "CLOSED"
            row["close_reason"] = pos.close_reason
            row["r"] = round(float(pos.trade_r_multiple), 4)
            row["pnl"] = round(float(pos.realized_pnl), 2)
        return row
    finally:
        pt.datetime = original


def summarise(rows: List[Dict], label: str) -> Dict:
    closed = [r for r in rows if r["outcome"] == "CLOSED"]
    filled = closed + [r for r in rows if r["outcome"] == "STILL_OPEN"]
    return {
        "arm": label,
        "signals": len(rows),
        "degenerate": sum(r["outcome"] == "DEGENERATE" for r in rows),
        "no_data": sum(r["outcome"] == "NO_DATA" for r in rows),
        "no_fill": sum(r["outcome"] == "NO_FILL" for r in rows),
        "cancelled": sum(r["outcome"] == "CANCELLED" for r in rows),
        "still_open": sum(r["outcome"] == "STILL_OPEN" for r in rows),
        "closed": len(closed),
        "wins": sum((r["pnl"] or 0) > 0 for r in closed),
        "losses": sum((r["pnl"] or 0) < 0 for r in closed),
        "scratches": sum((r["pnl"] or 0) == 0 for r in closed),
        "reached_1r": sum(bool(r["reached_1r"]) for r in filled),
        "path_ambiguous": sum(bool(r["path_ambiguous"]) for r in rows),
        "total_r": round(sum(r["r"] or 0 for r in closed), 4),
        "total_pnl": round(sum(r["pnl"] or 0 for r in closed), 2),
    }


def _fmt(val, spec):
    return format(val, spec) if val is not None else ""


def print_rows(rows: List[Dict]) -> None:
    hdr = ("%-10s %-11s %-5s %-11s %-10s %7s %10s %6s %5s %4s" %
           ("symbol", "call_date", "dir", "outcome", "reason", "R", "PnL",
            "maxR", "bars", "amb"))
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print("%-10s %-11s %-5s %-11s %-10s %7s %10s %6s %5d %4s" % (
            r["symbol"], r["call_date"], r["direction"], str(r["outcome"]),
            str(r["close_reason"] or ""), _fmt(r["r"], ".2f"), _fmt(r["pnl"], ".2f"),
            _fmt(r["max_fav_r"], ".2f"), r["bars_held"],
            "Y" if r["path_ambiguous"] else ""))
        if r["skip_reason"]:
            print("%-10s   -- %s" % ("", r["skip_reason"]))


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-goldtest", default="nocyc?.json",
                    help="glob of goldtest result JSONs to pull full signals from")
    ap.add_argument("--signals-file", help="JSON list of signals instead of goldtest output")
    ap.add_argument("--arm", action="append", default=[],
                    help="be_half=1 or be_half=0; repeatable")
    ap.add_argument("--ab", action="store_true",
                    help="run both arms and print the paired delta")
    ap.add_argument("--horizon", type=int, default=180, help="max forward bars per trade")
    ap.add_argument("--out", help="write the full per-trade rows here as JSON")
    a = ap.parse_args()

    if a.signals_file:
        raw = json.load(open(a.signals_file, encoding="utf-8"))
        sigs = [Signal(s["symbol"], s["direction"], float(s["entry_price"]),
                       float(s["stop_price"]), [float(t) for t in s["targets"]],
                       datetime.fromisoformat(s["call_date"][:10]),
                       s.get("income_strategy", "weekly"), a.signals_file)
                for s in raw]
    else:
        sigs = signals_from_goldtest(a.from_goldtest)

    print("%d signals loaded from %s\n" % (len(sigs), a.signals_file or a.from_goldtest))
    if not sigs:
        sys.exit("no signals -- nothing to replay")

    if a.ab:
        arms = [True, False]
    elif a.arm:
        arms = [v.split("=")[1] == "1" for v in a.arm]
    else:
        arms = [True]

    results: Dict[str, List[Dict]] = {}
    summaries: List[Dict] = []
    for be in arms:
        label = "be_half=" + ("1" if be else "0")
        rows = [replay_one(s, be, a.horizon) for s in sigs]
        results[label] = rows
        summaries.append(summarise(rows, label))
        print("=== arm %s ===" % label)
        print_rows(rows)
        print()

    print("=== summary ===")
    keys = ["arm", "signals", "degenerate", "no_data", "no_fill", "cancelled",
            "still_open", "closed", "wins", "losses", "scratches", "reached_1r",
            "path_ambiguous", "total_r", "total_pnl"]
    print(" | ".join(keys))
    for s in summaries:
        print(" | ".join(str(s[k]) for k in keys))

    if a.ab:
        on, off = results["be_half=1"], results["be_half=0"]
        diff = [(x, y) for x, y in zip(on, off)
                if (x["r"], x["outcome"]) != (y["r"], y["outcome"])]
        print("\npaired: %d of %d trades differ between the arms" % (len(diff), len(on)))
        for x, y in diff:
            print("  %-10s %s  be_half=1 %s/%s R=%s  ->  be_half=0 %s/%s R=%s%s" % (
                x["symbol"], x["call_date"], x["outcome"], x["close_reason"], x["r"],
                y["outcome"], y["close_reason"], y["r"],
                "   [PATH-AMBIGUOUS]" if x["path_ambiguous"] else ""))
        amb = sum(bool(x["path_ambiguous"]) for x, _ in diff)
        if amb:
            print("\n  %d of the %d differing trades are PATH-AMBIGUOUS -- their outcome "
                  "depends on\n  intra-bar ordering that daily bars do not record." %
                  (amb, len(diff)))

    if a.out:
        json.dump(results, open(a.out, "w", encoding="utf-8"), indent=1, default=str)
        print("\nwrote " + a.out)


if __name__ == "__main__":
    main()
