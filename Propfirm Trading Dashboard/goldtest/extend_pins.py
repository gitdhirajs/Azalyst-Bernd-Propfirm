#!/usr/bin/env python3
"""Fetch forward price history for symbols whose pin ends before a setup's call date.

WHY A SEPARATE DIRECTORY
18 of the 65 drawn setups (C-101 amended) resolve to "no data" -- not because the symbol
is unpinned, but because the pin ends weeks BEFORE the call date. All 18 are FX and
commodity setups from March 2024 against pins ending 2024-02-09 to 2024-03-04. Recovering
them raises the paired sample from 30 decided to roughly 48, which is the cheapest
available power increase for the C-101 test and needs no new frame reading.

The forward data is written to `ohlcv_extended/`, NOT to `ohlcv_snapshot/`. The snapshot
directory is what makes the 510-case corpus byte-reproducible; adding files there could
change which pin `--ohlcv-snapshot read` selects and would silently perturb every A/B
result recorded this session. Extended pins are opt-in, used only by tools that ask for
them via `expectancy.py --pin-dir`.

    python goldtest/extend_pins.py                       # what is missing, no fetch
    python goldtest/extend_pins.py --fetch --through 2024-12-31

Fetching hits the live feed, so the extended files are NOT reproducible in the way the
snapshot is. That is acceptable here because they are used to resolve outcomes on dates
already in the past, but it is the reason they are quarantined rather than merged.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

EXT = ROOT / "ohlcv_extended"


def needed(setups_file):
    """Symbols whose pinned series ends before a setup that references them."""
    from expectancy import pin
    sig = json.load(open(setups_file, encoding="utf-8"))
    short = {}
    for s in sig:
        px = pin(s["symbol"])
        if px is None:
            short.setdefault(s["symbol"], []).append((s["call_date"], "no pin at all"))
            continue
        end = px["timestamp"].max()
        if pd.Timestamp(s["call_date"]) >= end:
            short.setdefault(s["symbol"], []).append(
                (s["call_date"], f"pin ends {end.date()}"))
    return short


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--setups", default=str(HERE / "their_setups.json"))
    ap.add_argument("--fetch", action="store_true",
                    help="actually download; without it this only reports")
    ap.add_argument("--through", default="2025-01-01",
                    help="fetch forward to this date")
    a = ap.parse_args()

    short = needed(a.setups)
    if not short:
        print("every setup already has forward data -- nothing to extend")
        return
    total = sum(len(v) for v in short.values())
    print(f"{total} setups blocked across {len(short)} symbols:")
    for sym, rows in sorted(short.items()):
        print(f"  {sym:12s} {len(rows):2d} setups   {rows[0][1]}")

    if not a.fetch:
        print("\nre-run with --fetch to download forward history into "
              f"{EXT.relative_to(ROOT)}/")
        return

    EXT.mkdir(exist_ok=True)
    from BP_data_fetcher import DataFetcher
    f = DataFetcher()
    for sym in sorted(short):
        try:
            df = f.fetch_ohlcv(sym, "1d", period="5y")
        except Exception as e:
            print(f"  {sym:12s} FAILED {type(e).__name__}: {e}")
            continue
        if df is None or df.empty:
            print(f"  {sym:12s} FAILED empty")
            continue
        df = df.reset_index()
        cols = {c.lower(): c for c in df.columns}
        if "timestamp" not in df.columns:
            for cand in ("date", "index", "datetime"):
                if cand in cols:
                    df = df.rename(columns={cols[cand]: "timestamp"})
                    break
        out = EXT / f"{sym}__1d__5y__primary.csv"
        df.to_csv(out, index=False)
        end = pd.to_datetime(df["timestamp"]).max()
        print(f"  {sym:12s} {len(df):5d} bars through {str(end)[:10]} -> {out.name}")

    print(f"\nextended pins in {EXT}")
    print("use with: python goldtest/expectancy.py ... --pin-dir ohlcv_extended")


if __name__ == "__main__":
    main()
