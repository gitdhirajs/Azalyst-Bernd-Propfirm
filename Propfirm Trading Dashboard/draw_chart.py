"""
Render the per-signal chart PNG that send_discord.py attaches to each NEW SIGNAL
message (entry / stop / T1-T3 lines over the LTF candles from ohlcv_cache).

2026-09-27 hardening (hourly-run deploy):
  * Charts go to the system temp directory (unique file per call), not the
    working directory. On the GitHub runner the working directory is the repo
    checkout; a stray chart_*.png there could be picked up by a later
    `git add`, and two signals on the same symbol overwrote each other's file.
  * mplfinance / matplotlib are imported lazily. The old module-level
    `import mplfinance` meant a missing charting dependency raised ImportError
    at `import draw_chart` in send_discord.py -- killing the whole Discord send,
    including the account status, just because a picture could not be drawn.
  * Only COMPLETED candles are drawn when the cached rows carry "is_complete"
    (data-fetcher contract, 2026-09-27). The still-forming daily candle has an
    unreliable Close -- Yahoo daily FX Close was measured to be ~a copy of the
    Open -- and rule #4 says a zone is only valid on complete formation, so the
    chart must not show a candle the engine is no longer allowed to use.
  * Short / empty / non-finite data returns None (text-only message) instead
    of raising.
"""
from __future__ import annotations

import math
import os
import re
import tempfile
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# Fewer bars than this cannot show a zone in context; send the text alone.
MIN_BARS = 10
# Bars drawn (the tail of the completed series).
MAX_BARS = 90


def _finite(v) -> Optional[float]:
    """float(v) if it is a finite number, else None (NaN/inf/None/str)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _is_true(v) -> bool:
    """Interpret an is_complete cell. Rows round-trip through JSON so the value
    is normally a bool, but accept the string forms too. Missing -> True (the
    contract: consumers treat a missing column as all-complete)."""
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip().lower() not in ("false", "0", "no", "")
    try:
        if isinstance(v, float) and math.isnan(v):
            return True
    except TypeError:
        pass
    return bool(v)


def _completed_frame(rows: List[Dict]) -> Optional[pd.DataFrame]:
    """Build a clean OHLC frame from cached rows: completed bars only,
    non-finite rows dropped, DatetimeIndex (UTC). None if unusable."""
    if not rows:
        return None
    df = pd.DataFrame(rows)
    need = ("timestamp", "open", "high", "low", "close")
    if any(c not in df.columns for c in need):
        return None
    # Kill switch BP_CHART_COMPLETED_ONLY=0 draws the forming bar again.
    if "is_complete" in df.columns and os.environ.get("BP_CHART_COMPLETED_ONLY", "1") != "0":
        df = df[df["is_complete"].map(_is_true)]
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["timestamp", "open", "high", "low", "close"])
    df = df[np.isfinite(df[["open", "high", "low", "close"]]).all(axis=1)]
    if df.empty:
        return None
    df = df.sort_values("timestamp").set_index("timestamp")
    return df[["open", "high", "low", "close"]].tail(MAX_BARS)


def _safe_name(sym: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", sym).strip("_") or "chart"


def generate_chart(signal: dict, ohlcv_cache: dict) -> Optional[str]:
    """Draw the signal's chart and return the PNG path, or None when it cannot
    be drawn (no data, too few completed bars, charting library missing, or
    any plotting error). Never raises: a chart is decoration, the text alert
    must still go out."""
    try:
        sym = signal.get("symbol")
        if not sym or not ohlcv_cache or sym not in ohlcv_cache:
            return None
        ltf = signal.get("ltf", "1d")
        rows = (ohlcv_cache.get(sym) or {}).get(ltf)
        df = _completed_frame(rows or [])
        if df is None or len(df) < MIN_BARS:
            return None

        entry = _finite(signal.get("entry_price"))
        stop = _finite(signal.get("stop_price"))
        if entry is None or stop is None or entry == stop:
            return None
        targets = [t for t in (_finite(x) for x in (signal.get("targets") or [])[:3])
                   if t is not None]

        # Lazy import: see module docstring. Agg = no display needed (runner).
        try:
            import matplotlib
            matplotlib.use("Agg")
            import mplfinance as mpf
        except Exception as exc:  # ImportError, or a broken backend
            print(f"[chart] charting unavailable ({exc}); sending text only")
            return None

        hline_vals = [entry, stop]
        colors = ['#4A90E2', '#E74C3C']
        widths = [1.5, 1.5]
        styles = ['-', '-']
        for t in targets:
            hline_vals.append(t)
            colors.append('#2ECC71')
            widths.append(1.0)
            styles.append('--')
        hlines = dict(hlines=hline_vals, colors=colors, linewidths=widths,
                      linestyle=styles, alpha=0.8)
        fill_dict = dict(y1=entry, y2=stop, color="gray", alpha=0.2)

        fd, out_path = tempfile.mkstemp(prefix=f"azalyst_chart_{_safe_name(sym)}_",
                                        suffix=".png")
        os.close(fd)

        mc = mpf.make_marketcolors(up='g', down='r', edge='inherit', wick='inherit',
                                   volume='in', ohlc='i')
        s = mpf.make_mpf_style(marketcolors=mc, gridstyle=':', y_on_right=True,
                               facecolor='#2B2D31', edgecolor='white', figcolor='#2B2D31',
                               rc={'text.color': 'white', 'axes.labelcolor': 'white',
                                   'xtick.color': 'white', 'ytick.color': 'white'})
        try:
            mpf.plot(df, type='candle', style=s, hlines=hlines, fill_between=fill_dict,
                     title=f"{sym} ({ltf}, completed bars)", savefig=out_path,
                     figsize=(10, 6))
        except Exception:
            try:
                os.remove(out_path)
            except OSError:
                pass
            raise
        return out_path
    except Exception as e:
        print(f"[chart] failed for {signal.get('symbol')}: {e}")
        return None
