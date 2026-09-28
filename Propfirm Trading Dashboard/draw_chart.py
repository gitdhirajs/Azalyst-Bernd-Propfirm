"""
Trade charts for the Discord alerts (send_discord.py).

    generate_chart(signal, ohlcv_cache)              -> PNG for a NEW SIGNAL
    generate_trade_result_chart(trade, ohlcv_cache)  -> PNG for a CLOSED trade

2026-09-27 redesign ("proper charts in Discord"). The old chart was a bare
mplfinance plot: unlabeled lines pressed against the top edge, no zone, no
direction, all three targets drawn. The new one reads like a TradingView
long/short position:

  * header: symbol + direction, order type, entry type, timeframes, time;
    composite score top-right (signal) or the result badge (closed trade);
  * the last ~80 COMPLETED candles in TradingView colours; the in-progress bar,
    if any, hollow and labelled "live";
  * the zone as a shaded box from its first base candle to the right edge;
  * a position tool from the last bar to the right edge: red box entry->stop,
    green box entry->target. What the green part shows follows the configured
    trade management (stop_loss.management, read through BP_management -- the
    same reader the paper trader uses):
      - scale_out (default, 2026-09-28): green box entry -> +1R labelled
        "+1R: close 50% (+$X) - stop to BE", then a lighter dashed runner
        extension +1R -> +3R (or the runner target) "Runner 50% - trails in
        1R steps"; the result chart marks the partial exit and the runner exit
        and shows the blended R;
      - fixed / ladder: ONE take-profit, targets[1] (T2), as before;
  * right-axis price tags (Entry / Stop / Target or "+1R (50%)" / Now) nudged
    apart so they never overlap, and in-plot $ / R labels next to the boxes;
  * footer chips with the bias reads (Location, Valuation, COT, Seasonality,
    Trend) and a small watermark.

Robustness (unchanged contract from the 2026-09-27 hardening):
  * never raises -- a chart is decoration, the text alert must still go out;
    any failure returns None (text-only message) and is logged;
  * matplotlib is imported lazily and used through the object API with the Agg
    canvas (no pyplot, no display, no global figure registry: nothing leaks
    over 40+ symbols per run; figures are also cleared explicitly);
  * PNGs go to tempfile.gettempdir() with unique names (never the repo
    checkout on the runner);
  * only COMPLETED candles are drawn as candles when rows carry "is_complete"
    (missing = complete). Kill switch BP_CHART_COMPLETED_ONLY=0 draws the
    forming bar as a normal candle again.
"""
from __future__ import annotations

import logging
import math
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

try:   # the ONE management reader (shared with BP_paper_trader / send_discord)
    from BP_management import resolve_management, scale_out_levels, fmt_r as _fmt_r
except Exception:  # pragma: no cover - broken checkout: fall back to fixed drawing
    resolve_management = None
    scale_out_levels = None

    def _fmt_r(r):
        return f"{r:g}"

# Fewer bars than this cannot show a zone in context; send the text alone.
MIN_BARS = 10
# Completed bars drawn on a signal chart (the tail of the series).
MAX_BARS = 80
# Empty bars on the right of a signal chart for the position tool and labels.
RIGHT_PAD_BARS = 22
# Scale-out labels are longer ("+1R: close 50% (+$25.00) - stop to BE").
RIGHT_PAD_BARS_SCALE_OUT = 34
# Result chart window: bars before the fill / after the exit, and empty room.
RESULT_BARS_BEFORE = 40
RESULT_BARS_AFTER = 5
RESULT_RIGHT_PAD = 7

# ── Look ──────────────────────────────────────────────────────────────────
FIGSIZE = (12.0, 6.75)          # 16:9
DPI = 150                       # -> 1800 x 1012 px
FIG_BG = "#1E1F22"              # Discord dark
AX_BG = "#2B2D31"
GRID = "#3A3D44"
TEXT = "#F2F3F5"
MUTED = "#B5BAC1"
DIM = "#80848E"
UP = "#26A69A"                  # TradingView up / target / long
DOWN = "#EF5350"                # TradingView down / stop / short
ENTRY = "#5865F2"               # Discord blurple
NOW = "#949BA4"
NEUTRAL = "#4E5058"
RUNNER = "#80CBC4"              # lighter green: the scale-out runner
CHIP_TEXT_DARK = "#1E1F22"

# Figure-fraction layout. The axes' right edge is computed from the widest
# price tag so the tags always fit inside the canvas.
AX_LEFT = 0.022
AX_BOTTOM = 0.165
AX_TOP = 0.845
FIG_RIGHT = 0.993

FS_TITLE = 20
FS_SUB = 12.5
FS_CORNER = 15
FS_AXIS = 11
FS_TAG = 11.5
FS_LABEL = 12
FS_CHIP = 11.5
FS_WATERMARK = 9.5

TAG_PAD = 0.32                  # bbox pad of a price tag, in font sizes
WATERMARK = "Azalyst Propfirm · paper trade · not financial advice"

_INDEX_NAMES = {
    "^GDAXI": "DAX", "^FTSE": "FTSE 100", "^N225": "Nikkei 225",
    "^STOXX50E": "Euro Stoxx 50", "^GSPC": "S&P 500", "^NDX": "Nasdaq 100",
    "^DJI": "Dow Jones", "^RUT": "Russell 2000", "^FCHI": "CAC 40",
    "^HSI": "Hang Seng",
}
_TF_NAMES = {
    "1mo": "monthly", "1wk": "weekly", "1d": "daily", "4h": "4-hour",
    "240m": "4-hour", "1h": "1-hour", "60m": "1-hour", "30m": "30-minute",
    "15m": "15-minute", "5m": "5-minute",
}
_ENTRY_TYPES = {"E1": "E1 zone entry", "E2": "E2 mid-zone entry",
                "E3B": "E3b pattern entry", "E3A": "E3a refined-zone entry"}
_BIAS_KEYS = (("Location", "location"), ("Valuation", "valuation"),
              ("COT", "cot"), ("Seasonality", "seasonality"), ("Trend", "trend"))


# ── Small helpers ─────────────────────────────────────────────────────────

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


def _safe_name(sym: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(sym)).strip("_") or "chart"


def _log(msg: str) -> None:
    logger.warning(msg)
    print(f"[chart] {msg}", file=sys.stderr)


