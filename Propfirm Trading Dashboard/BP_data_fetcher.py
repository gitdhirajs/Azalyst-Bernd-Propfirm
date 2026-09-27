"""Data fetching module - Yahoo Finance for price data, CFTC for COT data."""

import time
import os
import re
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


# ===========================================================================
# Price-data hygiene (2026-09-27 audit of the live FundingPips paper account)
# ===========================================================================
# Every fix below has an environment kill switch that defaults ON, so each one
# can be measured by paired A/B. Setting the variable to "0" restores the old
# frame exactly:
#   BP_FX_CLOSE_REPAIR=0  -- keep Yahoo's broken daily FX Close        (defect 1)
#   BP_DROP_STUB_BARS=0   -- keep weekend stub bars and non-finite OHLC
#                            rows                                  (defects 7, 8)
#   BP_FX_WEEKLY_REPAIR=1 -- OPT-IN: repair weekly/monthly FX High/Low/Close
#                            (found 2026-09-27, see below; default OFF until A/B-measured)
# To A/B one of them alone, leave the others at their default in both arms.
# The `is_complete` column (defect 2) is data, not behaviour: its consumer
# (BP_zone_detector.completed_bars) owns the switch, BP_COMPLETED_BARS=0.

def _flag_on(name: str) -> bool:
    return os.environ.get(name, "1") != "0"


def _utcnow() -> pd.Timestamp:
    """Wall clock in UTC. A module function so tests can pin 'now'."""
    return pd.Timestamp.now(tz="UTC")


# Column contract of fetch_bars_since (and of every fetch_ohlcv frame, which
# additionally carries `is_complete` on 1d / 1wk frames).
BAR_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
_OHLC = ["open", "high", "low", "close"]

# How long one bar lasts, for "has the last bar finished forming?" (defect 2).
_COMPLETE_SPAN = {"1d": pd.Timedelta(days=1), "1wk": pd.Timedelta(days=7)}

# Yahoo's intraday history depth, in days. 60m is documented at 730 days; 729
# keeps the same safety margin fetch_multi_timeframe already uses.
_INTRADAY_MAX_DAYS = {"1m": 7, "2m": 59, "5m": 59, "15m": 59, "30m": 59,
                      "90m": 59, "60m": 729, "1h": 729}

# --- Defect 1: Yahoo daily FX Close is (nearly) a copy of the Open ----------
# Measured 2026-09-27 against the TRUE London-day candle built from Yahoo 1h
# bars (Europe/London), last 2 years, ~517 complete days per pair, medians
# (scratchpad smoke_fx_close.py; "next Open" = what pinned/goldtest reads get,
# "live" = next Open + the 1h refinement below):
#               body% yahoo/true   |close err|/range: yahoo  next Open  live
#   EURUSD=X      0.000 / 0.452                     0.429    0.064   0.046
#   NZDUSD=X      0.016 / 0.500                     0.501    0.061   0.041
#   USDJPY=X      0.000 / 0.483                     0.476    0.054   0.030
#   GBPAUD=X      0.000 / 0.440                     0.446    0.040   0.028
# Repaired body% 0.46-0.51 (true 0.44-0.50). Open/High/Low are fine (0.02-0.05
# of range). With the defect zero daily FX candles in a year were decisive
# (body > 50%), so the body-% zone rules could only ever read the still-forming
# bar -- whose Open is real -- as a leg-out.
#
# Which series: all 13 "=X" pairs measured (majors and crosses) have it.
# DX-Y.NYB (body 0.478 vs true 0.481), GC=F, CL=F (close err 0.08-0.10 =
# settlement vs last trade, body% intact), BTC-USD and ETH-USD (0.00) do NOT,
# so only "=X" daily frames get this repair. (Weekly/monthly FX bars have a
# DIFFERENT corruption -- see _repair_period_bars.)
#
# When: the defect starts on Yahoo in late July / early August 2010 for every
# pair checked (rolling 41-bar median body% drops from >= 0.20 to <= 0.07 in a
# single step, and stays there through 2026). Pre-2010 closes are genuine, so
# the repair is limited to the defective REGIME (see _defective_close_mask):
# pinned 2008-2023 goldtest frames keep their real early history.
#
# Weak spot: a bar followed by a GAP (Friday -> Monday). Its next Open carries
# the weekend gap: |close err|/range 0.12-0.15 on Fridays vs 0.03-0.06 on
# Mon-Thu, and 28-35% of Friday candles change body class (12-18% change
# colour) versus 11-13% (2-4%) on other days. In live mode (snapshot mode
# "off") gap bars, and the last bar, therefore take the last completed 1h
# close of their own London day instead (Friday error -> 0.00-0.04). In
# pinned/historical frames the Friday close is still the Monday Open, i.e. it
# includes the Sunday-evening gap: a small look-ahead for a backtest that cuts
# a full-period frame on a weekend (a frame that ENDS on the Friday is not
# affected -- its last bar has no next Open and is flagged incomplete).
_CLOSE_DEFECT_BODY_MAX = 0.15   # regime threshold; measured gap is 0.07 .. 0.20
_CLOSE_DEFECT_WINDOW = 41       # rolling bars (~2 months) for the regime test


