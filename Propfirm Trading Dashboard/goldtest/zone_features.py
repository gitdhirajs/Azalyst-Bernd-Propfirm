#!/usr/bin/env python3
"""Add zone-derived features to the Stage-1 feature table and re-test the ceiling.

WHY
`bias_ceiling.py` established that the seven existing bias components carry NO
out-of-sample information about the label: a maximally overfit lookup table reaches
71.4% in-sample and 48.7% out, against a 50.4% always-long baseline, and a search over
all 127 feature subsets found nothing better than +0.00 points. The engine's own additive
voting scores -8.5. That is why twenty phases of `_bias_consensus` tuning produced
memorisation -- there was no signal in those inputs to find.

So the bottleneck is the FEATURES, not the rules. The most obvious gap: Stage-1 bias is
computed with no knowledge of zones at all. Zones are Stage 2. But their calls are
routinely justified by zone context ("nice new demand sitting here"), so the thing the
label most depends on is absent from the vector used to predict it.

This computes, per case and strictly from data up to the call date:

    n_reach_demand / n_reach_supply   zones within 10% of price (C-110's band)
    dist_demand / dist_supply         % distance to the nearest zone of each type
    best_demand / best_supply         best composite among reachable zones of each type
    inside_zone                       price currently between proximal and distal
    htf_aligned_frac                  share of candidates carrying an HTF parent

then bins them to categoricals and re-runs the same ceiling test, so the comparison to
the existing components is like-for-like.

    python goldtest/zone_features.py --limit 510
    python goldtest/bias_ceiling.py --file goldtest/zone_features.json --features ...

No lookahead: the OHLCV snapshot is truncated at the call date by
`fetch_historical_snapshot`, exactly as the engine sees it live.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from datetime import datetime
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

BAND = 0.10


def bin_dist(d):
    if d is None:
        return "none"
    if d <= 0.02:
        return "at"
    if d <= 0.05:
        return "near"
    if d <= 0.10:
        return "mid"
    return "far"


def bin_score(s):
    if s is None:
        return "none"
    if s >= 8.0:
        return "high"
    if s >= 6.5:
        return "mid"
    return "low"


def bin_count(n):
    return "0" if n == 0 else ("1-3" if n <= 3 else ("4-9" if n <= 9 else "10+"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards", default="full510_shard?.yaml")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out", default=str(HERE / "zone_features.json"))
    a = ap.parse_args()

    from BP_data_fetcher import DataFetcher
    from BP_rules_engine import RulesEngine
    from run_goldtest import (fetch_historical_snapshot, STRATEGY_TIMEFRAMES,
                              ASSET_CLASS_BY_SYMBOL)

    config = yaml.safe_load(open(ROOT / "BP_config.yaml", encoding="utf-8"))
    fetcher, engine = DataFetcher(), RulesEngine(config)

    cases = []
    for p in sorted(glob.glob(str(HERE / a.shards))):
        cases += yaml.safe_load(open(p, encoding="utf-8")).get("cases", [])
    if a.limit:
        cases = cases[: a.limit]

    # existing components, to merge onto
    prev = {}
    bf = HERE / "bias_features.json"
    if bf.exists():
        for r in json.load(open(bf, encoding="utf-8")):
            prev[(r["symbol"], r["date"])] = r

    out = []
    for i, c in enumerate(cases, 1):
        sym = c["symbol"]
        date = str(c["call_date"])[:10]
        row = dict(prev.get((sym, date), {"symbol": sym, "date": date,
                                          "truth": c.get("bias"), "pred": None}))
        tf = STRATEGY_TIMEFRAMES.get(c.get("strategy", "weekly"))
        htf, ltf = tf["htf"], tf["ltf"]
        ac = ASSET_CLASS_BY_SYMBOL.get(sym, "equities")
        try:
            o = fetch_historical_snapshot(fetcher, sym, htf, ltf,
                                          datetime.strptime(date, "%Y-%m-%d"))
            hdf, ldf = o.get(htf), o.get(ltf)
            if hdf is None or hdf.empty or ldf is None or ldf.empty:
                raise ValueError("no data")
            zd = engine.zone_detector
            prov = zd.detect_zones(hdf, sym, htf)
            trend = engine._analyze_htf(hdf, prov, htf=htf, symbol=sym,
                                        asset_class=ac)["trend"]
            hz = zd.detect_zones(hdf, sym, htf, trend=trend)
            lz = zd.detect_zones(ldf, sym, ltf, trend=trend)
            lz = zd.align_multi_timeframe(hz, lz)
            lz = zd.filter_by_big_brother(lz, hz, require_coverage=False)
            px = float(ldf["close"].iloc[-1])

            feats = {}
            for kind in ("demand", "supply"):
                pool = [z for z in lz if z.get("zone_type") == kind]
                reach = [z for z in pool
                         if abs(float(z["proximal"]) - px) / abs(px) <= BAND]
                near = (min(pool, key=lambda z: abs(float(z["proximal"]) - px))
                        if pool else None)
                d = (abs(float(near["proximal"]) - px) / abs(px)) if near else None
                best = max((float(z["composite_score"]) for z in reach), default=None)
                k = kind[:3]
                feats[f"n_{k}"] = bin_count(len(reach))
                feats[f"dist_{k}"] = bin_dist(d)
                feats[f"best_{k}"] = bin_score(best)
            inside = any(min(float(z["proximal"]), float(z["distal"])) <= px
                         <= max(float(z["proximal"]), float(z["distal"])) for z in lz)
            feats["inside_zone"] = "yes" if inside else "no"
            al = [z for z in lz if z.get("htf_aligned")]
            feats["htf_aligned"] = ("none" if not lz else
                                    ("most" if len(al) / len(lz) >= 0.5 else "some"))
            feats["trend_ctx"] = trend
            row.update(feats)
            row["zone_error"] = None
        except Exception as e:
            row["zone_error"] = f"{type(e).__name__}"
        out.append(row)
        if i % 25 == 0:
            ok = sum(1 for r in out if not r.get("zone_error"))
            print(f"  {i}/{len(cases)}   usable {ok}", flush=True)

    json.dump(out, open(a.out, "w", encoding="utf-8"), indent=1)
    ok = sum(1 for r in out if not r.get("zone_error"))
    print(f"\n{ok}/{len(out)} cases with zone features -> {a.out}")


if __name__ == "__main__":
    main()