def display_name(symbol: str) -> str:
    """GBPNZD=X -> GBPNZD, GC=F -> GC, ^GDAXI -> DAX, BTC-USD -> BTCUSD."""
    s = str(symbol or "").strip()
    if s in _INDEX_NAMES:
        return _INDEX_NAMES[s]
    if s.endswith("=X") or s.endswith("=F"):
        s = s[:-2]
    s = s.lstrip("^")
    if re.fullmatch(r"[A-Z0-9]{2,6}-(USD|USDT|EUR)", s):
        s = s.replace("-", "")
    return s or "?"


def price_decimals(symbol: str, ref_price: Optional[float] = None) -> int:
    """5 for FX (3 for JPY pairs), 2 for indices / metals / crypto. A non-FX
    instrument priced under 10 (NG, 6E, small coins) gets 4 so it is not
    rounded flat."""
    s = str(symbol or "").upper()
    if s.endswith("=X"):
        return 3 if "JPY" in s else 5
    p = abs(ref_price) if ref_price is not None else None
    if p is not None and p > 0:
        if p < 1:
            return 5
        if p < 10:
            return 4
    return 2


def _fmt_px(v: Optional[float], dec: int) -> str:
    return "-" if v is None else f"{v:.{dec}f}"


def _money(v: Optional[float], sign: bool = True) -> str:
    if v is None:
        return ""
    s = "-" if v < 0 else ("+" if sign else "")
    return f"{s}${abs(v):,.2f}"


def _r_text(r: float) -> str:
    rr = abs(r)
    return f"{int(round(rr))}" if abs(rr - round(rr)) < 0.05 else f"{rr:.1f}"


def _to_utc(value) -> Optional[pd.Timestamp]:
    if value is None or value == "":
        return None
    try:
        t = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(t):
        return None
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _wall(value) -> Optional[pd.Timestamp]:
    """Wall-clock time of a bar stamp (its own offset dropped), so a daily bar
    stamped 2026-09-25 00:00+01:00 is labelled 25 Sep, not 24 Sep 23:00 UTC."""
    try:
        t = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(t):
        return None
    return t.tz_localize(None) if t.tzinfo is not None else t


def _fmt_when(value) -> str:
    t = _to_utc(value)
    return t.strftime("%d %b %Y %H:%M UTC") if t is not None else ""


def _fmt_day(value) -> str:
    t = _to_utc(value)
    return t.strftime("%d %b %Y") if t is not None else "?"


def _tf_name(tf: Optional[str]) -> str:
    return _TF_NAMES.get(str(tf or "").lower(), str(tf or "chart"))


def _dir_is_long(d) -> bool:
    return str(getattr(d, "value", d) or "").strip().lower() == "long"


def _order_word(p: Dict) -> str:
    """'Sell-limit' / 'Buy-stop' (same fallback rule as send_discord.order_label)."""
    ot = str(p.get("order_type") or "").strip().lower()
    if ot not in ("limit", "stop"):
        ot = "stop" if str(p.get("entry_type") or "").upper() == "E3B" else "limit"
    return f"{'Buy' if _dir_is_long(p.get('direction')) else 'Sell'}-{ot}"


def _management(obj: Optional[Dict], explicit: Optional[Dict]) -> Dict:
    """Management settings for a chart: explicit dict, else the one carried by
    the signal/trade, else BP_config.yaml. {'mode': 'fixed'} without the helper."""
    if resolve_management is None:
        return {"mode": "fixed"}
    try:
        return resolve_management(explicit, (obj or {}).get("management"))
    except Exception:
        return {"mode": "fixed"}


def _frac_txt(f) -> str:
    try:
        return f"{float(f) * 100:g}%"
    except (TypeError, ValueError):
        return "50%"


def _bias_colour(v: str) -> str:
    v = str(v or "").lower()
    if v in ("bullish", "uptrend", "long"):
        return UP
    if v in ("bearish", "downtrend", "short"):
        return DOWN
    return NEUTRAL


# ── Data ──────────────────────────────────────────────────────────────────

def _completed_frame(rows: List[Dict]) -> Optional[pd.DataFrame]:
    """Clean OHLC frame from cached rows: completed bars only, non-finite rows
    dropped, DatetimeIndex (UTC), last MAX_BARS. None if unusable."""
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


def _bars(rows: List[Dict]) -> Tuple[Optional[pd.DataFrame], Optional[Dict]]:
    """(completed bars, live bar or None) from cached rows.

    Completed frame: RangeIndex, columns t (UTC), wall (bar's own wall clock),
    open/high/low/close, sorted, de-duplicated, finite. The live bar is the
    newest not-complete row, only when it is newer than every completed bar.
    With BP_CHART_COMPLETED_ONLY=0 every row counts as completed (no live bar).
    """
    if not rows:
        return None, None
    df = pd.DataFrame(rows)
    if any(c not in df.columns for c in ("timestamp", "open", "high", "low", "close")):
        return None, None
    if "is_complete" in df.columns and os.environ.get("BP_CHART_COMPLETED_ONLY", "1") != "0":
        done = df["is_complete"].map(_is_true).astype(bool)
    else:
        done = pd.Series(True, index=df.index)
    out = pd.DataFrame({
        "t": [_to_utc(v) for v in df["timestamp"]],
        "wall": [_wall(v) for v in df["timestamp"]],
        "done": done.values,
    })
    for c in ("open", "high", "low", "close"):
        out[c] = pd.to_numeric(df[c], errors="coerce").values
    out = out.dropna(subset=["t", "wall", "open", "high", "low", "close"])
    if out.empty:
        return None, None
    out = out[np.isfinite(out[["open", "high", "low", "close"]].astype(float)).all(axis=1)]
    out["t"] = pd.to_datetime(out["t"], utc=True)
    out = out.sort_values("t").drop_duplicates("t", keep="last")
    comp = out[out["done"]].drop(columns="done").reset_index(drop=True)
    live = None
    pend = out[~out["done"]]
    if len(pend):
        last = pend.iloc[-1]
        if comp.empty or last["t"] > comp["t"].iloc[-1]:
            live = {k: last[k] for k in ("t", "wall", "open", "high", "low", "close")}
    if comp.empty:
        return None, live
    return comp, live


def _bar_index(times: pd.Series, when, side: str = "contain") -> Optional[int]:
    """Position of the bar that CONTAINS `when` (last bar starting at or before
    it). None if `when` is unparseable or before the first bar."""
    t = _to_utc(when)
    if t is None or times is None or len(times) == 0:
        return None
    arr = pd.to_datetime(times, utc=True).values
    i = int(np.searchsorted(arr, t.to_datetime64(), side="right")) - 1
    return i if i >= 0 else None


