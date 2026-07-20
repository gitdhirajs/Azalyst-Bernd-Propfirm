"""
Gold-Standard Test Harness
==========================
Replays Bernd Skorupinski's published trade calls (extracted from Funded Trader
monthly roadmaps) against the live system and produces a side-by-side diff.

Each case in gold_cases.yaml lists a date, symbol, and Bernd's directional bias
(plus zone/entry/stop/target if quoted). For each case the harness:
  1. Fetches OHLCV pinned to (call_date - 1 day) -- NO lookahead.
  2. Filters COT data to that as-of date.
  3. Runs RulesEngine.run_seven_step_process on the historical snapshot.
  4. Captures the system's output (bias, zone, entry, stop, target, score).
  5. Compares Bernd's call vs system's call -> verdict per field.

Usage:
    python run_goldtest.py                  # Run all cases
    python run_goldtest.py --case 5         # Run a single case (1-indexed)
    python run_goldtest.py --asset equities # Filter by asset class

Output: gold_results.json (machine-readable) + console summary.
View results: open gold_diff.html in a browser.
"""

import sys
import json
import yaml
import logging
import argparse
import traceback
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# Add parent dir to path so we can import the BP_* modules
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))

from BP_data_fetcher import DataFetcher, get_cftc_code

# Engine is selected via --engine flag (default: original, deepseek: uses deepseek folder fixes)
import argparse as _ap
_pre = _ap.ArgumentParser(add_help=False)
_pre.add_argument("--engine", default="original")
_pre_args, _ = _pre.parse_known_args()
if _pre_args.engine == "deepseek":
    from deepseek.BP_rules_engine import RulesEngine
else:
    from BP_rules_engine import RulesEngine

# ---------------------------------------------------------------------------
# Asset class -> default ticker (for symbols where call uses a name like
# "Nasdaq 100" but we need the futures ticker for COT/charts)
# ---------------------------------------------------------------------------
ASSET_CLASS_BY_SYMBOL = {
    "ES=F":  "equity_indices",
    "NQ=F":  "equity_indices",
    "YM=F":  "equity_indices",
    "RTY=F": "equity_indices",
    "GC=F":  "precious_metals",
    "SI=F":  "precious_metals",
    "PL=F":  "precious_metals",
    "PA=F":  "precious_metals",
    "HG=F":  "precious_metals",
    "CL=F":  "energies",
    "NG=F":  "energies",
    "BZ=F":  "energies",
    "ZB=F":  "interest_rates",
    "ZN=F":  "interest_rates",
    # Phase 14 correction — Grains + Cotton → Commercials 52w (Ch.159/168/113/144)
    # Only CC/KC/SB/OJ remain as NonCommercials 26w (corpus inconclusive).
    "CC=F":  "soft_commodities",   # Cocoa  — NonCommercials
    "KC=F":  "soft_commodities",   # Coffee — NonCommercials
    "SB=F":  "soft_commodities",   # Sugar  — NonCommercials
    "OJ=F":  "soft_commodities",   # OJ     — NonCommercials
    "CT=F":  "commodities",        # Cotton — Commercials (Ch.113/144)
    "ZC=F":  "commodities",        # Corn   — Commercials (Ch.159)
    "ZW=F":  "commodities",        # Wheat  — Commercials
    "ZS=F":  "commodities",        # Soybeans — Commercials (Ch.168)
    "MXN=X": "forex",
    "AAPL": "equities", "MSFT": "equities", "GOOG": "equities",
    "GOOGL": "equities",
    "META": "equities", "AMZN": "equities", "NFLX": "equities",
    "TSLA": "equities", "NVDA": "equities",
    "BABA": "equities", "BA": "equities",
    # Forex spot/futures
    "EURUSD=X": "forex", "GBPUSD=X": "forex", "AUDUSD=X": "forex",
    "USDJPY=X": "forex", "USDCAD=X": "forex", "USDCHF=X": "forex",
    "NZDUSD=X": "forex",
    "6E=F": "forex", "6B=F": "forex", "6J=F": "forex",
    "6A=F": "forex", "6C=F": "forex", "6S=F": "forex",
}

