#!/usr/bin/env python3
"""Distribution of every zone qualifier as RANKING actually sees it.

WHY THIS EXISTS
C-106 reported `level_on_top_score` as 0.00 on 100% of zones and concluded the
qualifier was dead. That sample was taken from the Stage-1 diagnostic fallback in
run_goldtest (`rank_zones(htf_zones, min_score=0.0)`), which ranks HTF zones
DIRECTLY. `align_multi_timeframe` only ever writes LOL onto LTF zones, using HTF
zones as the parents -- so on that path LOL is 0.00 by construction, and the
finding said nothing about the live signal path.

This captures what `rank_zones` receives at each call site separately, tagged by
timeframe, so a saturated qualifier can be distinguished from one that simply was
never populated on the path being sampled.

    python goldtest/zone_qualifier_stats.py --shards "full510_shard?.yaml" --limit 60

Reports, per call site and overall: n, mean, sd, and the share of zones sitting on
each of the extreme values -- which is the number that matters, since a qualifier
pinned at one value cannot contribute to ranking no matter its weight.
"""
from __future__ import annotations

import argparse
import collections
import glob
import statistics
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

QUALS = ["departure_score", "base_duration_score", "freshness_score",
         "originality_score", "profit_margin_score", "arrival_score",
         "level_on_top_score", "composite_score"]

CAPTURED = []


def install_probe():
    """Wrap ZoneDetector.rank_zones and record its input, tagged by caller."""
    from BP_zone_detector import ZoneDetector
    orig = ZoneDetector.rank_zones

    def probed(self, zones, *a, **kw):
        import inspect
        frame = inspect.currentframe().f_back
        site = f"{Path(frame.f_code.co_filename).name}:{frame.f_lineno}"
        for z in zones or []:
            row = {q: z.get(q) for q in QUALS}
            row["site"] = site
            row["timeframe"] = z.get("timeframe")
            row["htf_aligned"] = bool(z.get("htf_aligned"))
            row["retest_count"] = z.get("retest_count")
            CAPTURED.append(row)
        return orig(self, zones, *a, **kw)

    ZoneDetector.rank_zones = probed


def summarize(rows, label):
    if not rows:
        print(f"\n=== {label}: no zones captured ===")
        return
    print(f"\n=== {label}  (n={len(rows)}) ===")
    print(f"  {'qualifier':<22} {'mean':>6} {'sd':>6}   saturation")
    for q in QUALS:
        vals = [r[q] for r in rows if isinstance(r.get(q), (int, float))]
        if not vals:
            print(f"  {q:<22} {'--':>6} {'--':>6}   never set")
            continue
        sd = statistics.pstdev(vals) if len(vals) > 1 else 0.0
        counts = collections.Counter(vals)
        top_v, top_n = counts.most_common(1)[0]
        pct = 100.0 * top_n / len(vals)
        flag = "  <-- PINNED" if pct >= 95.0 else ("  <- saturated" if pct >= 70 else "")
        print(f"  {q:<22} {statistics.fmean(vals):>6.2f} {sd:>6.2f}   "
              f"{pct:5.1f}% at {top_v}{flag}")
        if q != "composite_score":
            # Full branch histogram: a scoring branch that never fires is a branch
            # whose condition the DETECTOR already guaranteed (C-108).
            hist = "  ".join(f"{v}:{100.0*n/len(vals):.0f}%"
                             for v, n in sorted(counts.items(), reverse=True))
            print(f"  {'':<22} {'':>6} {'':>6}   branches -> {hist}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards", default="full510_shard?.yaml")
    ap.add_argument("--limit", type=int, default=60)
    a = ap.parse_args()

    install_probe()
    from run_goldtest import run_case

    with open(ROOT / "BP_config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    cases = []
    for path in sorted(glob.glob(str(HERE / a.shards))):
        with open(path, encoding="utf-8") as f:
            cases.extend(yaml.safe_load(f).get("cases", []))
    cases = cases[: a.limit]
    print(f"running {len(cases)} cases through the real engine to sample zones...")

    for i, c in enumerate(cases, 1):
        try:
            run_case(c, config)
        except Exception as e:
            print(f"  [{i}] {c.get('symbol')} {c.get('call_date')}: {type(e).__name__}: {e}")
        if i % 10 == 0:
            print(f"  {i}/{len(cases)} cases, {len(CAPTURED)} zones captured", flush=True)

    by_site = collections.defaultdict(list)
    for r in CAPTURED:
        by_site[r["site"]].append(r)
    for site, rows in sorted(by_site.items(), key=lambda kv: -len(kv[1])):
        summarize(rows, f"call site {site}")
    summarize(CAPTURED, "ALL zones seen by rank_zones")

    dump = HERE / "zone_qualifier_sample.json"
    import json as _json
    dump.write_text(_json.dumps(CAPTURED), encoding="utf-8")
    print(f"  raw sample of {len(CAPTURED)} zones -> {dump}")

    aligned = [r for r in CAPTURED if r["htf_aligned"]]
    print(f"\n  zones carrying htf_aligned=True: {len(aligned)}/{len(CAPTURED)} "
          f"({100.0*len(aligned)/max(len(CAPTURED),1):.1f}%)")


if __name__ == "__main__":
    main()
