#!/usr/bin/env python3
"""Build a goldtest case file from the TRADE DECISIONS visible in the lecture frames.

The 479-case corpus the system is scored on today is built from TRANSCRIPT quotes --
what the presenter SAID. This builds a second, independent ground truth from what was
on the SCREEN: the vision pass recorded `trade_signal_direction` per chart frame, and
those come with the symbol, the timeframe, the price at the time and the drawn
support/resistance levels.

Why a second source is worth having: every label dispute settled this week
(`C-85 RESOLVED`, C-64) turned on the same failure -- a sparse transcript quoted
half a sentence and the refusal in the other half was lost. A frame showing a drawn
level does not have that failure mode.

    python gemini/build_frame_cases.py                     # report only
    python gemini/build_frame_cases.py --write out.yaml    # emit goldtest cases

Then score the system against it exactly like any other corpus:

    cd "...\\Propfirm Trading Dashboard\\goldtest"
    python run_goldtest.py --cases-file frame_cases.yaml \\
        --cot-snapshot fill --ohlcv-snapshot fill --output framearm.json

CONFLICTS ARE REPORTED, NOT RESOLVED. One session shows a symbol on several charts
and several timeframes, so the same (symbol, date) can carry more than one frame
decision. Where those disagree the case is EXCLUDED and listed, because silently
picking one would be inventing a ground truth -- the exact thing that made the old
in-sample score meaningless.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from frame_match import norm_symbol, norm_timeframe, is_inverted, flip  # noqa: E402

CORPUS = Path(r"D:/Trading/Output/Funded Traders")
ROOTS = ("Funded Trader Signals", "Funded Trader Weekly Outlook", "Practical Application")

# Asset class, needed by run_goldtest. Mirrors BP_config's watchlist grouping.
ASSET_CLASS = {
    "GC=F": "precious_metals", "SI=F": "precious_metals",
    "PL=F": "precious_metals", "PA=F": "precious_metals",
    "CL=F": "energies", "NG=F": "energies", "HO=F": "energies",
    "BZ=F": "energies", "RB=F": "energies",
    "HG=F": "commodities", "ZC=F": "commodities", "ZW=F": "commodities",
    "ZS=F": "commodities", "KC=F": "commodities", "SB=F": "commodities",
    "CC=F": "commodities", "CT=F": "commodities",
    "ES=F": "equity_indices", "NQ=F": "equity_indices",
    "YM=F": "equity_indices", "RTY=F": "equity_indices", "^GDAXI": "equity_indices",
    "ZB=F": "interest_rates", "ZN=F": "interest_rates",
    "BTC-USD": "crypto", "ETH-USD": "crypto",
}


def asset_class(sym):
    if sym in ASSET_CLASS:
        return ASSET_CLASS[sym]
    if sym.endswith("=X") or sym == "DX-Y.NYB":
        return "forex"
    return "equities"


def strategy_for(tf):
    """Chart timeframe -> goldtest income strategy.

    These are NOT the same thing, and conflating them was worth 33 errors out of
    70 on the first run. `strategy` selects which bar series run_goldtest loads:

        monthly  htf 1mo  ltf 1wk
        weekly   htf 1wk  ltf 1d
        daily    htf 1d   ltf 60m     <- 60m exists only for the last ~730 days
        intraday htf 60m  ltf 15m     <- same problem, worse

    Every case here is 2023-2024, so anything mapped to `daily` or `intraday`
    fails with "insufficient OHLCV" before the engine ever runs. That is a data
    limit, not a verdict, and scoring against a corpus half of which errors out
    would be measuring attrition.

    A DAILY chart is the LTF of the weekly strategy, so a decision seen on one is
    still scoreable in the weekly frame with the same bars in view. Intraday
    charts fold up the same way. The chart the presenter actually had open is
    preserved as `_chart_tf` so nothing is lost.

    (The scored 479-case corpus has the same latent problem: 16 daily and 15
    intraday cases, against 31 total errors per run.)
    """
    return {"1mo": "monthly", "1wk": "weekly"}.get(tf, "weekly")


def load_decisions():
    rows = []
    for root in ROOTS:
        pattern = str(CORPUS / root / "**" / "_gemini_analysis_output" / "*_analysis.json")
        for p in glob.glob(pattern, recursive=True):
            try:
                d = json.load(open(p, encoding="utf-8"))
            except Exception:
                continue
            ca = d.get("chart_analysis") or {}
            sd = str(ca.get("trade_signal_direction") or "").lower()
            if sd not in ("buy", "sell"):
                continue
            folder = os.path.basename(os.path.dirname(os.path.dirname(p)))
            m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", folder)
            if not m:
                continue
            sym = norm_symbol(ca.get("symbol_ticker"))
            if not sym:
                continue
            bias = "long" if sd == "buy" else "short"
            # A long on @JY / @SF / @CD is a short on USDJPY / USDCHF / USDCAD --
            # the futures are quoted as the reciprocal of the spot pair. See
            # frame_match.INVERTED for the price check that establishes it.
            inverted = is_inverted(ca.get("symbol_ticker"), sym)
            if inverted:
                bias = flip(bias)
            rows.append({
                "inverted": inverted,
                "root": root, "folder": folder,
                "date": f"{m.group(3)}-{m.group(2)}-{m.group(1)}",
                "frame": d.get("source_frame_file"),
                "ticker": ca.get("symbol_ticker"), "symbol": sym,
                "tf": norm_timeframe(ca.get("timeframe")) or "1wk",
                "tf_text": ca.get("timeframe"),
                "bias": bias,
                "price": ca.get("current_price"),
                "levels": ca.get("support_resistance_levels") or [],
                "why": ca.get("trade_signal_reasoning"),
            })
    return rows


def collapse(rows):
    """One case per (symbol, date). Disagreeing frames are excluded, not resolved."""
    by = collections.defaultdict(list)
    for r in rows:
        by[(r["symbol"], r["date"])].append(r)
    cases, conflicts = [], []
    for (sym, date), group in sorted(by.items()):
        biases = {g["bias"] for g in group}
        if len(biases) > 1:
            conflicts.append((sym, date, collections.Counter(g["bias"] for g in group),
                              [g["frame"] for g in group[:4]]))
            continue
        g0 = max(group, key=lambda g: len(g["levels"]))   # richest frame as the exemplar
        cases.append({
            "call_date": date, "symbol": sym, "display_name": sym,
            "asset_class": asset_class(sym), "bias": g0["bias"],
            "strategy": strategy_for(g0["tf"]),
            "reasoning": (g0["why"] or f"frame decision {g0['bias'].upper()} on "
                                        f"{g0['tf_text']} chart, price {g0['price']}"),
            "confidence": "clear" if len(group) >= 3 else "soft",
            "_source": "frame", "_frames": len(group), "_frame": g0["frame"],
            "_chart_tf": g0["tf"], "_chart_tf_text": g0["tf_text"],
            "_folder": g0["folder"], "_price": g0["price"],
            "_levels": g0["levels"][:6],
        })
    return cases, conflicts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", metavar="FILE", help="emit a goldtest cases YAML here")
    a = ap.parse_args()

    rows = load_decisions()
    cases, conflicts = collapse(rows)

    print(f"directional frame decisions (symbol+date resolved): {len(rows)}")
    print(f"distinct (symbol, date)                            : "
          f"{len({(r['symbol'], r['date']) for r in rows})}")
    print(f"CASES (frames agree)                               : {len(cases)}")
    print(f"EXCLUDED (frames disagree within the same session)  : {len(conflicts)}")
    print("\nbias mix:", collections.Counter(c["bias"] for c in cases).most_common())
    print("asset classes:", collections.Counter(c["asset_class"] for c in cases).most_common())
    print("strategies:", collections.Counter(c["strategy"] for c in cases).most_common())
    if cases:
        print("date range:", min(c["call_date"] for c in cases), "->",
              max(c["call_date"] for c in cases))

    if conflicts:
        print("\nEXCLUDED -- the same symbol carries opposite decisions in one session.")
        print("These are NOT noise to be averaged away; a session that shows a long setup")
        print("on one timeframe and a short on another is a real thing, and picking one")
        print("would be inventing ground truth.")
        for sym, date, cnt, frames in conflicts[:15]:
            print(f"   {sym:<10} {date}  {dict(cnt)}  frames {frames}")

    if a.write:
        import yaml
        payload = {"cases": [{k: v for k, v in c.items() if not k.startswith("_")}
                             for c in cases]}
        with open(a.write, "w", encoding="utf-8") as fh:
            yaml.safe_dump(payload, fh, sort_keys=False, allow_unicode=True)
        meta = a.write.replace(".yaml", "_provenance.json")
        json.dump(cases, open(meta, "w", encoding="utf-8"), indent=1)
        print(f"\nwrote {len(cases)} cases to {a.write}")
        print(f"wrote provenance (frame, folder, price, levels) to {meta}")


if __name__ == "__main__":
    main()