# Same valuation refs as run_scanner.py (kept in sync deliberately)
# Phase 16: Individual stocks ("equities") DXY removed — OTC 2025 L3 line 1890.
# Phase 21: ZN=F (10yr T-Note) REMOVED. Valuation_OTC.txt Pine Script canonical
# source uses ZB1! (30yr T-Bond) as Symbol3. ZN is a different instrument and
# was never in the Pine Script defaults. Equities = ZB (30yr) + GC only.
# Full-corpus indicator audit (2026-07): forex and crypto reverted from
# DXY-only to the standard 3-ref set (Bonds + Gold + DXY) -- see run_scanner.py
# VALUATION_REFS for the full evidence citation (Ch.167 CHF/GBP live 3-ref
# sighting; Ch082/102/119/126/130/135/142/151 BTC 3-ref sightings).
VALUATION_REFS = {
    "forex":             ["DX-Y.NYB", "ZB=F", "GC=F"],
    "equity_indices":    ["DX-Y.NYB", "ZB=F", "GC=F"],   # Phase 21: ZN removed
    "equities":          ["ZB=F", "GC=F"],                  # Phase 36 multi-agent consensus: Ch173 + Phase 32 rulebooks agree stocks use Bonds + Gold, DXY OFF.
    "commodities":       ["DX-Y.NYB", "GC=F", "ZB=F"],
    "soft_commodities":  ["DX-Y.NYB", "GC=F", "ZB=F"],
    "precious_metals":   ["DX-Y.NYB", "GC=F", "ZB=F"],
    "energies":          ["DX-Y.NYB", "GC=F", "ZB=F"],
    "interest_rates":    ["^TNX"],
    "crypto":            ["DX-Y.NYB", "ZB=F", "GC=F"],
}
VALUATION_REFS_PER_SYMBOL = {
    # Phase 41 chunk 3 P1 fix: Platinum and Palladium use 3 refs (@US+@GC+$DXY).
    # CW35 Aug 2023 + FT Signals Mar 2023 frames confirm both @PL and @PA use
    # bonds + gold + DXY -- not DXY+Gold only as previously documented.
    "PL=F": ["ZB=F", "GC=F", "DX-Y.NYB"],   # Platinum: bonds + gold + DXY
    "PA=F": ["ZB=F", "GC=F", "DX-Y.NYB"],   # Palladium: bonds + gold + DXY
    # Phase 41 REVERT: Phase 33 Crude-Oil-Gold-only reverted; chunk 2 frames show
    # standard commodity refs (DXY+GC+ZB).
}

# Phase 15: Equity index constituent stocks — must stay in sync with
# EQUITY_INDEX_CONSTITUENT_STOCKS in run_scanner.py and
# EQUITY_INDEX_CONSTITUENTS in BP_rules_engine.py.
EQUITY_INDEX_CONSTITUENT_STOCKS = {
    "NQ=F": ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "NFLX", "TSLA"],
    "ES=F": ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL"],
    "YM=F": ["MSFT", "UNH", "GS", "HD", "CAT", "AAPL"],
}

STRATEGY_TIMEFRAMES = {
    "monthly":  {"htf": "1mo", "ltf": "1wk"},
    "weekly":   {"htf": "1wk", "ltf": "1d"},
    "daily":    {"htf": "1d",  "ltf": "60m"},
    "intraday": {"htf": "60m", "ltf": "15m"},
}

# Configure logging -- keep it terse so the diff matters more than the noise.
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("goldtest")
logger.setLevel(logging.INFO)


# ============================================================
# Historical snapshot: fetch data with no lookahead
# ============================================================

def fetch_historical_snapshot(
    fetcher: DataFetcher,
    symbol: str,
    htf: str,
    ltf: str,
    call_date: datetime,
) -> Dict[str, "pd.DataFrame"]:
    """
    Fetch OHLCV ending the day BEFORE call_date so the system sees only
    data that was available when Bernd made the call. We fetch a wide
    window and slice -- yfinance honours start/end on most intervals.
    """
    import pandas as pd

    end = call_date.strftime("%Y-%m-%d")
    # 10 years back is enough for monthly / weekly seasonality + COT context
    start = (call_date - timedelta(days=365 * 10)).strftime("%Y-%m-%d")

    today = datetime.now()
    out: Dict[str, pd.DataFrame] = {}
    for tf in (htf, ltf):
        # Hourly intervals only have 730 days of history on yfinance, so
        # for intraday TFs we shorten the window.
        if tf in ("60m", "15m", "30m", "5m", "1m"):
            # Skip intraday fetch entirely for cases older than 730 days from today.
            # yfinance returns an error or hangs on such requests; and the bias_only
            # (Stage-1) path only uses HTF data anyway so nothing is lost.
            if (today - call_date).days > 729:
                continue
            tf_start = (call_date - timedelta(days=720)).strftime("%Y-%m-%d")
        else:
            tf_start = start

        df = fetcher.fetch_ohlcv(symbol, interval=tf, period="", start=tf_start, end=end)
        if df.empty:
            continue
        # Belt-and-braces: even if yfinance honoured end=, slice manually.
        # yfinance returns tz-aware timestamps (America/New_York); strip tz
        # to compare cleanly with the tz-naive call_date.
        ts = pd.to_datetime(df["timestamp"])
        if hasattr(ts.dt, "tz") and ts.dt.tz is not None:
            ts = ts.dt.tz_localize(None)
        df = df[ts.values < pd.Timestamp(call_date)].copy()
        if not df.empty:
            out[tf] = df
    return out


