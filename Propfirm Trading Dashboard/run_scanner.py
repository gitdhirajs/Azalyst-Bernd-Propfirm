"""
Blueprint Market Scanner -- Scans global markets through the 7-step process
and auto paper-trades valid signals.

Usage:
    python run_scanner.py            # Full scan with dashboard auto-open
    python run_scanner.py --no-open  # Scan only, skip browser launch
"""

import sys
import os
import time
import atexit
import json
import yaml
import logging
import webbrowser
import traceback
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import asdict

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

# Load DISCORD_WEBHOOK_URL / DISCORD_USER_ID from .secrets.bat when launching
# the scanner directly with `python run_scanner.py` (i.e. without going through
# scan_markets.bat). The bat file format is `set NAME=VALUE` per line; we parse
# those lines and inject any missing vars into os.environ so Discord posting
# works regardless of launch method.
def _load_secrets_from_bat() -> None:
    secrets_path = SCRIPT_DIR / ".secrets.bat"
    if not secrets_path.exists():
        return
    try:
        with open(secrets_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line.lower().startswith("set "):
                    continue
                _, _, kv = line.partition(" ")
                if "=" not in kv:
                    continue
                key, _, value = kv.partition("=")
                key, value = key.strip(), value.strip()
                if key and value and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        pass

_load_secrets_from_bat()

from BP_data_fetcher import DataFetcher, get_cftc_code
from BP_rules_engine import RulesEngine
from BP_paper_trader import PaperTrader
from BP_position_sizer import compute_lots, build_usd_quote_table

# ---------------------------------------------------------------------------
# ANSI colour helpers (Windows 10+ supports ANSI in cmd/powershell)
# ---------------------------------------------------------------------------
RESET  = "\033[0m"
BOLD   = "\033[1m"
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
MAGENTA = "\033[95m"
DIM    = "\033[90m"

# Enable ANSI escape codes on Windows
if sys.platform == "win32":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_FILE  = SCRIPT_DIR / "scanner.log"
LOCK_FILE = SCRIPT_DIR / ".scanner.lock"
# Only the shared rolling log file is set up at module level.
# The console handler (stderr) and per-strategy file handler are added
# inside main() so each run gets its own clean, non-interleaved log.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
logger = logging.getLogger("scanner")

# ---------------------------------------------------------------------------
# Process lock -- prevents multiple concurrent scanner instances from
# fighting over Yahoo Finance's rate limit and corrupting scan_results.json.
# ---------------------------------------------------------------------------

def _acquire_lock() -> bool:
    """Create a PID lock file.  Returns True on success."""
    try:
        if LOCK_FILE.exists():
            try:
                pid = int(LOCK_FILE.read_text().strip())
                # Try psutil first; fall back to file-age heuristic.
                try:
                    import psutil
                    if psutil.pid_exists(pid):
                        return False
                except ImportError:
                    age = time.time() - LOCK_FILE.stat().st_mtime
                    if age < 7200:        # < 2 hours → assume live run
                        return False
            except (ValueError, OSError):
                pass                      # unreadable lock → stale, overwrite
        LOCK_FILE.write_text(str(os.getpid()))
        return True
    except OSError:
        return False

def _release_lock():
    """Remove the lock file (only if it belongs to this process)."""
    try:
        if LOCK_FILE.exists():
            if LOCK_FILE.read_text().strip() == str(os.getpid()):
                LOCK_FILE.unlink()
    except OSError:
        pass

# ---------------------------------------------------------------------------
# Full watchlist
# ---------------------------------------------------------------------------
FULL_WATCHLIST: List[Dict] = [
    # Forex
    {"symbol": "6E=F", "name": "EUR/USD (Euro FX)",          "asset_class": "forex"},
    {"symbol": "6B=F", "name": "GBP/USD (British Pound)",    "asset_class": "forex"},
    {"symbol": "6J=F", "name": "USD/JPY (Japanese Yen)",     "asset_class": "forex"},
    {"symbol": "6A=F", "name": "AUD/USD (Australian Dollar)", "asset_class": "forex"},
    {"symbol": "6C=F", "name": "USD/CAD (Canadian Dollar)",  "asset_class": "forex"},
    {"symbol": "6S=F", "name": "USD/CHF (Swiss Franc)",      "asset_class": "forex"},
    # Precious Metals
    {"symbol": "GC=F", "name": "Gold",                       "asset_class": "precious_metals"},
    {"symbol": "SI=F", "name": "Silver",                     "asset_class": "precious_metals"},
    # Energy
    {"symbol": "CL=F", "name": "Crude Oil WTI",              "asset_class": "energies"},
    {"symbol": "NG=F", "name": "Natural Gas",                "asset_class": "energies"},
    # Equity Indices
    {"symbol": "ES=F", "name": "S&P 500 E-mini",            "asset_class": "equity_indices"},
    {"symbol": "NQ=F", "name": "Nasdaq 100 E-mini",         "asset_class": "equity_indices"},
    {"symbol": "YM=F", "name": "Dow Jones E-mini",          "asset_class": "equity_indices"},
    # Bonds / Interest Rates
    {"symbol": "ZB=F", "name": "30Y US Bond",               "asset_class": "interest_rates"},
    {"symbol": "ZN=F", "name": "10Y US Note",               "asset_class": "interest_rates"},
]

# ---------------------------------------------------------------------------
# Timeframe mapping per income strategy
# ---------------------------------------------------------------------------
STRATEGY_TIMEFRAMES = {
    "monthly": {"htf": "1mo", "ltf": "1wk"},
    "weekly":  {"htf": "1wk", "ltf": "1d"},
    "daily":   {"htf": "1d",  "ltf": "60m"},
    "intraday": {"htf": "60m", "ltf": "15m"},
}

# ---------------------------------------------------------------------------
# Valuation reference symbols by asset class
# ---------------------------------------------------------------------------
# Phase 4+5 P1 corrections applied (DXY for equities, Gold for precious metals,
# add equities/commodities/crypto entries, Platinum override).
# Phase 16: Individual stocks ("equities" class) — DXY REMOVED per OTC 2025
# Module 3 L3 (line 1890): Bernd says "unselect reference symbol three, which
# is the dollar" when setting up Valuation for an individual stock. References
# for stocks = ZB (30yr T-Bond) + Gold (GC).
# Phase 21: ZN=F (10yr T-Note) REMOVED from all refs. Valuation_OTC.txt Pine Script
# canonical source uses ZB1! (30yr T-Bond) as Symbol3. ZN (10yr) is a different
# instrument and was never in the Pine Script defaults.
VALUATION_REFS = {
    "forex":            ["DX-Y.NYB"],
    "equity_indices":   ["DX-Y.NYB", "ZB=F", "GC=F"],   # Phase 21: ZN removed, GC added per default
    "equities":         ["ZB=F", "GC=F"],                  # Phase 36 multi-agent consensus: Ch173 (Practical App Valuation) + Phase 32 Valuation rulebook + Phase 32 per-asset all agree stocks use Bonds + Gold, DXY OFF. Earlier frame_001240 Read may have been mid-demonstration state before Bernd flipped Show toggles.
    "commodities":      ["DX-Y.NYB", "GC=F", "ZB=F"],
    "soft_commodities": ["DX-Y.NYB", "GC=F", "ZB=F"],
    "precious_metals":  ["DX-Y.NYB", "GC=F", "ZB=F"],
    "energies":         ["DX-Y.NYB", "GC=F", "ZB=F"],
    "interest_rates":   ["^TNX"],
    "crypto":           ["DX-Y.NYB"],
}
VALUATION_REFS_PER_SYMBOL = {
    # Phase 41 chunk 3 P1 fix: Platinum and Palladium use @US+@GC+$DXY (3 refs),
    # NOT DXY+Gold only. Evidence: CW35 Aug 2023 frames 001942/001959/001881 all
    # show CampusValuationTool_V2("@US","@GC","$DXY") active for @PL Platinum;
    # FT Signals Mar 07 2023 frames 000993/001025 show same 3-ref config for @PA
    # Palladium. CLAUDE.md "Platinum = DXY + Gold only (no Bonds)" was incorrect.
    "PL=F": ["ZB=F", "GC=F", "DX-Y.NYB"],   # Platinum: bonds + gold + DXY
    "PA=F": ["ZB=F", "GC=F", "DX-Y.NYB"],   # Palladium: bonds + gold + DXY
    # Phase 41 REVERT: Crude Oil was set to Gold-only in Phase 33 based on one
    # frame reading. Phase 41 chunk 2 audit found 2 independent frames (L19 Jan
    # 2024 FT Signals + L28 Zone Qualifiers module) both showing CL=F Valuation
    # with @US + @GC + $DXY active -- standard commodity refs. Revert CL+BZ
    # to commodities default (which is DXY+GC+ZB, applied via the class default).
}

# Phase 15 — Equity index constituent stocks for Valuation analysis.
# Must stay in sync with EQUITY_INDEX_CONSTITUENTS in BP_rules_engine.py.
# Only the symbols listed here are fetched; the rules engine decides which
# are "primary" vs "secondary" for the bias logic.
EQUITY_INDEX_CONSTITUENT_STOCKS = {
    "NQ=F": ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "NFLX", "TSLA"],
    "ES=F": ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL"],
    "YM=F": ["MSFT", "UNH", "GS", "HD", "CAT", "AAPL"],
}

