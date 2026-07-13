"""
Position sizing for FundingPips (MatchTrader) execution.

The scanner produces a signal with an entry, a stop, and a chosen dollar
risk (account x risk_per_trade_pct). What the trader actually needs to type
into FundingPips is a VOLUME -- expressed in lots (and equivalently units).

The old code computed `position_size = risk_usd / stop_distance`, which is
only dimensionally correct when a 1.0 move in price equals $1 per unit. That
holds for US-listed shares but is wrong for forex (where price is in the quote
currency, not USD), wrong for metals/indices/crypto (which have a contract
multiplier), and produces a meaningless number for pairs like USDTRY whose
quote currency is not USD.

This module converts a dollar risk into a correct lot size per instrument:

    risk_per_lot_usd = stop_distance * usd_value_of_one_point_per_lot
    lots             = risk_usd / risk_per_lot_usd

where `usd_value_of_one_point_per_lot` depends on the asset class:

  forex   : 100,000 units/lot * (USD value of 1 unit of the QUOTE currency).
            Fully derivable from live rates -- NO broker spec needed.
  metals  : contract_size (oz/lot), price already in USD.
  indices : point_value_per_lot USD -- BROKER SPECIFIC, must be verified.
  crypto  : contract_size (coins/lot), price already in USD.
  energies: contract_size (barrels/lot or similar) -- broker specific.
  equities: 1 share/lot, price in USD.

Specs flagged `verified: false` mean the multiplier could not be confirmed
against FundingPips and the trader should confirm the contract size on the
MatchTrader order ticket before sizing off the alert.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


STANDARD_FX_LOT_UNITS = 100_000.0  # one standard forex lot = 100k base units


@dataclass
class SizingResult:
    lots: float                  # volume to type into MatchTrader (lots)
    units: float                 # equivalent units (lots * contract_size)
    risk_usd_actual: float       # dollar risk this volume actually carries
    usd_per_point_per_lot: float # $ P&L per 1.0 price move, per 1 lot
    contract_size: float         # units (or oz/coins) per lot
    verified: bool               # False -> confirm contract size on platform
    note: str = ""               # human-readable caveat / explanation


def _round_to_step(value: float, step: float) -> float:
    """Round a lot size DOWN to the broker's volume step so we never exceed
    the intended risk (rounding up would breach the dollar budget)."""
    if step <= 0:
        return value
    n = int(value / step)
    return round(n * step, 8)


def quote_currency(symbol_name: str) -> Optional[str]:
    """Infer the quote (right-hand) currency from a 6-letter FX name like
    'EURUSD' or 'USDTRY'. Returns None for non-FX names."""
    s = symbol_name.upper().replace("=X", "").replace("/", "")
    if len(s) == 6 and s.isalpha():
        return s[3:]
    return None


def base_currency(symbol_name: str) -> Optional[str]:
    s = symbol_name.upper().replace("=X", "").replace("/", "")
    if len(s) == 6 and s.isalpha():
        return s[:3]
    return None


def compute_lots(
    *,
    asset_class: str,
    symbol_name: str,
    entry: float,
    stop: float,
    risk_usd: float,
    spec: Dict,
    usd_per_quote_ccy: Optional[Dict[str, float]] = None,
    force_min_lot: bool = False,
    min_lot_multiplier: float = 1.0,
) -> SizingResult:
    """Convert a dollar risk into a MatchTrader lot size for one signal.

    Args:
        asset_class: 'forex' | 'precious_metals' | 'equity_indices' |
                     'crypto' | 'energies' | 'commodities' | 'equities'.
        symbol_name: broker display name, e.g. 'USDTRY', 'XAUUSD (Gold)'.
        entry, stop: signal prices (same scale as the instrument quotes).
        risk_usd:    dollar risk budget for this trade.
        spec:        instrument spec dict: contract_size, point_value_per_lot,
                     min_lot, lot_step, verified.
        usd_per_quote_ccy: map of currency -> USD value of one unit, derived
                     from live FX rates. Required for forex sizing.

    Returns:
        SizingResult. `lots` is what the trader enters on FundingPips.
    """
    stop_distance = abs(entry - stop)
    min_lot = float(spec.get("min_lot", 0.01))
    lot_step = float(spec.get("lot_step", 0.01))
    verified = bool(spec.get("verified", False))

    if stop_distance <= 0:
        return SizingResult(0, 0, 0, 0, 0, verified, "invalid stop (zero distance)")

    note = ""

    if asset_class == "forex":
        qccy = quote_currency(symbol_name)
        usd_per_quote = None
        if qccy and usd_per_quote_ccy:
            usd_per_quote = usd_per_quote_ccy.get(qccy)
        if qccy == "USD":
            usd_per_quote = 1.0
        if usd_per_quote is None:
            # Cannot value the quote currency in USD -> cannot size safely.
            return SizingResult(
                0, 0, 0, 0, STANDARD_FX_LOT_UNITS, False,
                f"missing USD rate for quote currency {qccy}; confirm size on platform",
            )
        contract_size = STANDARD_FX_LOT_UNITS
        usd_per_point_per_lot = STANDARD_FX_LOT_UNITS * usd_per_quote
        verified = True  # FX math is broker-independent
    elif asset_class in ("precious_metals", "crypto"):
        contract_size = float(spec.get("contract_size", 1.0))
        # price quoted in USD -> $ per 1.0 move per lot = contract_size
        usd_per_point_per_lot = contract_size
    elif asset_class in ("equity_indices", "energies", "commodities"):
        contract_size = float(spec.get("contract_size", 1.0))
        usd_per_point_per_lot = float(spec.get("point_value_per_lot", contract_size))
    elif asset_class == "equities":
        contract_size = float(spec.get("contract_size", 1.0))  # 1 share/lot
        usd_per_point_per_lot = contract_size  # price in USD
    else:
        contract_size = float(spec.get("contract_size", 1.0))
        usd_per_point_per_lot = float(spec.get("point_value_per_lot", contract_size))
        note = f"unknown asset_class '{asset_class}'; using contract_size={contract_size}"
        verified = False

    risk_per_lot = stop_distance * usd_per_point_per_lot
    if risk_per_lot <= 0:
        return SizingResult(0, 0, 0, usd_per_point_per_lot, contract_size, False,
                            "non-positive risk-per-lot")

    raw_lots = risk_usd / risk_per_lot
    lots = _round_to_step(raw_lots, lot_step)
    if force_min_lot:
        # Trade a FIXED size (the platform's min lot times a user-chosen
        # multiplier) regardless of the 1% risk budget. Originally only used
        # for CAUTION signals; also used account-wide when
        # risk.fixed_lot_mode is on (2026-07-13) so every trade stays at a
        # small, constant size until the account has proven profitable.
        lots = _round_to_step(min_lot * min_lot_multiplier, lot_step)
        note = (f"fixed lot {lots} ({min_lot} x {min_lot_multiplier:g}) "
                f"(risk ${lots * risk_per_lot:,.2f}, ignoring the 1% budget)")
    elif 0 < lots < min_lot:
        # Smallest tradable size already exceeds the intended risk.
        lots = min_lot
        note = (f"min lot {min_lot} carries ${min_lot * risk_per_lot:,.0f} risk "
                f"> intended ${risk_usd:,.0f} -- consider skipping or widening stop")

    units = lots * contract_size
    risk_usd_actual = lots * risk_per_lot

    if not verified and not note:
        note = "contract size unverified -- confirm on MatchTrader ticket before trading"

    return SizingResult(
        lots=round(lots, 4),
        units=round(units, 2),
        risk_usd_actual=round(risk_usd_actual, 2),
        usd_per_point_per_lot=round(usd_per_point_per_lot, 6),
        contract_size=contract_size,
        verified=verified,
        note=note,
    )


def build_usd_quote_table(live_prices: Dict[str, float]) -> Dict[str, float]:
    """Build {currency -> USD value of one unit} from live FX rates.

    `live_prices` maps broker FX names (e.g. 'EURUSD', 'USDJPY', 'USDTRY')
    to their current price. We derive the USD value of each quote currency
    we might encounter so forex sizing needs no broker-specific spec.

    USD-quote majors (EURUSD) give the base ccy's USD value directly.
    USD-base pairs (USDJPY, USDTRY) give the quote ccy's USD value as 1/price.
    """
    table: Dict[str, float] = {"USD": 1.0}
    for name, price in live_prices.items():
        if not price or price <= 0:
            continue
        b, q = base_currency(name), quote_currency(name)
        if not b or not q:
            continue
        if q == "USD":
            table.setdefault(b, price)          # 1 base = `price` USD
        elif b == "USD":
            table.setdefault(q, 1.0 / price)    # 1 quote = 1/price USD
    return table