def _bar_near(times: pd.Series, when) -> Optional[int]:
    """Position of the bar starting at `when`, tolerant to half a bar of clock
    skew; 0 when `when` is older than the window; None when unparseable."""
    t = _to_utc(when)
    if t is None or times is None or len(times) == 0:
        return None
    s = pd.to_datetime(times, utc=True)
    step = s.diff().dropna().median() if len(s) > 1 else pd.Timedelta(days=1)
    if pd.isna(step) or step <= pd.Timedelta(0):
        step = pd.Timedelta(days=1)
    i = int(np.searchsorted(s.values, (t - step / 2).to_datetime64(), side="left"))
    return min(i, len(s) - 1)


# ── Layout helpers ────────────────────────────────────────────────────────

def _spread(desired: Sequence[float], gap: float, lo: float, hi: float) -> List[float]:
    """Nudge 1-D label positions apart so neighbours are at least `gap` apart,
    keeping their order, each cluster centred on the mean of what it wanted,
    and everything inside [lo, hi] when it fits."""
    n = len(desired)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: desired[i])
    want = [float(desired[i]) for i in order]
    # clusters: [first_member, last_member] indices into `want`
    clusters: List[List[int]] = []
    starts: List[float] = []

    def _place(a: int, b: int) -> float:
        m = sum(want[a:b + 1]) / (b - a + 1)
        start = m - (b - a) * gap / 2.0
        span = (b - a) * gap
        if hi - lo >= span:
            start = min(max(start, lo), hi - span)
        return start

    for k in range(n):
        clusters.append([k, k])
        starts.append(_place(k, k))
        while len(clusters) > 1:
            a0, b0 = clusters[-2]
            end_prev = starts[-2] + (b0 - a0) * gap
            if starts[-1] - end_prev >= gap - 1e-9:
                break
            a1, b1 = clusters.pop()
            starts.pop()
            clusters[-1] = [a0, b1]
            starts[-1] = _place(a0, b1)
    placed = [0.0] * n
    for (a, b), s in zip(clusters, starts):
        for k in range(a, b + 1):
            placed[k] = s + (k - a) * gap
    out = [0.0] * n
    for k, i in enumerate(order):
        out[i] = placed[k]
    return out


class _Canvas:
    """One figure: dark background, header, main axes, footer."""

    def __init__(self, tag_texts: Sequence[str]):
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg

        self.fig = Figure(figsize=FIGSIZE, dpi=DPI, facecolor=FIG_BG)
        FigureCanvasAgg(self.fig)
        self.renderer = self.fig.canvas.get_renderer()
        self.W, self.H = self.fig.bbox.width, self.fig.bbox.height
        self.tag_pad_px = TAG_PAD * FS_TAG * DPI / 72.0
        self.tag_spans: List[Tuple[float, float]] = []    # (centre px, half height px)
        widest = max((self.text_size(t, FS_TAG, "bold")[0] for t in tag_texts), default=120.0)
        self.tag_offset_pt = 4.0
        tag_w = widest + 2 * self.tag_pad_px + self.tag_offset_pt * DPI / 72.0 + 4
        right = FIG_RIGHT - tag_w / self.W
        self.ax = self.fig.add_axes([AX_LEFT, AX_BOTTOM, right - AX_LEFT, AX_TOP - AX_BOTTOM])
        ax = self.ax
        ax.set_facecolor(AX_BG)
        for side in ("top", "left"):
            ax.spines[side].set_visible(False)
        for side in ("right", "bottom"):
            ax.spines[side].set_color(GRID)
        ax.yaxis.tick_right()
        ax.tick_params(axis="both", colors=MUTED, labelsize=FS_AXIS, length=0, pad=6)
        ax.grid(True, color=GRID, linewidth=0.6, alpha=0.7)
        ax.set_axisbelow(True)

    # -- measurement ---------------------------------------------------------
    def text_size(self, s: str, fs: float, weight: str = "normal") -> Tuple[float, float]:
        t = self.fig.text(0, 0, s, fontsize=fs, fontweight=weight)
        try:
            bb = t.get_window_extent(self.renderer)
            return bb.width, bb.height
        finally:
            t.remove()

    def px_per_x(self) -> float:
        x0, x1 = self.ax.get_xlim()
        return self.ax.bbox.width / (x1 - x0)

    def y_to_px(self, y: float) -> float:
        return float(self.ax.transData.transform((0.0, y))[1])

    def px_to_y(self, py: float) -> float:
        return float(self.ax.transData.inverted().transform((0.0, py))[1])

    # -- pieces --------------------------------------------------------------
    def header(self, title: str, colour: str, subtitle: str) -> None:
        self.fig.text(AX_LEFT, 0.938, title, fontsize=FS_TITLE, fontweight="bold",
                      color=colour, va="center", ha="left")
        fs = FS_SUB
        avail = (FIG_RIGHT - AX_LEFT) * self.W
        while fs > 9.5 and self.text_size(subtitle, fs)[0] > avail:
            fs -= 0.5
        self.fig.text(AX_LEFT, 0.883, subtitle, fontsize=fs, color=MUTED,
                      va="center", ha="left")

    def corner(self, text: str, fc: str, colour: str = TEXT, fs: float = FS_CORNER) -> None:
        pad = 0.45 * fs * DPI / 72.0
        self.fig.text(FIG_RIGHT - pad / self.W, 0.938, text, fontsize=fs, fontweight="bold",
                      color=colour, va="center", ha="right",
                      bbox=dict(boxstyle="round,pad=0.45", fc=fc, ec="none"))

    def chips(self, items: Sequence[Tuple[str, str, str]]) -> None:
        """items: (text, face colour, text colour), left to right."""
        if not items:
            return
        fs = FS_CHIP
        gap = 12.0
        avail = (FIG_RIGHT - AX_LEFT) * self.W
        while True:
            pad = 0.38 * fs * DPI / 72.0
            widths = [self.text_size(t, fs, "bold")[0] + 2 * pad for t, _, _ in items]
            if sum(widths) + gap * (len(items) - 1) <= avail or fs <= 8.5:
                break
            fs -= 0.5
        x = AX_LEFT * self.W + pad
        for (t, fc, tc), w in zip(items, widths):
            self.fig.text(x / self.W, 0.062, t, fontsize=fs, fontweight="bold", color=tc,
                          va="center", ha="left",
                          bbox=dict(boxstyle="round,pad=0.38", fc=fc, ec="none"))
            x += w + gap

    def watermark(self) -> None:
        self.fig.text(FIG_RIGHT, 0.02, WATERMARK, fontsize=FS_WATERMARK, color=DIM,
                      va="center", ha="right")

    def date_axis(self, walls: Sequence, first_x: int = 0) -> None:
        n = len(walls)
        if n == 0:
            return
        steps = (1, 2, 3, 5, 7, 10, 15, 20, 25, 30, 40, 50, 60, 100)
        step = next((s for s in steps if n / s <= 8), steps[-1])
        idxs = list(range(n - 1, -1, -step))[::-1]
        spacing = None
        if n > 1:
            d = pd.Series(pd.to_datetime(list(walls))).diff().dropna()
            spacing = d.median() if len(d) else None
        intraday = spacing is not None and spacing < pd.Timedelta(hours=20)
        fmt = "%d %b %H:%M" if intraday else "%d %b"
        self.ax.set_xticks([first_x + i for i in idxs])
        self.ax.set_xticklabels([pd.Timestamp(walls[i]).strftime(fmt) for i in idxs])

    def price_axis(self, dec: int) -> None:
        """Right-axis tick labels; a tick label that a price tag would cover is
        left blank (TradingView style) instead of peeking out between tags."""
        from matplotlib.ticker import FuncFormatter, MaxNLocator
        half_tick = self.text_size("0", FS_AXIS)[1] / 2 + 3

        def _fmt(v, _pos):
            py = self.y_to_px(v)
            if any(abs(py - c) < h2 + half_tick for c, h2 in self.tag_spans):
                return ""
            return f"{v:.{dec}f}"
        self.ax.yaxis.set_major_locator(MaxNLocator(nbins=8))
        self.ax.yaxis.set_major_formatter(FuncFormatter(_fmt))

    def price_tags(self, tags: Sequence[Tuple[str, float, str, str]]) -> None:
        """Right-axis tags: (text, price, face colour, text colour), nudged apart."""
        from matplotlib.transforms import blended_transform_factory
        tags = [t for t in tags if t[1] is not None]
        if not tags:
            return
        h = max(self.text_size(t[0], FS_TAG, "bold")[1] for t in tags) + 2 * self.tag_pad_px
        bb = self.ax.bbox
        ys = _spread([self.y_to_px(p) for _, p, _, _ in tags], h + 3,
                     bb.y0 + h / 2, bb.y1 - h / 2)
        tr = blended_transform_factory(self.ax.transAxes, self.ax.transData)
        self.tag_spans = [(py, h / 2) for py in ys]
        for (text, _p, fc, tc), py in zip(tags, ys):
            self.ax.annotate(text, xy=(1.0, self.px_to_y(py)), xycoords=tr,
                             xytext=(self.tag_offset_pt, 0), textcoords="offset points",
                             ha="left", va="center", fontsize=FS_TAG, fontweight="bold",
                             color=tc, annotation_clip=False, zorder=20,
                             bbox=dict(boxstyle=f"round,pad={TAG_PAD}", fc=fc, ec="none"))

    def save(self, prefix: str) -> str:
        fd, path = tempfile.mkstemp(prefix=prefix, suffix=".png")
        os.close(fd)
        try:
            self.fig.savefig(path, dpi=DPI, facecolor=FIG_BG)
        except Exception:
            try:
                os.remove(path)
            except OSError:
                pass
            raise
        return path

    def close(self) -> None:
        try:
            self.fig.clear()
        except Exception:
            pass


