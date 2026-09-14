"""Build signal_charts.html: every signal from the latest scan drawn on its own
candlestick chart (zone box, entry, stop, T1-T3) with the reasons it fired.

    python build_signal_charts.py                     # uses scan_results.json
    python build_signal_charts.py --live-state PATH   # also chart the live GitHub
                                                      # account's open/pending orders

Read-only: reads scan_results.json (and optionally a paper_trader_state.json),
writes signal_charts.html next to this file. No network, no Discord.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
from pathlib import Path

import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent
logging.disable(logging.CRITICAL)

HTF_BARS = 110
LTF_BARS = 170


def _r(x):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    return float(f"{float(x):.6g}")


def _bars(rows, n):
    rows = rows[-n:]
    return [[str(r["timestamp"])[:10], _r(r["open"]), _r(r["high"]), _r(r["low"]), _r(r["close"])]
            for r in rows]


def _find_zone(detector, rows, symbol, tf, sig):
    """Re-run the zone detector on the cached bars and return the signal's zone
    (matched by id, else by type + proximal/distal)."""
    if not rows:
        return None
    df = pd.DataFrame(rows)
    zones = detector.detect_zones(df, symbol, tf)
    zid = sig.get("zone_id")
    ztype = "demand" if sig["direction"] == "long" else "supply"
    hit = next((z for z in zones if z["id"] == zid), None)
    if hit is None:
        prox = sig["entry_price"]
        cands = [z for z in zones if z["zone_type"] == ztype]
        if cands:
            hit = min(cands, key=lambda z: abs(z["proximal"] - prox) + abs(z["distal"] - sig["stop_price"]))
            if abs(hit["proximal"] - prox) > abs(prox) * 0.002:
                hit = None
    if hit is None:
        return None
    base_start = int(hit["origin_index"]) - int(hit.get("base_candle_count", 1))
    return {
        "type": hit["zone_type"], "formation": hit.get("formation"),
        "proximal": _r(hit["proximal"]), "distal": _r(hit["distal"]),
        "start": str(df.iloc[max(base_start, 0)]["timestamp"])[:10],
        "origin": str(hit.get("origin_time", ""))[:10],
        "base_candles": hit.get("base_candle_count"),
        "fresh": bool(hit.get("is_fresh")), "retests": hit.get("retest_count"),
        "matched_by": "id" if hit["id"] == zid else "levels",
    }


def _indicators(ind):
    out = {}
    if not isinstance(ind, dict):
        return out
    cot = ind.get("cot_index")
    if isinstance(cot, dict):
        out["cot"] = cot
    val = ind.get("valuation_refs")
    if isinstance(val, dict):
        out["valuation"] = val
    return out


def _trim_series(obj, n=104):
    """Keep only the last n points of any list found in an indicator payload."""
    if isinstance(obj, list):
        return obj[-n:]
    if isinstance(obj, dict):
        return {k: _trim_series(v, n) for k, v in obj.items()}
    return obj


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", default=str(HERE / "scan_results.json"))
    ap.add_argument("--live-state", default=None)
    ap.add_argument("--out", default=str(HERE / "signal_charts.html"))
    args = ap.parse_args()

    res = json.load(open(args.scan, encoding="utf-8"))
    cfg = yaml.safe_load(open(HERE / "BP_config.yaml", encoding="utf-8"))
    from BP_zone_detector import ZoneDetector
    det = ZoneDetector(cfg.get("zone_detection", {}))
    cache = res.get("ohlcv_cache") or {}
    htf, ltf = res.get("htf", "1wk"), res.get("ltf", "1d")

    sigs = [dict(s, source="scan") for s in res.get("signals", [])]
    if args.live_state:
        st = json.load(open(args.live_state, encoding="utf-8"))
        for p in st.get("open_positions", []):
            sigs.append({
                "symbol": p["symbol"], "direction": p["direction"], "entry_price": p["entry_price"],
                "stop_price": p["stop_price"], "targets": p.get("targets", []), "zone_id": p.get("zone_id"),
                "trade_context": p.get("trade_context", "standard"), "pending_order": p.get("status") == "pending",
                "source": "live", "live_status": p.get("status"), "opened": str(p.get("entry_time", ""))[:16],
            })

    out = []
    for s in sigs:
        sym = s["symbol"]
        c = cache.get(sym) or {}
        item = {
            "symbol": sym, "name": s.get("display_name") or sym, "source": s["source"],
            "direction": s["direction"], "entry": _r(s["entry_price"]), "stop": _r(s["stop_price"]),
            "targets": [_r(t) for t in s.get("targets", [])],
            "current": _r(s.get("current_price")), "pending": bool(s.get("pending_order")),
            "at_zone": bool(s.get("price_at_zone")), "entry_type": s.get("entry_type"),
            "options": [{k: o.get(k) for k in ("label", "name", "entry", "stop", "rr", "fill_prob")}
                        for o in s.get("entry_options", [])],
            "context": s.get("trade_context"), "tier": s.get("action_tier"),
            "bias": s.get("bias_consensus") or {}, "q": s.get("qualifier_scores") or {},
            "big_brother": s.get("has_big_brother"), "speed_bump": s.get("speed_bump_warning"),
            "asset_class": s.get("asset_class"), "risk_usd": s.get("risk_usd_actual") or s.get("risk_amount"),
            "lots": s.get("lot_size"), "strategy": s.get("income_strategy"),
            "live_status": s.get("live_status"), "opened": s.get("opened"),
            "htf": htf, "ltf": ltf,
            "bars": {htf: _bars(c.get(htf, []), HTF_BARS), ltf: _bars(c.get(ltf, []), LTF_BARS)},
            "zone": _find_zone(det, c.get(ltf, []), sym, ltf, s) or {
                # Zone formed before the cached bars (the cache holds ~300 bars).
                # For weekly/monthly trades entry = proximal and stop = distal.
                "type": "demand" if s["direction"] == "long" else "supply",
                "proximal": _r(s["entry_price"]), "distal": _r(s["stop_price"]),
                "start": None, "approx": True,
            },
            "indicators": _trim_series(_indicators((res.get("indicators") or {}).get(sym))),
        }
        if item["current"] is None and item["bars"][ltf]:
            item["current"] = item["bars"][ltf][-1][4]
        out.append(item)

    payload = {
        "scan_time": res.get("scan_time"), "strategy": res.get("strategy"), "htf": htf, "ltf": ltf,
        "scanned": res.get("watchlist_scanned"), "signals": out,
        "account": {k: (res.get("account") or {}).get(k) for k in ("balance", "initial_balance")},
    }
    tpl = (HERE / "signal_charts_template.html").read_text(encoding="utf-8")
    html = tpl.replace("/*__DATA__*/null", json.dumps(payload, separators=(",", ":")))
    Path(args.out).write_text(html, encoding="utf-8")
    zmatch = sum(1 for s in out if s["zone"])
    print(f"wrote {args.out}: {len(out)} signals, zones located {zmatch}/{len(out)}")


if __name__ == "__main__":
    main()
