"""
Paper Trading Simulator - Simulated brokerage that executes trades,
manages stops, targets, trailing stops, and tracks P&L.
Implements Section F and G from the Strategy Rulebook.
"""

import uuid
import json
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field, asdict
from enum import Enum

from BP_rules_engine import RulesEngine

logger = logging.getLogger(__name__)


class TradeDirection(str, Enum):
    LONG = "long"
    SHORT = "short"


class TradeStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    CLOSED = "closed"
    CANCELLED = "cancelled"


@dataclass
class Position:
    id: str
    symbol: str
    direction: TradeDirection
    entry_price: float
    stop_price: float
    current_stop: float
    targets: List[float]
    position_size: float
    risk_amount: float
    entry_time: datetime
    status: TradeStatus = TradeStatus.ACTIVE
    realized_pnl: float = 0.0
    partial_taken: bool = False
    partial_qty: float = 0.0
    partial_price: float = 0.0
    breakeven_triggered: bool = False
    trail_stop_level: Optional[float] = None
    zone_id: Optional[str] = None
    close_time: Optional[datetime] = None
    close_price: Optional[float] = None
    trade_r_multiple: float = 0.0
    notes: str = ""
    income_strategy: Optional[str] = None


@dataclass
class AccountState:
    balance: float = 100000.0
    initial_balance: float = 100000.0
    closed_pnl_total: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    max_drawdown_pct: float = 0.0
    peak_balance: float = 100000.0
    daily_pnl: float = 0.0
    daily_trades: int = 0
    last_trade_day: Optional[str] = None


