#!/usr/bin/env python3
"""Does ANY zone property separate the zone they drew from the ones we rank above it?

WHY
The system's direction is 52.7% correct and its expectancy is negative, while the same
calls taken at THEIR drawn entry return +0.56R (C-101). The gap is zone selection: we
find their zone in the candidate set and then rank something else first.

This asks the question directly. For every drawn setup, it reproduces the engine zone
pipeline EXACTLY as `BP_rules_engine.run_seven_step_process` does -- provisional HTF
detect, trend, HTF re-detect, LTF detect, align_multi_timeframe, big-brother filter --
and then compares the zone nearest their drawn entry against every other candidate,
qualifier by qualifier.

    python goldtest/zone_choice_separation.py --strategy weekly

C-107 is the reason this reproduces the pipeline instead of calling detect_zones alone:
`level_on_top_score` is only ever written by `align_multi_timeframe`, onto LTF zones.
Sampling zones before that step measures a population no trade is ever taken from.

Separation is reported as a standardized mean difference (Cohen d) between the matched
zone and the rest. A qualifier that cannot separate cannot select, whatever weight it
carries -- so this is the shortlist for what ranking should actually use.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

SETUPS = Path(r"D:/Trading/Claude for Bernd/gemini/out/drawn_setups.json")

PROPS = ["departure_score", "base_duration_score", "freshness_score",
         "originality_score", "profit_margin_score", "arrival_score",
         "level_on_top_score", "composite_score", "retest_count",
         # C-108 raw measurements behind the flattened scores
         "departure_strength", "margin_ratio", "bars_to_return",
         "base_candle_count"]

# Persisted per candidate so `rank_rules.py` can evaluate alternative orderings
# offline, without paying for another engine run.
DUMP_KEYS = PROPS + ["id", "zone_type", "proximal", "distal", "with_trend",
                     "origin_time", "origin_index",
                     "htf_aligned", "is_fresh", "is_original", "is_flip",
                     "q5_failed_gate", "timeframe"]


def zones_for(engine, fetcher, symbol, call_date, htf, ltf, asset_class):
    """Mirror of run_seven_step_process steps 2-4, up to the ranking input.

    Returns (candidate LTF zones, ranked zones, last LTF close).
    """
    from run_goldtest import fetch_historical_snapshot
    ohlcv = fetch_historical_snapshot(fetcher, symbol, htf, ltf, call_date)
    htf_df, ltf_df = ohlcv.get(htf), ohlcv.get(ltf)
    if htf_df is None or htf_df.empty or ltf_df is None or ltf_df.empty:
        return None, None, None
    zd = engine.zone_detector
    prov = zd.detect_zones(htf_df, symbol, htf)
    ht_bias = engine._analyze_htf(htf_df, prov, htf=htf, symbol=symbol,
                                  asset_class=asset_class)
    trend = ht_bias["trend"]
    htf_zones = zd.detect_zones(htf_df, symbol, htf, trend=trend)
    ltf_zones = zd.detect_zones(ltf_df, symbol, ltf, trend=trend)
    ltf_zones = zd.align_multi_timeframe(htf_zones, ltf_zones)
    ltf_zones = zd.filter_by_big_brother(
        ltf_zones, htf_zones,
        require_coverage=bool(engine.config.get("require_big_brother", False)))
    ranked = zd.rank_zones(ltf_zones, min_score=4.0)
    return ltf_zones, ranked, float(ltf_df['close'].iloc[-1])


def cohens_d(a, b):
    if len(a) < 2 or len(b) < 2:
        return None
    sa, sb = statistics.pstdev(a), statistics.pstdev(b)
    pooled = ((sa ** 2 + sb ** 2) / 2) ** 0.5
    if pooled == 0:
        return 0.0
    return (statistics.fmean(a) - statistics.fmean(b)) / pooled


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="weekly",
                    choices=["monthly", "weekly", "daily", "intraday"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--source", default="position_tool",
                    choices=["position_tool", "zone_edges"],
                    help="which drawn-setup class to compare against (C-115)")
    ap.add_argument("--out", default=str(HERE / "zone_choice_separation.json"))
    a = ap.parse_args()

    from BP_data_fetcher import DataFetcher
    from BP_rules_engine import RulesEngine
    from run_goldtest import STRATEGY_TIMEFRAMES, ASSET_CLASS_BY_SYMBOL

    tf = STRATEGY_TIMEFRAMES[a.strategy]
    htf, ltf = tf["htf"], tf["ltf"]
    config = yaml.safe_load(open(ROOT / "BP_config.yaml", encoding="utf-8"))
    fetcher, engine = DataFetcher(), RulesEngine(config)

    setups = json.load(open(SETUPS, encoding="utf-8"))
    # C-115: drawn_setups.json now also carries `zone_edges` rows -- zones they merely
    # marked on a chart, which measure 18 points BELOW a drift-matched null and are not
    # trades. Comparing our zone selection against those would be aiming at the wrong
    # target. Only position-tool setups are trades they committed to.
    before = len(setups)
    setups = [s for s in setups if s.get("source", "position_tool") == a.source]
    if len(setups) != before:
        print(f"  filtered to source={a.source}: {before} -> {len(setups)} setups")
    if a.limit:
        setups = setups[: a.limit]
    print(f"{len(setups)} drawn setups, strategy={a.strategy} ({htf}/{ltf})\n")

    matched, rest, records = [], [], []
    skipped = {}
    for i, s in enumerate(setups, 1):
        sym, date = s["symbol"], s["date"]
        try:
            cd = datetime.strptime(date, "%Y-%m-%d")
        except Exception:
            skipped["bad date"] = skipped.get("bad date", 0) + 1
            continue
        ac = ASSET_CLASS_BY_SYMBOL.get(sym, "equities")
        try:
            cands, ranked, last_px = zones_for(engine, fetcher, sym, cd, htf, ltf, ac)
        except Exception as e:
            skipped[type(e).__name__] = skipped.get(type(e).__name__, 0) + 1
            continue
        if not cands:
            skipped["no zones"] = skipped.get("no zones", 0) + 1
            continue

        want = "demand" if s["direction"] == "long" else "supply"
        pool = [z for z in cands if z.get("zone_type") == want]
        if not pool:
            skipped["no zone of that type"] = skipped.get("no zone of that type", 0) + 1
            continue

        R = abs(s["entry"] - s["stop"])
        near = min(pool, key=lambda z: abs(z["proximal"] - s["entry"]))
        err_near = abs(near["proximal"] - s["entry"]) / R
        top = ranked[0] if ranked else None
        err_top = abs(top["proximal"] - s["entry"]) / R if top else None

        matched.append(near)
        rest.extend(z for z in pool if z is not near)
        records.append({
            "symbol": sym, "date": date, "direction": s["direction"],
            "their_entry": s["entry"], "R": R,
            "candidates": len(pool),
            "nearest_proximal": near["proximal"], "err_nearest_R": round(err_near, 3),
            "ranked1_proximal": top["proximal"] if top else None,
            "err_ranked1_R": round(err_top, 3) if err_top is not None else None,
            "nearest_is_ranked1": bool(top and top.get("id") == near.get("id")),
            "nearest_rank": next((j for j, z in enumerate(ranked or [], 1)
                                  if z.get("id") == near.get("id")), None),
            "nearest_id": near.get("id"),
            "last_price": last_px,
            "pool": [{k: z.get(k) for k in DUMP_KEYS} for z in pool],
        })
        if i % 10 == 0:
            print(f"  {i}/{len(setups)}  usable={len(records)}", flush=True)

    print(f"\nusable setups: {len(records)}   skipped: {skipped}")
    if not records:
        sys.exit("nothing usable")

    errs_top = [r["err_ranked1_R"] for r in records if r["err_ranked1_R"] is not None]
    errs_near = [r["err_nearest_R"] for r in records]
    hits = sum(1 for r in records if r["nearest_is_ranked1"])
    ranks = [r["nearest_rank"] for r in records if r["nearest_rank"]]

    print("\n=== ENTRY ERROR vs their drawn entry (in R) ===")
    if errs_top:
        print(f"  engine rank-1 zone   median {statistics.median(errs_top):.2f}R   "
              f"mean {statistics.fmean(errs_top):.2f}R   n={len(errs_top)}")
    print(f"  BEST candidate zone  median {statistics.median(errs_near):.2f}R   "
          f"mean {statistics.fmean(errs_near):.2f}R   n={len(errs_near)}")
    print(f"  rank-1 IS the nearest zone: {hits}/{len(records)} "
          f"({100*hits/len(records):.0f}%)")
    if ranks:
        avg_c = statistics.fmean([r["candidates"] for r in records])
        print(f"  when it is not, the nearest zone rank: median "
              f"{statistics.median(ranks):.0f} of {avg_c:.0f} avg candidates")

    print(f"\n=== SEPARATION: nearest zone (n={len(matched)}) vs rest (n={len(rest)}) ===")
    print(f"  {'property':<22}{'matched':>9}{'rest':>9}{'Cohen d':>10}")
    scored = []
    for p in PROPS:
        A = [z[p] for z in matched if isinstance(z.get(p), (int, float))]
        B = [z[p] for z in rest if isinstance(z.get(p), (int, float))]
        d = cohens_d(A, B)
        if d is None:
            continue
        scored.append((abs(d), p, d, statistics.fmean(A), statistics.fmean(B)))
    for _, p, d, ma, mb in sorted(scored, reverse=True):
        star = "  <-- separates" if abs(d) >= 0.30 else ""
        print(f"  {p:<22}{ma:>9.2f}{mb:>9.2f}{d:>10.2f}{star}")

    json.dump({"strategy": a.strategy, "records": records},
              open(a.out, "w", encoding="utf-8"), indent=1)
    print(f"\nper-setup detail -> {a.out}")


if __name__ == "__main__":
    main()
