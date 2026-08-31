#!/usr/bin/env python3
"""One command that decides whether a config change is real. Run it before believing anything.

WHY THIS EXISTS
Every false positive in this project passed at least one honest-looking test:

  "74/160 on the goldtest"      -- in-sample, ~20 phases tuned against those cases
  "+0.60R at market"            -- sample was 33 of 34 LONG in 2023; drift, not edge
  "midpoint entry helps"        -- different trade population, not a different entry
  "their entries beat market"   -- p=0.039 until de-duplicated; one position tool had been
                                   re-read seven times. Collapsed: 4:0, p=0.125 (C-127)
  "level_on_top is dead"        -- measured on a call site that never trades

No single check catches all of those. Accuracy alone misses expectancy. Expectancy against
the wrong null misses drift. Both miss a population that quietly changed underneath. This
runs the four gates together and reports the WEAKEST result, because a change is only as
real as its worst test.

    python goldtest/verdict.py --arm "myflag?.json"
    python goldtest/verdict.py --arm "myflag?.json" --baseline "base?.json"

GATE 1  ACCURACY, PAIRED       McNemar on cases scored in BOTH arms. Unpaired percentages
                               are unsafe: arms differ in how many cases error out, so a
                               +/-2 delta can be pure attrition.
GATE 2  SIGNAL POPULATION      Did the arm change WHICH trades it emits? If yes, no
                               outcome comparison between the arms is about the flag --
                               it is about the population. This is what made midpoint
                               entry look like an improvement (C-112).
GATE 3  EXPECTANCY vs DRIFT    Against a drift-matched null, never the 1/3 driftless one.
                               On a directionally lopsided sample the driftless null
                               understates the bar by ~8 points (C-111).
GATE 4  ENTRY vs MARKET        Paired, same trades. Their signals win it 4:0 (p=0.125 --
                               the floor at 4 discordant pairs, so consistent but NOT
                               significant); both of our arms LOSE it. A change that does
                               not move this has not touched the defect that matters
                               (C-119, corrected by C-127).

Exit code is 0 when every gate the arm was measurable on passed, 1 otherwise, so this can
gate a commit.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import sys
from math import comb, erf, sqrt
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import expectancy as E


def binom_ge(k: int, n: int, p0: float) -> float:
    """Exact one-sided P(X >= k) for Binomial(n, p0).

    The normal approximation is NOT usable here. Applied to a 2-of-2 result against a
    36.7% base rate it returned p=0.032 -- apparently significant -- where the exact
    answer is 0.135. Small decided-counts are the norm in this project (arms routinely
    resolve 2-22 trades), which is exactly where the approximation breaks, so every
    proportion test uses the exact distribution.
    """
    if n <= 0:
        return 1.0
    return sum(comb(n, i) * p0 ** i * (1 - p0) ** (n - i) for i in range(k, n + 1))


def mcnemar(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, sum(comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n * 2)


def load(pattern):
    rows = []
    for f in sorted(glob.glob(pattern)) or sorted(glob.glob(str(HERE / pattern))):
        rows += json.load(open(f, encoding="utf-8")).get("results", [])
    return {(r["symbol"], r["call_date"]): r for r in rows}


def gate(name, passed, detail, measurable=True, warn_only=False):
    if not measurable:
        mark = "  --"
    elif passed:
        mark = "  OK"
    else:
        mark = "WARN" if warn_only else "FAIL"
    print(f"  [{mark}] {name:<28} {detail}")
    return passed or not measurable


def run_expectancy_gate(sa, rr):
    res, _ = E.measure(sa, rr, control=False)
    w, l = res["win"], res["loss"]
    dec = w + l
    if not dec:
        return gate("expectancy vs drift null", False, "nothing decided", measurable=False)
    nul = E.drift_null(sa, rr, samples=25)
    ndec = nul["win"] + nul["loss"]
    if not ndec:
        return gate("expectancy vs drift null", False, "no null", measurable=False)
    wr, nwr = w / dec, nul["win"] / ndec
    per = (w * rr - l) / dec
    p3 = binom_ge(w, dec, nwr)
    thin = "  [n<10, underpowered]" if dec < 10 else ""
    return gate("expectancy vs drift null", wr > nwr and p3 < 0.05 and dec >= 10,
                f"{100*wr:.1f}% ({w}/{dec}) {per:+.2f}R vs null {100*nwr:.1f}%  "
                f"exact p={p3:.4f}{thin}")


def run_entry_gate(sa, rr):
    _, x = E.measure(sa, rr, control=False)
    _, y = E.measure(sa, rr, control=True)
    kx = {(r["symbol"], r["date"], r["dir"]): r["outcome"] for r in x}
    ky = {(r["symbol"], r["date"], r["dir"]): r["outcome"] for r in y}
    both = [k for k in kx if k in ky and kx[k] in ("win", "loss") and ky[k] in ("win", "loss")]
    eo = sum(1 for k in both if kx[k] == "win" and ky[k] == "loss")
    mo = sum(1 for k in both if ky[k] == "win" and kx[k] == "loss")
    return gate("zone entry beats market", eo > mo,
                f"entry {eo} / market {mo} on {len(both)} paired  p={mcnemar(eo, mo):.4f}"
                + ("   <- market still wins, the zone is still wrong" if mo >= eo else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", help="glob for the arm's goldtest output")
    ap.add_argument("--signals-file",
                    help="forward-test --emit-signals output instead of goldtest results. "
                         "The forward period has NO ground-truth calls, so gate 1 "
                         "(accuracy) is not measurable and is reported as such; gates 3 "
                         "and 4 -- the money questions -- still run.")
    ap.add_argument("--baseline", default="goldtest/base?.json")
    ap.add_argument("--pin-dir", action="append", default=["ohlcv_extended"])
    ap.add_argument("--rr", type=float, default=2.0)
    a = ap.parse_args()

    for d in a.pin_dir:
        p = Path(d)
        E.EXTRA_PIN_DIRS.append(p if p.is_absolute() else HERE.parent / p)

    if a.signals_file:
        raw = json.load(open(a.signals_file, encoding="utf-8"))
        if isinstance(raw, dict):
            raw = next(iter(raw.values()))
        sa = E.normalise(raw)
        print(f"signals  {a.signals_file}   {len(sa)} usable signals")
        if not sa:
            sys.exit("no usable signals in that file")
        print("  no ground-truth calls exist for a forward period, so gate 1 is skipped\n")
        ok = True
        gate("accuracy (paired McNemar)", True, "no ground truth in a forward period",
             measurable=False)
        gate("signal population", True, f"{len(sa)} trades (nothing to compare against)",
             measurable=False)
        ok &= run_expectancy_gate(sa, a.rr)
        ok &= run_entry_gate(sa, a.rr)
        print("\n  VERDICT:", "change is supported" if ok else
              "NOT supported -- do not flip the default")
        print("  Reference: their signals corpus wins gate 4 at 4:0, p=0.125 -- consistent"
              " in direction under every de-duplication rule, NOT significant (C-127).")
        return 0 if ok else 1

    if not a.arm:
        sys.exit("need --arm or --signals-file")
    A, B = load(a.arm), load(a.baseline)
    if not A:
        sys.exit(f"no results matched {a.arm}")
    if not B:
        sys.exit(f"no baseline matched {a.baseline}")
    # Only cases SCORED IN BOTH arms. A case that errored has verdict=None, and
    # including it would either crash or silently count as a miss -- which is the
    # attrition bias this tool exists to avoid (an arm that errors on more cases
    # would look worse for a reason unrelated to the flag).
    scored = lambda r: isinstance(r.get("verdict"), dict)
    keys = sorted(k for k in set(A) & set(B) if scored(A[k]) and scored(B[k]))
    dropped = len(set(A) & set(B)) - len(keys)
    print(f"arm      {a.arm}      {len(A)} cases")
    print(f"baseline {a.baseline}  {len(B)} cases      paired on {len(keys)}\n")

    ok = True

    # ---- GATE 1: accuracy, paired -------------------------------------------
    hit = lambda r: bool(r["verdict"].get("bias_only_match"))
    ao = sum(1 for k in keys if hit(A[k]) and not hit(B[k]))
    bo = sum(1 for k in keys if hit(B[k]) and not hit(A[k]))
    p1 = mcnemar(ao, bo)
    na = sum(1 for k in keys if hit(A[k]))
    nb = sum(1 for k in keys if hit(B[k]))
    ok &= gate("accuracy (paired McNemar)", ao > bo and p1 < 0.05,
               f"{100*na/len(keys):.2f}% vs {100*nb/len(keys):.2f}%  "
               f"discordant {ao}/{bo}  p={p1:.4f}")

    # ---- GATE 2: did the emitted population change? -------------------------
    sa = E.load_from_goldtest(a.arm)
    sb = E.load_from_goldtest(a.baseline)
    ka = {(s["symbol"], s["call_date"], s["direction"]) for s in sa}
    kb = {(s["symbol"], s["call_date"], s["direction"]) for s in sb}
    shared = ka & kb
    changed = bool(ka ^ kb)
    # Informational: it does NOT decide the verdict. A flag meant to change which
    # trades are emitted SHOULD change this. It is flagged so that no outcome delta
    # between the arms gets read as an effect of the flag when the population moved.
    gate("signal population", not changed, warn_only=True,
         detail=f"{len(sa)} vs {len(sb)} trades, {len(shared)} shared, "
                f"{len(ka - kb)} new / {len(kb - ka)} dropped"
                + ("   <- outcome deltas NOT attributable to the flag alone" if changed else ""))

    # ---- GATE 3: expectancy vs a drift-matched null -------------------------
    if sa:
        res, _ = E.measure(sa, a.rr, control=False)
        w, l = res["win"], res["loss"]
        dec = w + l
        nul = E.drift_null(sa, a.rr, samples=25)
        nw, nl = nul["win"], nul["loss"]
        ndec = nw + nl
        if dec and ndec:
            wr, nwr = w / dec, nw / ndec
            per = (w * a.rr - l) / dec
            p3 = binom_ge(w, dec, nwr)
            thin = "  [n<10, underpowered]" if dec < 10 else ""
            ok &= gate("expectancy vs drift null", wr > nwr and p3 < 0.05 and dec >= 10,
                       f"{100*wr:.1f}% ({w}/{dec}) {per:+.2f}R vs null {100*nwr:.1f}%  "
                       f"exact p={p3:.4f}{thin}")
        else:
            gate("expectancy vs drift null", False, "nothing decided", measurable=False)
    else:
        gate("expectancy vs drift null", False, "arm emitted no signals", measurable=False)

    # ---- GATE 4: zone entry vs market, paired on the SAME trades ------------
    if sa:
        _, x = E.measure(sa, a.rr, control=False)
        _, y = E.measure(sa, a.rr, control=True)
        kx = {(r["symbol"], r["date"], r["dir"]): r["outcome"] for r in x}
        ky = {(r["symbol"], r["date"], r["dir"]): r["outcome"] for r in y}
        both = [k for k in kx if k in ky and kx[k] in ("win", "loss")
                and ky[k] in ("win", "loss")]
        eo = sum(1 for k in both if kx[k] == "win" and ky[k] == "loss")
        mo = sum(1 for k in both if ky[k] == "win" and kx[k] == "loss")
        p4 = mcnemar(eo, mo)
        ok &= gate("zone entry beats market", eo > mo,
                   f"entry {eo} / market {mo} on {len(both)} paired  p={p4:.4f}"
                   + ("   <- market still wins, the zone is still wrong" if mo >= eo else ""))
    else:
        gate("zone entry beats market", False, "arm emitted no signals", measurable=False)

    print("\n  VERDICT:", "change is supported" if ok else
          "NOT supported -- do not flip the default")
    print("  Reference: their signals corpus wins gate 4 at 4:0, p=0.125 -- consistent"
          " in direction under every de-duplication rule, NOT significant (C-127).")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