# ---------------------------------------------------------------------------
# Output file paths
# ---------------------------------------------------------------------------
SCAN_RESULTS_FILE   = SCRIPT_DIR / "scan_results.json"
SCAN_HISTORY_FILE   = SCRIPT_DIR / "scan_history.json"
PAPER_STATE_FILE    = SCRIPT_DIR / "paper_trader_state.json"
DASHBOARD_FILE      = SCRIPT_DIR / "dashboard.html"


# ---------------------------------------------------------------------------
# Profiles -- isolate independent paper-trading tracks (Phase 47)
# ---------------------------------------------------------------------------
# Each "profile" is one paper-trading track with its OWN config + state files,
# so two runners never clobber each other's state:
#
#   fundingpips (DEFAULT): prop-firm gating ON. Reproduces the ORIGINAL
#       filenames byte-for-byte (suffix="") so the 4-hourly scan.yml and all
#       existing .bat / automation are completely unchanged when --profile is
#       omitted.
#   allcoins: prop-firm gating OFF, expanded watchlist, take every signal.
#       Writes *_allcoins.json state + a slim committable signals artifact
#       (scan_results_allcoins_slim.json) for the TradingView Ideas workflow.
#
# The allcoins config is an OVERRIDE layer deep-merged over BP_config.yaml so
# all the Phase 1-46 methodology settings stay DRY in one place.
PROFILES = {
    "fundingpips": {"config": "BP_config.yaml",          "suffix": ""},
    "allcoins":    {"config": "BP_config_allcoins.yaml", "suffix": "_allcoins"},
}

PROFILE_NAME   = "fundingpips"
PROFILE_SUFFIX = ""
PROFILE_CONFIG = "BP_config.yaml"


