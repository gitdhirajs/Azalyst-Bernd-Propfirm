#!/usr/bin/env python3
"""Does the SYSTEM reproduce the indicator value visible in the LECTURE FRAME?

This is a deterministic reproduction test, not a prediction test. For every frame
where the vision pass captured a chart symbol, a crosshair date, a timeframe and a
live indicator readout, the system should compute the same number. Unlike
directional accuracy, 100% here is a legitimate target: both sides are arithmetic
over the same price history.

The claim on file today is "the indicators reproduce Bernd's lecture frames exactly
(COT 85.10 / 18.10 / 74.56)" -- that is n=3. Across gemini/out/{weekly,practical}
there are 9,718 frame reads, 5,533 successful, and 1,656 carrying symbol + date +
timeframe + a legend. This turns n=3 into n=hundreds.

    python gemini/frame_match.py --extract          # build the observation set
    python gemini/frame_match.py --coverage         # what is comparable, and why not

WHAT THE LEGENDS LOOK LIKE, and how the live value is taken from each:

  Valuation
    CampusValuationTool V2 ("@US","@GC","$DXY", True, False, ... @US -56.33 Loaded 0.00 -75.00 75.00
                                                                     ^^^^^^
    The live reading is the float immediately after the echoed reference symbol.
    The trailing 0.00 / -75.00 / 75.00 are the zero line and the two thresholds --
    plot levels, not readings. Taking the last float instead gets the threshold.

  COT
    Campus COT Index V2 protected V1 (... 97.03 2.39 8.77 80.00 20.00 100.00 0.00
                                          ^^^^^^^^^^^^^^^
    Trailing 80/20/100/0 are the extreme lines and the axis bounds. What precedes
    them is the live plot set: 2 or 3 values depending on the build.

  Seasonality
    Campus True Seasonality 3383376 ( 5 , 100 , False , False , False ) 261.33
                                      ^                                 ^^^^^^
    First arg is the lookback N; the trailing float is the reading. Seasonality is
    an INDEX in the instrument's own units, so its absolute value is only
    comparable if the same normalisation is used -- see --coverage notes.

A SINGLE READ IS NOT EVIDENCE (rule 9). The same legend token has been read as
`$DXY`, `@SDXY`, `$OXY` and `@SOXY` off the same image. Every observation here
carries its source frame so a disputed row can be re-read, and the matcher reports
agreement across duplicate reads of the same frame separately from agreement with
the system.

=============================================================================
DO NOT JOIN A LEGEND VALUE TO ITS `crosshair_date`. MEASURED, 2026-08-26.
=============================================================================
The legend prints the value of the CURRENT bar; `crosshair_date` is wherever the
mouse happened to be. They are independent, and treating them as the same thing
silently fabricates a (value, date) pair that never existed on screen.

    (chapter, symbol) groups                                     120
    groups where ONE value spans >=3 DIFFERENT crosshair dates     50
    groups with >=3 distinct values                                 7

    AAPL: 77 readings, 42 distinct crosshair dates, only 13 distinct
          values. The single value -56.33 appears at 14 different
          crosshair dates.

So a numeric "our number vs his number at date D" test is NOT sound on this data,
and no such comparison is implemented here. What IS sound is anything that does
not need the date:

  * the DISTRIBUTION of readings per asset class (see --coverage), which is what
    established that his tool never once read bearish on an equity index across
    400 observations in 16 chapters;
  * the reference symbols, flags and Length parsed out of the argument list,
    which are settings and do not move with the bar.

To get a dated reading you would need the chart's last bar, which the vision pass
does not currently record. Capturing it would make the numeric test possible.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"

# TradeStation continuous-contract codes -> yfinance. Extends the map already in
# analyze_valuation.py with the spelled-out names the vision pass also returns.
NORM = {
    "@C": "ZC=F", "@W": "ZW=F", "@S": "ZS=F", "@KC": "KC=F", "@SB": "SB=F",
    "@CT": "CT=F", "@CC": "CC=F",
    "@GC": "GC=F", "@SI": "SI=F", "@PL": "PL=F", "@PA": "PA=F", "@HG": "HG=F",
    "@CL": "CL=F", "@NG": "NG=F", "@HO": "HO=F", "@RB": "RB=F",
    "@ES": "ES=F", "@NQ": "NQ=F", "@YM": "YM=F", "@RTY": "RTY=F", "@EMD": "ES=F",
    "@US": "ZB=F", "@TY": "ZN=F",
    "@DX": "DX-Y.NYB", "@EC": "EURUSD=X", "@BP": "GBPUSD=X", "@JY": "USDJPY=X",
    "@SF": "USDCHF=X", "@AD": "AUDUSD=X", "@CD": "USDCAD=X", "@NE": "NZDUSD=X",
    # spelled-out / vendor forms seen in chart_symbol_text
    "NATGAS": "NG=F", "USOIL": "CL=F", "UKOIL": "BZ=F",
    "XAUUSD": "GC=F", "XAGUSD": "SI=F", "XPTUSD": "PL=F", "XPDUSD": "PA=F",
    "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X",
    "USDCHF": "USDCHF=X", "AUDUSD": "AUDUSD=X", "USDCAD": "USDCAD=X",
    "NZDUSD": "NZDUSD=X", "EURJPY": "EURJPY=X", "GBPJPY": "GBPJPY=X",
    "DXY": "DX-Y.NYB", "US30": "YM=F", "US500": "ES=F", "NAS100": "NQ=F",
    "GER40": "^GDAXI", "GER30": "^GDAXI",
    "BTCUSD": "BTC-USD", "ETHUSD": "ETH-USD",
    # Forms seen in the Funded Trader frame reads that the @XX regex misses:
    # vendor prefixes without the @, spelled-out contract names, and @MP (peso).
    "@MP": "MXN=X", "MP": "MXN=X",
    "EC": "EURUSD=X", "BP": "GBPUSD=X", "JY": "USDJPY=X", "SF": "USDCHF=X",
    "AD": "AUDUSD=X", "CD": "USDCAD=X", "NE": "NZDUSD=X",
    "NG": "NG=F", "CL": "CL=F", "GC": "GC=F", "SI": "SI=F", "HG": "HG=F",
    "YM": "YM=F", "NQ": "NQ=F", "ES": "ES=F", "RTY": "RTY=F",
    "E-MINI DOW": "YM=F", "E-MINI S&P 500": "ES=F",
    "E-MINI NASDAQ 100": "NQ=F", "E-MINI RUSSELL 2000": "RTY=F",
    "CRUDE OIL": "CL=F", "NATURAL GAS": "NG=F", "GOLD": "GC=F", "SILVER": "SI=F",
}
# ---------------------------------------------------------------------------
# INVERTED PAIRS -- a direction on these is the OPPOSITE of a direction on the
# yfinance symbol they map to.
#
# The CME currency futures are quoted as USD per unit of the foreign currency.
# For EUR, GBP, AUD and NZD that is the same way round as the spot pair, so
# @EC -> EURUSD=X carries the direction through unchanged. For JPY, CHF and CAD
# the spot convention is the RECIPROCAL -- USDJPY, USDCHF, USDCAD are foreign
# currency per USD -- so a LONG @JY is a SHORT USDJPY.
#
# Verified against pinned closes on 2023-04-18:
#   @SF frame value 1.12155   1/1.12155  = 0.89162   USDCHF=X actual 0.89851
#   @JY frame value 0.75125   100/0.75125 = 133.111  USDJPY=X actual 134.425
#
# This is not a hypothetical. Mapping them straight through made three of the
# eight frame-vs-transcript disagreements, and all three flip to AGREEMENT once
# inverted. The map this was inherited from (gemini/analyze_valuation.py, also
# gemini/analyze_cot_groups.py) does NOT invert, so any finding derived from
# those two scripts for USDJPY / USDCHF / USDCAD needs re-checking.
INVERTED = {"USDJPY=X", "USDCHF=X", "USDCAD=X"}
INVERT_SOURCES = {"@JY", "@SF", "@CD", "JY", "SF", "CD"}


def is_inverted(symbol_text, mapped):
    """True when a long on the SCREEN symbol is a short on the mapped symbol."""
    if not symbol_text or mapped not in INVERTED:
        return False
    t = str(symbol_text).strip().upper()
    t = re.sub(r"[-=(].*$", "", t).strip()
    t = re.sub(r"\d+$", "", t)
    # Only the FUTURES codes are reciprocal. "USDJPY" written out is already spot.
    return t in INVERT_SOURCES


def flip(bias):
    return {"long": "short", "short": "long"}.get(bias, bias)


# Plain equity tickers pass straight through.
EQUITY = re.compile(r"^[A-Z]{1,5}$")

FLOAT = re.compile(r"-?\d+(?:\.\d+)?")
# Threshold / axis constants that trail a legend and are NOT readings.
COT_TRAILERS = ((80.0, 20.0, 100.0, 0.0), (80.0, 20.0), (100.0, 0.0))
VAL_TRAILERS = (0.0, 75.0, -75.0, 85.0, -85.0, 69.0, -69.0, 100.0, -100.0)


def norm_symbol(text):
    """chart_symbol_text -> yfinance symbol, or None if it cannot be mapped."""
    if not text:
        return None
    t = text.strip().upper()
    # Vendor descriptions carry the exchange in front: "NYMEX|Crude Oil Custom..."
    if "|" in t:
        t = t.split("|", 1)[1].strip()
    # "Crude Oil Custom Continuous Contract" -> "CRUDE OIL"
    t = re.sub(r"\s+(CUSTOM\s+)?CONTINUOUS\s+CONTRACT.*$", "", t)
    t = re.sub(r"\s+FUTURES?$", "", t)
    # Try the spelled-out name BEFORE stripping decorations: "E-MINI DOW" contains
    # a hyphen, and the decoration stripper below would cut it down to "E".
    if t in NORM:
        return NORM[t]
    # strip TradeStation contract decorations: @GC=120XN+GJMQZ, @NE1=103XN(D),
    # EC-103XN, YM.D, $YM=
    t = re.sub(r"\s*\(.*$", "", t)
    t = t.lstrip("$")
    t = re.sub(r"[-=].*$", "", t)
    t = re.sub(r"\.[A-Z]$", "", t)      # YM.D -> YM
    t = re.sub(r"\d+$", "", t)          # @NE1 -> @NE
    t = t.strip()
    if t in NORM:
        return NORM[t]
    m = re.match(r"(@[A-Z]{1,3})", t)
    if m and m.group(1) in NORM:
        return NORM[m.group(1)]
    if EQUITY.match(t):
        return t
    return None


def norm_timeframe(text):
    t = (text or "").lower()
    if "month" in t or t in ("1mo", "1m") or "monat" in t:
        return "1mo"
    if "week" in t or t in ("1w", "1wk") or "woche" in t:
        return "1wk"
    if "240" in t or "4std" in t or "4h" in t:
        return "240m"
    if "60" in t or "1h" in t or "std" in t:
        return "60m"
    if "day" in t or "daily" in t or t in ("1d", "d") or "tag" in t:
        return "1d"
    return None


def norm_date(text):
    """Crosshair dates come as MM/DD/YY, sometimes with a time and stray chars."""
    if not text:
        return None
    m = re.search(r"(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})", str(text))
    if not m:
        return None
    mo, dd, yy = (int(x) for x in m.groups())
    if yy < 100:
        yy += 2000
    if not (1 <= mo <= 12 and 1 <= dd <= 31 and 2000 <= yy <= 2030):
        return None
    return f"{yy:04d}-{mo:02d}-{dd:02d}"


def classify(raw):
    name = re.sub(r"[^A-Za-z ]", " ", raw.split("(")[0]).strip().lower()
    if "valuation" in name:
        return "valuation"
    if "cot" in name:
        return "cot"
    if "seasonality" in name:
        return "seasonality"
    if "algo forecast" in name:
        return "algo_forecast"
    if "smart money" in name:
        return "smart_money"
    return None


def parse_valuation(raw):
    """The float immediately after the echoed reference symbol."""
    m = re.search(r"(?:@[A-Z]{1,3}|\$?S?[A-Z]{3,4})\s+(-?\d+\.\d+)\s+Loaded", raw)
    if m:
        return float(m.group(1))
    # no "Loaded" marker: take the first float that follows the closing bracket
    tail = raw.split(",", 1)[-1]
    m = re.search(r"\.\.\.\s*(?:@[A-Z]{1,3}\s+)?(-?\d+\.\d+)", tail)
    return float(m.group(1)) if m else None


def parse_cot(raw):
    """Live plots = the floats before the trailing threshold/axis constants."""
    nums = [float(x) for x in FLOAT.findall(raw.split(")")[-1] or raw)]
    for trail in COT_TRAILERS:
        n = len(trail)
        if len(nums) > n and tuple(nums[-n:]) == trail:
            head = nums[:-n]
            return head[-3:] if len(head) >= 3 else head
    return None


def parse_seasonality(raw):
    nums = [float(x) for x in FLOAT.findall(raw)]
    return nums[-1] if nums else None


def extract():
    """Walk every frame read and emit one row per identifiable indicator value."""
    rows, skipped = [], collections.Counter()
    for f in sorted(glob.glob(str(OUT / "weekly" / "*.jsonl"))
                    + glob.glob(str(OUT / "practical" / "*.jsonl"))):
        chapter = os.path.basename(f).replace(".jsonl", "")
        for line in open(f, encoding="utf-8"):
            try:
                d = json.loads(line)
            except Exception:
                skipped["unparseable line"] += 1
                continue
            if not d.get("ok"):
                skipped["read failed"] += 1
                continue
            data = d.get("data") or {}
            legs = data.get("indicator_legends") or []
            if not legs:
                skipped["no legend"] += 1
                continue
            sym = norm_symbol(data.get("chart_symbol_text"))
            date = norm_date(data.get("crosshair_date"))
            tf = norm_timeframe(data.get("timeframe"))
            for l in legs:
                raw = l.get("raw_text") or ""
                kind = classify(raw)
                if kind is None:
                    skipped["unrecognised indicator"] += 1
                    continue
                if kind == "valuation":
                    val = parse_valuation(raw)
                elif kind == "cot":
                    val = parse_cot(raw)
                elif kind == "seasonality":
                    val = parse_seasonality(raw)
                else:
                    skipped[f"{kind} (not comparable)"] += 1
                    continue
                if val is None:
                    skipped[f"{kind}: value unparseable"] += 1
                    continue
                rows.append({
                    "chapter": chapter, "frame": d.get("frame"),
                    "model": d.get("model"), "key_id": d.get("key_id"),
                    "symbol_text": data.get("chart_symbol_text"), "symbol": sym,
                    "crosshair": data.get("crosshair_date"), "date": date,
                    "timeframe_text": data.get("timeframe"), "timeframe": tf,
                    "indicator": kind, "value": val, "raw": raw[:200],
                })
    return rows, skipped


def coverage(rows, skipped):
    print(f"observations extracted: {len(rows)}\n")
    print("skipped while extracting:")
    for k, v in skipped.most_common():
        print(f"   {k:<28} {v}")

    by = collections.Counter(r["indicator"] for r in rows)
    print("\nby indicator:")
    for k, v in by.most_common():
        print(f"   {k:<15} {v}")

    print("\ncomparable = symbol AND date AND timeframe all resolved:")
    for kind in ("valuation", "cot", "seasonality"):
        sub = [r for r in rows if r["indicator"] == kind]
        if not sub:
            continue
        ok = [r for r in sub if r["symbol"] and r["date"] and r["timeframe"]]
        print(f"   {kind:<15} {len(ok):>4} of {len(sub):>4}"
              f"   (no symbol {sum(1 for r in sub if not r['symbol']):>4},"
              f" no date {sum(1 for r in sub if not r['date']):>4},"
              f" no tf {sum(1 for r in sub if not r['timeframe']):>4})")

    ok = [r for r in rows if r["symbol"] and r["date"] and r["timeframe"]]
    print(f"\nTOTAL COMPARABLE: {len(ok)}")
    print("   distinct (symbol, date, timeframe, indicator) targets:",
          len({(r["symbol"], r["date"], r["timeframe"], r["indicator"]) for r in ok}))
    print("   top symbols:", collections.Counter(r["symbol"] for r in ok).most_common(8))
    print("   date range:", min(r["date"] for r in ok), "->", max(r["date"] for r in ok))

    unmapped = collections.Counter(
        r["symbol_text"] for r in rows if not r["symbol"] and r["symbol_text"])
    if unmapped:
        print("\nunmapped symbol_text (add to NORM to widen coverage):")
        for k, v in unmapped.most_common(15):
            print(f"   {str(k)[:38]:<40} {v}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract", action="store_true")
    ap.add_argument("--coverage", action="store_true")
    ap.add_argument("--out", default=str(OUT / "frame_observations.json"))
    a = ap.parse_args()

    rows, skipped = extract()
    if a.extract:
        json.dump(rows, open(a.out, "w", encoding="utf-8"), indent=1)
        print(f"wrote {len(rows)} observations to {a.out}")
    if a.coverage or not a.extract:
        coverage(rows, skipped)


if __name__ == "__main__":
    main()
