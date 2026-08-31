#!/usr/bin/env python3
"""Expectancy in R for a signal population, with the accounting C-101 established.

WHY A SEPARATE TOOL
`replay_trades.py` drives the real PaperTrader and answers "what would this config
have done". This answers the prior question -- "does this signal population have an
edge at all" -- with a mechanical rule that has an exact null hypothesis:

    enter at the signal's entry, stop at its stop, target at 2R.

On a driftless series the probability of touching +2R before -1R is EXACTLY 1/3, so
a random entry scores 33.3% and +0.00R by construction. That gives a baseline that
needs no simulation and cannot be argued with, which the win-rate-versus-always-long
comparisons in this project could not offer.

    python goldtest/expectancy.py --signals-file sigs.json
    python goldtest/expectancy.py --from-goldtest "zf?.json"        # goldtest output
    python goldtest/expectancy.py --from-goldtest "zf?.json" --control

TWO ACCOUNTINGS, BOTH REPORTED, because they answer different questions:

  per TRADE TAKEN    excludes signals price never reached. Answers "when I get
                     filled, is it worth it".
  per OPPORTUNITY    counts an unfilled signal as 0R. Answers "is this signal
                     population worth running", which is the one that matters for
                     a funded account, since an unfilled signal earns nothing but
                     also costs nothing.

C-101 measured their own drawn setups at +0.56R per trade and +0.37R per
opportunity, against -0.33R for the same calls entered at market.

--control re-runs every signal with the entry moved to the next bar's OPEN, keeping
symbol, date, direction and R-distance identical. That isolates the ENTRY PRICE from
the direction and from market drift -- the comparison that showed the entry is the
whole edge.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SNAP = ROOT / "ohlcv_snapshot"


# Extra directories searched BEFORE ohlcv_snapshot, set by --pin-dir. Kept separate
# so the reproducible snapshot is never shadowed unless a caller asks for it.
EXTRA_PIN_DIRS = []


def _naive(col):
    """Timestamps as tz-naive, tolerating mixed offsets.

    Freshly fetched FX/futures series carry per-row UTC offsets that straddle a DST
    change, which pandas refuses to parse into a single column without utc=True.
    The pinned snapshots predate that and parse either way, so both go through here.
    """
    ts = pd.to_datetime(col, utc=True, errors="coerce")
    return ts.dt.tz_localize(None)


def pin(symbol: str):
    """Longest pinned daily series, preferring the period-keyed (forward-reaching) pins.

    Searches --pin-dir directories first (see extend_pins.py), then the reproducible
    snapshot. A symbol absent from the extended dirs falls through unchanged, so
    passing --pin-dir affects only the symbols that were actually extended.
    """
    cands = []
    for d in EXTRA_PIN_DIRS:
        cands += sorted(Path(d).glob(f"{symbol}__1d__*__primary.csv"))
    if cands:
        df = pd.read_csv(cands[-1])
        df["timestamp"] = _naive(df["timestamp"])
        return df.sort_values("timestamp").reset_index(drop=True)
    cands = sorted(SNAP.glob(f"{symbol}__1d__*__primary.csv"))
    period = [c for c in cands if "__5y__" in c.name or "__2y__" in c.name]
    if not cands:
        return None
    df = pd.read_csv(period[0] if period else cands[-1])
    df["timestamp"] = _naive(df["timestamp"])
    return df.sort_values("timestamp").reset_index(drop=True)


def resolve(fwd, entry, stop, direction, start=0, rr=2.0):
    """Stop-first or target-first, walking bars in order. 'open' if neither is hit."""
    R = abs(entry - stop)
    if R <= 0:
        return "degenerate"
    tgt = entry + (rr * R if direction == "long" else -rr * R)
    for _, b in fwd.iloc[start:].iterrows():
        lo, hi = float(b["low"]), float(b["high"])
        if direction == "long":
            if lo <= stop:
                return "loss"
            if hi >= tgt:
                return "win"
        else:
            if hi >= stop:
                return "loss"
            if lo <= tgt:
                return "win"
    return "open"


def first_touch(fwd, entry, direction):
    for i, b in fwd.iterrows():
        if direction == "long" and float(b["low"]) <= entry:
            return i
        if direction == "short" and float(b["high"]) >= entry:
            return i
    return None


def load_from_goldtest(pattern, dedupe=True):
    """Signals from goldtest output, collapsed to DISTINCT TRADES by default.

    C-105: run_goldtest evaluates every case in isolation with a fresh engine and
    no trader state, so an unconsumed zone is re-emitted on every scan while it
    stays live. Measured on the C-104 midpoint arm: 11 signals were 4 distinct
    trades, with ONE BABA setup -- byte-identical entry 89.16 and stop 86.01 --
    appearing on 8 separate dates. Averaging over the raw emissions let that
    single losing trade carry 8/9 of the result.

    (`BP_paper_trader.submit_signal` guards against this in live use via
    zone_memory and a duplicate check; the harness has no trader, so it cannot.)

    Deduplication is on (symbol, direction, entry, stop) rounded to 6 places --
    the trade's identity, not the scan that emitted it -- and the EARLIEST date is
    kept, because that is when the setup first became actionable.

    Pass dedupe=False only to inspect emission counts; never for expectancy.
    """
    rows = []
    files = sorted(glob.glob(pattern)) or sorted(glob.glob(str(HERE / pattern)))
    for f in files:
        for c in json.load(open(f, encoding="utf-8")).get("results", []):
            s = c.get("system") or {}
            if not s.get("entry_price"):
                continue
            rows.append({"symbol": c["symbol"], "call_date": c["call_date"][:10],
                         "direction": s.get("direction"),
                         "entry_price": float(s["entry_price"]),
                         "stop_price": float(s["stop_price"])})
    if not dedupe:
        return rows
    best = {}
    for r in rows:
        key = (r["symbol"], r["direction"],
               round(r["entry_price"], 6), round(r["stop_price"], 6))
        if key not in best or r["call_date"] < best[key]["call_date"]:
            best[key] = r
    out = sorted(best.values(), key=lambda r: (r["call_date"], r["symbol"]))
    if len(out) != len(rows):
        print(f"  C-105 dedupe: {len(rows)} signal emissions -> {len(out)} distinct trades")
    return out


def normalise(rows):
    """Accept either signal shape and return the canonical one.

    `run_forward_test.py --emit-signals` writes `date` / `entry` / `stop`, because that
    is what `replay_trades.py` consumes. Everything in this file was written against
    `call_date` / `entry_price` / `stop_price` from the goldtest output. The two never
    met until a forward run was analysed, at which point every tool here would have
    raised KeyError on 15 hours of results. Normalising on input costs nothing and means
    neither producer has to change.
    """
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        d = dict(r)
        if "call_date" not in d and d.get("date"):
            d["call_date"] = str(d["date"])[:10]
        if "entry_price" not in d and d.get("entry") is not None:
            d["entry_price"] = d["entry"]
        if "stop_price" not in d and d.get("stop") is not None:
            d["stop_price"] = d["stop"]
        if d.get("call_date") and d.get("entry_price") is not None                 and d.get("stop_price") is not None and d.get("direction"):
            d["call_date"] = str(d["call_date"])[:10]
            try:
                d["entry_price"] = float(d["entry_price"])
                d["stop_price"] = float(d["stop_price"])
            except (TypeError, ValueError):
                continue
            out.append(d)
    return out


def measure(signals, rr, control=False, max_wait=None):
    signals = normalise(signals)
    res = collections.Counter()
    rows = []
    for s in signals:
        px = pin(s["symbol"])
        if px is None:
            res["no data"] += 1
            continue
        fwd = px[px["timestamp"] > pd.Timestamp(s["call_date"])].reset_index(drop=True)
        if fwd.empty:
            res["no data"] += 1
            continue
        entry, stop, d = s["entry_price"], s["stop_price"], s["direction"]
        R = abs(entry - stop)
        if R <= 0:
            res["degenerate"] += 1
            continue
        if control:
            # same direction, same R, but taken at market on the next open
            entry = float(fwd["open"].iloc[0])
            stop = entry - R if d == "long" else entry + R
            start = 0
        else:
            start = first_touch(fwd, entry, d)
            if start is None or (max_wait is not None and start > max_wait):
                res["never filled"] += 1
                continue
        out = resolve(fwd, entry, stop, d, start, rr)
        res[out] += 1
        rows.append({"symbol": s["symbol"], "date": s["call_date"], "dir": d,
                     "bars_to_fill": start, "outcome": out})
    return res, rows


def drift_null(signals, rr, samples=40, seed=12345):
    signals = normalise(signals)
    """Base rate for the SAME symbols, directions and R sizes at random dates.

    WHY THIS EXISTS
    The 1/(1+rr) null above is exact only on a DRIFTLESS series. It was quoted
    throughout this project against samples that turned out to be 97% long and
    concentrated in 2023 -- a strongly rising year -- where "long anything at
    market" beats 33.3% on drift alone and nothing is proven by clearing it.

    For each signal this re-runs the identical mechanical rule (enter at market,
    stop R away, target rr*R) on the same symbol and direction at `samples`
    random dates drawn from the pinned series. What comes back is what that
    direction earned on that instrument over that era for no skill at all, which
    is the number a real signal has to beat.

    Deterministic: seeded, and the dates are drawn from the pinned bars, so the
    null is reproducible across runs like everything else here.
    """
    import random
    rng = random.Random(seed)
    res = collections.Counter()
    for s in signals:
        px = pin(s["symbol"])
        if px is None or len(px) < 60:
            continue
        R_frac = abs(s["entry_price"] - s["stop_price"]) / max(abs(s["entry_price"]), 1e-9)
        d = s["direction"]
        hi = len(px) - 1
        for _ in range(samples):
            i = rng.randrange(0, max(1, hi - 1))
            fwd = px.iloc[i:].reset_index(drop=True)
            if len(fwd) < 2:
                continue
            entry = float(fwd["open"].iloc[0])
            R = entry * R_frac
            if R <= 0:
                continue
            stop = entry - R if d == "long" else entry + R
            res[resolve(fwd, entry, stop, d, 0, rr)] += 1
    return res


def report(name, res, rr):
    w, l, o = res["win"], res["loss"], res["open"]
    decided = w + l
    unfilled = res["never filled"]
    print(f"\n=== {name} ===")
    print(f"  signals {sum(res.values())}   never filled {unfilled}   "
          f"decided {decided}   still open {o}   no data {res['no data']}")
    if not decided:
        print("  nothing decided -- no expectancy")
        return
    per_trade = (w * rr - l) / decided
    opp = decided + unfilled
    per_opp = (w * rr - l) / opp if opp else 0.0
    print(f"  win rate        {w}/{decided} = {100*w/decided:.1f}%")
    print(f"  per TRADE TAKEN {per_trade:+.2f}R")
    print(f"  per OPPORTUNITY {per_opp:+.2f}R   (unfilled counted as 0R, n={opp})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--signals-file")
    ap.add_argument("--from-goldtest")
    ap.add_argument("--rr", type=float, default=2.0, help="target in R (their KPI is 2)")
    ap.add_argument("--control", action="store_true",
                    help="also measure the same calls entered at market")
    ap.add_argument("--max-wait", type=int,
                    help="drop fills that took longer than N bars")
    ap.add_argument("--drift-null", type=int, metavar="N",
                    help="drift-matched baseline: same symbols/directions/R at N "
                         "random dates each. Use this instead of the 1/(1+rr) null "
                         "whenever the sample is directionally lopsided.")
    ap.add_argument("--pin-dir", action="append", default=[],
                    help="extra pin directory searched before ohlcv_snapshot "
                         "(see extend_pins.py). Repeatable.")
    ap.add_argument("--no-dedupe", action="store_true",
                    help="count raw signal EMISSIONS instead of distinct trades (C-105) "
                         "-- for inspecting emission counts only, never for expectancy")
    a = ap.parse_args()

    for d in a.pin_dir:
        p = Path(d)
        EXTRA_PIN_DIRS.append(p if p.is_absolute() else ROOT / p)
    if EXTRA_PIN_DIRS:
        print(f"pin search order: {[str(x) for x in EXTRA_PIN_DIRS]} then {SNAP}")

    if a.from_goldtest:
        signals = load_from_goldtest(a.from_goldtest, dedupe=not a.no_dedupe)
    elif a.signals_file:
        raw = json.load(open(a.signals_file, encoding="utf-8"))
        if isinstance(raw, dict):           # replay output is keyed by arm
            raw = next(iter(raw.values()))
        signals = normalise(raw)
        if not signals:
            sys.exit(f"{a.signals_file}: no usable signals after normalising "
                     "(need direction + entry/entry_price + stop/stop_price + date)")
    else:
        ap.error("need --signals-file or --from-goldtest")
    print(f"{len(signals)} signals loaded")
    if not signals:
        sys.exit("nothing to measure")

    res, _ = measure(signals, a.rr, control=False, max_wait=a.max_wait)
    report(f"AT THE SIGNAL'S ENTRY (target {a.rr}R)", res, a.rr)
    if a.control:
        cres, _ = measure(signals, a.rr, control=True)
        report(f"CONTROL: same call at MARKET (target {a.rr}R)", cres, a.rr)
    if a.drift_null:
        dres = drift_null(signals, a.rr, samples=a.drift_null)
        report(f"DRIFT-MATCHED NULL: same symbols and directions, "
               f"{a.drift_null} random dates each", dres, a.rr)
        print("  ^ THIS is the number to beat when the sample is directionally "
              "lopsided,\n    not the driftless 33.3% below.")
    print(f"\n  random walk, no drift, by theory:  "
          f"{100/(1+a.rr):.1f}% win   +0.00R   <- exact, not simulated")
    print(f"  their published KPI slide:          40.0% win   "
          f"{0.4*a.rr - 0.6:+.2f}R at {a.rr}R")


if __name__ == "__main__":
    main()