def _y_limits(values: Sequence[Optional[float]], pad_frac: float = 0.06,
              levels: Sequence[Optional[float]] = (), axes_px: float = 0.0,
              headroom_px: float = 0.0) -> Tuple[float, float]:
    """Fit `values` with `pad_frac` padding; then make sure the outermost trade
    `levels` sit at least `headroom_px` from the axes edge, so the labels next
    to them are never squashed against the frame."""
    vals = [v for v in values if v is not None and math.isfinite(v)]
    lo, hi = min(vals), max(vals)
    span = hi - lo
    if span <= 0:
        span = abs(hi) * 0.01 or 1.0
    y0, y1 = lo - span * pad_frac, hi + span * pad_frac
    lv = [v for v in levels if v is not None and math.isfinite(v)]
    if lv and axes_px > 0 and 0 < headroom_px < axes_px / 3:
        f = headroom_px / axes_px
        for _ in range(3):
            upp = (y1 - y0)
            if (y1 - max(lv)) < f * upp:
                y1 = (max(lv) - f * y0) / (1 - f)
            if (min(lv) - y0) < f * (y1 - y0):
                y0 = (min(lv) - f * y1) / (1 - f)
    return y0, y1


def _draw_candles(ax, df: pd.DataFrame, x0: int, min_body: float) -> None:
    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l_ = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    x = np.arange(len(df)) + x0
    col = np.where(c >= o, UP, DOWN)
    ax.vlines(x, l_, h, colors=col, linewidth=1.1, zorder=4)
    bottom = np.minimum(o, c)
    height = np.maximum(np.abs(c - o), min_body)
    ax.bar(x, height, bottom=bottom, width=0.64, color=col, linewidth=0, zorder=5)


def _draw_live(ax, live: Dict, x: int, min_body: float) -> None:
    o, h, l_, c = (float(live[k]) for k in ("open", "high", "low", "close"))
    col = UP if c >= o else DOWN
    ax.vlines([x], [l_], [h], colors=col, linewidth=1.0, alpha=0.55, zorder=4)
    ax.bar([x], [max(abs(c - o), min_body)], bottom=[min(o, c)], width=0.64,
           facecolor=AX_BG, edgecolor=col, linewidth=1.2, alpha=0.9, zorder=5)
    ax.text(x, h, "live", fontsize=9.5, color=MUTED, ha="center", va="bottom", zorder=6)


def _rgba(colour: str, alpha: float):
    from matplotlib.colors import to_rgba
    return to_rgba(colour, alpha)


