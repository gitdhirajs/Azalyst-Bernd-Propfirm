"""
Trade-management settings: ONE reader for `stop_loss.management` and its keys.

The paper trader (BP_paper_trader), the Discord text (send_discord) and the
charts (draw_chart) must all describe the same management, so all three read
it through management_settings() / live_management() below.

Modes (BP_config.yaml, stop_loss.management):

  scale_out  (DEFAULT, user decision 2026-09-28: "when 1r reach close 50% move
             to breakeven n then let 50% run till possible")
             At +scale_out_at_r (1R) close scale_out_fraction (50%) of the
             original size and move the stop to breakeven (the fill price) from
             the next bar. The runner then trails in whole-R steps
             (runner_trail: r_steps): once the peak excursion reaches +2R the
             stop locks +1R, +3R locks +2R, ... It exits only on its stop, or
             at runner_target_r when one is set (null = no cap).
  fixed      set-and-forget (2026-09-27): the stop never moves, 100% closes at
             T<take_profit_target> (2R).
  ladder     the pre-2026-09-27 path: half-T1 / T1 breakeven, 50% at T2,
             1R trail, rest at T3.

Revert to the previous live behaviour with `stop_loss.management: fixed`.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

MODES = ("scale_out", "fixed", "ladder")
DEFAULT_MODE = "scale_out"
TRAIL_MODES = ("r_steps", "none")

_HERE = Path(__file__).resolve().parent
_LIVE_CACHE: Optional[Dict] = None


def _pos_float(v, default: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) and f > 0 else default


def _cfg_float(v):
    """(value, ok) for an explicitly configured number: None/'' = not set
    (ok, value None); anything unparseable, non-finite or <= 0 = not ok."""
    if v in (None, ""):
        return None, True
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None, False
    if not math.isfinite(f) or f <= 0:
        return None, False
    return f, True


# The conservative set-and-forget bracket every invalid setting falls back to.
SAFE_MODE = "fixed"


def management_settings(config: Optional[Dict]) -> Dict:
    """Normalised management settings from a full config dict (reads its
    `stop_loss` block), a bare stop_loss block, or an already-normalised
    settings dict (has a `mode` key). Never raises.

    A MISSING `management` key means scale_out (the 2026-09-28 default). An
    UNKNOWN value (e.g. 'fixd' typed during a revert) and a scale_out block
    whose numbers make no sense (scale_out_at_r / scale_out_fraction <= 0 or
    unparseable, scale_out_fraction > 1, runner_target_r <= scale_out_at_r)
    fall back to 'fixed' -- the conservative set-and-forget bracket -- with a
    logged ERROR, and the reason is listed under 'errors' (the Discord footer
    shows it), so a bad edit is loud instead of silently trading scale_out."""
    cfg = config or {}
    if not isinstance(cfg, dict):
        cfg = {}
    carried: List[str] = []
    if "mode" in cfg and "management" not in cfg:
        sl = dict(cfg)
        sl["management"] = cfg.get("mode")
        carried = [str(e) for e in (cfg.get("errors") or [])]
    elif isinstance(cfg.get("stop_loss"), dict):
        sl = cfg["stop_loss"]
    else:
        sl = cfg

    errors: List[str] = list(carried)
    raw_mode = sl.get("management")
    mode = str(raw_mode or DEFAULT_MODE).strip().lower()
    if mode not in MODES:
        errors.append(f"stop_loss.management={raw_mode!r} is not one of {MODES}; "
                      f"using {SAFE_MODE}")
        mode = SAFE_MODE

    at_r, ok_at = _cfg_float(sl.get("scale_out_at_r"))
    frac, ok_fr = _cfg_float(sl.get("scale_out_fraction"))
    at_r = 1.0 if at_r is None else at_r
    frac = 0.5 if frac is None else frac
    trail = str(sl.get("runner_trail") or "r_steps").strip().lower()
    if trail not in TRAIL_MODES:
        logger.warning(f"stop_loss.runner_trail={trail!r} is not one of {TRAIL_MODES}; "
                       f"using r_steps")
        trail = "r_steps"
    tgt = sl.get("runner_target_r")
    if isinstance(tgt, str) and tgt.strip().lower() in ("null", "none"):
        tgt = None
    target_r, ok_tg = _cfg_float(tgt)

    if mode == "scale_out":
        bad = []
        if not ok_at:
            bad.append(f"scale_out_at_r={sl.get('scale_out_at_r')!r} must be > 0")
        if not ok_fr or frac > 1.0:
            bad.append(f"scale_out_fraction={sl.get('scale_out_fraction')!r} "
                       f"must be > 0 and <= 1")
        if not ok_tg:
            bad.append(f"runner_target_r={sl.get('runner_target_r')!r} must be a "
                       f"number > 0 or null")
        elif target_r is not None and ok_at and target_r <= at_r:
            bad.append(f"runner_target_r={target_r:g} must be above "
                       f"scale_out_at_r={at_r:g}")
        if bad:
            errors.append("scale_out settings rejected (" + "; ".join(bad)
                          + f"); using {SAFE_MODE}")
            mode = SAFE_MODE
    frac = min(frac, 1.0) if ok_fr else 0.5
    if not ok_at:
        at_r = 1.0
    if not ok_tg:
        target_r = None

    for e in errors[len(carried):]:
        logger.error(e)
    try:
        tp_target = max(1, int(sl.get("take_profit_target", 2)))
    except (TypeError, ValueError):
        tp_target = 2
    rb = sl.get("runner_blocks_new_entries", True)
    if isinstance(rb, str):
        rb = rb.strip().lower() not in ("false", "0", "no", "off")
    out = {
        "mode": mode,
        "scale_out_at_r": at_r,
        "scale_out_fraction": frac,
        "runner_trail": trail,
        "runner_target_r": target_r,
        "take_profit_target": tp_target,
        # scale_out: does a de-risked runner (partial off, stop at or beyond
        # breakeven) still count toward max_open_positions and as a
        # correlation peer? true = unchanged behaviour (it does).
        "runner_blocks_new_entries": bool(rb),
        # ladder only (text): breakeven half-way to T1 (true, the paper
        # trader's default) or at T1.
        "ladder_be_at_half": str(sl.get("breakeven_at_half_target",
                                        sl.get("ladder_be_at_half", True))).strip().lower()
        not in ("false", "0", "no", "off"),
    }
    if errors:
        out["errors"] = errors
    return out


def live_management(path: Optional[Path] = None, refresh: bool = False) -> Dict:
    """Settings from BP_config.yaml next to this file (cached). Defaults when
    the file cannot be read, so a missing yaml never breaks an alert."""
    global _LIVE_CACHE
    if _LIVE_CACHE is not None and not refresh and path is None:
        return dict(_LIVE_CACHE)
    cfg: Dict = {}
    try:
        import yaml
        with open(path or (_HERE / "BP_config.yaml"), "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception as exc:          # pragma: no cover - environment dependent
        logger.warning(f"could not read BP_config.yaml for management settings: {exc}")
    out = management_settings(cfg)
    if path is None:
        _LIVE_CACHE = dict(out)
    return out


def resolve_management(*candidates) -> Dict:
    """First usable candidate (settings dict or config dict), else the live
    BP_config.yaml. Lets a scan/signal carry the mode it was produced under."""
    for c in candidates:
        if isinstance(c, dict) and c:
            return management_settings(c)
    return live_management()


def trade_mode(trade: Optional[Dict]) -> Optional[str]:
    """The management mode a TRADE actually ran under, or None when the record
    does not say. Order: the mode stamped on the position at fill
    (`management_mode`), else inferred from scale-out-only fields
    (partial_time / runner_peak_r are only ever set by the scale-out path),
    else a partial without them is a ladder T2 partial."""
    t = trade or {}
    if not isinstance(t, dict):
        return None
    m = str(t.get("management_mode") or "").strip().lower()
    if m in MODES:
        return m
    try:
        peak = float(t.get("runner_peak_r") or 0.0)
    except (TypeError, ValueError):
        peak = 0.0
    if t.get("partial_time") or peak > 0:
        return "scale_out"
    if t.get("partial_taken"):
        return "ladder"
    return None


def trade_management(trade: Optional[Dict], *fallbacks) -> Dict:
    """Settings to DESCRIBE a trade with (result charts, closed/partial text):
    the configured settings (first usable fallback, else BP_config.yaml) with
    the mode replaced by the one the trade actually ran under (trade_mode), so
    reverting the config does not redraw an old trade in the new mode."""
    base = resolve_management(*fallbacks)
    m = trade_mode(trade)
    if m and m != base.get("mode"):
        base = dict(base)
        base["mode"] = m
    return base


def is_single_order(obj: Optional[Dict]) -> bool:
    """A signal/position the alert tells the user to place as ONE order with
    its take-profit at +1R (lot too small to split): flagged on the signal as
    scale_out_unsplittable, on the paper position as scale_out_single."""
    o = obj if isinstance(obj, dict) else {}
    return bool(o.get("scale_out_unsplittable") or o.get("scale_out_single"))


def for_trade(settings: Dict, obj: Optional[Dict]) -> Dict:
    """Settings adjusted for one signal/position: a single-order scale_out
    trade closes 100% at +1R (scale_out_fraction 1.0)."""
    s = dict(settings or {})
    if s.get("mode") == "scale_out" and is_single_order(obj):
        s["scale_out_fraction"] = 1.0
    return s


def split_lots(lot, frac, step: float = 0.01):
    """(lots of order A, lots of order B) for a scale-out split, in `step` lot
    increments; None when the lot is unknown, too small to split, or the
    fraction closes everything (>= 1)."""
    try:
        lot, frac = float(lot), float(frac)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lot) and math.isfinite(frac)) or lot <= 0 or frac >= 1.0 or frac <= 0:
        return None
    a = round(round(lot * frac / step) * step, 2)
    b = round(lot - a, 2)
    if a < step - 1e-9 or b < step - 1e-9:
        return None
    return a, b


def scale_out_unsplittable(lot, settings: Dict) -> bool:
    """True when a scale_out signal with this lot cannot be placed as two
    orders (A +1R take-profit / B runner). Unknown lot -> False."""
    s = settings or {}
    if s.get("mode") != "scale_out" or lot in (None, ""):
        return False
    try:
        if float(lot) <= 0:
            return False
    except (TypeError, ValueError):
        return False
    return split_lots(lot, s.get("scale_out_fraction", 0.5)) is None


def fmt_r(r: float) -> str:
    """1.0 -> '1', 1.5 -> '1.5'."""
    return f"{r:g}"


def scale_out_levels(entry: float, stop: float, is_long: bool, settings: Dict,
                     n_locks: int = 2) -> Optional[Dict]:
    """Reference price levels of a scale-out trade, measured from the PLANNED
    entry in units of the planned risk |entry - stop|.

    Returns {risk, l1, l1_r, fraction, locks: [(peak_r, peak_px, lock_r, lock_px)],
    runner_target_r, runner_target, runner_top} or None for unusable levels.
    runner_top = where a chart draws the runner extension up to (the runner
    target when set, else +3R)."""
    try:
        entry, stop = float(entry), float(stop)
    except (TypeError, ValueError):
        return None
    risk = abs(entry - stop)
    if not (math.isfinite(risk) and risk > 0):
        return None
    s = settings or {}
    sign = 1.0 if is_long else -1.0
    at_r = float(s.get("scale_out_at_r") or 1.0)
    px = lambda r: entry + sign * r * risk          # noqa: E731
    locks: List = []
    if s.get("runner_trail", "r_steps") == "r_steps":
        for k in range(1, n_locks + 1):
            peak = k + 1.0
            if s.get("runner_target_r") and peak >= float(s["runner_target_r"]):
                break
            locks.append((peak, px(peak), float(k), px(k)))
    tr = s.get("runner_target_r")
    top_r = float(tr) if tr else max(3.0, at_r)
    single = float(s.get("scale_out_fraction") or 0.5) >= 1.0
    if single:
        locks, tr, top_r = [], None, at_r
    return {
        "single": single,
        "risk": risk,
        "l1_r": at_r,
        "l1": px(at_r),
        "fraction": float(s.get("scale_out_fraction") or 0.5),
        "locks": locks,
        "runner_target_r": float(tr) if tr else None,
        "runner_target": px(float(tr)) if tr else None,
        "runner_top_r": top_r,
        "runner_top": px(top_r),
    }