def slice_cot_to_date(cot_df: "pd.DataFrame", call_date: datetime) -> "pd.DataFrame":
    """COT publishes weekly with a 3-day reporting lag. We use the most recent
    report whose date is <= call_date so the harness only sees what Bernd saw."""
    if cot_df is None or cot_df.empty:
        return cot_df
    # cot_df is indexed by report_date (weekly Tuesdays / Fridays).
    # Normalise both sides to tz-naive Timestamps to avoid comparison errors.
    import pandas as pd
    idx = cot_df.index
    if hasattr(idx, "tz") and idx.tz is not None:
        idx = idx.tz_localize(None)
    cutoff = pd.Timestamp(call_date)
    return cot_df.loc[idx <= cutoff].copy()


def fetch_valuation_refs_at_date(
    fetcher: DataFetcher,
    asset_class: str,
    symbol: str,
    htf: str,
    call_date: datetime,
) -> Dict[str, "pd.DataFrame"]:
    """Fetch each valuation reference symbol at the historical date.

    CRITICAL: refs MUST be fetched at the same timeframe as the price_df fed
    to Valuation.calculate (which is htf_df inside _analyze_fundamentals).
    Using a different interval makes the index intersection too small for
    ROC(13) to produce any valuation rows -- the indicator silently returns
    'neutral' for every symbol.
    """
    import pandas as pd

    ref_symbols = VALUATION_REFS_PER_SYMBOL.get(symbol) or VALUATION_REFS.get(asset_class, ["DX-Y.NYB"])

    end = call_date.strftime("%Y-%m-%d")
    # Match the look-back window to the timeframe so we have enough bars for ROC.
    if htf in ("60m", "15m", "30m"):
        start = (call_date - timedelta(days=720)).strftime("%Y-%m-%d")
    elif htf == "1d":
        start = (call_date - timedelta(days=365 * 5)).strftime("%Y-%m-%d")
    else:  # 1wk / 1mo
        start = (call_date - timedelta(days=365 * 10)).strftime("%Y-%m-%d")

    refs: Dict[str, pd.DataFrame] = {}
    for ref in ref_symbols:
        df = fetcher.fetch_ohlcv(ref, interval=htf, period="", start=start, end=end)
        if not df.empty:
            ts = pd.to_datetime(df["timestamp"])
            if hasattr(ts.dt, "tz") and ts.dt.tz is not None:
                ts = ts.dt.tz_localize(None)
            df = df[ts.values < pd.Timestamp(call_date)].copy()
            if not df.empty:
                refs[ref] = df
    return refs


def fetch_constituent_dfs_at_date(
    fetcher: "DataFetcher",
    symbol: str,
    htf: str,
    call_date: datetime,
) -> Dict[str, "pd.DataFrame"]:
    """Fetch constituent stock OHLCV for equity indices, pinned to call_date.

    Phase 15: Used in the bias_only path so constituent Valuation is applied
    during historical goldtest replay just as it is in live scanning.
    Returns empty dict for non-equity-index symbols or when data unavailable.
    """
    import pandas as pd

    if symbol not in EQUITY_INDEX_CONSTITUENT_STOCKS:
        return {}

    stocks = EQUITY_INDEX_CONSTITUENT_STOCKS[symbol]
    end = call_date.strftime("%Y-%m-%d")
    if htf in ("60m", "15m", "30m"):
        start = (call_date - timedelta(days=720)).strftime("%Y-%m-%d")
    elif htf == "1d":
        start = (call_date - timedelta(days=365 * 5)).strftime("%Y-%m-%d")
    else:  # 1wk / 1mo
        start = (call_date - timedelta(days=365 * 10)).strftime("%Y-%m-%d")

    result: Dict[str, pd.DataFrame] = {}
    for ticker in stocks:
        df = fetcher.fetch_ohlcv(ticker, interval=htf, period="", start=start, end=end)
        if not df.empty:
            ts = pd.to_datetime(df["timestamp"])
            if hasattr(ts.dt, "tz") and ts.dt.tz is not None:
                ts = ts.dt.tz_localize(None)
            df = df[ts.values < pd.Timestamp(call_date)].copy()
            if not df.empty:
                result[ticker] = df
    return result


