#!/usr/bin/env python3
"""Score alternative zone-ranking rules offline against the drawn setups.

WHY OFFLINE
Changing `_score_zone` in the engine lowers composites, which pushes zones under the
`min_score=4.0` cut -- so an engine-side experiment changes which zones QUALIFY at the
same time as how they are ORDERED, and the two effects cannot be separated afterwards.
This evaluates ordering alone, on the candidate pools `zone_choice_separation.py`
dumped, with the admissible set held fixed. A rule only earns an engine flag and a
510-case A/B after it wins here.

    python goldtest/rank_rules.py
    python goldtest/rank_rules.py --split      # fit-free rules, first half vs second

WHAT IS BEING SCORED
For each setup, rank that setup candidate pool by the rule and ask where their drawn
zone lands. Two numbers, both reported:

  hit@1        share of setups where the rule puts their zone first. The engine
               currently does this on very few, which is C-101 restated.
  entry err    |rank-1 proximal - their entry| / R. This is the number that actually
               converts to money: C-101 measured +0.56R at their entry against -0.33R
               at market, and the error is how much of that spread we give back.

OVERFITTING DISCIPLINE
Every rule here is FIT-FREE -- no coefficients estimated from these 68 setups. A rule
with fitted weights would score better and mean nothing, which is exactly how the
earlier 1.27R "improvement" was produced (fitted in-sample on 38 samples, and not
reproducible). `--split` additionally reports first-half / second-half separately: a
fit-free rule should score about the same on both, and a rule that does not is
reading noise.
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
DUMP = HERE / "zone_choice_separation.json"


def _f(z, k, default=0.0):
    v = z.get(k)
    return float(v) if isinstance(v, (int, float)) else default


# ---------------------------------------------------------------- ranking rules
# Each takes (zone, record) and returns a sort key; higher ranks first.

def rule_current(z, rec):
    """What the engine does today."""
    return _f(z, "composite_score")


def rule_departure_strength(z, rec):
    """C-108: replace Q1's flat 10 with the leg-out impulse it was meant to measure.

    Detection only lower-bounds body/avg_body at leg_out_body_multiplier (2.0), so
    the multiple stays informative above the gate where the SCORE does not.
    """
    base = _f(z, "composite_score") - 0.30 * _f(z, "departure_score")
    strength = _f(z, "departure_strength", 2.0)
    return base + 0.30 * min(10.0, 2.0 * strength)


def rule_real_q5q6(z, rec):
    """C-108: undo the with_trend override and score Q5/Q6 on their measurements.

    The methodology skips these as GATES on trend trades. It does not say every
    trend zone measures identically well, which is what awarding 10.0 asserts.
    """
    base = (_f(z, "composite_score")
            - 0.10 * _f(z, "profit_margin_score")
            - 0.10 * _f(z, "arrival_score"))
    mr = _f(z, "margin_ratio")
    q5 = 10.0 if mr >= 5 else 7.0 if mr >= 3 else 5.0 if mr >= 2 else 0.0
    btr = _f(z, "bars_to_return", 999)
    q6 = 10.0 if btr <= 5 else 7.0 if btr <= 15 else 5.0 if btr <= 30 else 3.0
    return base + 0.10 * q5 + 0.10 * q6


def rule_both(z, rec):
    return rule_departure_strength(z, rec) + rule_real_q5q6(z, rec) - _f(z, "composite_score")


def rule_proximity(z, rec):
    """Pure control: nearest zone to current price, ignoring every qualifier.

    Included because it is the rule to beat. If the qualifier machinery cannot
    outrank "whatever is closest", the machinery is not earning its place.
    """
    px = rec.get("last_price")
    if not px:
        return 0.0
    return -abs(_f(z, "proximal") - px) / max(abs(px), 1e-9)


def rule_retests(z, rec):
    """Control: fewest retests first. Separated in the earlier (mis-sampled) pass."""
    return -_f(z, "retest_count")


def rule_lol(z, rec):
    """Control: level-on-top alone -- the one qualifier that varies freely (C-107)."""
    return _f(z, "level_on_top_score")


def rule_random_stable(z, rec):
    """Null: a deterministic pseudo-random order keyed on the zone id.

    Gives the hit@1 a rule earns by luck given this pool size, which is the only
    honest baseline when pools average a handful of candidates.
    """
    h = 0
    for ch in str(z.get("id") or ""):
        h = (h * 131 + ord(ch)) % 1000003
    return h


def rule_drop_q5(z, rec):
    """C-109: remove Q5 from the composite entirely and renormalise.

    `margin_ratio` grows with the history available after the zone formed, so Q5
    scores age. Deleting it is the cheapest test of whether that term is actively
    harmful, and needs no replacement metric to be defined first.
    """
    return (_f(z, "composite_score") - 0.10 * _f(z, "profit_margin_score")) / 0.90


def rule_recent(z, rec):
    """C-109 hypothesis, stated directly: prefer the most recently formed zone.

    If the engine keeps ranking zones from years before the call date, then a rule
    that does nothing but prefer young zones should beat the composite outright.
    """
    return _f(z, "origin_index", 0.0)


def rule_composite_recent(z, rec):
    """Composite as the primary key, recency as the tie-break.

    Composite sd is 1.46 with heavy clustering (C-108), so many candidates are
    effectively tied. This keeps the existing ordering and only decides the ties,
    which is the smallest change that could matter.
    """
    return (round(_f(z, "composite_score"), 1), _f(z, "origin_index", 0.0))


def _reachable_composite(band):
    """Composite, but only among zones price could plausibly reach.

    The band is a FREE PARAMETER, which is why several are reported rather than a
    chosen one. If the effect is real it should hold across the whole sweep and on
    both halves; if it only appears at one width it is a fit and must be discarded.
    """
    def rule(z, rec):
        px = rec.get("last_price")
        if not px:
            return _f(z, "composite_score")
        near = abs(_f(z, "proximal") - px) / abs(px) <= band
        # rank unreachable zones below every reachable one, keeping composite
        # order within each group -- a filter expressed as an ordering, so the
        # admissible set is unchanged and only the ordering is under test
        return (1 if near else 0, _f(z, "composite_score"))
    return rule


RULES = {
    "current (composite)":        rule_current,
    "reachable 2% + composite":   _reachable_composite(0.02),
    "reachable 5% + composite":   _reachable_composite(0.05),
    "reachable 10% + composite":  _reachable_composite(0.10),
    "reachable 20% + composite":  _reachable_composite(0.20),
    "Q1 -> departure_strength":   rule_departure_strength,
    "Q5/Q6 -> real measurement":  rule_real_q5q6,
    "both C-108 fixes":           rule_both,
    "C-109: drop Q5 entirely":    rule_drop_q5,
    "composite, recency tiebreak": rule_composite_recent,
    "control: most recent zone":  rule_recent,
    "control: nearest to price":  rule_proximity,
    "control: fewest retests":    rule_retests,
    "control: LOL only":          rule_lol,
    "null: pseudo-random":        rule_random_stable,
}


def evaluate(records, rule):
    hits, errs, ranks = 0, [], []
    for rec in records:
        pool = rec.get("pool") or []
        if not pool:
            continue
        order = sorted(pool, key=lambda z: rule(z, rec), reverse=True)
        top = order[0]
        if top.get("id") == rec.get("nearest_id"):
            hits += 1
        R = rec.get("R") or 0
        if R:
            errs.append(abs(_f(top, "proximal") - rec["their_entry"]) / R)
        ranks.append(next((i for i, z in enumerate(order, 1)
                           if z.get("id") == rec.get("nearest_id")), len(order)))
    n = len(ranks)
    return {
        "n": n,
        "hit1": hits / n if n else 0.0,
        "err_median": statistics.median(errs) if errs else None,
        "err_mean": statistics.fmean(errs) if errs else None,
        "rank_median": statistics.median(ranks) if ranks else None,
    }


def show(title, records):
    print(f"\n=== {title}  (n={len(records)} setups) ===")
    print(f"  {'rule':<28}{'hit@1':>8}{'err med':>10}{'err mean':>10}{'their rank':>12}")
    rows = []
    for name, fn in RULES.items():
        r = evaluate(records, fn)
        rows.append((name, r))
    base = dict(rows)["current (composite)"]
    for name, r in rows:
        if not r["n"]:
            continue
        delta = ""
        if name != "current (composite)" and base["err_median"] is not None:
            d = r["err_median"] - base["err_median"]
            delta = f"   {d:+.2f}R vs current"
        print(f"  {name:<28}{100*r['hit1']:>7.0f}%{r['err_median']:>10.2f}"
              f"{r['err_mean']:>10.2f}{r['rank_median']:>12.0f}{delta}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", default=str(DUMP))
    ap.add_argument("--split", action="store_true",
                    help="also report first half vs second half separately")
    a = ap.parse_args()

    d = json.load(open(a.dump, encoding="utf-8"))
    records = [r for r in d.get("records", []) if r.get("pool")]
    if not records:
        raise SystemExit(
            f"{a.dump} has no candidate pools -- re-run zone_choice_separation.py "
            "with the pool-dumping version")

    avg_pool = statistics.fmean(len(r["pool"]) for r in records)
    print(f"loaded {len(records)} setups, {avg_pool:.1f} candidate zones each "
          f"(strategy={d.get('strategy')})")
    print("lower entry error is better; hit@1 is how often the rule picks their zone")

    # C-109 diagnostic: how old is the zone the engine ranks first, against the one
    # they drew? Stated in bars because the pools mix timeframes.
    ages = []
    for rec in records:
        pool = rec["pool"]
        newest = max(_f(z, "origin_index") for z in pool)
        top = max(pool, key=lambda z: _f(z, "composite_score"))
        theirs = next((z for z in pool if z.get("id") == rec.get("nearest_id")), None)
        if theirs is None:
            continue
        ages.append((newest - _f(top, "origin_index"),
                     newest - _f(theirs, "origin_index")))
    if ages:
        print(f"\n=== ZONE AGE at selection (bars before the newest candidate) ===")
        print(f"  composite rank-1  median {statistics.median(a for a, _ in ages):.0f} bars old")
        print(f"  the zone they drew median {statistics.median(b for _, b in ages):.0f} bars old")
        print("  C-109 predicts rank-1 is systematically the older of the two.")

    show("ALL SETUPS", records)
    if a.split:
        half = len(records) // 2
        show("FIRST HALF (by date)", records[:half])
        show("SECOND HALF (by date)", records[half:])
        print("\n  A fit-free rule should score similarly on both halves.")
        print("  A large gap means the rule is reading noise, not structure.")


if __name__ == "__main__":
    main()