def _has_daily_close_defect(symbol: str) -> bool:
    """Only Yahoo spot FX ("=X") carries the copied-Open daily Close."""
    return str(symbol).upper().endswith("=X")


def _ts_series(df: pd.DataFrame) -> Optional[pd.Series]:
    if df is None or "timestamp" not in df.columns:
        return None
    try:
        return pd.to_datetime(df["timestamp"])
    except Exception:
        return None


def _as_utc(ts) -> Optional[pd.Timestamp]:
    """Timestamp/datetime/str -> tz-aware UTC. Naive values are taken as UTC."""
    if ts is None:
        return None
    try:
        t = pd.Timestamp(ts)
    except Exception:
        return None
    if t is pd.NaT:
        return None
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _utc_index(ts: pd.Series) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(ts)
    return idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")


def _interval_timedelta(interval: str) -> Optional[pd.Timedelta]:
    """"60m" -> 1h, "1h" -> 1h, "1d" -> 1 day, "1wk" -> 7 days. None if unknown."""
    m = re.fullmatch(r"(\d+)(m|h|d|wk)", str(interval).strip())
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    return {"m": pd.Timedelta(minutes=n), "h": pd.Timedelta(hours=n),
            "d": pd.Timedelta(days=n), "wk": pd.Timedelta(weeks=n)}[unit]


def _is_intraday(interval: str) -> bool:
    return str(interval).endswith(("m", "h")) and not str(interval).endswith("mo")


def _drop_bad_rows(df: pd.DataFrame, interval: str, symbol: str = "") -> pd.DataFrame:
    """Defects 7 + 8: drop non-finite OHLC rows and weekend stub bars.

    Non-finite: a NaN last close bypassed the engine's distance gate (every
    NaN comparison is False) and created the fake CL=F order. Any row with a
    NaN/inf open/high/low/close is dropped, on every interval.

    Weekend stubs: Yahoo appends a zero-volume placeholder dated Saturday or
    Sunday (the frame's own time zone) to FX daily series. Measured over 5 years
    of daily history: 0 of ~1,300 bars per pair are weekend-dated EXCEPT the
    live one at the end, so these are always artifacts. They are not always
    exactly flat -- EURUSD/GBPAUD/EURNZD stubs had 0.6-4.8% of the median daily
    range, and the EURUSD stub's Open was a stale Friday-16:00 price -- so on
    daily frames "stub" means weekend-dated, zero volume and a range of at most
    10% of the frame's median range. Crypto weekend bars carry volume and are
    kept. Intraday frames use the strict form (O==H==L==C, zero volume,
    weekend-dated). Weekly/monthly bars are never stubs (a monthly bar can be
    dated on a Saturday the 1st).
    """
    if df is None or df.empty or not all(c in df.columns for c in _OHLC):
        return df
    ohlc = df[_OHLC].apply(pd.to_numeric, errors="coerce")
    finite = pd.Series(np.isfinite(ohlc.to_numpy(dtype=float)).all(axis=1),
                       index=df.index)
    stub = pd.Series(False, index=df.index)
    ts = _ts_series(df)
    daily = interval == "1d"
    if ts is not None and (daily or _is_intraday(interval)):
        weekend = pd.Series(ts.dt.dayofweek.to_numpy() >= 5, index=df.index)
        vol = (pd.to_numeric(df["volume"], errors="coerce").fillna(0)
               if "volume" in df.columns else pd.Series(0.0, index=df.index))
        rng = ohlc["high"] - ohlc["low"]
        if daily:
            med = rng[finite & (rng > 0)].median()
            tiny = rng <= 0.10 * med if pd.notna(med) and med > 0 else rng <= 0
        else:
            tiny = ((ohlc["high"] == ohlc["low"]) & (ohlc["open"] == ohlc["close"])
                    & (ohlc["open"] == ohlc["high"]))
        stub = weekend & (vol == 0) & tiny & finite
    drop = ~finite | stub
    if drop.any():
        logger.debug("%s %s: dropped %d non-finite OHLC row(s) and %d weekend stub bar(s): %s",
                     symbol, interval, int((~finite).sum()), int(stub.sum()),
                     [str(t) for t in (ts[drop] if ts is not None else [])][:5])
        df = df.loc[~drop].reset_index(drop=True)
    return df