# ============================================================
# Comparison: judge how well system matches Bernd
# ============================================================

def normalize_bias(b: Optional[str]) -> str:
    if b is None:
        return "neutral"
    b = b.lower()
    if b in ("long", "bull", "bullish", "buy"):
        return "long"
    if b in ("short", "bear", "bearish", "sell"):
        return "short"
    return "neutral"


def compare_call(bernd: Dict, system: Optional[Dict]) -> Dict:
    """Return a per-field comparison verdict."""
    verdict: Dict = {
        "bias_match":      None,    # full-signal direction match
        "bias_only_match": None,    # directional analysis match (zone-arrival agnostic)
        "zone_match":      None,
        "entry_close":     None,
        "stop_close":      None,
        "target_close":    None,
    }

    bernd_bias  = normalize_bias(bernd.get("bias"))
    system_bias = normalize_bias((system or {}).get("direction"))
    verdict["bias_match"] = (bernd_bias == system_bias)
    bias_only = normalize_bias((system or {}).get("bias_only"))
    verdict["bias_only_match"] = (bernd_bias == bias_only)

    if not system:
        return verdict

    # Zone level: if Bernd quoted a level, check it's within the system's zone.
    if bernd.get("zone_level") is not None:
        zone_low  = min(system.get("zone_proximal", 0), system.get("zone_distal", 0))
        zone_high = max(system.get("zone_proximal", 0), system.get("zone_distal", 0))
        verdict["zone_match"] = zone_low <= float(bernd["zone_level"]) <= zone_high

    def _close(a, b, pct=0.01):
        if a is None or b is None:
            return None
        try:
            return abs(float(a) - float(b)) / abs(float(b)) <= pct
        except (TypeError, ValueError, ZeroDivisionError):
            return None

    verdict["entry_close"]  = _close(bernd.get("entry"),  system.get("entry_price"))
    verdict["stop_close"]   = _close(bernd.get("stop"),   system.get("stop_price"))
    verdict["target_close"] = _close(
        bernd.get("target"),
        (system.get("targets") or [None])[0] if system.get("targets") else None,
    )

    return verdict


# ============================================================
# Main per-case run
# ============================================================

