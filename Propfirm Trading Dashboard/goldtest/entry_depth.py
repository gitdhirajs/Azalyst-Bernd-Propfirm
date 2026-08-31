#!/usr/bin/env python3
"""Outcome as a function of how deep into the zone the entry is placed.

WHY
Three arms measured on 2026-08-28 line up monotonically once each is compared against
its OWN drift-matched null:

    entry at the zone proximal   -18.3 points vs null
    entry at the zone midpoint    -8.3
    entry at market               +4.3 to +12.3

That is the signature of adverse selection: a limit order deeper inside a demand zone
only fills when price keeps falling, so the deeper the entry the more the fills are
concentrated in the setups that were failing anyway. But those were three separate
goldtest runs over three different signal populations, so the comparison confounds
entry depth with which trades each arm happened to emit.

This removes that confound. It takes ONE signal set and re-prices every signal at a
sweep of depths, holding symbol, date, direction and STOP fixed. Same trades, same
stops, only the entry moves -- so any trend across the sweep is the depth itself.

    python goldtest/entry_depth.py --from-goldtest "goldtest/reach?.json"

Depth 0.0 is the zone proximal as the engine emits it, 1.0 is the stop. R shrinks as
depth grows (the stop stays put), so the 2R target moves closer too -- which is exactly
what a deeper entry buys you, and why the trade-off is worth measuring rather than
assuming.

Each depth also gets a drift-matched null at ITS OWN R, because the null moves with R:
a tighter stop is a different bet, and comparing a 0.3R trade against a 1.0R trade's
baseline would manufacture an effect.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import expectancy as E


def sweep(signals, depths, rr, null_samples):
    out = []
    for d in depths:
        moved = []
        for s in signals:
            e, st = s["entry_price"], s["stop_price"]
            moved.append({**s, "entry_price": e + (st - e) * d})
        res, _ = E.measure(moved, rr, control=False)
        nul = E.drift_null(moved, rr, samples=null_samples) if null_samples else None
        out.append((d, res, nul))
    return out


def line(d, res, nul, rr):
    w, l = res["win"], res["loss"]
    dec = w + l
    unf = res["never filled"]
    if not dec:
        return f"  {d:>5.2f}   {'--':>10}  no decided trades"
    wr = 100.0 * w / dec
    per = (w * rr - l) / dec
    opp = dec + unf
    per_opp = (w * rr - l) / opp if opp else 0.0
    s = (f"  {d:>5.2f}   {w:>3}/{dec:<3} {wr:>5.1f}%  {per:>+6.2f}R  {per_opp:>+6.2f}R"
         f"  {unf:>4}")
    if nul:
        nw, nl = nul["win"], nul["loss"]
        ndec = nw + nl
        if ndec:
            nwr = 100.0 * nw / ndec
            s += f"   {nwr:>5.1f}%   {wr - nwr:>+6.1f}"
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-goldtest")
    ap.add_argument("--signals-file")
    ap.add_argument("--rr", type=float, default=2.0)
    ap.add_argument("--null-samples", type=int, default=25,
                    help="random dates per signal for the per-depth null; 0 to skip")
    ap.add_argument("--pin-dir", action="append", default=[])
    a = ap.parse_args()

    for d in a.pin_dir:
        p = Path(d)
        E.EXTRA_PIN_DIRS.append(p if p.is_absolute() else HERE.parent / p)

    if a.from_goldtest:
        signals = E.load_from_goldtest(a.from_goldtest)
    elif a.signals_file:
        signals = json.load(open(a.signals_file, encoding="utf-8"))
    else:
        ap.error("need --from-goldtest or --signals-file")

    dirs = collections.Counter(s["direction"] for s in signals)
    print(f"{len(signals)} signals, direction split {dict(dirs)}")
    print("same trades and stops at every depth; only the entry moves\n")
    print("  depth   wins       win%    perTrade  perOpp  unfilled"
          + ("   null%   vs null" if a.null_samples else ""))

    depths = [0.0, 0.25, 0.5, 0.75, 1.0]
    rows = sweep(signals, depths, a.rr, a.null_samples)
    for d, res, nul in rows:
        print(line(d, res, nul, a.rr))

    print("\n  depth 0.00 = zone proximal (what the engine emits)")
    print("  depth 1.00 = the stop itself; R -> 0, so treat it as a limit, not a trade")
    if a.null_samples:
        print("  'vs null' is percentage points over a drift-matched baseline computed")
        print("  at THAT depth's R, so the comparison stays fair as the stop tightens.")


if __name__ == "__main__":
    main()
