#!/usr/bin/env python3
"""Consolidate every drawn position tool the frame readers found into one ground truth.

WHY
`signals_setups.json` and `practical_setups.json` were each written by an ad-hoc
snippet at a moment when the corpus was partly read, and went stale as the supervisor
kept going -- signals held 13 setups in the file against 54 in the corpus. Anything
measured against a stale file silently under-samples.

This rebuilds from the .jsonl reads, which are the durable record, so it can be re-run
after every supervisor cycle and always reflects the full corpus.

    python gemini/build_setups.py

A setup is kept only when the frame carries a position tool AND a readable entry and
stop -- direction alone is not a setup, and an entry without a stop gives no R.
Direction is flipped for the inverted futures contracts (@JY/@SF/@CD are reciprocals
of the USDJPY/USDCHF/USDCAD spot quotes we price against); see frame_match.INVERTED.

Duplicates are collapsed on (symbol, date, direction, entry, stop): the same position
tool survives across consecutive frames of one recording, and counting it once per
frame would weight a single trade by however long it stayed on screen.

INVERTED CONTRACTS CARRY INVERTED PRICES, NOT JUST INVERTED DIRECTION
`frame_match.is_inverted` exists because a long on @JY is a short on USDJPY. The first
version of this script flipped the direction and left the prices alone, which put five
USDJPY setups on the reciprocal scale -- a drawn entry of 0.7711 measured against a spot
series trading at 134. Every R-error computed from those was meaningless.

The transform is `1/p`, then a power of ten to match quote convention (@JY quotes USD
per JPY, so 1/0.007711 = 129.7 while the frame legend reads 0.7711). The exponent is
CHOSEN BY FITTING to the pinned series rather than hardcoded, because the decimal
convention differs per contract and guessing it silently corrupts the ground truth.

Every setup -- inverted or not -- is then scale-checked against the pinned daily
series: the entry must sit within 25% of the range price actually traded inside a year
of the call date. The band is deliberately wide. It exists to catch a wrong symbol
mapping or a misread decimal, which miss by orders of magnitude; a drawn entry a few
percent above recent highs is an ordinary resting order and is kept. A first version
that rejected on the raw range discarded 11 valid setups missing by 1-5%.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from frame_match import norm_symbol, is_inverted, flip

SNAP = Path(r"D:/Trading/Azalyst Bernd Skorupinski/Propfirm Trading Dashboard/ohlcv_snapshot")

TOL = 0.25   # scale-error tolerance; see the range check in main()

_PIN_CACHE = {}


def pinned(symbol):
    """Longest pinned daily series for a symbol, or None."""
    if symbol in _PIN_CACHE:
        return _PIN_CACHE[symbol]
    import pandas as pd
    cands = sorted(SNAP.glob(f"{symbol}__1d__*__primary.csv"))
    df = None
    if cands:
        df = pd.read_csv(cands[-1])
        ts = pd.to_datetime(df["timestamp"])
        if getattr(ts.dt, "tz", None) is not None:
            ts = ts.dt.tz_localize(None)
        df["timestamp"] = ts
    _PIN_CACHE[symbol] = df
    return df


def local_range(symbol, date, window_days=365):
    """(low, high) price actually traded within a year of the call date."""
    import pandas as pd
    df = pinned(symbol)
    if df is None or not date:
        return None
    try:
        d = pd.Timestamp(date)
    except Exception:
        return None
    w = df[(df["timestamp"] >= d - pd.Timedelta(days=window_days)) &
           (df["timestamp"] <= d + pd.Timedelta(days=window_days))]
    if w.empty:
        return None
    return float(w["low"].min()), float(w["high"].max())


def uninvert(p, rng):
    """1/p rescaled by the power of ten that lands it inside `rng`.

    Returns None when no exponent fits, which means the mapping is wrong and the
    setup must be dropped rather than guessed at.
    """
    if not p:
        return None
    base = 1.0 / p
    lo, hi = rng
    for k in range(-4, 5):
        v = base * (10.0 ** k)
        if lo * (1 - TOL) <= v <= hi * (1 + TOL):
            return v
    return None


SOURCES = {
    "signals":   HERE / "out" / "signals_trades.jsonl",
    "practical": HERE / "out" / "practical_trades.jsonl",
    "weekly":    HERE / "out" / "weekly_trades.jsonl",
}
OUT = HERE / "out" / "drawn_setups.json"


def zone_rows(dropped, seen):
    """Setups from DRAWN ZONE EDGES on frames that carry no position tool.

    83 frames across both corpora have a position tool with a readable entry and stop.
    265 more have no position tool but DO have a readable zone proximal and distal --
    and in this methodology those are the trade: entry at the proximal, stop at the
    distal, which is exactly what `BP_rules_engine` does with its own zones. Discarding
    them threw away four fifths of the available evidence, which is why the C-101 paired
    test has been stuck at 7:2 discordant and p=0.18.

    Kept as a SEPARATE class from the position-tool setups, and never silently pooled
    with them, because they support a weaker claim. A drawn position tool is a trade
    they committed to. A drawn zone is a level they thought worth marking while talking
    -- which is the right evidence for "is our zone selection like theirs" (C-110) but
    not proof they took it.

    Direction comes from the geometry: distal below proximal is a demand zone (long),
    above is supply (short). The `direction` field is null on all of these.
    """
    out = []
    for corpus, path in SOURCES.items():
        if not path.exists():
            continue
        for line in open(path, encoding="utf-8"):
            try:
                rec = json.loads(line)
            except Exception:
                continue
            d = rec.get("data") or {}
            if d.get("has_position_tool"):
                continue
            zp, zd = d.get("zone_proximal"), d.get("zone_distal")
            if not (zp and zd):
                continue
            sym = norm_symbol(d.get("chart_symbol_text"))
            if not sym:
                dropped["zone: unmappable symbol"] = \
                    dropped.get("zone: unmappable symbol", 0) + 1
                continue
            try:
                zp, zd = float(zp), float(zd)
            except (TypeError, ValueError):
                continue
            if zp == zd:
                continue
            rng = local_range(sym, rec.get("date"))
            if rng is None:
                dropped["zone: no pinned series"] = \
                    dropped.get("zone: no pinned series", 0) + 1
                continue
            inv = bool(is_inverted(d.get("chart_symbol_text"), sym))
            if inv:
                a, b = uninvert(zp, rng), uninvert(zd, rng)
                if a is None or b is None:
                    dropped["zone: inverted price unmappable"] = \
                        dropped.get("zone: inverted price unmappable", 0) + 1
                    continue
                zp, zd = a, b
            # Same scale gate as the position-tool path: catches a misread decimal or a
            # wrong symbol map, not an unusual level. BOTH edges must pass -- a zone with
            # one plausible edge is a misread, and it is the pair that defines the trade.
            lo, hi = rng[0] * (1 - TOL), rng[1] * (1 + TOL)
            if not (lo <= zp <= hi and lo <= zd <= hi):
                dropped["zone: edge off by >25% of traded range"] = \
                    dropped.get("zone: edge off by >25% of traded range", 0) + 1
                continue
            direction = "long" if zd < zp else "short"
            key = (sym, rec.get("date"), direction, round(zp, 6), round(zd, 6))
            if key in seen:
                continue
            seen[key] = True
            out.append({
                "symbol": sym, "date": rec.get("date"), "direction": direction,
                "stated_direction": d.get("direction"),
                "entry": zp, "stop": zd, "target": d.get("target"),
                "corpus": corpus, "folder": rec.get("folder"), "frame": rec.get("frame"),
                "chart_symbol_text": d.get("chart_symbol_text"),
                "inverted": inv, "source": "zone_edges",
            })
    return out


def collapse(rows, dropped):
    """One setup per (symbol, date, direction), and drop contradictory days.

    WHY (C-127). Reading the source frames directly exposed two things no aggregate
    check caught:

      * The same position tool is re-read as it is dragged around the screen.
        NQ=F 2023-02-14 produced SEVEN setups -- entries 12545.25 / 12130.0 / 12285.5 /
        12553.5 / 11800.0 / 11800.0 / 12560.5 against a 12000 stop -- which is one tool,
        not seven trades. The old key (symbol, date, direction, entry, stop) treated
        12545 and 12553 as distinct.
      * Same-day direction contradictions. PA=F 2023-03-21 appears as a long
        (1385.0 / 1331.37) and a short (1385.0 / 1405.5) -- identical entry, opposite
        direction. The chart shows a demand zone at 1331-1385 below a price of 1405, so
        the long is right and the short is a misread of a neighbouring chart's levels.
        One "winner" and one "loser" were the same setup.

    Together these carried C-117 from p=0.0703 to a spurious p=0.0391. Collapsing is
    therefore the default, not an option: the median entry and stop of a day's readings
    stand in for the tool, and a symbol/date whose readings disagree on DIRECTION is
    dropped entirely rather than resolved by majority, because the frames give no basis
    for choosing and a wrong direction is worse than a missing row.
    """
    import statistics
    bysd = {}
    for r in rows:
        bysd.setdefault((r["symbol"], r["date"]), set()).add(r["direction"])

    g = {}
    for r in rows:
        if len(bysd[(r["symbol"], r["date"])]) > 1:
            dropped["contradictory direction same day"] =                 dropped.get("contradictory direction same day", 0) + 1
            continue
        g.setdefault((r["symbol"], r["date"], r["direction"], r["source"]), []).append(r)

    out = []
    for k, v in g.items():
        base = dict(v[0])
        base["entry"] = statistics.median([x["entry"] for x in v])
        base["stop"] = statistics.median([x["stop"] for x in v])
        base["readings"] = len(v)
        out.append(base)
        if len(v) > 1:
            dropped["collapsed duplicate readings"] =                 dropped.get("collapsed duplicate readings", 0) + len(v) - 1
    return out


def main():
    seen, rows = {}, []
    stats = {}
    dropped = {}
    for corpus, path in SOURCES.items():
        if not path.exists():
            continue
        n = kept = unmapped = 0
        for line in open(path, encoding="utf-8"):
            try:
                rec = json.loads(line)
            except Exception:
                continue
            d = rec.get("data") or {}
            n += 1
            if not (d.get("has_position_tool") and d.get("entry") and d.get("stop")):
                continue
            sym = norm_symbol(d.get("chart_symbol_text"))
            if not sym:
                unmapped += 1
                continue
            direction = d.get("direction")
            inv = bool(is_inverted(d.get("chart_symbol_text"), sym))
            if inv:
                direction = flip(direction)
            e, s = float(d["entry"]), float(d["stop"])
            if e == s:
                continue

            rng = local_range(sym, rec.get("date"))
            if rng is None:
                dropped["no pinned series"] = dropped.get("no pinned series", 0) + 1
                continue
            if inv:
                # reciprocal + fitted decade; both legs must land on the same scale
                e2, s2 = uninvert(e, rng), uninvert(s, rng)
                if e2 is None or s2 is None:
                    dropped["inverted price unmappable"] = \
                        dropped.get("inverted price unmappable", 0) + 1
                    continue
                e, s = e2, s2
            elif not (rng[0] * (1 - TOL) <= e <= rng[1] * (1 + TOL)):
                # Scale check, NOT a plausibility check. A drawn entry a few percent
                # beyond the traded range is an ordinary resting order above recent
                # highs -- an audit of the first version, which rejected on the raw
                # range, found it discarded 11 valid setups that missed by 1-5%.
                # The error this is here to catch (an inverted contract priced at
                # 0.7711 against a series trading at 134) is off by ~17,000%, so a
                # wide band separates the two cleanly with nothing in between.
                dropped["entry off by >25% of traded range"] = \
                    dropped.get("entry off by >25% of traded range", 0) + 1
                continue

            # direction implied by the drawing beats a mislabelled field
            implied = "long" if s < e else "short"
            key = (sym, rec.get("date"), implied, round(e, 6), round(s, 6))
            if key in seen:
                continue
            seen[key] = True
            kept += 1
            rows.append({
                "symbol": sym, "date": rec.get("date"), "direction": implied,
                "stated_direction": direction,
                "entry": e, "stop": s,
                "target": d.get("target"),
                "corpus": corpus, "folder": rec.get("folder"), "frame": rec.get("frame"),
                "chart_symbol_text": d.get("chart_symbol_text"),
                "inverted": inv, "source": "position_tool",
            })
        stats[corpus] = (n, kept, unmapped)

    zrows = zone_rows(dropped, seen)
    rows.extend(zrows)

    rows = collapse(rows, dropped)
    rows.sort(key=lambda r: (r["date"] or "", r["symbol"]))
    OUT.write_text(json.dumps(rows, indent=1), encoding="utf-8")

    print(f"{'corpus':<12}{'frames':>8}{'setups':>8}{'unmapped':>10}")
    for c, (n, k, u) in stats.items():
        print(f"{c:<12}{n:>8}{k:>8}{u:>10}")
    print(f"\n{len(rows)} distinct drawn setups -> {OUT}")
    # only meaningful for position-tool rows; zone-edge rows carry no stated direction
    mism = sum(1 for r in rows if r.get("source") == "position_tool"
               and r["stated_direction"] != r["direction"])
    print(f"  entry/stop geometry disagreed with the stated direction on {mism}")
    bysrc = {}
    for r in rows:
        bysrc[r.get("source")] = bysrc.get(r.get("source"), 0) + 1
    print(f"  by source: {bysrc}")
    by = {}
    for r in rows:
        by[r["symbol"]] = by.get(r["symbol"], 0) + 1
    print("  top symbols: " + ", ".join(f"{k}={v}" for k, v in
                                        sorted(by.items(), key=lambda kv: -kv[1])[:10]))


if __name__ == "__main__":
    main()