def run_case(case: Dict, config: Dict) -> Dict:
    """Replay one case end-to-end and return a result row."""
    symbol     = case["symbol"]
    call_date  = datetime.strptime(case["call_date"], "%Y-%m-%d")
    bernd_bias = case.get("bias")
    asset_class = case.get("asset_class") or ASSET_CLASS_BY_SYMBOL.get(symbol, "commodities")

    # Pick strategy from case or default to monthly (these are monthly roadmap calls)
    strategy = case.get("strategy", "monthly")
    tf = STRATEGY_TIMEFRAMES.get(strategy, STRATEGY_TIMEFRAMES["monthly"])
    htf, ltf = tf["htf"], tf["ltf"]

    fetcher = DataFetcher()
    engine  = RulesEngine(config)

    result = {
        "case_index":   case.get("_index"),
        "symbol":       symbol,
        "display_name": case.get("display_name", symbol),
        "asset_class":  asset_class,
        "call_date":    case["call_date"],
        "strategy":     strategy,
        "htf":          htf,
        "ltf":          ltf,
        "bernd": {
            "bias":         bernd_bias,
            "zone_level":   case.get("zone_level"),
            "entry":        case.get("entry"),
            "stop":         case.get("stop"),
            "target":       case.get("target"),
            "reasoning":    case.get("reasoning"),
            "source_quote": case.get("source_quote"),
        },
        "system":  None,
        "verdict": None,
        "error":   None,
    }

    try:
        ohlcv = fetch_historical_snapshot(fetcher, symbol, htf, ltf, call_date)
        if htf not in ohlcv or ltf not in ohlcv:
            result["error"] = f"insufficient OHLCV ({list(ohlcv.keys())})"
            return result

        cot_lookup = case.get("cot_symbol", symbol)
        cftc_code = get_cftc_code(cot_lookup)
        cot_df    = slice_cot_to_date(fetcher.fetch_cot_data(cftc_code), call_date)

        opposing_cot_df = None
        if asset_class == "forex":
            opposing_cot_df = slice_cot_to_date(
                fetcher.fetch_cot_data(get_cftc_code("DX=F")), call_date,
            )

        val_refs = fetch_valuation_refs_at_date(fetcher, asset_class, symbol, htf, call_date)

        # Phase 15: For equity indices, fetch constituent stock prices at date
        # so the rules engine can compute per-stock Valuation instead of
        # reading the index directly (Bernd: "if AAPL + MSFT undervalued → buy NQ").
        constituent_dfs = fetch_constituent_dfs_at_date(fetcher, symbol, htf, call_date)

        seasonal_df = fetcher.fetch_ohlcv(
            symbol, interval="1d", period="",
            start=(call_date - timedelta(days=365 * 15)).strftime("%Y-%m-%d"),
            end=call_date.strftime("%Y-%m-%d"),
        )

        signal = engine.run_seven_step_process(
            symbol=symbol,
            ohlcv_data=ohlcv,
            cot_df=cot_df,
            valuation_refs=val_refs,
            seasonal_df=seasonal_df,
            htf=htf,
            ltf=ltf,
            income_strategy=strategy,
            asset_class=asset_class,
            opposing_cot_df=opposing_cot_df,
            constituent_dfs=constituent_dfs if constituent_dfs else None,
        )

        # ALSO compute the directional bias separately. Bernd's monthly
        # roadmap calls express directional thesis ("buy AAPL because
        # undervalued") -- they don't imply a tradeable setup right now.
        # The engine refuses signals when price hasn't arrived at a zone
        # (rule #4: never anticipate). To audit our directional accuracy
        # vs Bernd, we call the engine's analysis primitives directly
        # and run the consensus check, decoupled from zone-arrival.
        bias_only = "neutral"
        bias_components = {}
        try:
            htf_df = ohlcv.get(htf)
            if htf_df is not None and not htf_df.empty:
                htf_zones = engine.zone_detector.detect_zones(htf_df, symbol, htf)
                # Pass symbol and asset_class so ATH momentum fix and USD-base
                # inversion fire in the bias_only path (Phase 26 fix)
                ht_bias = engine._analyze_htf(
                    htf_df, htf_zones, htf=htf,
                    symbol=symbol, asset_class=asset_class,
                )
                fund_bias = engine._analyze_fundamentals(
                    cot_df, htf_df, val_refs, seasonal_df, asset_class,
                    opposing_cot_df=opposing_cot_df, symbol=symbol,
                    constituent_dfs=constituent_dfs if constituent_dfs else None,
                )
                biases = {
                    'location':    ht_bias.get('location'),
                    'trend':       ht_bias.get('trend'),
                    'cot':         fund_bias.get('cot'),
                    'cot_strength': fund_bias.get('cot_strength', 'normal'),
                    'valuation':   fund_bias.get('valuation'),
                    'seasonality': fund_bias.get('seasonality'),
                    'constituent': fund_bias.get('constituent', 'neutral'),  # Phase 24
                }
                # Phase 23 patch: wire up T4 (zone-arrival) + T1 (date override)
                # so the new _bias_consensus signature is fully exercised on the
                # historical case date instead of date.today().
                _at_zone = False
                _zone_composite = 0.0
                if htf_zones:
                    _ranked = engine.zone_detector.rank_zones(htf_zones, min_score=0.0)
                    if _ranked:
                        _at_zone = True
                        _zone_composite = float(_ranked[0].get('composite_score', 0.0))
                _today_override = call_date.date() if hasattr(call_date, 'date') else call_date
                consensus = engine._bias_consensus(
                    biases, strategy,
                    asset_class=asset_class,
                    at_zone=_at_zone,
                    zone_composite=_zone_composite,
                    today_override=_today_override,
                    symbol=symbol,
                )
                # Map 'hold' -> 'neutral' / 'bullish' -> 'long' / 'bearish' -> 'short'
                bias_only = {
                    'bullish': 'long', 'bearish': 'short',
                    'hold': 'neutral', 'neutral': 'neutral',
                }.get(consensus, 'neutral')
                bias_components = biases
        except Exception:
            pass

        if signal:
            result["system"] = {
                "direction":      signal.get("direction"),
                "entry_price":    signal.get("entry_price"),
                "stop_price":     signal.get("stop_price"),
                "targets":        signal.get("targets"),
                "zone_proximal":  signal.get("zone", {}).get("proximal"),
                "zone_distal":    signal.get("zone", {}).get("distal"),
                "composite":      signal.get("qualifier_scores", {}).get("composite"),
                "trade_context":  signal.get("trade_context"),
                "reasoning":      signal.get("reasoning"),
                "bias_only":      bias_only,
                "bias_components": bias_components,
            }
        else:
            result["system"] = {
                "direction":          "neutral",
                "no_signal_reason":   "no qualified zone or bias mismatch (bias_only shows directional analysis)",
                "bias_only":          bias_only,
                "bias_components":    bias_components,
            }

        result["verdict"] = compare_call(case, result["system"])

    except Exception as exc:
        logger.error(f"[{symbol} @ {case['call_date']}] {traceback.format_exc()}")
        result["error"] = str(exc)

    return result