class PaperTrader:
    """
    Simulated brokerage for paper trading.
    Manages position lifecycle: entry, stop management, targets, trailing.
    """

    def __init__(self, config: Dict):
        self.config = config
        self.risk_cfg = config.get('risk', {})
        self.stop_cfg = config.get('stop_loss', {})
        # Fundingpips-style prop firm guardrails. Configured under `prop_firm`
        # in BP_config.yaml. When `enabled: true`, trades that would breach
        # the max-daily-loss or max-loss thresholds are blocked at submit
        # time -- exactly matching what the broker would do on the real
        # account.
        self.prop_cfg = config.get('prop_firm', {})
        self.prop_enabled = bool(self.prop_cfg.get('enabled', False))

        # Starting balance: prop_firm.account_size overrides risk.account_balance
        # when prop_firm.enabled is true.
        if self.prop_enabled:
            self.balance = float(self.prop_cfg.get('account_size', 100000.0))
        else:
            self.balance = float(self.risk_cfg.get('account_balance', 100000.0))
        self.initial_balance = self.balance

        # Daily / max loss in DOLLARS (prop_firm config) or PERCENT (legacy)
        if self.prop_enabled:
            self.max_daily_loss = float(self.prop_cfg.get('max_daily_loss_usd', 5000.0))
            self.max_total_loss = float(self.prop_cfg.get('max_total_loss_usd', 10000.0))
            # The "daily" boundary on Fundingpips resets at 17:00 New York
            # time (22:00 UTC, give or take DST). Configurable.
            self.daily_reset_hour_utc = int(self.prop_cfg.get('daily_reset_hour_utc', 22))
        else:
            self.max_daily_loss = self.balance * self.risk_cfg.get('max_daily_loss_pct', 5.0) / 100
            self.max_total_loss = self.balance * self.risk_cfg.get('max_total_loss_pct', 10.0) / 100
            self.daily_reset_hour_utc = 22

        self.max_positions = self.risk_cfg.get('max_open_positions', 3)

        # Correlation-aware exposure cap (Rule #12: "ALWAYS use uncorrelated
        # positions -- max 2-3"). RulesEngine.is_correlated_to_open() carried
        # the right groups (HAI 1:19:29 + Funded 0:16:46) since 2026-05-24 but
        # was never called from anywhere -- confirmed dead code during the
        # 2026-07-27 portfolio risk audit (22 concurrently open positions, 8
        # of them long-EUR/short-USD simultaneously). Wired in below.
        self.correlation_check_enabled = bool(self.risk_cfg.get('correlation_check_enabled', True))

        # Pending limit orders used to sit forever (TradeStatus.CANCELLED was
        # defined but never assigned anywhere). A resting order whose zone
        # context has gone stale should expire rather than fill blind days
        # or weeks later. Per-income-strategy defaults below; override via
        # risk.pending_order_max_age_days in BP_config.yaml (flat number or
        # {weekly: N, daily: N, monthly: N, intraday: N, default: N} dict).
        _pend_cfg = self.risk_cfg.get('pending_order_max_age_days', 7)
        if isinstance(_pend_cfg, dict):
            self.pending_expiry_days = _pend_cfg
        else:
            self.pending_expiry_days = {'default': float(_pend_cfg)}
        self._default_pending_expiry_days = {
            'weekly': 14.0, 'monthly': 30.0, 'daily': 5.0, 'intraday': 2.0,
        }

        # Bernd's live-trading practice (Funded sessions): move stop to
        # breakeven once price has covered HALF the distance to T1, not at
        # T1 itself. This locks in protection earlier without giving up the
        # T1+ R-multiple. Set False to revert to T1 breakeven.
        self.breakeven_at_half = bool(self.stop_cfg.get('breakeven_at_half_target', True))

        self.positions: Dict[str, Position] = {}
        self.trade_history: List[Position] = []
        self.pending_signals: List[Dict] = []

        # Daily tracking. `today_starting_equity` is the equity at the start
        # of the current daily window (matches Fundingpips' "Today's Starting
        # Equity" panel). The Max-Daily-Loss threshold is computed as
        # `today_starting_equity - max_daily_loss`.
        self.today_starting_equity = self.balance
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.current_date = None
        self.account_blown = False  # latched true when max_total_loss is breached

        self.closed_pnl_total = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.scratch_trades = 0  # breakeven closes — excluded from win-rate
        self.peak_balance = self.balance
        self.max_drawdown_pct = 0.0

        self.zone_memory: Dict[str, bool] = {}  # Track broken zones

        # Challenge clock: when this account started (first scan after a
        # reset). Lets the Discord message show "Day N" + progress toward
        # profit_target_pct, so passing/failing has a visible timeline instead
        # of only a point-in-time balance. Set on first save if still None
        # (see save_paper_trader_state in run_scanner.py).
        self.challenge_started_at: Optional[str] = None
        self.profit_target_pct = float(self.prop_cfg.get('profit_target_pct', 0.0)) if self.prop_enabled else 0.0

    def maybe_roll_day(self) -> None:
        """If the daily-reset boundary has passed since the last call, snapshot
        today's starting equity and zero out daily PnL. Matches the broker's
        daily reset timer."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        # Bucket the current time into a "trading day" string keyed by the
        # reset hour. Days roll over at `daily_reset_hour_utc`.
        if now.hour < self.daily_reset_hour_utc:
            day_key = (now.date()).isoformat()
        else:
            from datetime import timedelta
            day_key = (now.date() + timedelta(days=1)).isoformat()
        if self.current_date != day_key:
            logger.info(f"Daily reset: previous_day={self.current_date} new_day={day_key} "
                        f"prior_daily_pnl={self.daily_pnl:.2f}")
            self.current_date = day_key
            self.today_starting_equity = self.balance
            self.daily_pnl = 0.0
            self.daily_trades = 0

    def is_breached(self) -> Tuple[bool, str]:
        """Return (breached, reason). Once breached, no further trades open."""
        # Total loss since initial balance
        total_loss = self.initial_balance - self.balance
        if total_loss >= self.max_total_loss:
            return True, f"MAX_LOSS_BREACH: total drawdown ${total_loss:,.2f} >= limit ${self.max_total_loss:,.2f}"
        # Today's drawdown vs today's starting equity
        today_loss = self.today_starting_equity - self.balance
        if today_loss >= self.max_daily_loss:
            return True, f"DAILY_LOSS_BREACH: today's drawdown ${today_loss:,.2f} >= limit ${self.max_daily_loss:,.2f}"
        return False, "OK"

    def _pending_expiry_days_for(self, income_strategy: Optional[str]) -> float:
        """Max age (calendar days) a resting PENDING order may sit before it
        expires. Strategy-specific default, overridable via
        risk.pending_order_max_age_days in BP_config.yaml.
        """
        key = income_strategy or 'default'
        if key in self.pending_expiry_days:
            return float(self.pending_expiry_days[key])
        if 'default' in self.pending_expiry_days and len(self.pending_expiry_days) == 1:
            # Flat config value applies to every strategy
            return float(self.pending_expiry_days['default'])
        return float(self._default_pending_expiry_days.get(key, 7.0))

    def _check_activation_gates(
        self, symbol: str, risk_amount: float, exclude_id: Optional[str] = None,
        peer_statuses: Tuple['TradeStatus', ...] = (TradeStatus.ACTIVE,),
    ) -> Tuple[bool, str]:
        """Shared gate: max open positions, aggregate daily/total loss budget,
        and correlation exposure. Used both at initial submit (immediate fill)
        and at pending->active promotion (check_pending_fills), so a resting
        order is re-validated against CURRENT portfolio state at the moment it
        actually becomes real risk -- not just the state at the moment it was
        first placed, which could be days or weeks stale.

        `peer_statuses` controls which open positions count as "peers" for the
        correlation check: at submit time we also want to see other PENDING
        orders (to stop correlated pending orders piling up in the first
        place); at fill-time re-validation only ACTIVE peers represent real
        simultaneous risk.
        """
        active_positions = [
            p for p in self.positions.values()
            if p.status == TradeStatus.ACTIVE and p.id != exclude_id
        ]
        if len(active_positions) >= self.max_positions:
            return False, f"max_positions ({self.max_positions}) reached"

        open_risk = sum(
            p.risk_amount for p in active_positions
            if not getattr(p, 'breakeven_triggered', False)
        )
        today_loss = self.today_starting_equity - self.balance
        if today_loss + open_risk + risk_amount >= self.max_daily_loss:
            return False, (
                f"daily loss budget would be exceeded (realized ${today_loss:.2f} + "
                f"open ${open_risk:.2f} + new ${risk_amount:.2f} >= limit ${self.max_daily_loss:.2f})"
            )
        total_loss = self.initial_balance - self.balance
        if total_loss + open_risk + risk_amount >= self.max_total_loss:
            return False, (
                f"total loss budget would be exceeded (realized ${total_loss:.2f} + "
                f"open ${open_risk:.2f} + new ${risk_amount:.2f} >= limit ${self.max_total_loss:.2f})"
            )

        if self.correlation_check_enabled:
            peers = [
                p for p in self.positions.values()
                if p.status in peer_statuses and p.id != exclude_id
            ]
            offenders = RulesEngine.is_correlated_to_open(
                symbol, [p.symbol for p in peers], self.config,
            )
            if offenders:
                return False, f"correlated with open position(s): {offenders}"

        return True, "OK"

    def submit_signal(self, signal: Dict) -> Optional[str]:
        """
        Submit a trade signal for paper execution.
        Returns position ID if executed, None if rejected.
        """
        # Roll the daily window first so today_starting_equity is current
        self.maybe_roll_day()

        # Account already blown -> no more trades (latched flag survives the day-roll)
        if self.account_blown:
            logger.info(f"Account already blown for the challenge -- signal rejected")
            return None

        # Re-check breach state on every submit
        breached, reason = self.is_breached()
        if breached:
            self.account_blown = True
            logger.warning(f"Account breach detected: {reason}")
            return None

        # ── Fill mode: PENDING limit vs immediate fill ──────────────────
        # A signal whose price has NOT yet reached the zone is placed as a
        # RESTING PENDING limit order (E1 at the zone proximal). It does NOT
        # open a live position now and carries NO risk until price actually
        # trades to the entry -- see check_pending_fills(). Only a signal that
        # is already AT the zone fills immediately as an ACTIVE position.
        # This fixes the bug where a buy-limit was "filled" instantly at the
        # zone price (e.g. EURCHF long booked at 0.933 while price was 0.927
        # and had never traded up to the entry).
        is_pending = bool(signal.get('pending_order')) and not bool(signal.get('price_at_zone'))
        new_risk = signal.get('risk_amount', 0.0)

        # Live-position gates (max open slots + loss budget) apply ONLY to an
        # order that fills NOW. A resting limit consumes no slot and no loss
        # budget until it fills -- check_pending_fills() re-validates these
        # SAME gates again at the moment it actually fills, since a resting
        # order can sit for days/weeks and portfolio state moves on.
        if not is_pending:
            ok, reason = self._check_activation_gates(signal['symbol'], new_risk)
            if not ok:
                logger.info(f"[{signal['symbol']}] Immediate-fill signal rejected: {reason}")
                return None
        elif self.correlation_check_enabled:
            # Pending orders carry no $ risk yet, but an uncapped pile of
            # correlated pending orders (e.g. 8 long-EUR pairs) all convert to
            # simultaneous real risk the moment price reaches them. Block a
            # NEW pending order from stacking onto an axis that already has
            # an open (active OR pending) position, so the correlation limit
            # is enforced at the earliest possible point, not just at fill.
            peers = [p for p in self.positions.values()
                     if p.status in (TradeStatus.ACTIVE, TradeStatus.PENDING)]
            offenders = RulesEngine.is_correlated_to_open(
                signal['symbol'], [p.symbol for p in peers], self.config,
            )
            if offenders:
                logger.info(
                    f"[{signal['symbol']}] Pending signal rejected: correlated "
                    f"with open position(s): {offenders}"
                )
                return None

        # Check if zone already consumed (applies to pending AND active)
        zone_id = signal.get('zone_id', '')
        if zone_id in self.zone_memory and self.zone_memory[zone_id]:
            logger.info(f"Zone {zone_id} already consumed, skipping")
            return None

        # Don't stack a DUPLICATE on a zone that already has an OPEN *or* PENDING
        # order. zone_memory only records CONSUMED (closed) zones, so without this
        # a zone that signals again while its first order is still live opens a
        # second identical trade (seen live: two EURCHF longs at the same entry).
        _sig_dir = TradeDirection(signal['direction'])
        _sig_entry = float(signal['entry_price'])
        for _p in self.positions.values():
            if _p.status not in (TradeStatus.ACTIVE, TradeStatus.PENDING):
                continue
            if zone_id and _p.zone_id == zone_id:
                logger.info(f"Zone {zone_id} already has a live/pending order; skipping duplicate")
                return None
            # Fallback: zone_id can drift a hair if the zone's proximal/distal
            # shift by a bar between scans -- same symbol + direction + ~same
            # entry (within 1bp) is the same trade.
            if (_p.symbol == signal['symbol'] and _p.direction == _sig_dir
                    and abs(_p.entry_price - _sig_entry) <= abs(_sig_entry) * 1e-4):
                logger.info(f"Duplicate live/pending ({signal['symbol']} {signal['direction']} "
                            f"@ ~{_sig_entry}); skipping")
                return None

        pos_id = str(uuid.uuid4())[:12]
        position = Position(
            id=pos_id,
            symbol=signal['symbol'],
            direction=_sig_dir,
            entry_price=signal['entry_price'],
            stop_price=signal['stop_price'],
            current_stop=signal['stop_price'],
            targets=signal['targets'],
            position_size=signal.get('position_size', 1.0),
            risk_amount=signal.get('risk_amount', 0.0),
            entry_time=datetime.now(),
            status=(TradeStatus.PENDING if is_pending else TradeStatus.ACTIVE),
            zone_id=zone_id,
            income_strategy=signal.get('income_strategy'),
        )

        self.positions[pos_id] = position
        if is_pending:
            logger.info(f"[{signal['symbol']}] PENDING {signal['direction']} limit {pos_id} "
                        f"@ {signal['entry_price']:.5f} (waiting for price to arrive)")
        else:
            logger.info(f"[{signal['symbol']}] OPENED {signal['direction']} position {pos_id} "
                        f"at {signal['entry_price']:.5f}")
        return pos_id

    def check_pending_fills(self, current_prices: Dict[str, Dict[str, float]]) -> List[str]:
        """Fill resting PENDING limit orders that price has now reached.

        A long limit fills when the latest bar's LOW trades down to/through the
        entry; a short limit fills when the HIGH trades up to/through it. The
        fill price is the entry (limit) price -- a limit fills at its level or
        better. Returns the list of position ids filled this call (now ACTIVE).

        Stop/target evaluation for a freshly-filled order is deferred to the
        NEXT scan (the caller sets it aside from update_positions) so a limit
        isn't opened and closed on the same bar.
        """
        filled: List[str] = []
        # Snapshot to a list: cancellations below mutate self.positions, which
        # would raise "dictionary changed size during iteration" against a
        # live .values() view.
        for pos in list(self.positions.values()):
            if pos.status != TradeStatus.PENDING:
                continue

            # Expire stale resting orders (2026-07-27 audit fix: TradeStatus.
            # CANCELLED was defined but never assigned anywhere -- a pending
            # order sat forever, filling blind on whatever price eventually
            # wandered back regardless of how stale its underlying zone/bias
            # had become). Age is measured from entry_time, which submit_signal
            # sets to the moment the order was first placed.
            age_days = (datetime.now() - pos.entry_time).total_seconds() / 86400.0
            max_age = self._pending_expiry_days_for(pos.income_strategy)
            if age_days >= max_age:
                pos.status = TradeStatus.CANCELLED
                pos.close_time = datetime.now()
                self.trade_history.append(pos)
                del self.positions[pos.id]
                logger.info(
                    f"[{pos.symbol}] PENDING limit EXPIRED after {age_days:.1f}d "
                    f"(max {max_age:.0f}d for strategy={pos.income_strategy}) -> CANCELLED"
                )
                continue

            prices = current_prices.get(pos.symbol, {})
            if not prices:
                continue
            close = prices.get('close', 0)
            low = prices.get('low', close)
            high = prices.get('high', close)
            entry = pos.entry_price
            reached = (
                (pos.direction == TradeDirection.LONG and low is not None and low <= entry)
                or (pos.direction == TradeDirection.SHORT and high is not None and high >= entry)
            )
            if not reached:
                continue

            # Re-validate the SAME gates submit_signal checks for an immediate
            # fill (max positions, aggregate loss budget, correlation) -- a
            # resting order can be days/weeks old, and the portfolio it would
            # now join may no longer have room for it. Correlation is checked
            # against ACTIVE peers only here: other still-pending orders carry
            # no real risk yet, and were already screened against each other
            # at submit time.
            ok, reason = self._check_activation_gates(
                pos.symbol, pos.risk_amount, exclude_id=pos.id,
            )
            if not ok:
                pos.status = TradeStatus.CANCELLED
                pos.close_time = datetime.now()
                self.trade_history.append(pos)
                del self.positions[pos.id]
                logger.info(
                    f"[{pos.symbol}] PENDING limit reached entry but CANCELLED "
                    f"instead of filling: {reason}"
                )
                continue

            pos.status = TradeStatus.ACTIVE
            pos.entry_time = datetime.now()
            filled.append(pos.id)
            logger.info(f"[{pos.symbol}] PENDING limit FILLED at {entry:.5f} -> ACTIVE")
        return filled

    def get_pending_orders(self) -> List[Dict]:
        """Return resting (unfilled) PENDING limit orders in dashboard shape."""
        out = []
        for p in self.positions.values():
            if p.status != TradeStatus.PENDING:
                continue
            out.append(asdict(p))
        return out

    def update_positions(self, current_prices: Dict[str, Dict[str, float]]) -> List[Dict]:
        """
        Update all open positions with current prices.
        Checks stop-loss hits, target hits, and applies trailing/breakeven rules.

        Args:
            current_prices: Dict[symbol] -> {'bid': price, 'ask': price, 'high': price, 'low': price}

        Returns:
            List of closed position events
        """
        closed_events = []

        for pos_id, pos in list(self.positions.items()):
            if pos.status != TradeStatus.ACTIVE:
                continue

            prices = current_prices.get(pos.symbol, {})
            if not prices:
                continue

            bid = prices.get('bid', prices.get('close', 0))
            ask = prices.get('ask', prices.get('close', 0))
            current_high = prices.get('high', max(bid, ask))
            current_low = prices.get('low', min(bid, ask))
            current_price = bid if pos.direction == TradeDirection.LONG else ask

            if current_price == 0:
                continue

            # Half-target breakeven: per live trading practice, move stop to
            # entry once price has travelled half the distance to T1. Saves
            # us from giving back open profit when a setup fades. Only
            # applies before T1 has been hit (then the T1 BE block takes over).
            if self.breakeven_at_half and not pos.breakeven_triggered and pos.targets:
                t1 = pos.targets[0]
                halfway = (pos.entry_price + t1) / 2.0
                if pos.direction == TradeDirection.LONG and current_high >= halfway:
                    pos.current_stop = pos.entry_price
                    pos.breakeven_triggered = True
                    logger.info(f"[{pos.symbol}] Half-target BE triggered at {halfway:.4f}")
                elif pos.direction == TradeDirection.SHORT and current_low <= halfway:
                    pos.current_stop = pos.entry_price
                    pos.breakeven_triggered = True
                    logger.info(f"[{pos.symbol}] Half-target BE triggered at {halfway:.4f}")

            # Advance trailing stop if partial taken
            if pos.partial_taken and pos.trail_stop_level is not None:
                risk = abs(pos.entry_price - pos.stop_price)
                if pos.direction == TradeDirection.LONG:
                    # Trail in 1R increments (zone-distal trailing is applied
                    # separately via apply_zone_trailing when zones are known)
                    new_trail = current_price - risk
                    if new_trail > pos.trail_stop_level:
                        pos.trail_stop_level = new_trail
                        pos.current_stop = new_trail
                else:
                    new_trail = current_price + risk
                    if new_trail < pos.trail_stop_level:
                        pos.trail_stop_level = new_trail
                        pos.current_stop = new_trail

            # Check stop-loss hit
            if pos.direction == TradeDirection.LONG:
                if current_low <= pos.current_stop:
                    close_price = pos.current_stop
                    realized_pnl = (close_price - pos.entry_price) * pos.position_size
                    # Accumulate (+=): if a T2 partial was already booked into
                    # realized_pnl, a trailing-stop close of the runner must ADD
                    # to it, not overwrite it. With no partial, realized_pnl is
                    # still 0 so += behaves as =.
                    pos.realized_pnl += realized_pnl
                    pos.close_price = close_price
                    pos.close_time = datetime.now()
                    pos.status = TradeStatus.CLOSED
                    pos.trade_r_multiple = (close_price - pos.entry_price) / abs(pos.entry_price - pos.stop_price) if abs(pos.entry_price - pos.stop_price) > 0 else 0

                    closed_events.append(self._close_position(pos))
                    if pos.zone_id:
                        self.zone_memory[pos.zone_id] = True
                    continue
            else:  # SHORT
                if current_high >= pos.current_stop:
                    close_price = pos.current_stop
                    realized_pnl = (pos.entry_price - close_price) * pos.position_size
                    # Accumulate (+=): retain any T2 partial already booked
                    # into realized_pnl (see LONG stop path above).
                    pos.realized_pnl += realized_pnl
                    pos.close_price = close_price
                    pos.close_time = datetime.now()
                    pos.status = TradeStatus.CLOSED
                    pos.trade_r_multiple = (pos.entry_price - close_price) / abs(pos.entry_price - pos.stop_price) if abs(pos.entry_price - pos.stop_price) > 0 else 0

                    closed_events.append(self._close_position(pos))
                    if pos.zone_id:
                        self.zone_memory[pos.zone_id] = True
                    continue

            # Check take-profit targets
            for i, target in enumerate(pos.targets):
                if pos.direction == TradeDirection.LONG:
                    if current_high >= target:
                        if i == 0 and not pos.breakeven_triggered:
                            pos.current_stop = pos.entry_price
                            pos.breakeven_triggered = True
                            logger.info(f"[{pos.symbol}] Breakeven at {pos.entry_price:.2f}")

                        if i == 1 and not pos.partial_taken:
                            partial_pnl = (target - pos.entry_price) * pos.position_size * 0.5
                            pos.realized_pnl += partial_pnl
                            pos.partial_taken = True
                            pos.partial_qty = pos.position_size * 0.5
                            pos.partial_price = target
                            pos.position_size *= 0.5
                            # NOTE: do NOT add partial_pnl to closed_pnl_total here.
                            # It is already accumulated into pos.realized_pnl and
                            # will be booked once in _close_position; adding it here
                            # too double-counted the partial into balance/target.
                            logger.info(f"[{pos.symbol}] Partial 50% at T2={target:.2f}, PnL={partial_pnl:.2f}")
                            # Begin trailing stop after T2
                            risk = abs(pos.entry_price - pos.stop_price)
                            pos.trail_stop_level = pos.entry_price + risk  # Trail to T1 level initially
                            pos.current_stop = pos.trail_stop_level
                            logger.info(f"[{pos.symbol}] Trailing stop set to {pos.trail_stop_level:.2f}")

                        if i == 2:
                            close_price = target
                            realized_pnl = (target - pos.entry_price) * pos.position_size
                            pos.realized_pnl += realized_pnl
                            pos.close_price = close_price
                            pos.close_time = datetime.now()
                            pos.status = TradeStatus.CLOSED
                            pos.trade_r_multiple = 3.0
                            closed_events.append(self._close_position(pos))
                            if pos.zone_id:
                                self.zone_memory[pos.zone_id] = True
                            break
                else:  # SHORT
                    if current_low <= target:
                        if i == 0 and not pos.breakeven_triggered:
                            pos.current_stop = pos.entry_price
                            pos.breakeven_triggered = True

                        if i == 1 and not pos.partial_taken:
                            partial_pnl = (pos.entry_price - target) * pos.position_size * 0.5
                            pos.realized_pnl += partial_pnl
                            pos.partial_taken = True
                            pos.partial_qty = pos.position_size * 0.5
                            pos.partial_price = target
                            pos.position_size *= 0.5
                            # See LONG partial above: partial_pnl is booked once
                            # at close via pos.realized_pnl, not here.
                            # Begin trailing stop after T2
                            risk = abs(pos.entry_price - pos.stop_price)
                            pos.trail_stop_level = pos.entry_price - risk  # Trail to T1 level initially
                            pos.current_stop = pos.trail_stop_level

                        if i == 2:
                            realized_pnl = (pos.entry_price - target) * pos.position_size
                            pos.realized_pnl += realized_pnl
                            pos.close_price = target
                            pos.close_time = datetime.now()
                            pos.status = TradeStatus.CLOSED
                            pos.trade_r_multiple = 3.0
                            closed_events.append(self._close_position(pos))
                            if pos.zone_id:
                                self.zone_memory[pos.zone_id] = True
                            break

        return closed_events

    def _close_position(self, pos: Position) -> Dict:
        """Record closed position and update stats."""
        self.trade_history.append(pos)
        del self.positions[pos.id]

        self.total_trades += 1
        if pos.realized_pnl > 0:
            self.winning_trades += 1
        elif pos.realized_pnl < 0:
            self.losing_trades += 1
        else:
            # Breakeven / scratch (e.g. stopped at BE after half-target move).
            # Excluded from the win-rate denominator so it isn't miscounted as
            # a loss. The strategy moves to BE early, so scratches are common.
            self.scratch_trades += 1

        self.closed_pnl_total += pos.realized_pnl
        self.balance = self.initial_balance + self.closed_pnl_total
        self.daily_pnl += pos.realized_pnl
        self.daily_trades += 1

        if self.balance > self.peak_balance:
            self.peak_balance = self.balance
        if self.peak_balance > 0:
            dd = (self.peak_balance - self.balance) / self.peak_balance * 100
            if dd > self.max_drawdown_pct:
                self.max_drawdown_pct = dd

        return {
            'event': 'position_closed',
            'position_id': pos.id,
            'symbol': pos.symbol,
            'direction': pos.direction.value,
            'entry_price': pos.entry_price,
            'close_price': pos.close_price,
            'realized_pnl': pos.realized_pnl,
            'r_multiple': pos.trade_r_multiple,
            'close_time': pos.close_time.isoformat() if pos.close_time else ''
        }

    def get_account_summary(self) -> Dict:
        """Return current account summary.

        win_rate is returned as a 0-1 fraction (the dashboard multiplies it by
        100 for display). avg_r covers only closed trades with a valid R.
        """
        # Roll the day before computing summary so dashboards always read fresh
        self.maybe_roll_day()

        # Win-rate over DECIDED trades only (wins + losses); breakeven scratches
        # are excluded from the denominator so an early-BE strategy isn't
        # penalised as if every scratch were a loss.
        _decided = self.winning_trades + self.losing_trades
        win_rate = (self.winning_trades / _decided) if _decided > 0 else 0.0
        closed = [p for p in self.trade_history if p.status == TradeStatus.CLOSED]
        avg_r = sum(p.trade_r_multiple for p in closed) / max(1, len(closed))

        # Fundingpips-style "Trading Objectives" block ──────────────────────
        today_loss = max(0.0, self.today_starting_equity - self.balance)
        total_loss = max(0.0, self.initial_balance - self.balance)
        breached, breach_reason = self.is_breached()

        # Challenge clock + progress toward profit_target_pct. days_elapsed is
        # None until challenge_started_at is set (first save after a reset).
        days_elapsed = None
        if self.challenge_started_at:
            try:
                started = datetime.fromisoformat(self.challenge_started_at)
                now = datetime.now(started.tzinfo) if started.tzinfo else datetime.now()
                days_elapsed = (now - started).days
            except ValueError:
                days_elapsed = None

        target_gain = self.initial_balance * self.profit_target_pct / 100.0
        target_equity = self.initial_balance + target_gain
        current_gain = self.balance - self.initial_balance
        progress_to_target_pct = (
            round(current_gain / target_gain * 100.0, 1) if target_gain > 0 else None
        )

        prop_firm_status = {
            'enabled':                  self.prop_enabled,
            'account_size':             round(self.initial_balance, 2),
            'todays_starting_equity':   round(self.today_starting_equity, 2),
            'current_equity':           round(self.balance, 2),
            # Maximum Daily Loss
            'max_daily_loss_limit':     round(self.max_daily_loss, 2),
            'todays_loss':              round(today_loss, 2),
            'daily_loss_remaining':     round(max(0.0, self.max_daily_loss - today_loss), 2),
            'daily_balance_threshold':  round(self.today_starting_equity - self.max_daily_loss, 2),
            # Maximum Loss
            'max_total_loss_limit':     round(self.max_total_loss, 2),
            'total_loss':               round(total_loss, 2),
            'total_loss_remaining':     round(max(0.0, self.max_total_loss - total_loss), 2),
            'total_balance_threshold':  round(self.initial_balance - self.max_total_loss, 2),
            # Status flags
            'breached':                 breached or self.account_blown,
            'breach_reason':            breach_reason if breached else "OK",
            # Challenge clock / pass-target progress
            'profit_target_pct':        self.profit_target_pct,
            'target_equity':            round(target_equity, 2),
            'progress_to_target_pct':   progress_to_target_pct,
            'challenge_started_at':     self.challenge_started_at,
            'days_elapsed':             days_elapsed,
        }

        return {
            'balance': round(self.balance, 2),
            'equity': round(self.balance, 2),
            'open_pnl': 0.0,
            'closed_pnl': round(self.closed_pnl_total, 2),
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': round(win_rate, 4),
            'avg_r': round(avg_r, 2),
            'avg_r_per_trade': round(avg_r, 2),
            'max_drawdown_pct': round(self.max_drawdown_pct, 2),
            'daily_pnl': round(self.daily_pnl, 2),
            'open_positions': len(self.positions),
            'total_pnl': round(self.closed_pnl_total, 2),
            'prop_firm': prop_firm_status,
        }

    def get_open_positions(self) -> List[Dict]:
        """Return list of current open positions in dashboard-friendly shape."""
        out = []
        for p in self.positions.values():
            if p.status != TradeStatus.ACTIVE:
                continue
            d = asdict(p)
            # Dashboard reads 'unrealized_pnl' but Position only tracks realized;
            # leave None so the UI shows '--' until prices drive an update.
            d['unrealized_pnl'] = d.get('realized_pnl') or 0.0
            out.append(d)
        return out

    def get_trade_history(self, limit: int = 50) -> List[Dict]:
        """Return recent trade history, mapping internal field names to the
        keys the dashboard expects."""
        out = []
        for t in self.trade_history[-limit:]:
            d = asdict(t)
            d['r_multiple'] = d.pop('trade_r_multiple', 0.0)
            d['pnl'] = d.get('realized_pnl', 0.0)
            out.append(d)
        return out

    def reset_daily_stats(self):
        """Reset daily tracking at start of new day.

        Prefer maybe_roll_day() (the UTC-anchored single source of truth). This
        helper is kept for any direct caller and now ALSO re-anchors
        today_starting_equity so the daily-loss cap is measured from the correct
        equity even if this path is used.
        """
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.today_starting_equity = self.balance
        self.current_date = datetime.now().strftime('%Y-%m-%d')

    def apply_zone_trailing(self, symbol_zones: Dict[str, List[Dict]]) -> None:
        """Trail the stop on already-partialled positions to the most recent
        zone distal beyond the current stop (longs: highest demand distal below
        price; shorts: lowest supply distal above price). Per Blueprint
        management rules, this kicks in after T2 has been taken.

        Args:
            symbol_zones: mapping of symbol -> list of detected zones, each
                with keys zone_type/proximal/distal.
        """
        for pos in self.positions.values():
            if pos.status != TradeStatus.ACTIVE or not pos.partial_taken:
                continue
            zones = symbol_zones.get(pos.symbol, [])
            if not zones:
                continue

            if pos.direction == TradeDirection.LONG:
                candidates = [
                    z['distal'] for z in zones
                    if z['zone_type'] == 'demand'
                    and z['distal'] > pos.current_stop
                    and z['proximal'] < pos.entry_price + 5 * abs(pos.entry_price - pos.stop_price)
                ]
                if candidates:
                    new_stop = max(candidates)
                    if new_stop > pos.current_stop:
                        pos.current_stop = new_stop
                        pos.trail_stop_level = new_stop
                        logger.info(f"[{pos.symbol}] Zone-trail stop -> {new_stop:.4f}")
            else:
                candidates = [
                    z['distal'] for z in zones
                    if z['zone_type'] == 'supply'
                    and z['distal'] < pos.current_stop
                    and z['proximal'] > pos.entry_price - 5 * abs(pos.entry_price - pos.stop_price)
                ]
                if candidates:
                    new_stop = min(candidates)
                    if new_stop < pos.current_stop:
                        pos.current_stop = new_stop
                        pos.trail_stop_level = new_stop
                        logger.info(f"[{pos.symbol}] Zone-trail stop -> {new_stop:.4f}")