def _zone_box(cv: _Canvas, zone: Dict, times: pd.Series, x_right: float,
              x_label_limit: float, dec: int, ltf: str) -> None:
    """Shaded zone from its first base candle to the right edge + label."""
    from matplotlib.patches import Rectangle
    ax = cv.ax
    p, d = _finite(zone.get("proximal")), _finite(zone.get("distal"))
    if p is None or d is None or p == d:
        return
    ztype = str(zone.get("type") or zone.get("zone_type") or "").lower()
    if ztype not in ("demand", "supply"):
        ztype = "demand" if p > d else "supply"
    col = UP if ztype == "demand" else DOWN
    lo, hi = min(p, d), max(p, d)
    xl = ax.get_xlim()[0]
    i0 = _bar_near(times, zone.get("base_start") or zone.get("leg_out_end"))
    x0 = xl if i0 is None else max(xl, i0 - 0.45)
    ax.add_patch(Rectangle((x0, lo), x_right - x0, hi - lo, facecolor=_rgba(col, 0.18),
                           edgecolor=_rgba(col, 0.75), linewidth=1.0, zorder=1.5))
    tf = _tf_name(zone.get("timeframe") or ltf).capitalize()
    form = str(zone.get("formation") or "").strip()
    label = f"{tf} {ztype} zone" + (f" ({form})" if form else "") + \
        f"  {lo:.{dec}f} - {hi:.{dec}f}"
    fs = 11
    w, h = cv.text_size(label, fs, "bold")
    zone_px = abs(cv.y_to_px(hi) - cv.y_to_px(lo))
    ppx = cv.px_per_x()
    if zone_px >= h + 8:
        y, va = (lo + hi) / 2, "center"
    elif ztype == "supply":
        y, va = cv.px_to_y(cv.y_to_px(hi) + 4), "bottom"
    else:
        y, va = cv.px_to_y(cv.y_to_px(lo) - 4), "top"
    # Left-aligned just inside the box when there is room before the position
    # tool; otherwise right-aligned against the tool.
    if (x_label_limit - (x0 + 0.6)) * ppx >= w + 10:
        x, ha = x0 + 0.6, "left"
    else:
        x, ha = x_label_limit - 0.6, "right"
    ax.text(x, y, label, fontsize=fs, fontweight="bold", color=col, ha=ha, va=va, zorder=12,
            bbox=dict(boxstyle="round,pad=0.25", fc=_rgba(AX_BG, 0.78), ec="none"))


def _fit_font(cv: _Canvas, texts: Sequence[str], max_px: float, fs: float,
              weight: str = "bold", floor: float = 9.0) -> float:
    while fs > floor and max(cv.text_size(t, fs, weight)[0] for t in texts) > max_px:
        fs -= 0.5
    return fs


# ── Signal chart ──────────────────────────────────────────────────────────