def _defective_close_mask(df: pd.DataFrame) -> np.ndarray:
    """True for bars inside Yahoo's copied-Open regime (see header comment).

    A centred rolling median of body% is compared with 0.15: real FX daily
    bodies never median below 0.20 over 41 bars (2003-2010), defective ones
    never above 0.07 (2011-2026), so the boundary lands on the July/Aug 2010
    onset. Short frames (< 11 bars) use the whole-frame median.
    """
    rng = (df["high"] - df["low"]).astype(float)
    body = (df["close"] - df["open"]).abs().astype(float) / rng.where(rng > 0)
    if len(df) >= 11:
        med = body.rolling(_CLOSE_DEFECT_WINDOW, center=True, min_periods=11).median()
        med = med.fillna(body.median())
    else:
        med = pd.Series(body.median(), index=df.index)
    # an all-flat frame has no body at all -- treat as defective
    return (med.fillna(0.0) < _CLOSE_DEFECT_BODY_MAX).to_numpy()


def _session_last_close(day_starts_utc: pd.DatetimeIndex, hourly: pd.DataFrame,
                        span: pd.Timedelta = pd.Timedelta(days=1)) -> pd.Series:
    """Last hourly close whose bar STARTS inside each daily session.

    Returns a Series indexed by daily row POSITION (only sessions that have at
    least one hourly bar). `hourly` must already be cleaned by _clean_bars:
    completed, finite, stub-free, UTC timestamps, ascending.
    """
    if hourly is None or hourly.empty or len(day_starts_utc) == 0:
        return pd.Series(dtype=float)
    d_ns = day_starts_utc.as_unit("ns").asi8
    h_ns = _utc_index(hourly["timestamp"]).as_unit("ns").asi8
    pos = np.searchsorted(d_ns, h_ns, side="right") - 1
    ok = pos >= 0
    ok &= h_ns < d_ns[np.clip(pos, 0, None)] + span.value
    if not ok.any():
        return pd.Series(dtype=float)
    closes = pd.Series(hourly["close"].to_numpy(dtype=float)[ok])
    return closes.groupby(pos[ok]).last()


def _repair_daily_close(df: pd.DataFrame, hourly: Optional[pd.DataFrame] = None,
                        now_utc: Optional[pd.Timestamp] = None,
                        symbol: str = "") -> Tuple[pd.DataFrame, bool]:
    """Defect 1: rebuild Yahoo's daily FX Close. Returns (frame, last_unrepaired).

    Inside the defective regime:
      * every bar with a next bar: Close[d] := Open[d+1] (the London-day close
        IS the next London-day open for a 24h market), clamped into the bar's
        own [Low, High] because Yahoo's daily Open comes from a slightly
        different feed and a gap would otherwise give body% > 1;
      * if `hourly` is given (live mode): GAP bars (next bar > 1 calendar day
        later, i.e. Friday) take the last completed 1h close of their own
        London day instead of the gap-contaminated Monday Open;
      * the LAST bar has no next Open (the next bar does not exist yet in live
        data, and a pinned frame is cut there). Complete: last completed 1h
        close of its day. Still forming: the latest completed 1h close of its
        day, widening High/Low if Yahoo's live range lags it. With no hourly
        data (snapshot modes, or a failed fetch) it is left untouched and
        reported as `last_unrepaired=True`: its Open/High/Low are real but its
        Close is not, exactly like an unfinished bar, so the caller marks it
        is_complete=False.
    """
    if df is None or df.empty or not all(c in df.columns for c in _OHLC):
        return df, False
    df = df.copy()
    n = len(df)
    bad = _defective_close_mask(df)
    o = df["open"].astype(float)
    h = df["high"].astype(float).copy()
    l = df["low"].astype(float).copy()
    c = df["close"].astype(float)

    new_c = o.shift(-1).clip(lower=l, upper=h)
    new_c = new_c.where(new_c.notna(), c)      # NaN next open -> keep original
    new_c.iloc[n - 1] = c.iloc[n - 1]          # last bar decided below

    ts = _ts_series(df)
    last_unrepaired = bool(bad[n - 1])
    if hourly is not None and not hourly.empty and ts is not None \
            and getattr(ts.dt, "tz", None) is not None:
        starts = _utc_index(ts)
        sess = _session_last_close(starts, hourly)
        local_day = ts.dt.tz_localize(None).dt.normalize()
        gap = ((local_day.shift(-1) - local_day) > pd.Timedelta(days=1)).to_numpy()
        for p in np.flatnonzero(gap & bad):
            if p in sess.index:
                new_c.iloc[p] = min(max(float(sess[p]), l.iloc[p]), h.iloc[p])
        last = n - 1
        if bad[last] and last in sess.index:
            v = float(sess[last])
            now = now_utc if now_utc is not None else _utcnow()
            if starts[last] + pd.Timedelta(days=1) <= now:
                new_c.iloc[last] = min(max(v, l.iloc[last]), h.iloc[last])
            else:
                new_c.iloc[last] = v
                h.iloc[last] = max(h.iloc[last], v)
                l.iloc[last] = min(l.iloc[last], v)
            last_unrepaired = False
    if last_unrepaired:
        logger.debug("%s 1d: last bar close could not be repaired (no hourly data) "
                     "-- flagged is_complete=False", symbol)

    df["close"] = np.where(bad, new_c.to_numpy(), c.to_numpy())
    df["high"] = h.to_numpy()
    df["low"] = l.to_numpy()
    return df, last_unrepaired