# ============================================================
# Driver
# ============================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", default="original", help="Engine to use: original or deepseek")
    parser.add_argument("--case", type=int, default=None, help="Run only case N (1-indexed)")
    parser.add_argument("--asset", default=None, help="Filter by asset class (equities, forex, ...)")
    parser.add_argument("--cases-file", default=str(SCRIPT_DIR / "gold_cases.yaml"))
    parser.add_argument("--output", default=str(SCRIPT_DIR / "gold_results.json"))
    parser.add_argument("--config", default=str(PROJECT_DIR / "BP_config.yaml"))
    args = parser.parse_args()

    cases_path = Path(args.cases_file)
    if not cases_path.exists():
        print(f"ERROR: cases file not found: {cases_path}", file=sys.stderr)
        sys.exit(1)

    with open(cases_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or []
    if not isinstance(raw, list):
        # Allow {"cases": [...]} style too
        raw = raw.get("cases", [])

    cases = [{**c, "_index": i + 1} for i, c in enumerate(raw)]

    if args.case is not None:
        cases = [c for c in cases if c["_index"] == args.case]
    if args.asset:
        cases = [c for c in cases if c.get("asset_class") == args.asset
                 or ASSET_CLASS_BY_SYMBOL.get(c.get("symbol", ""), "") == args.asset]

    if not cases:
        print("No cases match the filter.", file=sys.stderr)
        sys.exit(1)

    with open(args.config, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    print(f"\nRunning {len(cases)} gold case(s)...\n")

    results: List[Dict] = []
    for c in cases:
        label = f"#{c['_index']:02d} {c['symbol']:<10} {c['call_date']}"
        print(f"  {label} ...", end="", flush=True)
        r = run_case(c, config)
        results.append(r)
        if r["error"]:
            print(f"  ERROR: {r['error']}")
            continue
        v = r["verdict"] or {}
        flag = "OK " if v.get("bias_match") else "DIVERGE"
        sys_bias = (r["system"] or {}).get("direction", "?")
        print(f"  {flag}  Bernd={c.get('bias','?'):<7}  System={sys_bias:<7}")

    # ---- Save JSON ----
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump({"generated_at": datetime.now().isoformat(), "results": results}, f, indent=2, default=str)
    print(f"\nResults written to {args.output}")

    # ---- Summary ----
    total = len(results)
    bias_match      = sum(1 for r in results if (r.get("verdict") or {}).get("bias_match"))
    bias_only_match = sum(1 for r in results if (r.get("verdict") or {}).get("bias_only_match"))
    errors = sum(1 for r in results if r.get("error"))
    valid  = total - errors
    print(f"\n  Stage-2 full-signal:  {bias_match}/{total}  ({bias_match/total*100:.1f}%)")
    print(f"  Stage-1 bias_only:    {bias_only_match}/{total}  ({bias_only_match/valid*100:.1f}% of {valid} valid)")
    print(f"  Errors:               {errors}/{total}")
    print(f"\n  View diff: open {SCRIPT_DIR / 'gold_diff.html'}")


if __name__ == "__main__":
    main()
