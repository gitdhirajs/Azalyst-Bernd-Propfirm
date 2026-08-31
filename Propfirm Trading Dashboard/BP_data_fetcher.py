"""Data fetching module - Yahoo Finance for price data, CFTC for COT data."""

import time
import os
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Real CFTC Socrata endpoint (legacy futures-only report).
# Field names returned here match the keys the parser expects.
CFTC_URL = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"

# When a futures contract is unreachable on yfinance, fall back to a liquid
# ETF/index proxy that tracks the same underlying. Used only for price action;
# COT is still keyed off the futures CFTC code.
FUTURES_PROXY = {
    "ES=F": "SPY",
    "NQ=F": "QQQ",
    "YM=F": "DIA",
    "RTY=F": "IWM",  # iShares Russell 2000 ETF
    "ZB=F": "TLT",
    "ZN=F": "IEF",
    "GC=F": "GLD",
    "SI=F": "SLV",
    "CL=F": "USO",
    "NG=F": "UNG",
    "CC=F": "NIB",    # iPath Bloomberg Cocoa Subindex ETN
    "KC=F": "JO",     # iPath Bloomberg Coffee Subindex ETN
    "SB=F": "SGG",    # iPath Bloomberg Sugar Subindex ETN (note: SGG tracks sugar)
    "CT=F": "BAL",    # iPath Bloomberg Cotton Subindex ETN
    "6E=F": "FXE",
    "6B=F": "FXB",
    "6J=F": "FXY",
    "6A=F": "FXA",
    "6C=F": "FXC",
    "6S=F": "FXF",
    "DX-Y.NYB": "UUP",
}