# --- Weekly / monthly FX bars: corrupted Low and Close ----------------------
# NOT one of the audited defects -- found while measuring defect 1, contrary to
# the audit's "weekly FX candles are fine" (true for EURUSD, not for crosses).
# Yahoo's COMPLETED weekly FX bars often carry a Low far below anything traded
# that week and a Close outside the week's range (GBPAUD week of 2026-09-14:
# Low = Close = 1.8168 while every daily/1h bar of the week sat 1.873-1.895).
# Measured over 2 years (104 weeks) against the TRUE weekly low built from 1h:
#   |weekly Low - true Low| / range   EURAUD 0.507 (72% of weeks > 0.1),
#   GBPAUD 0.554; the daily bars aggregated into the week: 0.015 (8%).
# Share of weeks where Yahoo's weekly Low/High sits > 10% of range outside the
# daily bars, or its Close lies outside them: GBPAUD 76%, EURAUD 74%, EURNZD
# 30%, AUDNZD 29%, EURGBP 26%, EURCHF 23% ... 18 of the 28 watchlist pairs
# above 10%, EURUSD 5%. The daily High/Low are right (0.02-0.06 vs 1h), so
# weekly/monthly FX bars take High/Low from the daily bars inside them, and the
# Close only when Yahoo's lies outside that range (then: last daily close).
# The Open (0.000 median error) is kept. OPT-IN with BP_FX_WEEKLY_REPAIR=1: it moves
# Stage-1 FX bias on pinned cases (EURUSD 2024-02-19, NZDUSD 2024-01-27) and has not
# been measured on the full set, so it stays off in live until it is.
_PERIOD_MIN_DAILY_BARS = {"1wk": 3, "1mo": 15}


def _repair_period_bars(df: pd.DataFrame, daily: Optional[pd.DataFrame],
                        interval: str, symbol: str = "") -> pd.DataFrame:
    """Rebuild weekly/monthly FX High/Low (and a corrupt Close) from daily bars.

    `daily` must be the same instrument over the same scope (already cleaned
    and Close-repaired). A period is rebuilt only when the daily frame covers
    it from its start and holds enough bars (3 per week, 15 per month) --
    except the last, still-forming period, which the daily frame covers by
    construction. Timestamps must be both tz-aware or both naive (pins).
    """
    if (df is None or df.empty or daily is None or daily.empty
            or not all(c in df.columns for c in _OHLC)
            or not all(c in daily.columns for c in _OHLC)):
        return df
    tw, td = _ts_series(df), _ts_series(daily)
    if tw is None or td is None:
        return df
    aware_w = getattr(tw.dt, "tz", None) is not None
    aware_d = getattr(td.dt, "tz", None) is not None
    if aware_w != aware_d:
        return df
    w_idx = _utc_index(tw) if aware_w else pd.DatetimeIndex(tw)
    d_idx = _utc_index(td) if aware_d else pd.DatetimeIndex(td)
    w_ns = w_idx.as_unit("ns").asi8
    d_ns = d_idx.as_unit("ns").asi8
    nxt = np.empty_like(w_ns)
    nxt[:-1] = w_ns[1:]
    # the last period ends one week/month later in LOCAL wall-clock (DST-safe)
    last_end = pd.Timestamp(tw.iloc[-1]) + (pd.DateOffset(months=1) if interval == "1mo"
                                             else pd.DateOffset(days=7))
    last_end = last_end.tz_convert("UTC") if aware_w else last_end
    nxt[-1] = pd.DatetimeIndex([last_end]).as_unit("ns").asi8[0]
    pos = np.searchsorted(w_ns, d_ns, side="right") - 1
    ok = (pos >= 0) & (d_ns < nxt[np.clip(pos, 0, None)])
    if not ok.any():
        return df
    g = pd.DataFrame({"p": pos[ok],
                      "h": daily["high"].to_numpy(dtype=float)[ok],
                      "l": daily["low"].to_numpy(dtype=float)[ok],
                      "c": daily["close"].to_numpy(dtype=float)[ok]}).groupby("p")
    agg = pd.DataFrame({"h": g["h"].max(), "l": g["l"].min(), "c": g["c"].last(),
                        "n": g["h"].size()})
    min_n = _PERIOD_MIN_DAILY_BARS.get(interval, 3)
    last = len(df) - 1
    covered = (w_ns[agg.index.to_numpy()] >= d_ns[0]) & \
              ((agg["n"].to_numpy() >= min_n) | (agg.index.to_numpy() == last))
    agg = agg[covered]
    if agg.empty:
        return df
    df = df.copy()
    o = df["open"].to_numpy(dtype=float).copy()
    h = df["high"].to_numpy(dtype=float).copy()
    l = df["low"].to_numpy(dtype=float).copy()
    c = df["close"].to_numpy(dtype=float).copy()
    p = agg.index.to_numpy()
    nh, nl, dc = agg["h"].to_numpy(), agg["l"].to_numpy(), agg["c"].to_numpy()
    eps = 1e-9 * np.abs(nh)
    bad_c = (c[p] > nh + eps) | (c[p] < nl - eps)
    changed = int(((np.abs(h[p] - nh) > eps) | (np.abs(l[p] - nl) > eps) | bad_c).sum())
    c[p] = np.where(bad_c, np.clip(dc, nl, nh), c[p])
    h[p] = np.fmax(np.fmax(nh, o[p]), c[p])     # fmax/fmin: a NaN open never wins
    l[p] = np.fmin(np.fmin(nl, o[p]), c[p])
    df["high"], df["low"], df["close"] = h, l, c
    if changed:
        logger.debug("%s %s: rebuilt High/Low/Close of %d of %d bars from daily bars "
                     "(%d corrupt closes)", symbol, interval, changed, len(p), int(bad_c.sum()))
    return df


