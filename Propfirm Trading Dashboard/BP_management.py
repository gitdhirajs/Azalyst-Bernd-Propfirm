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


def management_settings(config: Optional[Dict]) -> Dict:
    """Normalised management settings from a full config dict (reads its
    `stop_loss` block), a bare stop_loss block, or an already-normalised
    settings dict (has a `mode` key). Never raises; unknown values fall back
    to the defaults above."""
    cfg = config or {}
    if not isinstance(cfg, dict):
        cfg = {}
    if "mode" in cfg and "management" not in cfg:
        sl = dict(cfg)
        sl["management"] = cfg.get("mode")
    elif isinstance(cfg.get("stop_loss"), dict):
        sl = cfg["stop_loss"]
    else:
        sl = cfg

    mode = str(sl.get("management") or DEFAULT_MODE).strip().lower()
    if mode not in MODES:
        logger.warning(f"stop_loss.management={mode!r} is not one of {MODES}; "
                       f"using {DEFAULT_MODE}")
        mode = DEFAULT_MODE

    frac = _pos_float(sl.get("scale_out_fraction"), 0.5)
    frac = min(frac, 1.0)
    trail = str(sl.get("runner_trail") or "r_steps").strip().lower()
    if trail not in TRAIL_MODES:
        logger.warning(f"stop_loss.runner_trail={trail!r} is not one of {TRAIL_MODES}; "
                       f"using r_steps")
        trail = "r_steps"
    tgt = sl.get("runner_target_r")
    target_r = None if tgt in (None, "", "null", "none") else _pos_float(tgt, 0.0) or None
    try:
        tp_target = max(1, int(sl.get("take_profit_target", 2)))
    except (TypeError, ValueError):
        tp_target = 2
    return {
        "mode": mode,
        "scale_out_at_r": _pos_float(sl.get("scale_out_at_r"), 1.0),
        "scale_out_fraction": frac,
        "runner_trail": trail,
        "runner_target_r": target_r,
        "take_profit_target": tp_target,
    }


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
    return {
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
