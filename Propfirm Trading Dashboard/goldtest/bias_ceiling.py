#!/usr/bin/env python3
"""What accuracy the Stage-1 bias components can support, in-sample and out.

WHY
Twenty phases of `_bias_consensus` tuning produced a 74/160 goldtest score that turned
out to be memorisation. The question those phases never asked is the prior one: how much
information do the seven components CARRY? If the answer is "not much", no rule over them
can be good, and tuning is just a slow way to memorise the corpus.

This measures the ceiling directly, by building the maximally overfit predictor -- a
lookup table that memorises the best answer for every distinct component combination --
and then measuring the same construction out-of-sample.

    python goldtest/bias_ceiling.py
    python goldtest/bias_ceiling.py --features location trend valuation

The in-sample number is an upper bound no rule can beat. The out-of-sample number is what
a rule could realistically reach. The gap between them is how much of any reported score
is memorisation.

VALIDATION IS BY DATE, NOT RANDOM. A random split leaks: the corpus contains the same
symbol days apart with near-identical components, so a random fold puts near-duplicates
on both sides and inflates the score. Training on the earlier period and testing on the
later one is also the only split that matches how the system would actually be used.
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEYS = ["location", "trend", "cot", "cot_strength", "valuation",
        "seasonality", "constituent"]


def load(path):
    return json.load(open(path, encoding="utf-8"))


def fit(rows, keys):
    """Lookup table: combination -> majority truth label in training rows."""
    g = collections.defaultdict(collections.Counter)
    for r in rows:
        g[tuple(r.get(k) for k in keys)][r["truth"]] += 1
    fallback = collections.Counter(r["truth"] for r in rows).most_common(1)[0][0]
    return {k: c.most_common(1)[0][0] for k, c in g.items()}, fallback


def score(table, fallback, rows, keys):
    hit = unseen = 0
    for r in rows:
        k = tuple(r.get(k) for k in keys)
        if k not in table:
            unseen += 1
        if table.get(k, fallback) == r["truth"]:
            hit += 1
    return hit / len(rows) if rows else 0.0, unseen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(HERE / "bias_features.json"))
    ap.add_argument("--features", nargs="*", default=KEYS)
    ap.add_argument("--folds", type=int, default=5)
    a = ap.parse_args()

    F = sorted(load(a.file), key=lambda r: r["date"])
    keys = a.features
    maj = collections.Counter(r["truth"] for r in F).most_common(1)[0]
    print(f"{len(F)} cases, features {keys}")
    print(f"always-'{maj[0]}' baseline: {maj[1]}/{len(F)} = {100*maj[1]/len(F):.2f}%")
    engine = sum(1 for r in F if r.get("pred") == r["truth"])
    print(f"current engine:            {engine}/{len(F)} = {100*engine/len(F):.2f}%\n")

    tbl, fb = fit(F, keys)
    ins, _ = score(tbl, fb, F, keys)
    cells = len(tbl)
    singles = sum(1 for k, c in collections.Counter(
        tuple(r.get(x) for x in keys) for r in F).items() if c == 1)
    print(f"IN-SAMPLE ceiling (memorise everything): {100*ins:.2f}%")
    print(f"  {cells} distinct cells, {singles} seen exactly once "
          f"({100*singles/len(F):.0f}% of cases)\n")

    # Forward-chaining splits by date: always train on the past, test on the future.
    print(f"OUT-OF-SAMPLE, {a.folds} forward splits by date (train past -> test future):")
    n = len(F)
    accs = []
    for i in range(1, a.folds + 1):
        cut = int(n * i / (a.folds + 1))
        tr, te = F[:cut], F[cut:int(n * (i + 1) / (a.folds + 1))]
        if not te:
            continue
        t, f = fit(tr, keys)
        acc, unseen = score(t, f, te, keys)
        bl = collections.Counter(r["truth"] for r in te).most_common(1)[0]
        accs.append(acc)
        print(f"  train {len(tr):>3}  test {len(te):>3}   acc {100*acc:5.2f}%   "
              f"unseen combos {unseen:>3}   test-set majority {100*bl[1]/len(te):5.2f}%")
    if accs:
        m = sum(accs) / len(accs)
        print(f"\n  mean out-of-sample: {100*m:.2f}%")
        print(f"  memorisation gap:   {100*(ins-m):.2f} points "
              f"(in-sample {100*ins:.1f}% -> out {100*m:.1f}%)")


if __name__ == "__main__":
    main()