def _mark_is_complete(df: pd.DataFrame, interval: str, now_utc: pd.Timestamp,
                      from_snapshot: bool, force_last_incomplete: bool = False) -> pd.DataFrame:
    """Defect 2: add `is_complete` to 1d / 1wk frames.

    Rule: every bar that has a later bar is complete. The last bar is complete
    when its start + 1 day (1d) / 7 days (1wk) <= now UTC, `now` being the wall
    clock when the bars were fetched. Frames served from a pinned snapshot are
    history, so all their bars are complete (now = the frame's own end) -- the
    one exception, for either source, is an FX daily last bar whose Close could
    not be repaired (force_last_incomplete).
    """
    span = _COMPLETE_SPAN.get(interval)
    if span is None or df is None or df.empty:
        return df
    flags = np.ones(len(df), dtype=bool)
    ts = _ts_series(df)
    if not from_snapshot and ts is not None:
        last = _as_utc(ts.iloc[-1])
        flags[-1] = last is not None and (last + span) <= now_utc
    if force_last_incomplete:
        flags[-1] = False
    df = df.copy()
    df["is_complete"] = flags
    return df


def _clean_bars(raw: pd.DataFrame, interval: str, now_utc: pd.Timestamp,
                since_utc: Optional[pd.Timestamp] = None,
                drop_stubs: bool = True) -> pd.DataFrame:
    """fetch_bars_since contract: UTC bar starts, completed, finite, no stubs.

    Completed means start + interval <= now_utc (the in-progress bar Yahoo
    appends is partial). A stub is a bar with O==H==L==C and no volume: a
    placeholder, not a trade -- e.g. the FX 22:00-London print after Friday's
    close, or DX-Y.NYB's Sunday pre-open bars (measured: 78 of 128 flat EURUSD
    hours are Friday 21:00 UTC, 40 more Friday 22:00 UTC).
    """
    if raw is None or raw.empty or "timestamp" not in raw.columns:
        return _empty_bars()
    df = raw.copy()
    for col in BAR_COLUMNS[1:]:
        if col not in df.columns:
            df[col] = 0.0 if col == "volume" else np.nan
    df = df[BAR_COLUMNS].copy()
    df["timestamp"] = _utc_index(df["timestamp"]).as_unit("ns")
    for col in BAR_COLUMNS[1:]:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
    keep = pd.Series(np.isfinite(df[_OHLC].to_numpy()).all(axis=1), index=df.index)
    if drop_stubs:
        flat = ((df["open"] == df["high"]) & (df["high"] == df["low"])
                & (df["low"] == df["close"]))
        keep &= ~(flat & (df["volume"].fillna(0) == 0))
    span = _interval_timedelta(interval) or pd.Timedelta(0)
    keep &= (df["timestamp"] + span) <= now_utc
    if since_utc is not None:
        keep &= df["timestamp"] >= since_utc
    df = df.loc[keep].sort_values("timestamp", kind="mergesort")
    df = df.drop_duplicates(subset="timestamp", keep="last").reset_index(drop=True)
    return df


def _empty_bars() -> pd.DataFrame:
    return pd.DataFrame({
        "timestamp": pd.Series(dtype="datetime64[ns, UTC]"),
        "open": pd.Series(dtype=float), "high": pd.Series(dtype=float),
        "low": pd.Series(dtype=float), "close": pd.Series(dtype=float),
        "volume": pd.Series(dtype=float),
    })


