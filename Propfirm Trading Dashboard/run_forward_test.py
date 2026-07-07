"""
Blueprint Trading System — Weekly Forward Test
===============================================
Replays the weekly scanner week-by-week from 2026-03-01 to 2026-05-06,
records every signal that fires, then checks if price hit T1 (win) or
the stop (loss) first.

Usage:
    python run_forward_test.py
    python run_forward_test.py --strategy weekly    # default
    python run_forward_test.py --strategy daily
    python run_forward_test.py --symbols GC=F CL=F  # subset of watchlist
    python run_forward_test.py --start 2026-03-01 --end 2026-05-06
"""

import sys
import os
import argparse
import logging
import yaml
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta, date
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Path setup — same pattern as run_scanner.py
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from BP_data_fetcher import DataFetcher, get_cftc_code
from BP_rules_engine import RulesEngine

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.WARNING,          # suppress verbose engine/indicator logs
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("forward_test")

# Make the engine quiet by default — only show warnings
for noisy in ("scanner", "BP_rules_engine", "BP_indicators",
              "BP_data_fetcher", "BP_zone_detector", "BP_patterns",
              "BP_paper_trader"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Valuation refs — copied verbatim from run_scanner.py so this script is
# self-contained and stays in sync with the production logic.
# ---------------------------------------------------------------------------
VALUATION_REFS: Dict[str, List[str]] = {
    "forex":            ["DX-Y.NYB"],
    "equity_indices":   ["DX-Y.NYB", "ZB=F", "GC=F"],
    "equities":         ["ZB=F", "GC=F"],
    "commodities":      ["DX-Y.NYB", "GC=F", "ZB=F"],
    "soft_commodities": ["DX-Y.NYB", "GC=F", "ZB=F"],
    "precious_metals":  ["DX-Y.NYB", "GC=F", "ZB=F"],
    "energies":         ["DX-Y.NYB", "GC=F", "ZB=F"],
    "interest_rates":   ["^TNX"],
    "crypto":           ["DX-Y.NYB"],
    "nat_gas":          ["DX-Y.NYB", "GC=F", "ZB=F"],
}
VALUATION_REFS_PER_SYMBOL: Dict[str, List[str]] = {
    "PL=F": ["DX-Y.NYB", "GC=F"],
}

EQUITY_INDEX_CONSTITUENT_STOCKS: Dict[str, List[str]] = {
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

# ---------------------------------------------------------------------------
# ANSI colours
# ---------------------------------------------------------------------------
RESET  = "\033[0m"
BOLD   = "\033[1m"
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
DIM    = "\033[90m"

if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleMode(
            ctypes.windll.kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mondays_between(start: date, end: date) -> List[date]:
    """Return every Monday (or nearest trading day proxy) from start to end."""
    days = []
    d = start
    # Advance to first Monday
    while d.weekday() != 0:
        d += timedelta(days=1)
    while d <= end:
        days.append(d)
        d += timedelta(weeks=1)
    return days


def _truncate_df(df: pd.DataFrame, cutoff: date) -> pd.DataFrame:
    """
    Return rows of df whose 'timestamp' column is <= cutoff date.
    Handles both timezone-aware and naive timestamps.
    """
    if df.empty or "timestamp" not in df.columns:
        return df
    ts = df["timestamp"]
    # Normalise to date
    if hasattr(ts.iloc[0], "date"):
        mask = ts.apply(lambda x: x.date() if hasattr(x, "date") else x) <= cutoff
    else:
        # Already date or string
        mask = pd.to_datetime(ts).dt.date <= cutoff
    return df[mask].reset_index(drop=True)


def _outcome(
    direction: str,
    entry: float,
    stop: float,
    t1: float,
    future_df: pd.DataFrame,
) -> Tuple[str, float]:
    """
    Walk through future weekly OHLCV bars (each bar = one week after signal).
    Return ('WIN', +1) / ('LOSS', -1) / ('OPEN', 0).

    Uses bar High/Low to detect which level is touched first within the same bar,
    then subsequent bars until one is hit or data runs out.
    """
    if future_df.empty:
        return "OPEN", 0.0

    for _, bar in future_df.iterrows():
        hi = bar["high"]
        lo = bar["low"]
        if direction == "long":
            t1_hit  = hi >= t1
            stop_hit = lo <= stop
        else:
            t1_hit  = lo <= t1
            stop_hit = hi >= stop

        if t1_hit and stop_hit:
            # Both on same bar: conservative — count as loss (worst case)
            return "LOSS", -1.0
        if t1_hit:
            return "WIN", 1.0
        if stop_hit:
            return "LOSS", -1.0

    return "OPEN", 0.0


# ---------------------------------------------------------------------------
# Core: scan one symbol at one cutoff date
# ---------------------------------------------------------------------------

def scan_symbol_at_cutoff(
    symbol_info: Dict,
    fetcher: DataFetcher,
    engine: RulesEngine,
    htf: str,
    ltf: str,
    strategy: str,
    full_htf_df: pd.DataFrame,
    full_ltf_df: pd.DataFrame,
    full_val_refs: Dict[str, pd.DataFrame],
    full_cot_df: Optional[pd.DataFrame],
    full_seasonal_df: pd.DataFrame,
    full_constituent_dfs: Dict[str, pd.DataFrame],
    cutoff: date,
    opposing_cot_df: Optional[pd.DataFrame] = None,
) -> Optional[Dict]:
    """
    Truncate all data to `cutoff`, then run the seven-step process.
    Returns the signal dict (with `entry_price`, `stop_price`, `targets`)
    or None if no signal fired.
    """
    sym = symbol_info["symbol"]
    ac  = symbol_info["asset_class"]

    # Slice every series to the cutoff
    htf_df  = _truncate_df(full_htf_df,  cutoff)
    ltf_df  = _truncate_df(full_ltf_df,  cutoff)
    cot_df  = full_cot_df  # COT is weekly — already historical
    seas_df = _truncate_df(full_seasonal_df, cutoff)

    val_refs = {k: _truncate_df(v, cutoff) for k, v in full_val_refs.items()
                if not v.empty}

    constituent_dfs = {k: _truncate_df(v, cutoff)
                       for k, v in full_constituent_dfs.items()
                       if not v.empty}

    if htf_df.empty or len(htf_df) < 20:
        return None
    if ltf_df.empty or len(ltf_df) < 20:
        return None

    ohlcv_data = {htf: htf_df, ltf: ltf_df}

    try:
        signal = engine.run_seven_step_process(
            symbol=sym,
            ohlcv_data=ohlcv_data,
            cot_df=cot_df,
            valuation_refs=val_refs,
            seasonal_df=seas_df,
            htf=htf,
            ltf=ltf,
            income_strategy=strategy,
            asset_class=ac,
            opposing_cot_df=opposing_cot_df,
            constituent_dfs=constituent_dfs if constituent_dfs else None,
        )
        return signal
    except Exception as exc:
        logger.warning(f"[{sym}] scan error at {cutoff}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Main forward-test runner
# ---------------------------------------------------------------------------

def run_forward_test(
    watchlist: List[Dict],
    config: Dict,
    strategy: str = "weekly",
    start_date: date = date(2026, 3, 1),
    end_date: date = date(2026, 5, 6),
) -> List[Dict]:
    """
    For each symbol in the watchlist, for each weekly date from start→end:
      1. Truncate data to that date.
      2. Run the scanner.
      3. If signal fires, record it.
      4. Use subsequent bars to determine outcome.
    Returns list of trade record dicts.
    """
    tf = STRATEGY_TIMEFRAMES.get(strategy, STRATEGY_TIMEFRAMES["weekly"])
    htf, ltf = tf["htf"], tf["ltf"]

    # Reference period for fetching — 5y for weekly gives 260 HTF bars,
    # enough for zone detection to find the same zones as the live scanner.
    # (2y was too short — missed older zones that live scanner finds.)
    if htf in ("1mo", "1wk"):
        _ref_period = "5y"
    elif htf == "1d":
        _ref_period = "2y"
    else:
        _ref_period = "729d"

    fetcher = DataFetcher()
    engine  = RulesEngine(config)

    scan_dates = _mondays_between(start_date, end_date)
    print(f"\n{BOLD}{CYAN}{'='*65}{RESET}")
    print(f"{BOLD}{CYAN}  Blueprint Forward Test — {strategy.upper()} strategy{RESET}")
    print(f"{BOLD}{CYAN}  Period : {start_date} to {end_date}  ({len(scan_dates)} weekly bars){RESET}")
    print(f"{BOLD}{CYAN}  Symbols: {len(watchlist)}{RESET}")
    print(f"{BOLD}{CYAN}  HTF={htf}  LTF={ltf}{RESET}")
    print(f"{BOLD}{CYAN}{'='*65}{RESET}\n")

    all_trades: List[Dict] = []

    for idx, sym_info in enumerate(watchlist, 1):
        sym  = sym_info["symbol"]
        name = sym_info.get("name", sym)
        ac   = sym_info["asset_class"]

        print(f"{DIM}[{idx:>3}/{len(watchlist)}] Fetching {sym} ({name})...{RESET}",
              end=" ", flush=True)

        # ---- Fetch ALL data once per symbol ----
        try:
            full_htf_df  = fetcher.fetch_ohlcv(sym, interval=htf,  period=_ref_period)
            full_ltf_df  = fetcher.fetch_ohlcv(sym, interval=ltf,  period=_ref_period)
        except Exception as exc:
            print(f"{YELLOW}SKIP (fetch error: {exc}){RESET}")
            continue

        if full_htf_df.empty or full_ltf_df.empty:
            print(f"{YELLOW}SKIP (no price data){RESET}")
            continue

        # COT
        cot_lookup_sym = sym_info.get("cot_symbol", sym)
        cftc_code = get_cftc_code(cot_lookup_sym)
        full_cot_df = fetcher.fetch_cot_data(cftc_code)

        # Opposing COT for forex
        opposing_cot_df = None
        if ac == "forex":
            opposing_cot_df = fetcher.fetch_cot_data(get_cftc_code("DX=F"))

        # Valuation refs
        full_val_refs: Dict[str, pd.DataFrame] = {}
        ref_syms = VALUATION_REFS_PER_SYMBOL.get(sym) or VALUATION_REFS.get(ac, ["DX-Y.NYB"])
        for ref_sym in ref_syms:
            # refs are relative/ROC series — ETF proxy fallback is fine (unlike
            # the tradable, whose absolute levels must not be proxied).
            ref_df = fetcher.fetch_ohlcv(ref_sym, interval=htf, period=_ref_period, allow_proxy=True)
            if not ref_df.empty:
                full_val_refs[ref_sym] = ref_df

        # Constituent stocks (equity indices only)
        full_constituent_dfs: Dict[str, pd.DataFrame] = {}
        if ac == "equity_indices" and sym in EQUITY_INDEX_CONSTITUENT_STOCKS:
            for stock in EQUITY_INDEX_CONSTITUENT_STOCKS[sym]:
                s_df = fetcher.fetch_ohlcv(stock, interval=htf, period=_ref_period, allow_proxy=True)
                if not s_df.empty:
                    full_constituent_dfs[stock] = s_df

        # Seasonality reference (full history, not truncated — only close prices used)
        full_seasonal_df = fetcher.fetch_seasonality_reference(sym, lookback_years=5)

        print(f"{DIM}OK{RESET}")

        # ---- Walk each weekly scan date ----
        # Re-entry suppression: track which zone_ids have been stopped out.
        # Key = zone_id → scan_date when it was stopped out.
        # After a stop-out, that zone is suppressed for the rest of the test period.
        # After a win (T1 hit), the zone is also consumed (no more entries).
        consumed_zone_ids: Dict[str, str] = {}  # zone_id → outcome date

        # Also track the currently "open" zone_id to avoid same zone firing
        # multiple weeks before its outcome is determined.
        open_zone_ids: Dict[str, Dict] = {}  # zone_id → trade_rec (pending outcome)

        for scan_date in scan_dates:
            cutoff_str = scan_date.isoformat()

            signal = scan_symbol_at_cutoff(
                symbol_info=sym_info,
                fetcher=fetcher,
                engine=engine,
                htf=htf,
                ltf=ltf,
                strategy=strategy,
                full_htf_df=full_htf_df,
                full_ltf_df=full_ltf_df,
                full_val_refs=full_val_refs,
                full_cot_df=full_cot_df,
                full_seasonal_df=full_seasonal_df,
                full_constituent_dfs=full_constituent_dfs,
                cutoff=scan_date,
                opposing_cot_df=opposing_cot_df,
            )

            if signal is None:
                continue

            direction = signal.get("direction", "neutral")
            if direction == "neutral":
                continue

            entry = signal.get("entry_price", 0.0)
            stop  = signal.get("stop_price",  0.0)
            targets = signal.get("targets", [])
            t1 = targets[0] if targets else None

            if entry == 0.0 or stop == 0.0 or t1 is None:
                continue

            # Zone-based re-entry suppression (uses stable zone_id from MD5 hash).
            # A zone that has been stopped out or won is never re-entered.
            zone_id = signal.get("zone_id", "")
            if zone_id and zone_id in consumed_zone_ids:
                continue  # This zone already played out — skip
            if zone_id and zone_id in open_zone_ids:
                continue  # This zone is already open / pending outcome — skip

            # ---- Outcome: look at HTF bars AFTER the signal date ----
            after_mask = full_htf_df["timestamp"].apply(
                lambda x: (x.date() if hasattr(x, "date") else pd.to_datetime(x).date())
                          > scan_date
            )
            future_df = full_htf_df[after_mask].reset_index(drop=True)

            outcome, r = _outcome(direction, entry, stop, t1, future_df)

            rr_ratio = abs(t1 - entry) / abs(entry - stop) if abs(entry - stop) > 0 else 0

            trade_rec = {
                "date":      cutoff_str,
                "symbol":    sym,
                "name":      name[:12],
                "direction": direction,
                "entry":     entry,
                "stop":      stop,
                "t1":        t1,
                "rr":        round(rr_ratio, 2),
                "outcome":   outcome,
                "r":         r,
                "trade_context": signal.get("trade_context", "standard"),
                "composite": round(signal.get("qualifier_scores", {}).get("composite", 0), 1),
                "zone_id":   zone_id,
            }
            all_trades.append(trade_rec)

            # Zone memory: if outcome is resolved (WIN or LOSS), consume the zone.
            # If still OPEN (not enough future bars), track as open so it isn't
            # re-fired next week.
            if outcome in ("WIN", "LOSS"):
                if zone_id:
                    consumed_zone_ids[zone_id] = cutoff_str
            else:  # OPEN — pending outcome, suppress re-entry
                if zone_id:
                    open_zone_ids[zone_id] = trade_rec

    return all_trades


# ---------------------------------------------------------------------------
# Pretty-print results
# ---------------------------------------------------------------------------

def print_results(trades: List[Dict], start_date: date, end_date: date) -> None:
    if not trades:
        print(f"\n{YELLOW}No signals fired in the test period.{RESET}\n")
        return

    # Sort by date then symbol
    trades.sort(key=lambda r: (r["date"], r["symbol"]))

    col_w = {
        "date": 11, "symbol": 12, "dir": 6, "entry": 10,
        "stop": 10, "t1": 10, "rr": 5, "outcome": 7, "r": 7, "ctx": 12,
    }

    hdr = (
        f"{'DATE':<{col_w['date']}}"
        f"{'SYMBOL':<{col_w['symbol']}}"
        f"{'DIR':<{col_w['dir']}}"
        f"{'ENTRY':>{col_w['entry']}}"
        f"{'STOP':>{col_w['stop']}}"
        f"{'T1':>{col_w['t1']}}"
        f"{'R:R':>{col_w['rr']}}"
        f"{'OUTCOME':<{col_w['outcome']}}"
        f"{'R':>{col_w['r']}}"
        f"  {'CONTEXT':<{col_w['ctx']}}"
    )
    sep = "-" * len(hdr)

    print(f"\n{BOLD}=== FORWARD TEST {start_date} to {end_date} ==={RESET}")
    print(BOLD + hdr + RESET)
    print(sep)

    wins = losses = opens = 0
    total_r = 0.0

    for t in trades:
        if t["outcome"] == "WIN":
            colour = GREEN
            wins += 1
        elif t["outcome"] == "LOSS":
            colour = RED
            losses += 1
        else:
            colour = YELLOW
            opens += 1
        total_r += t["r"]

        r_str = f"+{t['r']:.0f}R" if t["r"] > 0 else (f"-{abs(t['r']):.0f}R" if t["r"] < 0 else "open")
        row = (
            f"{t['date']:<{col_w['date']}}"
            f"{t['symbol']:<{col_w['symbol']}}"
            f"{t['direction']:<{col_w['dir']}}"
            f"{t['entry']:>{col_w['entry']}.5f}"
            f"{t['stop']:>{col_w['stop']}.5f}"
            f"{t['t1']:>{col_w['t1']}.5f}"
            f"{t['rr']:>{col_w['rr']}.1f}"
            f"  {t['outcome']:<{col_w['outcome']-2}}"
            f"{r_str:>{col_w['r']}}"
            f"  {t['trade_context']}"
        )
        print(colour + row + RESET)

    print(sep)

    total   = len(trades)
    closed  = wins + losses
    wr      = (wins / closed * 100) if closed > 0 else 0.0
    avg_r   = total_r / closed if closed > 0 else 0.0

    print(
        f"\n{BOLD}"
        f"Total signals : {total}  |  "
        f"Wins: {GREEN}{wins}{RESET}{BOLD}  |  "
        f"Losses: {RED}{losses}{RESET}{BOLD}  |  "
        f"Open: {YELLOW}{opens}{RESET}{BOLD}  |  "
        f"Win rate: {wr:.1f}%  |  "
        f"Avg R (closed): {avg_r:+.2f}R"
        f"{RESET}"
    )

    # Breakdown by asset class
    from collections import defaultdict
    by_ac: Dict[str, Dict] = defaultdict(lambda: {"wins": 0, "losses": 0, "opens": 0})
    for t in trades:
        sym = t["symbol"]
        # Infer asset class from symbol patterns (approximate)
        ac = "other"
        if any(sym.endswith(x) for x in ("=F",)):
            if sym in ("GC=F", "SI=F", "HG=F", "PL=F", "PA=F"):
                ac = "precious_metals"
            elif sym in ("CL=F", "BZ=F", "NG=F", "RB=F", "HO=F"):
                ac = "energies"
            elif sym in ("ES=F", "NQ=F", "YM=F", "RTY=F"):
                ac = "equity_indices"
            elif sym in ("ZB=F", "ZN=F", "ZT=F", "ZF=F"):
                ac = "interest_rates"
            elif sym in ("6E=F", "6B=F", "6J=F", "6A=F", "6C=F", "6S=F", "6N=F"):
                ac = "forex"
            else:
                ac = "commodities"
        elif sym.endswith("=X") or sym.endswith("USD") or sym.startswith("USD"):
            ac = "forex"
        elif sym.endswith("-USD") or sym in ("BTC-USD", "ETH-USD"):
            ac = "crypto"
        elif sym.isupper() and len(sym) <= 5 and not sym.endswith("=F"):
            ac = "equities"

        _outcome_map = {"WIN": "wins", "LOSS": "losses", "OPEN": "opens"}
        outcome_key = _outcome_map.get(t["outcome"].upper(), "opens")
        by_ac[ac][outcome_key] += 1

    print(f"\n{BOLD}Breakdown by asset class:{RESET}")
    for ac_name, counts in sorted(by_ac.items()):
        w = counts["wins"]
        l = counts["losses"]
        o = counts["opens"]
        wr_ac = (w / (w + l) * 100) if (w + l) > 0 else 0
        print(f"  {ac_name:<20}  W:{w:>3}  L:{l:>3}  O:{o:>3}  WR:{wr_ac:>5.1f}%")

    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Blueprint Trading System — Weekly Forward Test"
    )
    parser.add_argument(
        "--strategy", choices=["weekly", "daily", "monthly", "intraday"],
        default="weekly", help="Income strategy to test (default: weekly)"
    )
    parser.add_argument(
        "--start", default="2026-03-01",
        help="Start date YYYY-MM-DD (default: 2026-03-01)"
    )
    parser.add_argument(
        "--end", default="2026-05-06",
        help="End date YYYY-MM-DD (default: 2026-05-06)"
    )
    parser.add_argument(
        "--symbols", nargs="*", default=None,
        help="Subset of symbols to test (default: full watchlist)"
    )
    parser.add_argument(
        "--config", default=str(SCRIPT_DIR / "BP_config.yaml"),
        help="Path to BP_config.yaml"
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Show INFO-level engine logs"
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)
        for noisy in ("scanner", "BP_rules_engine", "BP_indicators",
                      "BP_data_fetcher", "BP_zone_detector"):
            logging.getLogger(noisy).setLevel(logging.INFO)

    # Load config
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"{RED}Config not found: {config_path}{RESET}", file=sys.stderr)
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Build watchlist from config
    watchlist: List[Dict] = config.get("watchlist", [])
    if not watchlist:
        print(f"{RED}No watchlist found in config.{RESET}", file=sys.stderr)
        sys.exit(1)

    # Filter by --strategy: skip crypto on weekly (pinned to daily)
    strategy = args.strategy
    filtered_wl = []
    for entry in watchlist:
        strategies = entry.get("strategies", None)
        if strategies is not None and strategy not in strategies:
            continue
        filtered_wl.append(entry)

    # Filter by --symbols if provided
    if args.symbols:
        sym_set = set(s.upper() for s in args.symbols)
        filtered_wl = [e for e in filtered_wl
                       if e["symbol"].upper() in sym_set]
        if not filtered_wl:
            print(f"{RED}None of the requested symbols found in watchlist.{RESET}")
            sys.exit(1)

    start_date = datetime.strptime(args.start, "%Y-%m-%d").date()
    end_date   = datetime.strptime(args.end,   "%Y-%m-%d").date()

    # Run forward test
    trades = run_forward_test(
        watchlist=filtered_wl,
        config=config,
        strategy=strategy,
        start_date=start_date,
        end_date=end_date,
    )

    # Print results
    print_results(trades, start_date, end_date)


if __name__ == "__main__":
    main()
