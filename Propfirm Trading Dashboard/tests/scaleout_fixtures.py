"""Shared GBPNZD fixtures for the scale-out tests and research/make_scaleout_samples.py.

GBPNZD=X short from a weekly RBD supply zone 2.34939 - 2.35340 (the live
2026-09-28 example): entry 2.34939 (sell-limit at the proximal), stop 2.35340,
risk 0.00401 = $50 at 1% of $5,000, engine targets 1R/2R/3R.
"""
from typing import Dict, List

import numpy as np
import pandas as pd

ENTRY, STOP = 2.34939, 2.35340
RISK = STOP - ENTRY                                   # 0.00401 (short)
L1, R2, R3 = 2.34538, 2.34137, 2.33736
SIZE = 50.0 / RISK                                    # units for a $50 risk
SCALE_OUT = {"mode": "scale_out", "scale_out_at_r": 1.0, "scale_out_fraction": 0.5,
             "runner_trail": "r_steps", "runner_target_r": None, "take_profit_target": 2}

# Daily bars. The zone base prints ~bar 44, price trades up into it and the
# signal is on bar 79; the trade fills on bar 82.
N_BARS = 100
T0 = pd.Timestamp("2026-06-01", tz="UTC")


def _day(i: int) -> pd.Timestamp:
    return T0 + pd.Timedelta(days=i)


def daily_rows(n: int = N_BARS, last_complete: bool = True) -> List[Dict]:
    rng = np.random.default_rng(7)
    # Anchors: rally (leg-in) to the highs, base, explosive drop (leg-out),
    # grind back up towards the supply zone; small noise on top.
    anchors = [(0, 2.3250), (40, 2.3515), (44, 2.3512), (50, 2.3330), (79, 2.3455),
               (n - 1, 2.3455)]
    xs, ys = zip(*anchors)
    base = np.interp(np.arange(n), xs, ys)
    closes = list(base + rng.normal(0, 0.0005, n))
    # Shape the trade window (bars 80-95) explicitly: into the entry, down past
    # +1R, back up to breakeven.
    shaped = {80: 2.3462, 81: 2.3478, 82: 2.3490, 83: 2.3472, 84: 2.3460, 85: 2.3449,
              86: 2.3444, 87: 2.3456, 88: 2.3470, 89: 2.3490, 90: 2.3480, 91: 2.3462,
              92: 2.3440, 93: 2.3425, 94: 2.3409, 95: 2.3418}
    for k, v in shaped.items():
        if k < n:
            closes[k] = v
    rows = []
    prev = closes[0] - 0.0005
    for i, c in enumerate(closes):
        o = prev
        h = max(o, c) + abs(rng.normal(0.0009, 0.0003))
        lo = min(o, c) - abs(rng.normal(0.0009, 0.0003))
        if i == 82:
            h = max(h, ENTRY + 0.00005)                          # the fill
        if i == 86:
            lo = min(lo, L1 - 0.00020)                           # +1R reached
        if i == 89:
            h = max(h, ENTRY + 0.00008)                          # back to breakeven
        if i == 94:
            lo = min(lo, R3 - 0.00015)                           # +3R peak (trail example)
        rows.append({"timestamp": str(_day(i)), "open": round(o, 5), "high": round(h, 5),
                     "low": round(lo, 5), "close": round(c, 5), "volume": 0,
                     "is_complete": bool(last_complete or i < n - 1)})
        prev = c
    return rows


def cache() -> Dict:
    return {"GBPNZD=X": {"1d": daily_rows()}}


def signal() -> Dict:
    return {
        "symbol": "GBPNZD=X", "display_name": "GBPNZD", "direction": "short",
        "entry_price": ENTRY, "stop_price": STOP, "targets": [L1, R2, R3],
        "order_type": "limit", "entry_type": "E1", "htf": "1wk", "ltf": "1d",
        "income_strategy": "weekly", "trade_context": "standard",
        "pending_order": True, "price_at_zone": False, "current_price": 2.34620,
        "setup_key": f"GBPNZD=X|short|{ENTRY:.5g}|{STOP:.5g}", "zone_id": "gbpnzd-rbd",
        "paper_trade_id": "P-GBPNZD", "signal_time": str(_day(79)),
        "qualifier_scores": {"composite": 8.4},
        "risk_amount": 50.0, "risk_usd_actual": 50.0, "risk_usd_target": 50.0,
        "lot_size": 0.12, "units": 12000, "position_size": SIZE,
        "zone": {"type": "supply", "proximal": ENTRY, "distal": STOP, "formation": "RBD",
                 "timeframe": "1wk", "base_start": str(_day(40))},
        "bias_consensus": {"location": "bearish", "valuation": "bearish", "cot": "bearish",
                           "cot_strength": "strong", "seasonality": "neutral",
                           "trend": "downtrend"},
    }


def closed_trade(kind: str = "breakeven") -> Dict:
    """A closed scale-out GBPNZD short as get_trade_history() renders it."""
    half = SIZE / 2
    base = {
        "id": f"T-{kind}", "symbol": "GBPNZD=X", "direction": "short", "status": "closed",
        "entry_price": ENTRY, "stop_price": STOP, "targets": [L1, R2, R3],
        "fill_price": ENTRY, "filled_at": str(_day(82)), "order_type": "limit",
        "partial_taken": True, "partial_qty": half, "position_size": half,
        "partial_price": L1, "partial_time": str(_day(86)), "breakeven_triggered": True,
        "risk_amount": 50.0, "ltf": "1d",
    }
    if kind == "breakeven":
        base.update(close_price=ENTRY, current_stop=ENTRY, close_reason="breakeven",
                    close_time=str(_day(89)), realized_pnl=25.0, pnl=25.0,
                    r_multiple=0.5, runner_peak_r=1.3)
    else:  # runner locked +2R after a +3R peak, then stopped there
        base.update(close_price=R2, current_stop=R2, trail_stop_level=R2,
                    close_reason="trail", close_time=str(_day(95)),
                    realized_pnl=25.0 + 50.0, pnl=75.0, r_multiple=1.5, runner_peak_r=3.2,
                    partial_time=str(_day(86)))
    return base