def clean_ohlcv_frame(df: pd.DataFrame, symbol: str, interval: str,
                      daily: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Offline hygiene for a pinned OHLCV frame read WITHOUT DataFetcher.

    Applies exactly what fetch_ohlcv applies to a snapshot read (stub/NaN
    drop, FX daily Close repair, is_complete), never touching the network.
    For scripts that pd.read_csv pins directly (goldtest/expectancy.py,
    goldtest/replay_trades.py) so they see the same candles as the engine.
    Weekly/monthly FX frames are only repaired when the matching daily frame
    is passed as `daily`.
    """
    return DataFetcher._post_process_frame(df, symbol, interval, from_snapshot=True,
                                           hourly=None, now_utc=_utcnow(), daily=daily)


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
        # 1h bars used to repair the FX daily Close (defect 1), fetched once per
        # symbol per process: symbol -> cleaned hourly frame (may be empty).
        self._repair_hourly: Dict[str, pd.DataFrame] = {}
        # (symbol, interval) -> ETF proxy that actually served it this process,
        # so fetch_bars_since(allow_proxy=True) prices against the same series.
        self._proxy_served: Dict[Tuple[str, str], str] = {}

    # Depth of the 1h history used for the live FX daily-Close repair. Gap bars
    # (Fridays) older than this keep Close := next Open.
    FX_REPAIR_HOURLY_PERIOD = "729d"

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
            DataFrame with columns: timestamp, open, high, low, close, volume,
            plus a boolean `is_complete` on 1d / 1wk frames (False only for a
            still-forming last bar -- see _mark_is_complete). Non-finite OHLC
            rows and weekend stub bars are dropped, and the Yahoo daily FX
            Close is repaired (see the module header). Both happen on live
            downloads AND on snapshot reads; pins on disk stay raw Yahoo data.
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
        # Snapshot-served frames get the same hygiene as live ones (so pinned
        # goldtest data is repaired on LOAD; the files stay untouched), but no
        # network: the FX last-bar / gap-bar 1h refinement is live-only.
        if self.ohlcv_snapshot_mode == "fill":
            _cached = self._read_ohlcv_snapshot(_snap_key)
            if _cached is not None:
                _cached = self._post_process(_cached, symbol, interval, from_snapshot=True,
                                             scope=(period, start, end, allow_proxy))
                self._ohlcv_cache[cache_key] = _cached
                return _cached.copy()
        if self.ohlcv_snapshot_mode == "read":
            snap = self._read_ohlcv_snapshot(_snap_key)
            if snap is None:
                logger.warning(
                    "OHLCV snapshot missing for %s (mode=read) — returning empty. "
                    "Run build_ohlcv_snapshot.py to create it.", _snap_key)
                return pd.DataFrame()
            snap = self._post_process(snap, symbol, interval, from_snapshot=True,
                                      scope=(period, start, end, allow_proxy))
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
            # Pin the RAW Yahoo bars under the key actually requested, BEFORE any
            # repair: repairs are re-applied on every load, so a repair change
            # never needs a re-pin and A/B kill switches work on pinned data.
            # Proxy-derived bars are only ever written under the allow_proxy=True
            # key, preserving the C-51 guarantee that proxy data can never
            # satisfy a tradable request.
            self._write_ohlcv_snapshot(
                self._ohlcv_snap_key(symbol, interval, _scope,
                                     True if used_proxy else allow_proxy), df)
            if used_proxy:
                self._proxy_served[(symbol, interval)] = FUTURES_PROXY[symbol]
            df = self._post_process(df, FUTURES_PROXY[symbol] if used_proxy else symbol,
                                    interval, from_snapshot=False,
                                    scope=(period, start, end, allow_proxy))
        if not df.empty:
            self._ohlcv_cache[(symbol, interval, _scope, True)] = df.copy()
            if not used_proxy:
                # genuine primary data — safe for the tradable path too
                self._ohlcv_cache[(symbol, interval, _scope, False)] = df.copy()
        return df

    # ------------------------------------------------------------------
    # Price-data hygiene (defects 1, 2, 7, 8 -- see module header)
    # ------------------------------------------------------------------
    def _post_process(self, df: pd.DataFrame, symbol: str, interval: str,
                      from_snapshot: bool, scope: Optional[tuple] = None) -> pd.DataFrame:
        """Instance wrapper: gathers what the pure repair needs from the network.

        1h refinement of the FX daily Close: only in snapshot mode "off". In
        write/fill the frame is being pinned for a reproducible test, and the
        next read of that pin has no 1h data -- so the first (live) run must
        process it exactly as the later reads will.

        Weekly/monthly FX repair: needs the daily frame of the SAME scope
        (period or start/end, allow_proxy) -- fetched through fetch_ohlcv, so it
        is cached, Close-repaired, and in read mode served only from its own
        pin (skipped, with no warning, when that pin does not exist).
        """
        if df is None or df.empty:
            return df
        hourly = None
        if (not from_snapshot and self.ohlcv_snapshot_mode == "off"
                and interval == "1d" and _has_daily_close_defect(symbol)
                and _flag_on("BP_FX_CLOSE_REPAIR") and self._frame_is_recent(df)):
            hourly = self._hourly_for_close_repair(symbol)
        daily = None
        if (interval in ("1wk", "1mo") and _has_daily_close_defect(symbol)
                and os.environ.get("BP_FX_WEEKLY_REPAIR") == "1" and scope is not None):
            daily = self._daily_for_period_repair(symbol, *scope)
        return self._post_process_frame(df, symbol, interval, from_snapshot,
                                        hourly=hourly, now_utc=_utcnow(), daily=daily)

    def _daily_for_period_repair(self, symbol: str, period, start, end,
                                 allow_proxy: bool) -> Optional[pd.DataFrame]:
        try:
            _scope = (start, end) if (start and end) else period
            if self.ohlcv_snapshot_mode == "read" and not self._ohlcv_snapshot_path(
                    self._ohlcv_snap_key(symbol, "1d", _scope, allow_proxy)).exists():
                return None
            d = self.fetch_ohlcv(symbol, "1d", period=period, start=start, end=end,
                                 allow_proxy=allow_proxy)
            return d if d is not None and not d.empty else None
        except Exception as exc:  # never let a repair input break the fetch
            logger.warning("%s: daily bars for the weekly repair unavailable: %s", symbol, exc)
            return None

    @staticmethod
    def _post_process_frame(df: pd.DataFrame, symbol: str, interval: str,
                            from_snapshot: bool, hourly: Optional[pd.DataFrame],
                            now_utc: pd.Timestamp,
                            daily: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """Pure (no network): stub/NaN drop -> FX Close repair (daily) or FX
        High/Low/Close rebuild from `daily` (weekly/monthly) -> is_complete.

        Order matters: stubs go first because a weekend stub's Open is stale
        (the EURUSD Saturday stub's Open was the Friday 16:00 London price) and
        would otherwise become Friday's repaired Close.
        """
        if df is None or df.empty:
            return df
        ts = _ts_series(df)
        if ts is not None and not ts.is_monotonic_increasing:
            df = df.iloc[ts.argsort(kind="mergesort").to_numpy()].reset_index(drop=True)
        if _flag_on("BP_DROP_STUB_BARS"):
            df = _drop_bad_rows(df, interval, symbol)
            if df.empty:
                return df
        last_unrepaired = False
        if interval == "1d" and _has_daily_close_defect(symbol) and _flag_on("BP_FX_CLOSE_REPAIR"):
            df, last_unrepaired = _repair_daily_close(df, hourly=hourly, now_utc=now_utc,
                                                      symbol=symbol)
        if (interval in ("1wk", "1mo") and daily is not None
                and _has_daily_close_defect(symbol) and os.environ.get("BP_FX_WEEKLY_REPAIR") == "1"):
            df = _repair_period_bars(df, daily, interval, symbol)
        return _mark_is_complete(df, interval, now_utc, from_snapshot,
                                 force_last_incomplete=last_unrepaired)

    def _frame_is_recent(self, df: pd.DataFrame) -> bool:
        """Does the frame reach into the 1h history window? (skip the 1h fetch for
        historical goldtest slices, which it could never cover)."""
        ts = _ts_series(df)
        if ts is None or ts.empty:
            return False
        last = _as_utc(ts.iloc[-1])
        return last is not None and last >= _utcnow() - pd.Timedelta(days=725)

    def _hourly_for_close_repair(self, symbol: str) -> pd.DataFrame:
        """Cleaned, completed 1h bars for the FX Close repair; once per symbol.

        Completeness is judged at FETCH time, so a cached frame can never pass
        off a then-partial hour as finished. Stubs are always excluded here
        (the 22:00-London flat print after Friday's close is not a trade), so
        BP_DROP_STUB_BARS only changes what callers see, not the repair.
        A failed fetch is cached as empty: the scan must not retry 3x per frame.
        """
        if symbol not in self._repair_hourly:
            fetched_at = _utcnow()
            raw = self._fetch_one(symbol, "60m", self.FX_REPAIR_HOURLY_PERIOD, None, None, 3)
            hourly = _clean_bars(raw, "60m", now_utc=fetched_at, drop_stubs=True)
            if hourly.empty:
                logger.warning("%s: no 1h bars for the daily-Close repair -- gap bars keep "
                               "next Open, last bar flagged incomplete", symbol)
            self._repair_hourly[symbol] = hourly
        return self._repair_hourly[symbol]

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

    def fetch_bars_since(
        self,
        symbol: str,
        since_utc,
        interval: str = "60m",
        retries: int = 4,
        allow_proxy: bool = False,
    ) -> pd.DataFrame:
        """Completed bars that STARTED at or after `since_utc`, for order replay.

        Why (defect 6): the paper trader priced every order against ONE daily
        bar per run, so it filled on lows printed before the order existed,
        armed breakeven on the bar high and stopped out on the same bar's low,
        and -- seeing only ~6h of each FX day at a once-a-day schedule -- missed
        stops outright (USDJPY 24 Sep). Replaying completed 1h bars since the
        last evaluation gives the real order of events, like a broker's book.

        Returns columns timestamp (tz-aware UTC bar START), open, high, low,
        close, volume: only bars with start + interval <= now UTC, start >=
        since_utc, finite OHLC, no stub bars (O==H==L==C with no volume; kept
        when BP_DROP_STUB_BARS=0), ascending, unique. `since_utc` may be naive
        (taken as UTC), aware, or an ISO string. Never raises: any failure
        returns an empty frame with the same columns.

        Instrument: the SAME series the daily data came from. The tradable path
        fetches daily bars with allow_proxy=False, so it is never a proxy (C-51)
        and the default here is primary-only too -- replaying GLD bars against
        GC=F order levels would fill/stop at ~1/10th the price. With
        allow_proxy=True the proxy is used when the daily for `symbol` was
        served by it in this process, or as fetch_ohlcv's fallback.

        Snapshot modes: "read" serves only a pin written by this method
        (`<symbol>__<interval>__bars-utc__<primary|proxy>.csv`, UTC timestamps)
        and returns empty without one; "fill" reads that pin or fetches and
        writes it; "write" always fetches and (re)writes it. The pin holds the
        completed bars of the first fetch -- a later request that starts
        earlier than the pin cannot be served from it.
        """
        empty = _empty_bars()
        try:
            span = _interval_timedelta(interval)
            since = _as_utc(since_utc)
            if span is None or since is None:
                logger.warning("fetch_bars_since(%s): bad interval %r or since %r",
                               symbol, interval, since_utc)
                return empty
            now = _utcnow()          # captured BEFORE the download: conservative
            if since >= now:
                return empty
            drop_stubs = _flag_on("BP_DROP_STUB_BARS")
            snap_key = self._ohlcv_snap_key(symbol, interval, "bars-utc", allow_proxy)

            if self.ohlcv_snapshot_mode in ("read", "fill"):
                pinned = self._read_ohlcv_snapshot(snap_key)
                if pinned is not None:
                    return _clean_bars(pinned, interval, now_utc=now, since_utc=since,
                                       drop_stubs=drop_stubs)
                if self.ohlcv_snapshot_mode == "read":
                    logger.debug("bars-since pin missing for %s (mode=read) -- empty", snap_key)
                    return empty

            proxy = FUTURES_PROXY.get(symbol)
            fetch_sym = symbol
            if allow_proxy and proxy and self._proxy_served.get((symbol, "1d")) == proxy:
                fetch_sym = proxy

            if _is_intraday(interval):
                days = int(np.ceil((now - since) / pd.Timedelta(days=1))) + 2
                max_days = _INTRADAY_MAX_DAYS.get(interval, 59)
                if days > max_days:
                    logger.warning("fetch_bars_since(%s): since %s is beyond Yahoo's %dd %s "
                                   "history -- older bars unavailable", symbol, since,
                                   max_days, interval)
                    days = max_days
                period, start, end = f"{max(days, 1)}d", None, None
            else:
                period = None
                start = (since - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
                end = (now + pd.Timedelta(days=2)).strftime("%Y-%m-%d")

            raw = self._fetch_one(fetch_sym, interval, period, start, end, retries)
            if raw.empty and allow_proxy and proxy and fetch_sym == symbol:
                logger.warning("%s %s bars unreachable, falling back to REFERENCE proxy %s "
                               "(allow_proxy=True)", symbol, interval, proxy)
                raw = self._fetch_one(proxy, interval, period, start, end, retries)
                fetch_sym = proxy if not raw.empty else symbol

            if raw.empty:
                return empty
            if self.ohlcv_snapshot_mode in ("write", "fill"):
                # pin every COMPLETED bar (stubs/NaN kept: hygiene re-applied on read)
                self._write_ohlcv_snapshot(
                    self._ohlcv_snap_key(symbol, interval, "bars-utc",
                                         True if fetch_sym != symbol else allow_proxy),
                    _clean_bars(raw, interval, now_utc=now, drop_stubs=False))
            return _clean_bars(raw, interval, now_utc=now, since_utc=since,
                               drop_stubs=drop_stubs)
        except Exception as exc:
            logger.error("fetch_bars_since(%s, %s) failed: %s", symbol, interval, exc)
            return empty

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