def generate_chart(signal: dict, ohlcv_cache: dict, asof=None,
                   management: Optional[Dict] = None) -> Optional[str]:
    """Draw a NEW SIGNAL's chart and return the PNG path, or None when it cannot
    be drawn (no data, too few completed bars, charting library missing, or any
    plotting error). Never raises. `asof` (e.g. the scan time) is the time shown
    in the header; default: the signal's own time. `management` = settings from
    BP_management (default: the signal's own, else BP_config.yaml)."""
    cv = None
    try:
        sym = (signal or {}).get("symbol")
        if not sym or not ohlcv_cache or sym not in ohlcv_cache:
            return None
        ltf = signal.get("ltf") or "1d"
        comp, live = _bars((ohlcv_cache.get(sym) or {}).get(ltf) or [])
        if comp is None or len(comp) < MIN_BARS:
            return None
        comp = comp.tail(MAX_BARS).reset_index(drop=True)

        entry = _finite(signal.get("entry_price"))
        stop = _finite(signal.get("stop_price"))
        if entry is None or stop is None or entry == stop:
            return None
        tl = list(signal.get("targets") or [])
        target = _finite(tl[1]) if len(tl) > 1 else None
        is_long = _dir_is_long(signal.get("direction"))
        # scale_out: the take is at +1R (50%), the runner extends beyond it.
        mg = _management(signal, management)
        lv = (scale_out_levels(entry, stop, is_long, mg)
              if mg.get("mode") == "scale_out" and scale_out_levels is not None else None)
        runner_top = None
        if lv:
            target = lv["l1"]
            runner_top = lv["runner_top"]
        if target is not None and (target > entry) != is_long:
            target = None                       # nonsense level: do not draw it

        n = len(comp)
        x_last = n if live is not None else n - 1
        now = _finite(signal.get("current_price"))
        if now is None:
            now = float(live["close"]) if live is not None else float(comp["close"].iloc[-1])
        dec = price_decimals(sym, entry)
        zone = signal.get("zone") if isinstance(signal.get("zone"), dict) else None

        tags = [(f"Entry {_fmt_px(entry, dec)}", entry, ENTRY, "white"),
                (f"Stop {_fmt_px(stop, dec)}", stop, DOWN, "white")]
        if target is not None:
            t_name = (f"+{_fmt_r(lv['l1_r'])}R ({_frac_txt(lv['fraction'])})"
                      if lv else "Target")
            tags.append((f"{t_name} {_fmt_px(target, dec)}", target, UP, "white"))
        tags.append((f"Now {_fmt_px(now, dec)}", now, NOW, CHIP_TEXT_DARK))

        try:
            cv = _Canvas([t[0] for t in tags])
        except Exception as exc:   # ImportError, or a broken matplotlib
            _log(f"charting unavailable ({exc}); sending text only")
            return None
        ax = cv.ax

        # Y range: visible candles + every level drawn, 6% padding.
        ys = list(comp["low"]) + list(comp["high"]) + [entry, stop, target, now, runner_top]
        if live is not None:
            ys += [float(live["low"]), float(live["high"])]
        if zone:
            ys += [_finite(zone.get("proximal")), _finite(zone.get("distal"))]
        y0, y1 = _y_limits(ys, levels=[entry, stop, target, now, runner_top],
                           axes_px=ax.bbox.height, headroom_px=52)
        x_right = x_last + (RIGHT_PAD_BARS_SCALE_OUT if lv else RIGHT_PAD_BARS) + 0.5
        ax.set_xlim(-0.8, x_right)
        ax.set_ylim(y0, y1)
        min_body = (y1 - y0) * 0.0015

        xs = x_last + 0.8                       # position tool: last bar -> right edge
        if zone:
            _zone_box(cv, zone, comp["t"], x_right, xs, dec, ltf)

        _draw_candles(ax, comp, 0, min_body)
        if live is not None:
            _draw_live(ax, live, n, min_body)

        from matplotlib.patches import Rectangle
        ax.add_patch(Rectangle((xs, min(entry, stop)), x_right - xs, abs(entry - stop),
                               facecolor=_rgba(DOWN, 0.24), edgecolor="none", zorder=2))
        if target is not None:
            ax.add_patch(Rectangle((xs, min(entry, target)), x_right - xs, abs(target - entry),
                                   facecolor=_rgba(UP, 0.24), edgecolor="none", zorder=2))
        if lv and target is not None and runner_top is not None:
            # Runner extension: lighter, dashed outline -- it has no take-profit
            # (unless runner_target_r is set), it trails in whole-R steps.
            ax.add_patch(Rectangle((xs, min(target, runner_top)), x_right - xs,
                                   abs(runner_top - target), facecolor=_rgba(UP, 0.08),
                                   edgecolor=_rgba(RUNNER, 0.75), linewidth=1.1,
                                   linestyle=(0, (5, 3)), zorder=2))
            for _pk, pk_px, _lr, _lp in lv["locks"]:
                if (pk_px - runner_top) * (1 if is_long else -1) < 0:
                    ax.hlines(pk_px, xs, x_right, colors=RUNNER, linewidth=0.9,
                              linestyles=(0, (2, 3)), alpha=0.7, zorder=6)
        # Levels: faint over the history, strong across the position tool.
        levels = [(entry, ENTRY, 1.7), (stop, DOWN, 1.7)]
        if target is not None:
            levels.append((target, UP, 2.6))
        for y, colr, lw in levels:
            ax.hlines(y, -0.8, xs, colors=colr, linewidth=1.0, alpha=0.45, zorder=3)
            ax.hlines(y, xs, x_right, colors=colr, linewidth=lw, zorder=7)
        if lv and runner_top is not None:
            ax.hlines(runner_top, xs, x_right, colors=RUNNER, linewidth=1.6,
                      linestyles=(0, (5, 3)), zorder=7)
        ax.axhline(now, color=NOW, linewidth=1.2, linestyle=(0, (2, 3)), zorder=6)

        # In-plot labels next to the boxes.
        risk_usd = _finite(signal.get("risk_usd_actual")) or _finite(signal.get("risk_amount"))
        rr = abs(target - entry) / abs(entry - stop) if target is not None else None
        stop_txt = "Stop" + (f"  {_money(-risk_usd)}" if risk_usd else "") + "  (-1R)"
        lab = [(stop_txt, stop, DOWN)]
        if target is not None and lv:
            frac = lv["fraction"]
            booked = f" ({_money(risk_usd * lv['l1_r'] * frac)})" if risk_usd else ""
            lab.append((f"+{_fmt_r(lv['l1_r'])}R: close {_frac_txt(frac)}{booked} - stop to BE",
                        target, UP))
            rest = _frac_txt(1.0 - frac)
            if lv["runner_target"] is not None:
                r_txt = f"Runner {rest} - target +{_fmt_r(lv['runner_target_r'])}R"
            elif mg.get("runner_trail") == "r_steps":
                r_txt = f"Runner {rest} - trails in 1R steps"
            else:
                r_txt = f"Runner {rest} - stop stays at BE"
            lab.append((r_txt, runner_top, RUNNER))
        elif target is not None:
            tgt_txt = "Target" + (f"  {_money(risk_usd * rr)}" if risk_usd else "") + \
                f"  (+{_r_text(rr)}R)"
            lab.append((tgt_txt, target, UP))
        lots = _finite(signal.get("lot_size"))
        units = _finite(signal.get("units"))
        size_txt = (f"  {lots:g} lots" if lots else (f"  {units:,.0f} units" if units else ""))
        entry_txt = f"Entry  {_order_word(signal).upper()}{size_txt}"
        lab.append((entry_txt, entry, ENTRY))

        tool_px = (x_right - xs) * cv.px_per_x() - 14
        texts = [t for t, _, _ in lab]
        weight = "bold"
        fs = _fit_font(cv, texts, tool_px, FS_LABEL, weight, floor=10.5)
        if max(cv.text_size(t, fs, weight)[0] for t in texts) > tool_px:
            weight = "normal"              # regular is ~12% narrower than bold
            fs = _fit_font(cv, texts, tool_px, 11.5, weight, floor=9.5)
        th = max(cv.text_size(t, fs, weight)[1] for t in texts) + 8
        e_px = cv.y_to_px(entry)
        desired = []
        for text, y, colr in lab:
            if colr == ENTRY:
                desired.append(e_px)
                continue
            y_px = cv.y_to_px(y)
            box_px = abs(y_px - e_px)
            away = 1.0 if y_px > e_px else -1.0          # direction from entry to the level
            inside = box_px >= 2.2 * th
            desired.append(y_px - away * (th / 2 + 3) if inside else y_px + away * (th / 2 + 3))
        bb = ax.bbox
        placed = _spread(desired, th + 2, bb.y0 + th / 2, bb.y1 - th / 2)
        fits = max(cv.text_size(t, fs, weight)[0] for t in texts) <= tool_px
        x_text, ha = (xs + 0.5, "left") if fits else (x_right - 0.4, "right")
        for (text, _y, colr), py in zip(lab, placed):
            if colr == ENTRY:
                style = dict(color="white", bbox=dict(boxstyle="round,pad=0.3", fc=ENTRY, ec="none"))
            else:
                style = dict(color=colr, bbox=dict(boxstyle="round,pad=0.25",
                                                   fc=_rgba(AX_BG, 0.82), ec="none"))
            ax.text(x_text, cv.px_to_y(py), text, fontsize=fs, fontweight=weight,
                    ha=ha, va="center", zorder=15, **style)

        cv.price_axis(dec)
        walls = list(comp["wall"]) + ([live["wall"]] if live is not None else [])
        cv.date_axis(walls)
        cv.price_tags(tags)

        # Header / footer.
        name = display_name(sym)
        dir_word = "LONG" if is_long else "SHORT"
        et = str(signal.get("entry_type") or "").upper()
        parts = [_order_word(signal),
                 _ENTRY_TYPES.get(et, f"{signal.get('entry_type')} entry") if et else "zone entry",
                 f"{_tf_name(signal.get('htf') or signal.get('income_strategy')).capitalize()} "
                 f"setup on the {_tf_name(ltf)} chart"]
        if str(signal.get("trade_context") or "") == "counter_trend":
            parts.append("counter-trend, half size")
        if lv:
            parts.append(f"{_frac_txt(lv['fraction'])} off at +{_fmt_r(lv['l1_r'])}R, runner trails")
        when = _fmt_when(asof or signal.get("signal_time") or signal.get("placed_at")
                         or signal.get("timestamp"))
        if when:
            parts.append(when)
        cv.header(f"{name}  {dir_word}", UP if is_long else DOWN, "  ·  ".join(parts))
        qs = signal.get("qualifier_scores") or {}
        comp_score = _finite(qs.get("composite", signal.get("composite")))
        if comp_score is not None:
            cv.corner(f"Composite {round(comp_score + 1e-9, 1):.1f} / 10", "#383A40")

        bias = signal.get("bias_consensus") or {}
        chips = []
        for label, key in _BIAS_KEYS:
            v = str(bias.get(key) or "n/a")
            txt = f"{label}: {v}"
            if key == "cot" and str(bias.get("cot_strength") or "") == "strong":
                txt += " (strong)"
            fc = _bias_colour(v)
            chips.append((txt, fc, "white" if fc != NEUTRAL else TEXT))
        cv.chips(chips)
        cv.watermark()
        return cv.save(f"azalyst_chart_{_safe_name(sym)}_")
    except Exception as e:
        _log(f"failed for {(signal or {}).get('symbol')}: {e}")
        return None
    finally:
        if cv is not None:
            cv.close()