def _deep_merge(base: Dict, ov: Optional[Dict]) -> Dict:
    """Recursively merge override dict `ov` over `base`. Nested dicts merge;
    scalars and lists in `ov` replace those in `base`."""
    out = dict(base)
    for k, v in (ov or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _apply_profile() -> None:
    """Parse --profile / --config / --state-suffix from argv and rebind the
    module-level state-file globals so every reader (save_results,
    load/save_paper_trader_state, the lock, the per-strategy log) is
    profile-aware.

    MUST be called at the very top of main(), BEFORE _acquire_lock(), so the
    lock file itself is profile-specific and the two tracks can run
    concurrently without one blocking the other.
    """
    global PROFILE_NAME, PROFILE_SUFFIX, PROFILE_CONFIG
    global SCAN_RESULTS_FILE, SCAN_HISTORY_FILE, PAPER_STATE_FILE, LOCK_FILE

    name = "fundingpips"
    if "--profile" in sys.argv:
        try:
            name = sys.argv[sys.argv.index("--profile") + 1].lower()
        except (IndexError, ValueError):
            print(f"{RED}--profile requires a value ({'|'.join(PROFILES)}){RESET}")
            sys.exit(1)
    prof = PROFILES.get(name)
    if prof is None:
        print(f"{RED}Unknown profile '{name}'. Choose one of: {list(PROFILES)}{RESET}")
        sys.exit(1)

    suffix = prof["suffix"]
    config = prof["config"]
    # Explicit escape hatches override the profile mapping (testing / one-offs).
    if "--state-suffix" in sys.argv:
        try:
            suffix = sys.argv[sys.argv.index("--state-suffix") + 1]
        except (IndexError, ValueError):
            pass
    if "--config" in sys.argv:
        try:
            config = sys.argv[sys.argv.index("--config") + 1]
        except (IndexError, ValueError):
            pass

    PROFILE_NAME   = name
    PROFILE_SUFFIX = suffix
    PROFILE_CONFIG = config

    SCAN_RESULTS_FILE = SCRIPT_DIR / f"scan_results{suffix}.json"
    SCAN_HISTORY_FILE = SCRIPT_DIR / f"scan_history{suffix}.json"
    PAPER_STATE_FILE  = SCRIPT_DIR / f"paper_trader_state{suffix}.json"
    LOCK_FILE         = SCRIPT_DIR / f".scanner{suffix}.lock"


def _load_profile_config() -> Dict:
    """Load BP_config.yaml as the base, then (for non-default profiles)
    deep-merge the profile's override file over it and append `watchlist_extra`
    to the watchlist. Keeps all methodology settings DRY in BP_config.yaml."""
    base_path = SCRIPT_DIR / "BP_config.yaml"
    if not base_path.exists():
        print(f"{RED}ERROR: Base config not found at {base_path}{RESET}")
        sys.exit(1)
    with open(base_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if PROFILE_CONFIG and PROFILE_CONFIG != "BP_config.yaml":
        ov_path = Path(PROFILE_CONFIG)
        if not ov_path.is_absolute():
            ov_path = SCRIPT_DIR / PROFILE_CONFIG
        if not ov_path.exists():
            print(f"{RED}ERROR: Profile override config not found at {ov_path}{RESET}")
            sys.exit(1)
        with open(ov_path, "r", encoding="utf-8") as f:
            overrides = yaml.safe_load(f) or {}
        extra = overrides.pop("watchlist_extra", None) or []
        config = _deep_merge(config, overrides)
        if extra:
            config["watchlist"] = (config.get("watchlist") or []) + extra
        logger.info(
            f"Profile '{PROFILE_NAME}': merged {ov_path.name} over base "
            f"(+{len(extra)} extra symbols)"
        )
    return config


def _write_slim_artifact(results: Dict) -> None:
    """Write a slim, committable subset of the scan results (signals + account
    summary, WITHOUT the ~30MB ohlcv_cache / indicators) for downstream
    consumers like the TradingView Ideas workflow. Only called for non-default
    profiles so the FundingPips run stays byte-for-byte unchanged."""
    keep = [
        "scan_time", "scan_duration_sec", "strategy", "htf", "ltf",
        "watchlist_scanned", "signals_found", "auto_traded",
        "signals", "errors", "account", "positions",
    ]
    slim = {k: results.get(k) for k in keep}
    slim["profile"] = PROFILE_NAME
    slim["engine_accuracy"] = 0.74  # Phase 41 forward-price accuracy (tier framing)
    slim_path = SCRIPT_DIR / f"scan_results{PROFILE_SUFFIX}_slim.json"
    with open(slim_path, "w", encoding="utf-8") as f:
        json.dump(slim, f, indent=2, default=str)
    n = len(slim.get("signals") or [])
    logger.info(f"Slim artifact written to {slim_path} ({n} signals)")
    print(f"  {GREEN}Slim artifact: {slim_path.name} ({n} signals){RESET}")


# ===================================================================
# Helper: load / save paper trader state for persistence
# ===================================================================

def _position_to_dict(pos) -> Dict:
    """Serialise a Position for JSON state (enum -> value, datetime -> iso)."""
    d = asdict(pos)
    d["direction"] = pos.direction.value if hasattr(pos.direction, "value") else pos.direction
    d["status"]    = pos.status.value if hasattr(pos.status, "value") else pos.status
    d["entry_time"] = pos.entry_time.isoformat() if hasattr(pos.entry_time, "isoformat") else pos.entry_time
    d["close_time"] = pos.close_time.isoformat() if getattr(pos, "close_time", None) and hasattr(pos.close_time, "isoformat") else None
    return d


def _position_from_dict(d: Dict):
    """Reconstruct a Position from its serialised dict."""
    from BP_paper_trader import Position, TradeDirection, TradeStatus
    def _dt(v):
        try:
            return datetime.fromisoformat(v) if v else None
        except (TypeError, ValueError):
            return None
    fields = {
        "id": d.get("id"), "symbol": d.get("symbol"),
        "direction": TradeDirection(d.get("direction", "long")),
        "entry_price": d.get("entry_price", 0.0), "stop_price": d.get("stop_price", 0.0),
        "current_stop": d.get("current_stop", d.get("stop_price", 0.0)),
        "targets": d.get("targets", []) or [],
        "position_size": d.get("position_size", 1.0), "risk_amount": d.get("risk_amount", 0.0),
        "entry_time": _dt(d.get("entry_time")) or datetime.now(),
        "status": TradeStatus(d.get("status", "active")),
        "realized_pnl": d.get("realized_pnl", 0.0),
        "partial_taken": d.get("partial_taken", False),
        "partial_qty": d.get("partial_qty", 0.0), "partial_price": d.get("partial_price", 0.0),
        "breakeven_triggered": d.get("breakeven_triggered", False),
        "trail_stop_level": d.get("trail_stop_level"),
        "zone_id": d.get("zone_id"), "close_time": _dt(d.get("close_time")),
        "close_price": d.get("close_price"),
        "trade_r_multiple": d.get("trade_r_multiple", 0.0), "notes": d.get("notes", ""),
    }
    return Position(**fields)


def load_paper_trader_state(trader: PaperTrader) -> None:
    """Restore paper trader state from disk if a save file exists.

    Open positions and trade history are restored too, so trades persist
    across scan runs and can be priced forward each cycle (instead of being
    discarded and re-opened every run, which left the track record empty).
    """
    if not PAPER_STATE_FILE.exists():
        logger.info("No previous paper trader state found -- starting fresh.")
        return
    try:
        with open(PAPER_STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)

        trader.balance           = state.get("balance", trader.balance)
        trader.initial_balance   = state.get("initial_balance", trader.initial_balance)
        trader.closed_pnl_total  = state.get("closed_pnl_total", 0.0)
        trader.total_trades      = state.get("total_trades", 0)
        trader.winning_trades    = state.get("winning_trades", 0)
        trader.losing_trades     = state.get("losing_trades", 0)
        trader.peak_balance      = state.get("peak_balance", trader.balance)
        trader.max_drawdown_pct  = state.get("max_drawdown_pct", 0.0)
        trader.daily_pnl         = state.get("daily_pnl", 0.0)
        trader.daily_trades      = state.get("daily_trades", 0)
        trader.zone_memory       = state.get("zone_memory", {})
        trader.today_starting_equity = state.get("today_starting_equity", trader.balance)
        trader.current_date      = state.get("current_date", trader.current_date)
        trader.account_blown     = state.get("account_blown", False)
        trader.challenge_started_at = state.get("challenge_started_at")

        # Restore open positions + closed trade history
        for pd in state.get("open_positions", []) or []:
            try:
                pos = _position_from_dict(pd)
                trader.positions[pos.id] = pos
            except Exception as exc:
                logger.warning(f"Skipping unreadable open position: {exc}")
        for pd in state.get("trade_history", []) or []:
            try:
                trader.trade_history.append(_position_from_dict(pd))
            except Exception as exc:
                logger.warning(f"Skipping unreadable history record: {exc}")

        logger.info(
            f"Restored paper trader state: balance=${trader.balance:,.2f}, "
            f"trades={trader.total_trades}, open={len(trader.positions)}, "
            f"PnL=${trader.closed_pnl_total:,.2f}"
        )
    except Exception as exc:
        logger.warning(f"Could not load paper trader state: {exc}")


def save_paper_trader_state(trader: PaperTrader) -> None:
    """Persist paper trader state to disk, including open positions and history."""
    # Start the challenge clock on the first save after a reset (state file
    # didn't exist / had no challenge_started_at yet).
    if not trader.challenge_started_at:
        trader.challenge_started_at = datetime.now().isoformat()

    state = {
        "balance":          trader.balance,
        "initial_balance":  trader.initial_balance,
        "closed_pnl_total": trader.closed_pnl_total,
        "total_trades":     trader.total_trades,
        "winning_trades":   trader.winning_trades,
        "losing_trades":    trader.losing_trades,
        "peak_balance":     trader.peak_balance,
        "max_drawdown_pct": trader.max_drawdown_pct,
        "daily_pnl":        trader.daily_pnl,
        "daily_trades":     trader.daily_trades,
        "today_starting_equity": trader.today_starting_equity,
        "current_date":     trader.current_date,
        "account_blown":    trader.account_blown,
        "zone_memory":      trader.zone_memory,
        "challenge_started_at": trader.challenge_started_at,
        "open_positions":   [_position_to_dict(p) for p in trader.positions.values()],
        "trade_history":    [_position_to_dict(p) for p in trader.trade_history[-200:]],
        "saved_at":         datetime.now().isoformat(),
    }
    with open(PAPER_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    logger.info(
        f"Paper trader state saved to {PAPER_STATE_FILE} "
        f"(open={len(trader.positions)}, history={len(trader.trade_history)})"
    )


# ===================================================================
# Helper: JSON-safe serialisation (handles datetime, numpy, etc.)
# ===================================================================

def json_safe(obj, _depth=0):
    """Make an object JSON-serialisable.

    _depth guard prevents infinite recursion when an object's __dict__
    contains circular back-references (e.g. Enum member -> Enum class ->
    Enum member).  Enum members are also caught explicitly and converted
    to their .value so the TradeDirection/TradeStatus str-Enum subclasses
    never reach the __dict__ branch.
    """
    if _depth > 60:
        return str(obj)  # circuit-breaker
    # Primitives first -- short-circuit before any isinstance cascade
    if obj is None or isinstance(obj, bool):
        return obj
    if isinstance(obj, (int, float)):
        return obj
    # Enum before str: str-Enum subclasses satisfy isinstance(x, str) too,
    # but we want .value ('long', 'active') not the full repr.
    from enum import Enum as _Enum
    if isinstance(obj, _Enum):
        return obj.value
    if isinstance(obj, str):
        return obj
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "item"):  # numpy scalar
        return obj.item()
    if hasattr(obj, "tolist"):  # numpy array / pandas Series
        try:
            return obj.tolist()
        except Exception:
            return str(obj)
    # dict before __dict__ so plain dicts go through the fast path
    if isinstance(obj, dict):
        return {str(k): json_safe(v, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(i, _depth + 1) for i in obj]
    if hasattr(obj, "__dict__"):
        return {k: json_safe(v, _depth + 1)
                for k, v in obj.__dict__.items()
                if not k.startswith('_')}
    return str(obj)  # last resort: stringify unknown types


# ===================================================================
# Core: scan a single symbol
# ===================================================================

def build_indicator_series(
    engine: RulesEngine,
    asset_class: str,
    price_df,
    cot_df,
    val_refs: Dict,
    seasonal_df,
) -> Dict:
    """Compute the COT / Valuation / Seasonality timeseries that the dashboard
    plots. Each entry mirrors the data the rules engine already calculates --
    we just expose it for visualization so the user can verify the indicators
    are firing correctly.
    """
    import pandas as pd

    series: Dict = {
        "asset_class":              asset_class,
        "cot_index":                [],   # normalized 0-100 (3 lines)
        "cot_index_extreme":        [],   # 156-week extreme overlay (3 lines)
        "cot_report":               [],   # raw position counts (signed)
        "valuation_refs":           {},   # per-reference series, e.g. {DXY: [...], ZB=F: [...]}
        "seasonality":              [],   # 15y main series (kept for back-compat)
        "seasonality_multi":        {},   # {5: [...], 10: [...], 15: [...]}
        "seasonality_current_bin":  None,
    }

    # Use the same asset-class-tuned engines that _analyze_fundamentals uses
    # so the dashboard charts reflect what actually drove the bias decision.
    cot_engine, val_engine = engine._indicators_for_class(asset_class)
    from BP_indicators import COTReport
    cot_report_engine = COTReport()

    # ---- COT Index (last 156 weeks ~ 3 years) ----
    try:
        if cot_df is not None and not cot_df.empty:
            cot_calc = cot_engine.calculate(cot_df).tail(156)
            for idx, row in cot_calc.iterrows():
                date_s = str(idx.date()) if hasattr(idx, "date") else str(idx)
                series["cot_index"].append({
                    "date":        date_s,
                    "commercials": _safe_float(row.get("commercials_index")),
                    "large_specs": _safe_float(row.get("large_specs_index")),
                    "small_specs": _safe_float(row.get("small_specs_index")),
                })
                series["cot_index_extreme"].append({
                    "date":        date_s,
                    "commercials": _safe_float(row.get("comm_net_extreme")),
                    "large_specs": _safe_float(row.get("lspec_net_extreme")),
                    "small_specs": _safe_float(row.get("sspec_net_extreme")),
                })
    except Exception as e:
        logger.warning(f"build cot series failed: {e}")

    # ---- COT Report (raw positions, last 104 weeks) ----
    try:
        if cot_df is not None and not cot_df.empty:
            rep = cot_report_engine.calculate(cot_df).tail(104)
            for idx, row in rep.iterrows():
                series["cot_report"].append({
                    "date":           str(idx.date()) if hasattr(idx, "date") else str(idx),
                    "comm_net":       _safe_float(row.get("comm_net")),
                    "lspec_net":      _safe_float(row.get("lspec_net")),
                    "sspec_net":      _safe_float(row.get("sspec_net")),
                })
    except Exception as e:
        logger.warning(f"build cot report failed: {e}")

    # ---- Valuation per-reference (3 separate lines per textbook Pine Script) ----
    try:
        if val_refs:
            val_calc = val_engine.calculate(price_df, val_refs)
            if not val_calc.empty:
                tail = val_calc.tail(100)
                for ref_name in val_refs.keys():
                    col = f"valuation_{ref_name}"
                    if col not in tail.columns:
                        continue
                    pts = []
                    for idx, row in tail.iterrows():
                        v = row.get(col)
                        if pd.notna(v):
                            pts.append({
                                "date":  str(idx.date()) if hasattr(idx, "date") else str(idx),
                                "value": float(v),
                            })
                    if pts:
                        series["valuation_refs"][ref_name] = pts
    except Exception as e:
        logger.warning(f"build valuation series failed: {e}")

    # ---- Seasonality multi-lookback (5y / 10y / 15y) ----
    try:
        if seasonal_df is not None and not seasonal_df.empty:
            multi = engine.seasonality.calculate_multi(seasonal_df, timeframe="weekly")
            for years, seas in multi.items():
                series["seasonality_multi"][str(years)] = [
                    {"bin": int(r["bin"]), "value": float(r["seasonal_value"])}
                    for _, r in seas.iterrows()
                ]
            # Keep the 15y series in the legacy slot so older dashboard JS
            # versions still find it.
            if 15 in multi:
                series["seasonality"] = series["seasonality_multi"]["15"]
            elif multi:
                series["seasonality"] = next(iter(series["seasonality_multi"].values()))
            series["seasonality_current_bin"] = int(
                engine.seasonality.get_current_bin(price_df, "weekly")
            )
    except Exception as e:
        logger.warning(f"build seasonality series failed: {e}")

    return series


def _safe_float(v) -> Optional[float]:
    import math
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return round(f, 2)
    except (TypeError, ValueError):
        return None


def scan_symbol(
    symbol_info: Dict,
    fetcher: DataFetcher,
    engine: RulesEngine,
    htf: str,
    ltf: str,
    strategy: str,
) -> Optional[Dict]:
    """
    Run the full 7-step process on one symbol.
    Returns a signal dict or None.
    """
    sym  = symbol_info["symbol"]
    name = symbol_info["name"]
    ac   = symbol_info["asset_class"]

    logger.info(f"--- Scanning {sym} ({name}) [{ac}] ---")

    out = {"signal": None, "indicators": None}

    # 1. Fetch OHLCV for HTF + LTF
    ohlcv = fetcher.fetch_multi_timeframe(sym, timeframes=[htf, ltf])
    if htf not in ohlcv or ltf not in ohlcv:
        logger.warning(f"[{sym}] Insufficient price data -- skipped.")
        return out

    # 2. Fetch COT data
    # `cot_symbol` is an optional override on the watchlist entry: when the
    # OHLCV ticker is a spot/CFD symbol that has no direct COT report (e.g.
    # EURUSD=X), the entry can map it to the underlying futures (e.g. 6E=F)
    # so we still get COT bias. Falls back to the OHLCV symbol when absent.
    cot_lookup_sym = symbol_info.get("cot_symbol", sym)
    cftc_code = get_cftc_code(cot_lookup_sym)
    cot_df = fetcher.fetch_cot_data(cftc_code)

    # 2b. For forex pairs: fetch USD Index COT for the opposing-currency
    # cross-check. The rules engine compares EUR-side bias against
    # inverted USD-side bias and demotes to neutral on disagreement.
    opposing_cot_df = None
    if ac == 'forex':
        opposing_cot_df = fetcher.fetch_cot_data(get_cftc_code('DX=F'))

    # 3. Fetch valuation reference symbols (cached in DataFetcher across calls,
    #    so the dollar/bond series is downloaded once per scan, not 15 times)
    # CRITICAL: refs MUST match the HTF interval. _analyze_fundamentals feeds
    # the symbol's HTF data into Valuation.calculate; if refs are at a
    # different interval, the index intersection is too small and the
    # indicator silently returns 'neutral' for every symbol.
    # Match window to HTF: monthly/weekly need years of bars; daily 5y;
    # intraday capped at 729d (Yahoo limit). Used for both val refs and
    # constituent stock fetching (Phase 15).
    if htf in ("1mo", "1wk"):
        _ref_period = "10y"
    elif htf == "1d":
        _ref_period = "5y"
    else:
        _ref_period = "729d"

    val_refs: Dict = {}
    ref_symbols = VALUATION_REFS_PER_SYMBOL.get(sym) or VALUATION_REFS.get(ac, ["DX-Y.NYB"])
    for ref_sym in ref_symbols:
        ref_df = fetcher.fetch_ohlcv(ref_sym, interval=htf, period=_ref_period)
        if not ref_df.empty:
            val_refs[ref_sym] = ref_df

    # 3b. Phase 15: For equity indices, also fetch constituent stock prices.
    # These are passed to the rules engine which computes per-stock Valuation
    # instead of reading the index directly (Bernd: "if AAPL + MSFT are
    # undervalued, you can buy NQ / ES"). The refs (DXY/ZN/ZB) are shared.
    constituent_dfs: Dict = {}
    if ac == 'equity_indices' and sym in EQUITY_INDEX_CONSTITUENT_STOCKS:
        for stock in EQUITY_INDEX_CONSTITUENT_STOCKS[sym]:
            s_df = fetcher.fetch_ohlcv(stock, interval=htf, period=_ref_period)
            if not s_df.empty:
                constituent_dfs[stock] = s_df

    # 4. Fetch seasonality data
    seasonal_df = fetcher.fetch_seasonality_reference(sym, lookback_years=15)

    # 5. Run the seven-step process
    signal = engine.run_seven_step_process(
        symbol=sym,
        ohlcv_data=ohlcv,
        cot_df=cot_df,
        valuation_refs=val_refs,
        seasonal_df=seasonal_df,
        htf=htf,
        ltf=ltf,
        income_strategy=strategy,
        asset_class=ac,
        opposing_cot_df=opposing_cot_df,
        constituent_dfs=constituent_dfs if constituent_dfs else None,
    )

    if signal:
        signal["asset_class"] = ac
        signal["display_name"] = name
        # Store current LTF close so display can show distance-to-zone
        try:
            signal["current_price"] = float(ohlcv[ltf]["close"].iloc[-1])
        except Exception:
            signal["current_price"] = 0.0
        out["signal"] = signal

    # 6. Build indicator timeseries for the dashboard (always, even when no signal)
    out["indicators"] = build_indicator_series(
        engine, ac, ohlcv[htf], cot_df, val_refs, seasonal_df
    )

    return out


# ===================================================================
# Core: scan all markets
# ===================================================================

def scan_all_markets(
    config: Dict,
    watchlist: Optional[List[Dict]] = None,
) -> Dict:
    """
    Scan every symbol in the watchlist through the 7-step process.
    Auto paper-trades valid signals.

    Returns a results dict ready for JSON serialisation.
    """
    scan_start = datetime.now()

    strategy = config.get("active_strategy", "weekly")
    tf = STRATEGY_TIMEFRAMES.get(strategy, STRATEGY_TIMEFRAMES["weekly"])
    htf, ltf = tf["htf"], tf["ltf"]

    if watchlist is None:
        watchlist = FULL_WATCHLIST

    # --full-cot flag: fetch ALL available CFTC history (~30-40 years for major
    # contracts) instead of the default 260-week window.  This makes all COT
    # normalisation (rolling 52w / 156w extremes / all-time bands) run against
    # the complete dataset so extreme signals are measured against their true
    # historic context.  Trade-off: ~1-2 s extra per unique CFTC code on the
    # first call of a session; subsequent symbol scans hit the in-process cache.
    _use_full_cot = "--full-cot" in sys.argv
    if _use_full_cot:
        logger.info("full_history_cot=True — fetching 30-year CFTC history for all symbols")
        print("  [COT] full_history_cot mode: using 30+ years of CFTC data for all signals")
    fetcher = DataFetcher(full_history_cot=_use_full_cot)
    engine  = RulesEngine(config)
    trader  = PaperTrader(config)

    # Restore persisted paper trader state
    load_paper_trader_state(trader)
    # Start the challenge clock immediately (not just at save time) so the
    # very first scan after a reset already reports "Day 0" instead of a gap.
    if not trader.challenge_started_at:
        trader.challenge_started_at = datetime.now().isoformat()
    # Positions carried over from prior runs -- these get priced forward this
    # scan. Positions opened during THIS scan are excluded from the update so
    # they aren't closed against the same bar they were entered on.
    restored_position_ids = set(trader.positions.keys())

    # Reset daily stats if new day
    today = datetime.now().strftime("%Y-%m-%d")
    if trader.current_date != today:
        trader.reset_daily_stats()
        trader.current_date = today

    signals: List[Dict] = []
    errors:  List[Dict] = []
    auto_traded = 0
    ohlcv_cache: Dict[str, Dict[str, List[Dict]]] = {}
    zones_by_symbol: Dict[str, List[Dict]] = {}
    indicators_by_symbol: Dict[str, Dict] = {}

    total = len(watchlist)
    print()
    print(f"{BOLD}{CYAN}{'=' * 60}{RESET}")
    print(f"{BOLD}{CYAN}  Blueprint Market Scanner{RESET}")
    print(f"{BOLD}{CYAN}  Strategy: {strategy.upper()}  |  HTF: {htf}  |  LTF: {ltf}{RESET}")
    print(f"{BOLD}{CYAN}  Watchlist: {total} symbols  |  {scan_start.strftime('%Y-%m-%d %H:%M:%S')}{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 60}{RESET}")
    print()

    for idx, sym_info in enumerate(watchlist, 1):
        sym  = sym_info["symbol"]
        name = sym_info["name"]
        progress = f"[{idx}/{total}]"

        print(f"  {DIM}{progress}{RESET}  Scanning {BOLD}{sym}{RESET} ({name})...", flush=True)

        try:
            # Cache OHLCV so the dashboard can chart even without a live API.
            # Last ~250 bars per timeframe is enough for the lightweight-charts panel.
            sym = sym_info["symbol"]
            for tf_label in (htf, ltf):
                # FIX Bug 2: Yahoo Finance caps hourly data at 730 days;
                # requesting 5y on 60m/15m intervals causes triple-retry waste.
                _intraday = tf_label not in ("1mo", "1wk", "1d")
                _period = "729d" if _intraday else ("10y" if tf_label in ("1mo", "1wk") else "5y")
                df_tf = fetcher.fetch_ohlcv(
                    sym,
                    interval=tf_label,
                    period=_period,
                )
                if not df_tf.empty:
                    tail = df_tf.tail(300).copy()
                    tail["timestamp"] = tail["timestamp"].astype(str)
                    ohlcv_cache.setdefault(sym, {})[tf_label] = tail.to_dict(orient="records")

            scan_out = scan_symbol(sym_info, fetcher, engine, htf, ltf, strategy)
            signal = scan_out.get("signal")
            if scan_out.get("indicators"):
                indicators_by_symbol[sym] = scan_out["indicators"]

            if signal:
                signals.append(signal)
                print(f"  {GREEN}SIGNAL: {signal['direction'].upper()}{RESET}")
                # NOTE: paper trades are submitted AFTER the loop, once each
                # signal has been sized (position_size in USD-per-point) so the
                # paper trader's PnL comes out in real dollars for every class.
            else:
                print(f"  {DIM}no signal{RESET}")

        except Exception as exc:
            print(f"  {RED}ERROR: {exc}{RESET}")
            logger.error(f"[{sym}] Scan error: {traceback.format_exc()}")
            errors.append({"symbol": sym, "error": str(exc)})

        # Small pause between symbols to stay well under Yahoo Finance's
        # rate limit even when scanning a large watchlist (77+ symbols).
        time.sleep(0.4)

    scan_end = datetime.now()
    elapsed = (scan_end - scan_start).total_seconds()

    # ----------------------------------------------------------------
    # Phase 27 — Constituent routing for equity indices.
    # When an index (NQ=F / ES=F / YM=F / RTY=F) has no direct signal
    # (no demand zone at current price, typically at ATH), surface any
    # long signals on its primary constituent stocks as alternative
    # trade candidates that implement the same directional thesis.
    # Bernd HAI 1:57:07 — "if apple rallies the market rallies — take
    # the constituent stock trade instead of the index itself."
    # ----------------------------------------------------------------
    _INDEX_CONSTITUENTS: Dict = {
        'NQ=F':  ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'GOOGL', 'NFLX', 'TSLA'],
        'ES=F':  ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'GOOGL'],
        'YM=F':  ['MSFT', 'UNH', 'GS', 'HD', 'MCD'],
        'RTY=F': ['IWM'],
    }
    _signal_symbols = {s.get('symbol') for s in signals if s.get('direction') == 'long'}
    constituent_routing: Dict[str, List[str]] = {}
    for _idx_sym, _constituents in _INDEX_CONSTITUENTS.items():
        if _idx_sym not in _signal_symbols:
            # Index has no direct long signal — check if constituents do
            _hits = [c for c in _constituents if c in _signal_symbols]
            if _hits:
                constituent_routing[_idx_sym] = _hits
                print(
                    f"\n  {CYAN}[Constituent route]{RESET} {_idx_sym} has no zone "
                    f"but {', '.join(_hits)} signal long "
                    f"— consider these as the index thesis trade"
                )

    # ----------------------------------------------------------------
    # Price carried-over positions forward against the latest bar so they
    # progress (breakeven, targets, stop, trailing) and close when hit.
    # This is what builds the track record -- before this, open positions
    # were discarded each run and nothing ever closed.
    # ----------------------------------------------------------------
    current_prices: Dict[str, Dict[str, float]] = {}
    for _sym, _tfs in ohlcv_cache.items():
        _bars = _tfs.get(ltf) or _tfs.get(htf)
        if _bars:
            _last = _bars[-1]
            try:
                current_prices[_sym] = {
                    "high":  float(_last.get("high", _last.get("close", 0))),
                    "low":   float(_last.get("low",  _last.get("close", 0))),
                    "close": float(_last.get("close", 0)),
                    "bid":   float(_last.get("close", 0)),
                    "ask":   float(_last.get("close", 0)),
                }
            except (TypeError, ValueError):
                continue

    closed_events: List[Dict] = []
    if restored_position_ids:
        # Temporarily set aside positions opened this scan, update only the
        # carried-over ones, then put the new ones back.
        _new_only = {pid: trader.positions.pop(pid)
                     for pid in list(trader.positions)
                     if pid not in restored_position_ids}
        try:
            closed_events = trader.update_positions(current_prices)
        finally:
            trader.positions.update(_new_only)
        for ev in closed_events:
            print(f"  {MAGENTA}[CLOSED]{RESET} {ev['symbol']} {ev['direction']} "
                  f"PnL=${ev['realized_pnl']:,.2f} ({ev['r_multiple']:+.2f}R)")

    # ----------------------------------------------------------------
    # Position sizing -- convert each signal's $ risk into a MatchTrader
    # LOT SIZE the trader can enter directly on FundingPips. Forex is sized
    # from live rates (broker-independent); other classes use config specs.
    # ----------------------------------------------------------------
    specs_cfg   = config.get("instrument_specs", {}) or {}
    specs_class = specs_cfg.get("defaults_by_class", {}) or {}
    specs_over  = specs_cfg.get("overrides", {}) or {}

    # Build {currency -> USD value of one unit} from scanned FX last prices.
    _fx_prices: Dict[str, float] = {}
    for _si in watchlist:
        if _si.get("asset_class") != "forex":
            continue
        _bars = (ohlcv_cache.get(_si["symbol"], {}) or {})
        _b = _bars.get(ltf) or _bars.get(htf)
        if _b:
            try:
                _fx_prices[_si["name"]] = float(_b[-1].get("close", 0))
            except (TypeError, ValueError):
                pass
    usd_quote_table = build_usd_quote_table(_fx_prices)

    risk_pct = float(config.get("risk", {}).get("risk_per_trade_pct", 1.0)) / 100.0
    for s in signals:
        ac    = s.get("asset_class", "")
        sname = s.get("display_name") or s.get("symbol", "")
        spec  = dict(specs_class.get(ac, {}))
        spec.update(specs_over.get(sname, {}))
        # Risk budget for this trade, off the live (prop-firm) balance.
        risk_usd = trader.balance * risk_pct
        try:
            sz = compute_lots(
                asset_class=ac, symbol_name=sname,
                entry=float(s["entry_price"]), stop=float(s["stop_price"]),
                risk_usd=risk_usd, spec=spec, usd_per_quote_ccy=usd_quote_table,
            )
            s["lot_size"]        = sz.lots
            s["units"]           = sz.units
            s["risk_usd_target"] = round(risk_usd, 2)
            s["risk_usd_actual"] = sz.risk_usd_actual
            s["contract_size"]   = sz.contract_size
            s["spec_verified"]   = sz.verified
            s["sizing_note"]     = sz.note
            # position_size for the paper trader is USD-per-1.0-price-move for
            # the WHOLE position. Then realized_pnl = price_move * position_size
            # comes out in real USD for every asset class, and risk_amount lines
            # up with the prop-firm dollar limits.
            usd_per_point = sz.lots * sz.usd_per_point_per_lot
            s["position_size"] = round(usd_per_point, 6)
            s["risk_amount"]   = sz.risk_usd_actual
        except Exception as exc:
            s["lot_size"] = None
            s["sizing_note"] = f"sizing error: {exc}"
            logger.warning(f"[{sname}] sizing failed: {exc}")

    # ----------------------------------------------------------------
    # Submit sized signals to the paper trader (after sizing, so PnL is USD).
    # Only paper-trade signals that clear the alert quality bar
    # (alerts.min_composite_to_post) so the paper track record mirrors
    # EXACTLY the setups you'd actually take -- not every low-conviction zone.
    # ----------------------------------------------------------------
    _min_comp = float(config.get("alerts", {}).get("min_composite_to_post", 7.0))
    for s in signals:
        if not s.get("lot_size"):
            s["paper_trade_id"] = None
            continue
        _comp = float((s.get("qualifier_scores") or {}).get("composite", 0) or 0)
        if _comp < _min_comp:
            s["paper_trade_id"] = None
            print(f"  {YELLOW}-> {s.get('display_name')}: below quality bar "
                  f"(composite {_comp:.1f} < {_min_comp:g}); not paper-traded{RESET}")
            continue
        pos_id = trader.submit_signal(s)
        if pos_id:
            auto_traded += 1
            s["paper_trade_id"] = pos_id
            print(f"  {MAGENTA}-> Paper trade opened: {s.get('display_name')} "
                  f"{s.get('lot_size')} lots ({pos_id}){RESET}")
        else:
            s["paper_trade_id"] = None
            print(f"  {YELLOW}-> {s.get('display_name')}: paper trade rejected "
                  f"(limits / max positions){RESET}")

    # Build the results payload
    account_summary = trader.get_account_summary()
    open_positions  = trader.get_open_positions()
    trade_history   = trader.get_trade_history(limit=100)

    # Stamp live price, unrealized USD PnL, and open R-multiple onto open
    # positions so the alert shows running-trade progress.
    for op in open_positions:
        px = current_prices.get(op.get("symbol"), {})
        now = px.get("close")
        if now:
            entry = float(op.get("entry_price", 0))
            size  = float(op.get("position_size", 0))   # USD per 1.0 move
            stopd = abs(entry - float(op.get("stop_price", entry)))
            move  = (now - entry) if op.get("direction") == "long" else (entry - now)
            op["current_price"]   = round(now, 6)
            op["unrealized_pnl"]  = round(move * size, 2)
            op["r_multiple_open"] = round(move / stopd, 2) if stopd > 0 else 0.0

    results = {
        "scan_time":           scan_start.isoformat(),
        "scan_duration_sec":   round(elapsed, 1),
        "strategy":            strategy,
        "htf":                 htf,
        "ltf":                 ltf,
        "watchlist_scanned":   total,
        "signals_found":       len(signals),
        "auto_traded":         auto_traded,
        "signals":             json_safe(signals),
        "errors":              errors,
        "account":             json_safe(account_summary),
        "positions":           json_safe(open_positions),
        "trade_history":       json_safe(trade_history),
        "ohlcv_cache":         ohlcv_cache,
        "indicators":          indicators_by_symbol,
        # Phase 27: constituent routing — index symbols that have no direct zone
        # but whose primary constituent stocks do have long signals.
        "constituent_routing": constituent_routing,
    }

    # Save paper trader state for next run
    save_paper_trader_state(trader)

    return results


# ===================================================================
# File I/O: save results + append history
# ===================================================================

def save_results(results: Dict) -> None:
    """Write scan_results.json (overwrite) and append to scan_history.json."""

    # 1. Current scan results (dashboard reads this)
    with open(SCAN_RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"Scan results saved to {SCAN_RESULTS_FILE}")

    # 2. Append to history log
    history_entry = {
        "scan_time":        results["scan_time"],
        "strategy":         results["strategy"],
        "watchlist_scanned": results["watchlist_scanned"],
        "signals_found":    results["signals_found"],
        "auto_traded":      results["auto_traded"],
        "account_balance":  results["account"].get("balance", 0),
        "closed_pnl":       results["account"].get("closed_pnl", 0),
        "win_rate":         results["account"].get("win_rate", 0),
        "total_trades":     results["account"].get("total_trades", 0),
        "signals_summary": [
            {
                "symbol":    s.get("symbol"),
                "direction": s.get("direction"),
                "entry":     s.get("entry_price"),
                "composite": s.get("qualifier_scores", {}).get("composite", 0),
            }
            for s in results.get("signals", [])
        ],
    }

    history: List[Dict] = []
    if SCAN_HISTORY_FILE.exists():
        try:
            with open(SCAN_HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
            if not isinstance(history, list):
                history = []
        except (json.JSONDecodeError, Exception):
            history = []

    history.append(history_entry)

    with open(SCAN_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, default=str)
    logger.info(f"Scan history appended to {SCAN_HISTORY_FILE} ({len(history)} entries)")


# ===================================================================
# Console summary
# ===================================================================

def print_summary(results: Dict) -> None:
    """Print a nicely formatted console summary."""
    print()
    print(f"{BOLD}{CYAN}{'=' * 60}{RESET}")
    print(f"{BOLD}{CYAN}  SCAN COMPLETE{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 60}{RESET}")
    print()

    # Scan stats
    print(f"  {BOLD}Scan Time:{RESET}       {results['scan_time']}")
    print(f"  {BOLD}Duration:{RESET}        {results['scan_duration_sec']}s")
    print(f"  {BOLD}Symbols Scanned:{RESET} {results['watchlist_scanned']}")
    print(f"  {BOLD}Signals Found:{RESET}   {results['signals_found']}")
    print(f"  {BOLD}Auto Traded:{RESET}     {results['auto_traded']}")
    print()

    # Signals table
    signals = results.get("signals", [])
    if signals:
        print(f"  {BOLD}{GREEN}--- SIGNALS ---{RESET}")
        print(f"  {'Symbol':<10} {'Dir':<6} {'Status':<12} {'CurPrice':<12} {'Entry':<12} {'Stop':<12} {'T1':<12} {'Dist%':<8} {'Score':<6}")
        print(f"  {'-'*90}")
        for s in signals:
            direction = s.get("direction", "?")
            color = GREEN if direction == "long" else RED
            targets = s.get("targets", [0, 0, 0])
            t1 = targets[0] if targets else 0
            composite = s.get("qualifier_scores", {}).get("composite", 0)
            pending = s.get("pending_order", False)
            cur_price = s.get("current_price", 0)
            entry = s.get("entry_price", 0)
            dist_pct = abs(cur_price - entry) / cur_price * 100 if cur_price else 0
            status_color = YELLOW if pending else GREEN
            status_label = "PENDING" if pending else "AT ZONE"
            print(
                f"  {s.get('symbol','?'):<10} "
                f"{color}{direction.upper():<6}{RESET} "
                f"{status_color}{status_label:<12}{RESET} "
                f"{cur_price:<12.4f} "
                f"{entry:<12.4f} "
                f"{s.get('stop_price',0):<12.4f} "
                f"{t1:<12.4f} "
                f"{dist_pct:<8.1f} "
                f"{composite:<6.1f}"
            )
        print()
    else:
        print(f"  {YELLOW}No signals generated this scan.{RESET}")
        print()

    # Account summary
    acct = results.get("account", {})
    balance = acct.get("balance", 0)
    pnl     = acct.get("closed_pnl", 0)
    wr      = acct.get("win_rate", 0)
    trades  = acct.get("total_trades", 0)
    dd      = acct.get("max_drawdown_pct", 0)
    open_p  = acct.get("open_positions", 0)

    pnl_color = GREEN if pnl >= 0 else RED

    print(f"  {BOLD}--- ACCOUNT ---{RESET}")
    print(f"  Balance:       ${balance:>12,.2f}")
    print(f"  Closed PnL:    {pnl_color}${pnl:>12,.2f}{RESET}")
    print(f"  Win Rate:      {wr:>11.1f}%")
    print(f"  Total Trades:  {trades:>12}")
    print(f"  Max Drawdown:  {dd:>11.2f}%")
    print(f"  Open Positions:{open_p:>12}")
    print()

    # Errors
    errors = results.get("errors", [])
    if errors:
        print(f"  {RED}--- ERRORS ({len(errors)}) ---{RESET}")
        for e in errors:
            print(f"  {RED}  {e['symbol']}: {e['error']}{RESET}")
        print()

    print(f"{BOLD}{CYAN}{'=' * 60}{RESET}")
    print()


# ===================================================================
# Main entry point
# ===================================================================

def main():
    """Main scanner entry point."""
    print()
    print(f"{BOLD}{CYAN}============================================{RESET}")
    print(f"{BOLD}{CYAN}  Blueprint Trading System - Market Scanner{RESET}")
    print(f"{BOLD}{CYAN}============================================{RESET}")
    print()

    # ---- Resolve profile FIRST (rebinds state-file globals incl. LOCK_FILE) ----
    # Must run before _acquire_lock() so the lock is profile-specific and the
    # FundingPips + all-coins tracks can run concurrently.
    _apply_profile()
    if PROFILE_NAME != "fundingpips":
        print(f"  {MAGENTA}Profile: {PROFILE_NAME}  (state suffix '{PROFILE_SUFFIX}'){RESET}")

    # ---- Process lock: abort immediately if another scanner is running ----
    if not _acquire_lock():
        print(f"{RED}ERROR: Another scanner is already running.{RESET}")
        print(f"{RED}       Close that console window first, then try again.{RESET}")
        print(f"{YELLOW}       (If you are sure no scanner is running, delete .scanner.lock){RESET}")
        sys.exit(1)
    atexit.register(_release_lock)  # always clean up, even on crash

    # ---- Load config (profile-aware: base BP_config.yaml + optional override) ----
    config = _load_profile_config()
    logger.info(f"Config loaded for profile '{PROFILE_NAME}'")

    # ---- CLI override: --strategy <weekly|daily|monthly|intraday> ----
    # Lets the operator run a one-off scan on a different timeframe pair without
    # editing BP_config.yaml. Falls back to the config's active_strategy.
    if "--strategy" in sys.argv:
        try:
            i = sys.argv.index("--strategy")
            strat_arg = sys.argv[i + 1].lower()
        except (IndexError, ValueError):
            print(f"{RED}--strategy requires a value (weekly|daily|monthly|intraday){RESET}")
            sys.exit(1)
        if strat_arg not in STRATEGY_TIMEFRAMES:
            print(f"{RED}Unknown strategy '{strat_arg}'. Choose one of: {list(STRATEGY_TIMEFRAMES.keys())}{RESET}")
            sys.exit(1)
        config["active_strategy"] = strat_arg
        logger.info(f"CLI override: active_strategy = {strat_arg}")

    # ---- Attach per-run log handlers (console + per-strategy file) ----------
    # These are added here (not at module level) so:
    #   1. Each run writes a clean per-strategy log (mode='w' overwrites stale runs).
    #   2. Logger output goes to stderr so it doesn't pollute stdout if
    #      the caller redirects stdout for other purposes.
    _root = logging.getLogger()
    _fmt  = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    _con = logging.StreamHandler(sys.stderr)
    _con.setFormatter(_fmt)
    _root.addHandler(_con)

    _active_strategy = config.get("active_strategy", "daily")
    # Suffix the per-strategy log with the profile so two concurrent runners
    # (which both open the log in mode='w') don't truncate each other's logs.
    _strat_log_path  = SCRIPT_DIR / f"scanner_{_active_strategy}{PROFILE_SUFFIX}.log"
    _strat_fh = logging.FileHandler(_strat_log_path, encoding="utf-8", mode="w")
    _strat_fh.setFormatter(_fmt)
    _root.addHandler(_strat_fh)
    print(f"  {DIM}Log -> {_strat_log_path.name}  |  Full: scanner.log{RESET}")
    print()

    # ---- Determine watchlist ----
    # Default: read watchlist from BP_config.yaml (so user edits land in scans).
    # `--full-watchlist` falls back to the in-code FULL_WATCHLIST baseline
    # (futures-only set), and `--config-only` is kept as an alias.
    if "--full-watchlist" in sys.argv:
        watchlist = FULL_WATCHLIST
        logger.info(f"Using in-code FULL_WATCHLIST ({len(watchlist)} symbols)")
    else:
        watchlist = config.get("watchlist") or FULL_WATCHLIST
        source = "BP_config.yaml" if config.get("watchlist") else "FULL_WATCHLIST (config empty)"
        logger.info(f"Using watchlist from {source} ({len(watchlist)} symbols)")

    # ---- Start the dashboard server FIRST so the user has something to look at
    # while the scan runs. The server runs in a background thread; the new scan
    # results land on disk when scan_all_markets() finishes, and the user can
    # hit Refresh in the dashboard to see them.
    server_thread = None
    if "--no-open" not in sys.argv and DASHBOARD_FILE.exists():
        if "--no-serve" in sys.argv:
            dashboard_path = str(DASHBOARD_FILE)
            print(f"  Opening dashboard (file://): {dashboard_path}")
            print(f"  {YELLOW}NOTE: file:// blocks JSON fetch in modern browsers.{RESET}")
            if sys.platform == "win32":
                os.startfile(dashboard_path)
            else:
                webbrowser.open(DASHBOARD_FILE.as_uri())
        else:
            server_thread = _start_server_in_background(SCRIPT_DIR, port=8765)

    # ---- Run scan ----
    try:
        results = scan_all_markets(config, watchlist)
    except Exception as exc:
        logger.error(f"Fatal scan error: {traceback.format_exc()}")
        print(f"\n{RED}FATAL ERROR: {exc}{RESET}")
        if server_thread is not None:
            server_thread.shutdown()
        sys.exit(1)

    # ---- Save results ----
    save_results(results)

    # ---- Slim committable artifact (non-default profiles only) ----
    # The full scan_results.json carries a ~30MB OHLCV cache and is never
    # committed. The slim file (signals + account summary) is what the
    # TradingView Ideas workflow reads from the all-coins GitHub runner.
    if PROFILE_SUFFIX:
        _write_slim_artifact(results)

    # ---- Print summary ----
    print_summary(results)

    # ---- Send Discord notification (fires immediately, BEFORE the dashboard
    # server blocks the main thread). Only triggers when DISCORD_WEBHOOK_URL
    # is set in the environment. send_discord.py decides whether to @-ping
    # the user based on whether there are NEW signals; --always-send makes
    # sure a "no signals" status message still posts each scan. ----
    if os.environ.get("DISCORD_WEBHOOK_URL"):
        try:
            import subprocess
            print(f"  {CYAN}Sending Discord notification...{RESET}")
            # Pass the profile suffix so send_discord.py reads THIS profile's
            # scan_results / discord_state (not the FundingPips defaults).
            _denv = os.environ.copy()
            _denv["AZALYST_STATE_SUFFIX"] = PROFILE_SUFFIX
            subprocess.run(
                [sys.executable, str(SCRIPT_DIR / "send_discord.py"), "--always-send"],
                check=False,
                cwd=str(SCRIPT_DIR),
                env=_denv,
            )
        except Exception as exc:
            logger.warning(f"Discord notification failed: {exc}")

    print(f"  {DIM}Log file: {LOG_FILE}{RESET}")
    print()

    # ---- Block until Ctrl-C so the dashboard server stays up ----
    if server_thread is not None:
        print(f"  {GREEN}Refresh the dashboard tab to see the latest scan.{RESET}")
        print(f"  {DIM}Press Ctrl-C in this window to stop the server.{RESET}")
        try:
            server_thread.serve_until_interrupted()
        except KeyboardInterrupt:
            print(f"\n  {DIM}Dashboard server stopped.{RESET}")


class _DashboardServer:
    """Background HTTP server for the dashboard. The server runs in a worker
    thread immediately so the browser can paint stale-but-real data while the
    scan is in progress; the main thread blocks at the end via
    serve_until_interrupted() to keep the server alive.
    """

    def __init__(self, server, thread):
        self._server = server
        self._thread = thread

    def shutdown(self):
        try:
            self._server.shutdown()
        except Exception:
            pass
        self._server.server_close()

    def serve_until_interrupted(self):
        try:
            while self._thread.is_alive():
                self._thread.join(timeout=0.5)
        except KeyboardInterrupt:
            self.shutdown()
            raise


def _start_server_in_background(serve_dir: Path, port: int = 8765):
    """Bind a localhost HTTP server and open the dashboard. Returns a
    _DashboardServer handle, or None on bind failure.
    """
    import http.server
    import socketserver
    import functools
    import threading

    class _QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args, **kwargs):
            return

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

    handler = functools.partial(_QuietHandler, directory=str(serve_dir))
    socketserver.TCPServer.allow_reuse_address = True

    chosen_port = port
    server = None
    for _ in range(10):
        try:
            server = socketserver.TCPServer(("127.0.0.1", chosen_port), handler)
            break
        except OSError:
            chosen_port += 1
    if server is None:
        print(f"  {RED}Could not bind a local port near {port}. Open dashboard manually.{RESET}")
        return None

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{chosen_port}/dashboard.html"
    print(f"  {GREEN}Dashboard live at {url}{RESET}")
    print(f"  {DIM}(scan is running in this window -- dashboard shows previous results until it finishes){RESET}")
    try:
        webbrowser.open(url)
    except Exception:
        pass

    return _DashboardServer(server, thread)


if __name__ == "__main__":
    main()