class DataFetcher:
    """Fetches OHLCV data from Yahoo Finance and COT data from CFTC.

    Phase 25 fix (DeepSeek P0): COT simulation is now OPT-IN. Default behaviour
    on CFTC API failure is to return an empty DataFrame, which makes the rules
    engine treat COT bias as 'neutral' for that symbol. This prevents random
    synthetic data from triggering false trade signals in live execution.

    To re-enable simulation for development/testing only, instantiate with
    `DataFetcher(allow_cot_simulation=True)`.
    """

    # Default on-disk location for pinned CFTC snapshots (see cot_snapshot_dir).
    DEFAULT_COT_SNAPSHOT_DIR = Path(__file__).parent / "cot_snapshot"
    DEFAULT_OHLCV_SNAPSHOT_DIR = Path(__file__).parent / "ohlcv_snapshot"

    def __init__(
        self,
        allow_cot_simulation: bool = False,
        full_history_cot: bool = False,
        cot_snapshot_dir: Optional[str] = None,
        cot_snapshot_mode: str = "off",
        ohlcv_snapshot_dir: Optional[str] = None,
        ohlcv_snapshot_mode: str = "off",
    ):
        # OHLCV pinning: same off/write/read contract as the COT snapshot.
        # Yahoo revises history (roll splicing, split/dividend adjustment) and
        # fails intermittently, so unpinned price data makes regression scores
        # drift on rerun exactly the way CFTC revisions did.
        if ohlcv_snapshot_mode not in ("off", "write", "read", "fill"):
            raise ValueError(
                f"ohlcv_snapshot_mode must be off/write/read/fill, got {ohlcv_snapshot_mode!r}")
        self.ohlcv_snapshot_mode = ohlcv_snapshot_mode
        self.ohlcv_snapshot_dir = Path(ohlcv_snapshot_dir) if ohlcv_snapshot_dir \
            else self.DEFAULT_OHLCV_SNAPSHOT_DIR
        # --- CFTC snapshot pinning ------------------------------------------
        # The CFTC REVISES historical positioning data, so the same (code, date)
        # can return a different net position months later. That makes any
        # COT-dependent regression test non-reproducible: goldtest scores drift
        # even with zero code changes. Verified concretely -- GC=F 2023-08-26
        # was recorded during Phase 18 as comm_idx_26w=68.59 / 156w=86.32, but
        # today the same date/window returns 97.96 / 77.24 from the live API.
        #
        # cot_snapshot_mode:
        #   "off"   -- always hit the live CFTC API (default; live scanning)
        #   "write" -- hit the API, then persist each result to disk
        #   "read"  -- read ONLY from disk; never touch the network. Use this
        #              for regression tests so results are byte-reproducible.
        #              A missing snapshot returns empty (treated as neutral)
        #              rather than silently falling back to live data.
        if cot_snapshot_mode not in ("off", "write", "read", "fill"):
            raise ValueError(
                f"cot_snapshot_mode must be off/write/read/fill, got {cot_snapshot_mode!r}")
        self.cot_snapshot_mode = cot_snapshot_mode
        self.cot_snapshot_dir = Path(cot_snapshot_dir) if cot_snapshot_dir \
            else self.DEFAULT_COT_SNAPSHOT_DIR

        self.allow_cot_simulation = allow_cot_simulation
        # When True, fetch_cot_data() transparently calls fetch_cot_full_history()
        # so the COT normalization (rolling 52w / 156w extremes / all-time bands)
        # runs against the complete CFTC dataset (~30-40 years for major contracts)
        # instead of the default 260-week (5-year) window.
        # Bernd: "pull as much data as you can."
        # Trade-off: ~1-2 seconds extra per unique CFTC code on first call;
        # subsequent calls hit the in-process cache instantly.
        self.full_history_cot = full_history_cot
        self._cot_cache: Dict[str, pd.DataFrame] = {}
        # Cache OHLCV by (symbol, interval, period) so repeat calls within one
        # scan (valuation refs reused across symbols) don't hammer Yahoo.
        self._ohlcv_cache: Dict[Tuple[str, str, str], pd.DataFrame] = {}

    def fetch_ohlcv(
        self,
        symbol: str,
        interval: str = "1d",
        period: str = "2y",
        start: Optional[str] = None,
        end: Optional[str] = None,
        retries: int = 4,
        allow_proxy: bool = False,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV data from Yahoo Finance with retry-with-backoff and
        an in-memory cache.

        allow_proxy (default False): when True and the primary symbol returns
        nothing, fall back to a registered ETF proxy (FUTURES_PROXY). The proxy
        trades at a DIFFERENT absolute price scale (e.g. GC=F~2400 vs GLD~220,
        YM=F~44000 vs DIA~440), so it is ONLY safe for series consumed as
        RATE-OF-CHANGE / relative references (Valuation, seasonality, index
        constituents). It is NEVER safe for the TRADABLE instrument whose
        absolute entry/stop/target/lot are placed on the FundingPips ticket —
        a mis-scaled level would compute a ~10x-too-large position. So the
        primary fetch_multi_timeframe path leaves allow_proxy=False: a dropped
        futures feed yields an empty frame -> no signal (fail-safe) rather than
        a plausible-but-mis-scaled one. (Audit rank 2.)

        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume.
            Empty DataFrame when no data is available after all retries.
        """
        # 2026-08 FTW audit C-51 (CRITICAL) — the cache key used to omit
        # `allow_proxy`, which silently defeated the fail-safe documented above.
        # A reference fetch (allow_proxy=True) that fell back to an ETF proxy
        # stored GLD bars under the key ('GC=F', ...); the later TRADABLE fetch
        # for GC=F (allow_proxy=False) hit that same key and was served proxy
        # data from cache WITHOUT any network call or warning. Entry/stop/target
        # were then computed on ~$310 GLD bars instead of ~$3,400 gold, and
        # because lot size is risk-budget / stop-distance, the position came out
        # roughly an order of magnitude too large — on a real FundingPips ticket.
        #
        # Two changes below:
        #  1. `allow_proxy` is part of the key, so a proxy-allowed entry can
        #     never satisfy a proxy-forbidden request.
        #  2. PRIMARY data (no proxy fallback taken) is valid for both modes, so
        #     it is written under both keys; PROXY data is written ONLY under the
        #     allow_proxy=True key. This keeps the cache-hit rate for references
        #     while making proxy leakage into the tradable path impossible.
        # Also fixed: start/end now take precedence in the key, matching
        # _fetch_one's own precedence (period defaults to "2y" and is never
        # falsy, so a bounded slice used to be cached under the unbounded key).
        _scope = (start, end) if (start and end) else period
        cache_key = (symbol, interval, _scope, allow_proxy)
        if cache_key in self._ohlcv_cache:
            return self._ohlcv_cache[cache_key].copy()

        # --- OHLCV snapshot pinning (mirrors the COT mechanism) -------------
        # Yahoo revises/re-splices history (continuous-futures rolls, split and
        # dividend adjustments) and intermittently fails outright, so a rerun of
        # the same test can score differently with zero code changes. In "read"
        # mode we serve only pinned bars and never touch the network; a missing
        # pin returns empty (-> no signal, fail-safe) rather than silently
        # falling back to live data.
        _snap_key = self._ohlcv_snap_key(symbol, interval, _scope, allow_proxy)
        if self.ohlcv_snapshot_mode == "fill":
            _cached = self._read_ohlcv_snapshot(_snap_key)
            if _cached is not None:
                self._ohlcv_cache[cache_key] = _cached
                return _cached.copy()
        if self.ohlcv_snapshot_mode == "read":
            snap = self._read_ohlcv_snapshot(_snap_key)
            if snap is None:
                logger.warning(
                    "OHLCV snapshot missing for %s (mode=read) — returning empty. "
                    "Run build_ohlcv_snapshot.py to create it.", _snap_key)
                return pd.DataFrame()
            self._ohlcv_cache[cache_key] = snap
            return snap.copy()

        df = self._fetch_one(symbol, interval, period, start, end, retries)
        used_proxy = False
        if df.empty and allow_proxy and symbol in FUTURES_PROXY:
            proxy = FUTURES_PROXY[symbol]
            logger.warning(
                f"{symbol} unreachable, falling back to REFERENCE proxy {proxy} "
                f"(allow_proxy=True — valid for ROC/valuation refs only, never a tradable)"
            )
            df = self._fetch_one(proxy, interval, period, start, end, retries)
            used_proxy = not df.empty

        if not df.empty:
            self._ohlcv_cache[(symbol, interval, _scope, True)] = df.copy()
            if not used_proxy:
                # genuine primary data — safe for the tradable path too
                self._ohlcv_cache[(symbol, interval, _scope, False)] = df.copy()
            # Pin under the key actually requested. Proxy-derived bars are only
            # ever written under the allow_proxy=True key, preserving the C-51
            # guarantee that proxy data can never satisfy a tradable request.
            self._write_ohlcv_snapshot(
                self._ohlcv_snap_key(symbol, interval, _scope,
                                     True if used_proxy else allow_proxy), df)
        return df

    def _fetch_one(
        self,
        symbol: str,
        interval: str,
        period: Optional[str],
        start: Optional[str],
        end: Optional[str],
        retries: int,
    ) -> pd.DataFrame:
        import socket as _socket
        backoff = 3.0
        for attempt in range(retries):
            try:
                # Hard socket timeout so TCP hangs don't block indefinitely.
                # yfinance doesn't expose a requests timeout, so we set it at
                # the OS socket level.  30s is enough for any normal response.
                _prev_timeout = _socket.getdefaulttimeout()
                _socket.setdefaulttimeout(30)
                try:
                    ticker = yf.Ticker(symbol)
                    if start and end:
                        df = ticker.history(start=start, end=end, interval=interval, auto_adjust=False)
                    else:
                        df = ticker.history(period=period, interval=interval, auto_adjust=False)
                finally:
                    _socket.setdefaulttimeout(_prev_timeout)

                if df is None or df.empty:
                    if attempt < retries - 1:
                        time.sleep(backoff ** attempt)
                        continue
                    logger.warning(f"No data returned for {symbol} ({interval})")
                    return pd.DataFrame()

                df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
                df.columns = ['open', 'high', 'low', 'close', 'volume']
                df.index.name = 'timestamp'
                df.reset_index(inplace=True)
                return df
            except Exception as e:
                if attempt < retries - 1:
                    time.sleep(backoff ** attempt)
                    continue
                logger.error(f"Error fetching {symbol} ({interval}): {e}")
                return pd.DataFrame()
        return pd.DataFrame()

    def fetch_multi_timeframe(
        self,
        symbol: str,
        timeframes: List[str] = ["1wk", "1d", "4h"]
    ) -> Dict[str, pd.DataFrame]:
        """Fetch data for multiple timeframes."""
        results = {}
        for tf in timeframes:
            if tf in ['1mo', '1wk']:
                period = '10y'
            elif tf == '1d':
                period = '5y'
            elif tf in ('60m', '30m', '15m', '5m', '1m'):
                # Yahoo hard limit: 1h data only available for last 730 days.
                # Use 729d to stay safely within the window.
                period = '729d'
            else:
                period = '2y'

            df = self.fetch_ohlcv(symbol, interval=tf, period=period)
            if not df.empty:
                results[tf] = df

        return results

    def fetch_cot_data(self, cftc_code: str = "") -> pd.DataFrame:
        """
        Fetch COT (Commitment of Traders) data from the CFTC public dataset.

        Phase 25 (DeepSeek P0 fix): on CFTC API failure, returns an empty
        DataFrame rather than synthetic random data. The rules engine treats
        an empty COT DataFrame as 'neutral' bias — safer than feeding random
        signal into a live prop-firm account. Simulation can be re-enabled
        ONLY by passing `allow_cot_simulation=True` to DataFetcher (intended
        for development/testing of indicator math, never for live signals).

        When `cftc_code` is empty (symbol has no COT report -- e.g. forex
        crosses, individual stocks, XRP), return an empty DataFrame so the
        rules engine treats COT bias as `neutral` instead of pulling Gold COT
        as a Wrong Default.
        """
        if not cftc_code:
            return pd.DataFrame()

        # --- snapshot pinning (see __init__ for rationale) -------------------
        # Keyed by code AND history depth: the 260-week and full-history pulls
        # are different datasets and must never share a snapshot file.
        _snap_key = f"{cftc_code}_{'full' if self.full_history_cot else '260w'}"
        if self.cot_snapshot_mode == "fill":
            # Resumable pin build: reuse an existing pin, else fetch it below.
            _cached = self._read_cot_snapshot(_snap_key)
            if _cached is not None:
                return _cached
        if self.cot_snapshot_mode == "read":
            df = self._read_cot_snapshot(_snap_key)
            if df is None:
                logger.warning(
                    "COT snapshot missing for %s (mode=read) — returning empty; "
                    "COT bias will be neutral. Run build_cot_snapshot.py to create it.",
                    _snap_key)
                return pd.DataFrame()
            return df

        # full_history_cot mode: transparently delegate to the paginated
        # full-history fetch so the scanner uses 30+ years of CFTC data for
        # all COT normalization and extreme detection (Bernd: "pull as much
        # data as you can").  The full-history cache key is distinct so the
        # standard 260-week cache is never evicted.
        if self.full_history_cot:
            return self.fetch_cot_full_history(cftc_code)

        if cftc_code in self._cot_cache:
            return self._cot_cache[cftc_code]

        import requests
        params = {
            "$where": f"cftc_contract_market_code='{cftc_code}'",
            "$order": "report_date_as_yyyy_mm_dd DESC",
            "$limit": 260,  # ~5 years of weekly reports
        }
        # Retry a couple of times with a short delay: a transient CFTC/Socrata
        # hiccup must NOT poison the whole scan by caching an empty (neutral)
        # COT for this code. Only NON-empty frames are cached (mirrors OHLCV).
        for _attempt in range(3):
            try:
                resp = requests.get(CFTC_URL, params=params, timeout=20)
                if resp.status_code == 200:
                    data = resp.json()
                    if data:
                        records = []
                        for entry in data:
                            records.append({
                                'date':         entry.get('report_date_as_yyyy_mm_dd'),
                                'comm_long':    int(float(entry.get('comm_positions_long_all', 0) or 0)),
                                'comm_short':   int(float(entry.get('comm_positions_short_all', 0) or 0)),
                                'noncomm_long': int(float(entry.get('noncomm_positions_long_all', 0) or 0)),
                                'noncomm_short':int(float(entry.get('noncomm_positions_short_all', 0) or 0)),
                                'nonrep_long':  int(float(entry.get('nonrept_positions_long_all', 0) or 0)),
                                'nonrep_short': int(float(entry.get('nonrept_positions_short_all', 0) or 0)),
                            })
                        df = pd.DataFrame(records)
                        df['date'] = pd.to_datetime(df['date'])
                        df.set_index('date', inplace=True)
                        df.sort_index(inplace=True)
                        self._cot_cache[cftc_code] = df
                        self._write_cot_snapshot(f"{cftc_code}_260w", df)
                        logger.info(f"COT live data loaded for {cftc_code}: {len(df)} weeks")
                        return df
                    # HTTP 200 with no rows: a definitive "no data", not transient.
                    logger.warning(f"CFTC returned empty result for {cftc_code}")
                    break
                logger.warning(f"CFTC HTTP {resp.status_code} for {cftc_code} (attempt {_attempt + 1}/3)")
            except Exception as e:
                logger.warning(f"CFTC API fetch failed for {cftc_code} (attempt {_attempt + 1}/3): {e}")
            if _attempt < 2:
                time.sleep(2.0)

        # Phase 25 (DeepSeek P0): default to empty DataFrame on fetch failure.
        # Simulation is opt-in via DataFetcher(allow_cot_simulation=True) for
        # development only. Live trading must NEVER use synthetic COT data
        # because random extremes could trigger trades on noise.
        if self.allow_cot_simulation:
            logger.warning(
                f"COT for {cftc_code}: USING SIMULATED DATA "
                f"(allow_cot_simulation=True; for development only)"
            )
            df = self._simulate_cot_data(cftc_code)
            self._cot_cache[cftc_code] = df
            return df
        # Live path: return empty WITHOUT caching, so a later scan can retry a
        # transient failure instead of being pinned to neutral for this code.
        logger.warning(
            f"COT for {cftc_code}: live fetch failed; returning empty DataFrame "
            f"(rules engine treats as neutral). Not cached — will retry next scan."
        )
        return pd.DataFrame()

    # ------------------------------------------------------------------
    # CFTC snapshot pinning helpers
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # OHLCV snapshot pinning helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _ohlcv_snap_key(symbol, interval, scope, allow_proxy) -> str:
        """Filesystem-safe key. `scope` is either (start,end) or a period str."""
        import re as _re
        scope_s = f"{scope[0]}_{scope[1]}" if isinstance(scope, tuple) else str(scope)
        raw = f"{symbol}__{interval}__{scope_s}__{'proxy' if allow_proxy else 'primary'}"
        return _re.sub(r"[^A-Za-z0-9_.=-]", "-", raw)

    def _ohlcv_snapshot_path(self, snap_key: str) -> Path:
        return self.ohlcv_snapshot_dir / f"{snap_key}.csv"

    def _read_ohlcv_snapshot(self, snap_key: str) -> Optional[pd.DataFrame]:
        path = self._ohlcv_snapshot_path(snap_key)
        if not path.exists():
            return None
        try:
            df = pd.read_csv(path)
            if "timestamp" in df.columns:
                # Pins are stored as naive local wall-clock (see _write_ohlcv_snapshot).
                # utc=True guards against any legacy tz-aware file with mixed
                # DST offsets, which pandas otherwise refuses to parse.
                try:
                    df["timestamp"] = pd.to_datetime(df["timestamp"])
                except Exception:
                    df["timestamp"] = pd.to_datetime(
                        df["timestamp"], utc=True, format="ISO8601").dt.tz_localize(None)
            return df
        except Exception as exc:  # pragma: no cover
            logger.error("OHLCV snapshot %s unreadable: %s", path.name, exc)
            return None

    def _write_ohlcv_snapshot(self, snap_key: str, df: pd.DataFrame) -> None:
        if self.ohlcv_snapshot_mode not in ("write", "fill") or df is None or df.empty:
            return
        try:
            self.ohlcv_snapshot_dir.mkdir(parents=True, exist_ok=True)
            out = df.copy()
            # Store NAIVE local wall-clock. yfinance returns tz-aware stamps whose
            # UTC offset flips with DST, and a CSV round-trip of mixed offsets is
            # unparseable. Every consumer calls tz_localize(None) before comparing
            # dates anyway, so stripping tz here makes a pinned read byte-identical
            # to a live fetch instead of shifting bars by the UTC offset.
            if "timestamp" in out.columns:
                _ts = pd.to_datetime(out["timestamp"])
                if getattr(_ts.dt, "tz", None) is not None:
                    out["timestamp"] = _ts.dt.tz_localize(None)
            # Atomic write: 6 parallel pin builders share reference series
            # (ZB=F / GC=F / DXY), so a plain to_csv lets one process read a file
            # another is mid-write -- observed as "No columns to parse from file".
            # Write to a unique temp file then rename (atomic on the same volume).
            _final = self._ohlcv_snapshot_path(snap_key)
            _tmp = _final.with_suffix(f".tmp{os.getpid()}")
            out.to_csv(_tmp, index=False)
            os.replace(_tmp, _final)
        except Exception as exc:  # pragma: no cover
            logger.error("Failed writing OHLCV snapshot %s: %s", snap_key, exc)

    def _cot_snapshot_path(self, snap_key: str) -> Path:
        return self.cot_snapshot_dir / f"cot_{snap_key}.csv"

    def _read_cot_snapshot(self, snap_key: str) -> Optional[pd.DataFrame]:
        """Load a pinned snapshot. Returns None when absent/unreadable so the
        caller can decide (we return empty -> neutral, never silent live data)."""
        path = self._cot_snapshot_path(snap_key)
        if not path.exists():
            return None
        try:
            df = pd.read_csv(path, parse_dates=["date"], index_col="date")
            df.sort_index(inplace=True)
            return df
        except Exception as exc:  # pragma: no cover - corrupt file is rare
            logger.error("COT snapshot %s unreadable: %s", path.name, exc)
            return None

    def _write_cot_snapshot(self, snap_key: str, df: pd.DataFrame) -> None:
        """Persist a freshly fetched COT frame when snapshot_mode == 'write'."""
        if self.cot_snapshot_mode not in ("write", "fill") or df is None or df.empty:
            return
        try:
            self.cot_snapshot_dir.mkdir(parents=True, exist_ok=True)
            path = self._cot_snapshot_path(snap_key)
            out = df.copy()
            out.index.name = "date"
            _tmp = path.with_suffix(f".tmp{os.getpid()}")
            out.to_csv(_tmp)
            os.replace(_tmp, path)
            logger.info("COT snapshot written: %s (%d rows)", path.name, len(out))
        except Exception as exc:  # pragma: no cover
            logger.error("Failed writing COT snapshot %s: %s", snap_key, exc)

    def fetch_cot_full_history(self, cftc_code: str = "") -> pd.DataFrame:
        """
        Fetch ALL available CFTC COT history for a given contract code by
        paginating through the entire Socrata dataset (~30+ years for major
        contracts — Gold goes back to 1986, ES to 1992, etc.).

        Bernd's teaching: "pull as much data as you can" when evaluating COT.
        Seeing a position at a 30-year historic extreme is a fundamentally
        stronger signal than a 5-year extreme on the standard 260-week fetch.

        Implementation: paginate with $limit=5000 & $offset=N until the API
        returns fewer records than the page size (last page).

        Returns a complete DataFrame sorted ascending, cached separately from
        the standard 260-week fetch (cache key = f"{cftc_code}_full").
        """
        if not cftc_code:
            return pd.DataFrame()

        cache_key = f"{cftc_code}_full"
        if cache_key in self._cot_cache:
            return self._cot_cache[cache_key]

        try:
            import requests

            all_records = []
            page_size = 5000
            offset = 0

            while True:
                params = {
                    "$where": f"cftc_contract_market_code='{cftc_code}'",
                    "$order": "report_date_as_yyyy_mm_dd ASC",
                    "$limit": page_size,
                    "$offset": offset,
                }
                resp = requests.get(CFTC_URL, params=params, timeout=30)

                if resp.status_code != 200:
                    logger.warning(
                        f"CFTC full-history HTTP {resp.status_code} for {cftc_code} "
                        f"at offset {offset}"
                    )
                    break

                data = resp.json()
                if not data:
                    break  # No more records

                for entry in data:
                    all_records.append({
                        'date':         entry.get('report_date_as_yyyy_mm_dd'),
                        'comm_long':    int(float(entry.get('comm_positions_long_all', 0) or 0)),
                        'comm_short':   int(float(entry.get('comm_positions_short_all', 0) or 0)),
                        'noncomm_long': int(float(entry.get('noncomm_positions_long_all', 0) or 0)),
                        'noncomm_short':int(float(entry.get('noncomm_positions_short_all', 0) or 0)),
                        'nonrep_long':  int(float(entry.get('nonrept_positions_long_all', 0) or 0)),
                        'nonrep_short': int(float(entry.get('nonrept_positions_short_all', 0) or 0)),
                    })

                if len(data) < page_size:
                    break  # Last page — no need to query further
                offset += page_size

            if all_records:
                df = pd.DataFrame(all_records)
                df['date'] = pd.to_datetime(df['date'])
                df.set_index('date', inplace=True)
                df.sort_index(inplace=True)
                # CFTC dataset can have duplicate rows for the same report week
                df = df[~df.index.duplicated(keep='last')]
                self._cot_cache[cache_key] = df
                self._write_cot_snapshot(f"{cftc_code}_full", df)
                years = (df.index[-1] - df.index[0]).days / 365.25
                logger.info(
                    f"COT full history loaded for {cftc_code}: {len(df)} weeks "
                    f"({df.index[0].year}–{df.index[-1].year}, {years:.1f} yrs)"
                )
                return df

            logger.warning(f"CFTC full history: empty result for {cftc_code}")

        except Exception as e:
            logger.warning(f"CFTC full history fetch failed for {cftc_code}: {e}")

        return pd.DataFrame()

    def _simulate_cot_data(self, cftc_code: str, periods: int = 260) -> pd.DataFrame:
        """Generate realistic simulated COT data for development purposes."""
        np.random.seed(hash(cftc_code) % (2**31))
        dates = pd.date_range(end=datetime.now(), periods=periods, freq='W-FRI')
        n = len(dates)

        comm_long = np.zeros(n)
        comm_short = np.zeros(n)
        noncomm_long = np.zeros(n)
        noncomm_short = np.zeros(n)

        base = abs(hash(cftc_code)) % 100000 + 50000
        comm_long[0] = base
        comm_short[0] = base * np.random.uniform(0.7, 1.3)
        noncomm_long[0] = base * np.random.uniform(0.3, 0.6)
        noncomm_short[0] = base * np.random.uniform(0.3, 0.6)

        for i in range(1, n):
            comm_long[i] = comm_long[i-1] + np.random.randn() * base * 0.05
            comm_short[i] = comm_short[i-1] + np.random.randn() * base * 0.05
            noncomm_long[i] = noncomm_long[i-1] + np.random.randn() * base * 0.03
            noncomm_short[i] = noncomm_short[i-1] + np.random.randn() * base * 0.03

            comm_long[i] = comm_long[i] * 0.98 + base * 0.02
            comm_short[i] = comm_short[i] * 0.98 + base * 0.02

        comm_long = np.maximum(comm_long, 0)
        comm_short = np.maximum(comm_short, 0)
        noncomm_long = np.maximum(noncomm_long, 0)
        noncomm_short = np.maximum(noncomm_short, 0)

        total = (comm_long + comm_short + noncomm_long + noncomm_short) * np.random.uniform(0.3, 0.5)
        nonrep_long = total * np.random.uniform(0.4, 0.6)
        nonrep_short = total - nonrep_long

        df = pd.DataFrame({
            'comm_long':     comm_long.astype(int),
            'comm_short':    comm_short.astype(int),
            'noncomm_long':  noncomm_long.astype(int),
            'noncomm_short': noncomm_short.astype(int),
            'nonrep_long':   nonrep_long.astype(int),
            'nonrep_short':  nonrep_short.astype(int),
        }, index=dates)

        return df

    def fetch_seasonality_reference(
        self,
        symbol: str,
        lookback_years: int = 15
    ) -> pd.DataFrame:
        """Fetch long-term historical data for seasonality calculation.

        Seasonality is a detrended cyclical pattern (relative, not absolute),
        so an ETF proxy fallback at a different price scale is acceptable here.
        """
        df = self.fetch_ohlcv(symbol, interval='1d', period=f'{lookback_years}y',
                              allow_proxy=True)
        return df


def get_cftc_code(symbol: str) -> str:
    """Map Yahoo Finance / spot ticker to CFTC commodity code.

    Spot Fundingpips-style tickers (EURUSD=X, BTC-USD, XAUUSD, etc.) are
    mapped to their underlying futures COT code so the COT layer keeps
    working when the OHLCV chart is the broker spot symbol.
    """
    mapping = {
        # ── Futures (canonical) ───────────────────────────────────────
        'GC=F':  '088691',  # Gold
        'SI=F':  '084691',  # Silver
        'HG=F':  '085692',  # Copper
        'PL=F':  '076651',  # Platinum
        'PA=F':  '075651',  # Palladium
        'CL=F':  '067651',  # Crude Oil WTI
        'NG=F':  '023651',  # Natural Gas
        'RB=F':  '111659',  # RBOB Gasoline
        'HO=F':  '022651',  # Heating Oil
        'ES=F':  '13874A',  # S&P 500
        'YM=F':  '124603',  # Dow Jones
        'NQ=F':  '209742',  # Nasdaq 100
        'RTY=F': '239742',  # Russell 2000
        '6E=F':  '099741',  # Euro FX
        '6B=F':  '096742',  # GBP
        '6J=F':  '097741',  # JPY
        '6A=F':  '232741',  # AUD
        '6C=F':  '090741',  # CAD
        '6S=F':  '092741',  # CHF
        '6N=F':  '112741',  # NZD
        'ZB=F':  '020601',  # 30Y Bond
        'ZN=F':  '043602',  # 10Y Note
        'ZC=F':  '002602',  # Corn
        'ZW=F':  '001602',  # Wheat
        'ZS=F':  '005602',  # Soybeans
        'ZL=F':  '007601',  # Soybean Oil
        'CT=F':  '033661',  # Cotton
        'KC=F':  '083731',  # Coffee
        'SB=F':  '080732',  # Sugar
        'CC=F':  '073732',  # Cocoa
        'BTC=F': '133741',  # Bitcoin (CME futures)
        'ETH=F': '146021',  # Ether (CME futures)
        'DX=F':  '098662',  # US Dollar Index (opposing-currency cross-check)

        # ── Spot Fundingpips-style mappings to futures COT ────────────
        # Forex majors (spot=USD on right side -> direct mapping)
        'EURUSD=X': '099741',  # = 6E
        'GBPUSD=X': '096742',  # = 6B
        'AUDUSD=X': '232741',  # = 6A
        'NZDUSD=X': '112741',  # = 6N
        # Forex inverted spot (spot=USD on left, futures=XXX/USD)
        # Same COT code; the rules engine cross-check handles the directional flip
        'USDJPY=X': '097741',  # = 6J (inverted)
        'USDCAD=X': '090741',  # = 6C (inverted)
        'USDCHF=X': '092741',  # = 6S (inverted)
        # Phase 28 COT #8: bare Yahoo forex tickers (Yahoo default form, no USD suffix).
        # Previously fell through to '' and got neutral COT silently.
        'EUR=X': '099741',  # = 6E (EUR/USD)
        'GBP=X': '096742',  # = 6B (GBP/USD)
        'JPY=X': '097741',  # = 6J (USD/JPY inverted)
        'AUD=X': '232741',  # = 6A (AUD/USD)
        'CAD=X': '090741',  # = 6C (USD/CAD inverted)
        'CHF=X': '092741',  # = 6S (USD/CHF inverted)
        'NZD=X': '112741',  # = 6N (NZD/USD)
        # Forex crosses -- no direct COT, fall through to default
        # (rules engine derives bias from each leg's COT separately)

        # Metals spot
        'XAUUSD':   '088691',  # = GC
        'XAUUSD=X': '088691',
        'XAGUSD':   '084691',  # = SI
        'XAGUSD=X': '084691',

        # Crypto spot (CME bitcoin/ether futures COT)
        'BTC-USD': '133741',  # = BTC
        'ETH-USD': '146021',  # = ETH
        # XRP-USD, LTC-USD: no CFTC reportable -> defaults

        # Cash equity indices (use futures COT proxy)
        '^GSPC': '13874A',  # = ES
        '^DJI':  '124603',  # = YM
        '^IXIC': '209742',  # = NQ
        '^RUT':  '239742',  # = RTY

        # Brent crude (separate CFTC reportable from WTI)
        'BZ=F':  '06765T',  # ICE Brent crude
    }
    # Return empty string for unmapped symbols (forex crosses, individual
    # stocks without single-name COT, XRP, etc). Empty -> fetcher returns
    # empty DataFrame -> rules engine treats COT as neutral and bias is
    # derived from Valuation/Seasonality/Location/Trend only.
    return mapping.get(symbol, '')