# ── Closed-trade result chart ─────────────────────────────────────────────

def _reason_label(reason, r: Optional[float]) -> str:
    rs = str(reason or "").strip()
    low = rs.lower()
    if re.match(r"^t\d", low) or low in ("target", "tp", "take_profit"):
        return "Target"
    names = {"stop": "Stop", "sl": "Stop", "breakeven": "Breakeven", "trail": "Trail stop",
             "expired": "Expired", "drifted": "Cancelled", "cancelled": "Cancelled"}
    if low in names:
        return names[low]
    if not rs:
        if r is None:
            return "Closed"
        return "Target" if r > 0 else ("Stop" if r < 0 else "Closed")
    return rs.replace("_", " ").capitalize()


def generate_trade_result_chart(trade: dict, ohlcv_cache: dict,
                                timeframe: Optional[str] = None,
                                management: Optional[Dict] = None) -> Optional[str]:
    """Draw a CLOSED trade (fill -> exit) and return the PNG path, or None.
    Never raises. `timeframe` picks the cached series (default: the trade's
    `ltf`, else 1d, else whatever the cache holds for the symbol). In scale_out
    mode the +1R partial and the runner exit are both marked and the badge
    shows the blended R."""
    cv = None
    try:
        sym = (trade or {}).get("symbol")
        if not sym or not ohlcv_cache or sym not in ohlcv_cache:
            return None
        series = ohlcv_cache.get(sym) or {}
        tf = timeframe or trade.get("ltf")
        if not tf or tf not in series:
            tf = "1d" if "1d" in series else next(iter(series), None)
        comp, live = _bars(series.get(tf) or [])
        if comp is None or len(comp) < MIN_BARS:
            return None
        frame = comp
        if live is not None:     # an exit on today's bar must still be placeable
            frame = pd.concat([comp, pd.DataFrame([live])], ignore_index=True)
        n_live = len(frame) - 1 if live is not None else None

        entry = _finite(trade.get("entry_price"))
        stop = _finite(trade.get("stop_price"))
        fill = _finite(trade.get("fill_price")) or entry
        close = _finite(trade.get("close_price"))
        if entry is None or stop is None or close is None or fill is None or entry == stop:
            return None
        tl = list(trade.get("targets") or [])
        target = _finite(tl[1]) if len(tl) > 1 else None
        is_long = _dir_is_long(trade.get("direction"))
        mg = _management(trade, management)
        lv = (scale_out_levels(entry, stop, is_long, mg)
              if mg.get("mode") == "scale_out" and scale_out_levels is not None else None)
        if lv:
            target = lv["l1"]
        if target is not None and (target > entry) != is_long:
            target = None
        # The partial / runner markers are scale_out drawing only; a ladder T2
        # partial keeps the unchanged fixed/ladder chart.
        p_px = (_finite(trade.get("partial_price"))
                if lv and trade.get("partial_taken") else None)
        peak_px = None
        if lv and p_px is not None:
            pk = _finite(trade.get("runner_peak_r"))
            if pk is not None and pk > lv["l1_r"]:
                peak_px = entry + (1 if is_long else -1) * pk * lv["risk"]

        times = frame["t"]
        i_x = _bar_index(times, trade.get("close_time"))
        if i_x is None:
            i_x = len(frame) - 1
        i_f = _bar_index(times, trade.get("filled_at") or trade.get("fill_time")
                         or trade.get("entry_time"))
        if i_f is None or i_f > i_x:
            i_f = max(0, i_x - 3)
        start = max(0, i_f - RESULT_BARS_BEFORE)
        end = min(len(frame) - 1, i_x + RESULT_BARS_AFTER)
        win = frame.iloc[start:end + 1].reset_index(drop=True)
        xf, xx = i_f - start, i_x - start
        live_x = (n_live - start) if (n_live is not None and start <= n_live <= end) else None
        xp = None
        if p_px is not None:
            i_p = _bar_index(times, trade.get("partial_time"))
            i_p = i_x if i_p is None else min(max(i_p, i_f), i_x)
            xp = i_p - start

        r = _finite(trade.get("r_multiple", trade.get("trade_r_multiple")))
        if r is None or (r == 0 and close != fill):
            risk = abs(fill - stop)
            if risk > 0:
                r = ((close - fill) if is_long else (fill - close)) / risk
        pnl = _finite(trade.get("realized_pnl", trade.get("pnl")))
        good = (pnl if pnl is not None and pnl != 0 else (r or 0.0))
        res_col = UP if good > 0 else (DOWN if good < 0 else NEUTRAL)
        reason = _reason_label(trade.get("close_reason"), r)
        dec = price_decimals(sym, entry)
        t_name = (f"+{_fmt_r(lv['l1_r'])}R ({_frac_txt(lv['fraction'])})" if lv else "Target")
        x_name = "Runner exit" if xp is not None else "Exit"
        if xp is not None:
            # Blended scale-out result, e.g. "50% at +1R, runner BE".
            rs_ = str(trade.get("close_reason") or "").lower()
            xr = ((close - entry) if is_long else (entry - close)) / abs(entry - stop)
            runner = {"breakeven": "runner BE", "trail": f"runner +{_r_text(xr)}R lock",
                      "runner_target": f"runner target +{_r_text(xr)}R"}.get(
                rs_, f"runner {xr:+.1f}R")
            pr = ((p_px - entry) if is_long else (entry - p_px)) / abs(entry - stop)
            pq, rem = _finite(trade.get("partial_qty")) or 0.0, _finite(trade.get("position_size")) or 0.0
            frac = pq / (pq + rem) if pq + rem > 0 else (lv["fraction"] if lv else 0.5)
            reason = f"{_frac_txt(frac)} at +{_r_text(pr)}R, {runner}"

        tags = [(f"Entry {_fmt_px(entry, dec)}", entry, ENTRY, "white"),
                (f"Stop {_fmt_px(stop, dec)}", stop, DOWN, "white")]
        if target is not None:
            tags.append((f"{t_name} {_fmt_px(target, dec)}", target, UP, "white"))
        tags.append((f"{x_name} {_fmt_px(close, dec)}", close, res_col, "white"))
        try:
            cv = _Canvas([t[0] for t in tags])
        except Exception as exc:
            _log(f"charting unavailable ({exc}); sending text only")
            return None
        ax = cv.ax

        n = len(win)
        x_right = n - 1 + RESULT_RIGHT_PAD + 0.5
        ys = list(win["low"]) + list(win["high"]) + [entry, stop, target, fill, close,
                                                     p_px, peak_px]
        y0, y1 = _y_limits(ys, levels=[entry, stop, target, close, peak_px],
                           axes_px=ax.bbox.height, headroom_px=52)
        ax.set_xlim(-0.8, x_right)
        ax.set_ylim(y0, y1)
        min_body = (y1 - y0) * 0.0015

        from matplotlib.patches import Rectangle
        a, b = xf - 0.45, xx + 0.45
        ax.add_patch(Rectangle((a, min(entry, stop)), b - a, abs(entry - stop),
                               facecolor=_rgba(DOWN, 0.22), edgecolor="none", zorder=2))
        if target is not None:
            ax.add_patch(Rectangle((a, min(entry, target)), b - a, abs(target - entry),
                                   facecolor=_rgba(UP, 0.22), edgecolor="none", zorder=2))
        if xp is not None and target is not None and peak_px is not None:
            ra = xp - 0.45
            ax.add_patch(Rectangle((ra, min(target, peak_px)), b - ra, abs(peak_px - target),
                                   facecolor=_rgba(UP, 0.08), edgecolor=_rgba(RUNNER, 0.75),
                                   linewidth=1.0, linestyle=(0, (5, 3)), zorder=2))
        if live_x is not None:
            _draw_candles(ax, win.iloc[:live_x], 0, min_body)
            _draw_live(ax, win.iloc[live_x], live_x, min_body)
            if live_x + 1 < n:
                _draw_candles(ax, win.iloc[live_x + 1:], live_x + 1, min_body)
        else:
            _draw_candles(ax, win, 0, min_body)
        levels = [(entry, ENTRY, 1.6), (stop, DOWN, 1.6)]
        if target is not None:
            levels.append((target, UP, 2.4))
        for y, colr, lw in levels:
            ax.hlines(y, -0.8, a, colors=colr, linewidth=1.0, alpha=0.35, zorder=3)
            ax.hlines(y, a, b, colors=colr, linewidth=lw, zorder=7)

        path_x, path_y = [xf, xx], [fill, close]
        if xp is not None:
            path_x, path_y = [xf, xp, xx], [fill, p_px, close]
        ax.plot(path_x, path_y, color=TEXT, linewidth=1.6, linestyle=(0, (4, 3)),
                alpha=0.85, zorder=16)
        ax.scatter([xf], [fill], marker="^" if is_long else "v", s=230, color=ENTRY,
                   edgecolors="white", linewidths=1.2, zorder=17)
        ax.scatter([xx], [close], marker="X", s=240, color=res_col, edgecolors="white",
                   linewidths=1.2, zorder=17)
        captions = [("Fill", xf, fill, is_long)]
        if xp is not None:
            ax.scatter([xp], [p_px], marker="D", s=170, color=UP, edgecolors="white",
                       linewidths=1.2, zorder=17)
            captions.append((f"{_frac_txt(lv['fraction'] if lv else 0.5)} off +"
                             f"{_fmt_r(lv['l1_r']) if lv else '1'}R",
                             xp, p_px, not is_long))
            captions.append(("Runner exit", xx, close, close < p_px))
        else:
            captions.append(("Exit", xx, close, close < fill))
        # Marker captions on the side away from the connecting line, flipped when
        # that would push them out of the plot.
        bb = ax.bbox
        for text, x, y, below in captions:
            py = cv.y_to_px(y)
            if below and py - bb.y0 < 48:
                below = False
            elif not below and bb.y1 - py < 48:
                below = True
            ax.annotate(text, xy=(x, y), xytext=(0, -14 if below else 14),
                        textcoords="offset points", ha="center",
                        va="top" if below else "bottom",
                        fontsize=10.5, fontweight="bold", color=TEXT, zorder=18,
                        bbox=dict(boxstyle="round,pad=0.2", fc=_rgba(AX_BG, 0.75), ec="none"))

        cv.price_axis(dec)
        cv.date_axis(list(win["wall"]))
        cv.price_tags(tags)

        name = display_name(sym)
        dir_word = "LONG" if is_long else "SHORT"
        held = i_x - i_f
        f_when = trade.get("filled_at") or trade.get("fill_time") or trade.get("entry_time")
        f_day = _fmt_day(f_when) if _to_utc(f_when) is not None else \
            pd.Timestamp(frame["wall"].iloc[i_f]).strftime("%d %b %Y")
        x_day = _fmt_day(trade.get("close_time")) if _to_utc(trade.get("close_time")) is not None \
            else pd.Timestamp(frame["wall"].iloc[i_x]).strftime("%d %b %Y")
        sub = [f"{_order_word(trade)} filled {f_day}", f"closed {x_day}",
               f"{held} bar{'s' if held != 1 else ''} on the {_tf_name(tf)} chart"]
        cv.header(f"{name}  {dir_word}  ·  CLOSED", UP if is_long else DOWN, "  ·  ".join(sub))
        badge = (f"{r:+.2f}R" if r is not None else "") + \
            (f"  {_money(pnl)}" if pnl is not None else "") + f"  {reason}"
        cv.corner(badge.strip(), res_col, "white", fs=16)
        cv.chips([(f"Entry {_fmt_px(entry, dec)}", ENTRY, "white"),
                  (f"Fill {_fmt_px(fill, dec)}", "#383A40", TEXT),
                  (f"Stop {_fmt_px(stop, dec)}", DOWN, "white")]
                 + ([(f"{t_name} {_fmt_px(target, dec)}", UP, "white")] if target is not None else [])
                 + [(f"{x_name} {_fmt_px(close, dec)}", res_col, "white")])
        cv.watermark()
        return cv.save(f"azalyst_result_{_safe_name(sym)}_")
    except Exception as e:
        _log(f"result chart failed for {(trade or {}).get('symbol')}: {e}")
        return None
    finally:
        if cv is not None:
            cv.close()
