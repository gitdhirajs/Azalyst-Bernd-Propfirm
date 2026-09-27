"""
Paper Trading Simulator - Simulated brokerage that executes trades,
manages stops, targets, trailing stops, and tracks P&L.
Implements Section F and G from the Strategy Rulebook.
"""

import os
import math
import uuid
import json
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field, asdict
from enum import Enum

from BP_rules_engine import RulesEngine

logger = logging.getLogger(__name__)

# The REAL datetime class, captured at import. goldtest/replay_trades.py swaps
# the module-level `datetime` name for a fake clock during a replay, and an
# isinstance() check against the fake class would reject every real datetime.
# Type checks use _DT; clock reads go through the (patchable) `datetime` name.
_DT = datetime


def bar_replay_enabled() -> bool:
    """BP_BAR_REPLAY=0 restores the old single-bar pricing path.

    2026-09-27 audit (defect 6): the old path priced every order against ONE
    bar per run -- the last 1d bar -- so a fill could come from a low printed
    before the order existed, the half-T1 breakeven was armed by the bar's high
    and then "hit" by the same bar's low (winning trades closed at $0), and a
    once-a-day schedule only ever saw ~6h of each FX day (the USDJPY stop hit on
    24 Sep never registered; its fill registered 4 days late). The replacement
    replays COMPLETED 1h bars since the last evaluation, in time order.
    """
    return os.environ.get('BP_BAR_REPLAY') != '0'


def to_utc(value) -> Optional[datetime]:
    """Normalise a datetime / pandas Timestamp / ISO string to an AWARE UTC datetime.

    Naive values are taken to be UTC. Before 2026-09-27 the trader stamped
    `datetime.now()` (machine-local, naive): UTC on the GitHub runner, IST on the
    operator's PC. Mixing the two is what produced "Day -1 since reset" on
    Discord (defect 10). Everything the trader writes is now aware UTC; a naive
    value can only be a legacy record, and the live bot has always run on UTC.
    """
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            value = _DT.fromisoformat(s.replace('Z', '+00:00'))
        except ValueError:
            return None
    if hasattr(value, 'to_pydatetime'):          # pandas Timestamp
        value = value.to_pydatetime()
    if not isinstance(value, _DT):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def utcnow() -> datetime:
    """Current time as aware UTC. Reads the module-level `datetime` so the
    goldtest replay clock (which returns a naive bar time) still drives it."""
    return to_utc(datetime.now(timezone.utc))


def make_setup_key(symbol: str, direction: str, entry: float, stop: float) -> str:
    """Identity of a trade SETUP, independent of the zone id.

    Defect 9: zone_id hashes the leg-out bar timestamp; while zones were built on
    the still-forming daily candle that timestamp moved every day, so the id
    changed daily and the exact-id "consumed" check never matched -- EURNZD was
    traded (and lost) twice on the same levels. Symbol + direction + entry +
    stop at 5 significant figures is stable across scans. The engine emits the
    same string as signal["setup_key"].
    """
    d = direction.value if hasattr(direction, 'value') else str(direction)
    return f"{symbol}|{d}|{float(entry):.5g}|{float(stop):.5g}"


def _finite(*vals) -> bool:
    try:
        return all(v is not None and math.isfinite(float(v)) for v in vals)
    except (TypeError, ValueError):
        return False


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
    # E-01 (2026-08-26): why the position closed. Previously send_discord.py
    # read a "close_reason" that existed nowhere, so it always rendered blank.
    # Distinguishes an original-stop loss from a breakeven scratch from a
    # trailing exit -- the measurement E-03 needs.
    close_reason: str = ""
    notes: str = ""
    income_strategy: Optional[str] = None
    # Signal's trade_context (standard / counter_trend / anticipatory). Read by the
    # BP_TYPE_LADDERS exit branch; before 2026-09-14 the paper trader dropped it.
    trade_context: str = "standard"
    # --- 2026-09-27 bar-replay fields (all aware UTC) ----------------------
    # placed_at: when the order came into existence (signal_time). No bar that
    #   STARTED before this may fill it -- the old path filled orders from lows
    #   printed before the order existed.
    # filled_at: start of the 1h bar on which the order filled.
    # last_priced_ts: the position has been evaluated against every completed
    #   bar ending at or before this instant (= END of the last replayed bar).
    #   The next run fetches bars from here, and replay skips anything earlier,
    #   so a bar is never applied twice.
    placed_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    last_priced_ts: Optional[datetime] = None
    # "limit" (E1/E2 zone entry: a long fills when price trades DOWN to entry)
    # or "stop" (E3b pattern entry: a long fills when price trades UP to entry).
    # Defect 4: stop entries were treated as limits, i.e. "filled" when price
    # was BELOW a buy-stop -- exactly when the setup had failed.
    order_type: str = "limit"
    setup_key: str = ""
    # Actual fill price. A limit that gaps through fills at the (better) open,
    # a stop that gaps through at the (worse) open, so it can differ from
    # entry_price, which stays the ORDER level the R-multiples are measured in.
    fill_price: Optional[float] = None


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
        self.type_ladders = os.environ.get('BP_TYPE_LADDERS') == '1'

        # Set-and-forget management (user decision 2026-09-27): the stop never
        # moves and 100% closes at T<take_profit_target>. The half-T1 breakeven
        # was closing trades at $0 when price came back to entry before TP.
        # stop_loss.management: ladder restores breakeven / T2 partial / trail / T3.
        self.fixed_bracket = str(self.stop_cfg.get('management', 'ladder')).lower() == 'fixed'
        self.fixed_tp_index = max(0, int(self.stop_cfg.get('take_profit_target', 2)) - 1)

        # Read once per trader so a run cannot mix the two pricing models.
        self.bar_replay = bar_replay_enabled()
        # Defect 9: a setup that already closed or was cancelled is not placed
        # again for this many days (EURNZD lost twice on the same levels).
        # BP_SETUP_KEY_DEDUP=0 disables the check.
        self.setup_dedup_days = 30.0
        self.setup_dedup_enabled = os.environ.get('BP_SETUP_KEY_DEDUP') != '0'

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

    def maybe_roll_day(self, now: Optional[datetime] = None) -> None:
        """If the daily-reset boundary has passed since the last call, snapshot
        today's starting equity and zero out daily PnL. Matches the broker's
        daily reset timer.

        `now` is the BAR time during a replay (defect 6: daily-loss accounting
        must follow when the fill/stop actually happened, not when the scan
        ran). It only ever rolls FORWARD: replay interleaves symbols in time
        order, but a stale older timestamp must never re-open a finished day
        and reset today's starting equity.
        """
        now = to_utc(now) if now is not None else utcnow()
        # Bucket the current time into a "trading day" string keyed by the
        # reset hour. Days roll over at `daily_reset_hour_utc`.
        if now.hour < self.daily_reset_hour_utc:
            day_key = (now.date()).isoformat()
        else:
            day_key = (now.date() + timedelta(days=1)).isoformat()
        cur = self.current_date
        _forward = (cur is None) or (day_key > str(cur)) or (len(str(cur)) != 10)
        if cur != day_key and _forward:
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
        #
        # 2026-09-27 (defect 3): under bar replay NOTHING fills at signal time.
        # "price_at_zone" was computed as close<=entry (long), which is also
        # true when price is already far PAST the entry -- 6 of 8 losing setups
        # were booked as an immediate fill at an entry the market was no longer
        # at (NZDUSD/NZDCAD already beyond their stops). Every order now rests
        # and can only fill inside replay_bars() on a bar that trades to it.
        # BP_BAR_REPLAY=0 restores the old immediate-fill behaviour.
        if self.bar_replay:
            is_pending = True
        else:
            is_pending = bool(signal.get('pending_order')) and not bool(signal.get('price_at_zone'))
        new_risk = signal.get('risk_amount', 0.0)

        # Non-finite levels would silently disable every later comparison
        # (defect 8: a NaN close let the fake CL=F order through).
        if not _finite(signal.get('entry_price'), signal.get('stop_price')):
            logger.info(f"[{signal.get('symbol')}] Signal rejected: non-finite entry/stop "
                        f"({signal.get('entry_price')}, {signal.get('stop_price')})")
            return None

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
        _setup_key = signal.get('setup_key') or make_setup_key(
            signal['symbol'], _sig_dir, _sig_entry, float(signal['stop_price']))
        _now = utcnow()

        # Defect 9: zone ids were unstable (see make_setup_key), so a setup that
        # had already been traded and closed looked brand new the next day. The
        # setup key is compared against live orders AND against anything closed
        # or cancelled in the last `setup_dedup_days`.
        if self.setup_dedup_enabled:
            for _p in self.positions.values():
                if (_p.status in (TradeStatus.ACTIVE, TradeStatus.PENDING)
                        and self._setup_key_of(_p) == _setup_key):
                    logger.info(f"[{signal['symbol']}] Setup {_setup_key} already live "
                                f"({_p.status.value} {_p.id}); skipping")
                    return None
            _window = timedelta(days=self.setup_dedup_days)
            for _t in reversed(self.trade_history):
                # Only setups the market actually decided block a re-entry: closed
                # trades, drifted orders and stop entries whose stop traded first.
                # Expiry and fill-time gate cancellations (max open, loss budget,
                # correlation) say nothing about the setup, so it may be re-placed.
                if not (_t.status == TradeStatus.CLOSED
                        or (_t.status == TradeStatus.CANCELLED
                            and (_t.close_reason or '') in ('drifted', 'invalidated'))):
                    continue
                if self._setup_key_of(_t) != _setup_key:
                    continue
                _when = to_utc(_t.close_time) or to_utc(_t.placed_at) or to_utc(_t.entry_time)
                if _when is None or (_now - _when) <= _window:
                    logger.info(
                        f"[{signal['symbol']}] Setup {_setup_key} was already "
                        f"{_t.status.value} ({_t.close_reason or '-'}) on "
                        f"{_when.isoformat() if _when else '?'} -- not re-placed within "
                        f"{self.setup_dedup_days:.0f}d"
                    )
                    return None

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

        # placed_at = signal_time (the engine's UTC stamp); bars that STARTED
        # before it can never fill this order (see replay_bars).
        _placed_at = to_utc(signal.get('signal_time')) or _now
        _order_type = str(signal.get('order_type') or 'limit').lower()
        if _order_type not in ('limit', 'stop'):
            logger.warning(f"[{signal['symbol']}] unknown order_type {_order_type!r}; treating as limit")
            _order_type = 'limit'

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
            entry_time=_placed_at,
            status=(TradeStatus.PENDING if is_pending else TradeStatus.ACTIVE),
            zone_id=zone_id,
            income_strategy=signal.get('income_strategy'),
            trade_context=signal.get('trade_context') or 'standard',
            placed_at=_placed_at,
            order_type=_order_type,
            setup_key=_setup_key,
        )
        if not is_pending:
            # Legacy immediate fill (BP_BAR_REPLAY=0 only).
            position.filled_at = _placed_at
            position.fill_price = float(signal['entry_price'])

        self.positions[pos_id] = position
        if is_pending:
            logger.info(f"[{signal['symbol']}] PENDING {signal['direction']} {_order_type} {pos_id} "
                        f"@ {signal['entry_price']:.5f} (waiting for price to arrive)")
        else:
            logger.info(f"[{signal['symbol']}] OPENED {signal['direction']} position {pos_id} "
                        f"at {signal['entry_price']:.5f}")
        return pos_id

    def check_pending_fills(self, current_prices: Dict[str, Dict[str, float]]) -> List[str]:
        """LEGACY single-bar path (BP_BAR_REPLAY=0). The live path is replay_bars().

        Fill resting PENDING limit orders that price has now reached.

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
            _placed = to_utc(pos.placed_at) or to_utc(pos.entry_time) or utcnow()
            age_days = (utcnow() - _placed).total_seconds() / 86400.0
            max_age = self._pending_expiry_days_for(pos.income_strategy)
            if age_days >= max_age:
                pos.status = TradeStatus.CANCELLED
                pos.close_time = utcnow()
                pos.close_reason = "expired"
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

            # E-05 (2026-08-26): re-apply the entry-distance cap while the order
            # RESTS. BP_rules_engine.py:660 enforces both an R cap and a raw-%
            # cap, but only at signal creation. pending_order_max_age_days lets a
            # weekly limit sit for 14 days and a monthly one for 30, and nothing
            # re-checked distance in between -- so an order placed 6% away could
            # rest for a fortnight while the underlying walked away from it.
            # Measured over the 72 live pending rows: median 7.8% away, max
            # 31.5%, 17 beyond the 15% weekly cap; CL=F printed "29.04% away" on
            # four consecutive scans. Set BP_PENDING_DISTANCE_RECHECK=0 to revert.
            if os.environ.get('BP_PENDING_DISTANCE_RECHECK') != '0' and close:
                _ed = self.config.get('entry_distance', {}) or {}
                _risk_unit = abs(pos.entry_price - pos.stop_price)
                _r_away = (abs(close - entry) / _risk_unit) if _risk_unit > 0 else 0.0
                _pct_away = abs(close - entry) / close * 100
                _max_r = float((_ed.get('max_r_to_entry_pending', {}) or {}).get(
                    pos.income_strategy, _ed.get('default_max_r', 3.0)))
                _max_pct = float((_ed.get('max_pct_to_entry', {}) or {}).get(
                    pos.income_strategy, _ed.get('default_max_pct', 15.0)))
                if (_risk_unit > 0 and _r_away > _max_r) or (_pct_away > _max_pct):
                    pos.status = TradeStatus.CANCELLED
                    pos.close_time = utcnow()
                    pos.close_reason = "drifted"
                    self.trade_history.append(pos)
                    del self.positions[pos.id]
                    logger.info(
                        f"[{pos.symbol}] PENDING limit DRIFTED out of range: "
                        f"{_pct_away:.1f}% / {_r_away:.1f}R away "
                        f"(caps {_max_pct}% / {_max_r}R, strategy={pos.income_strategy}) "
                        f"-> CANCELLED"
                    )
                    continue

            if (pos.order_type or 'limit') == 'stop':
                # Defect 4: a buy-stop triggers when price trades UP to it.
                reached = (
                    (pos.direction == TradeDirection.LONG and high is not None and high >= entry)
                    or (pos.direction == TradeDirection.SHORT and low is not None and low <= entry)
                )
            else:
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
                pos.close_time = utcnow()
                pos.close_reason = "cancelled"
                self.trade_history.append(pos)
                del self.positions[pos.id]
                logger.info(
                    f"[{pos.symbol}] PENDING limit reached entry but CANCELLED "
                    f"instead of filling: {reason}"
                )
                continue

            pos.status = TradeStatus.ACTIVE
            pos.entry_time = utcnow()
            pos.filled_at = pos.entry_time
            pos.fill_price = entry
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
        LEGACY single-bar path (BP_BAR_REPLAY=0). The live path is replay_bars().

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
            if (self.breakeven_at_half and not self.fixed_bracket
                    and not pos.breakeven_triggered and pos.targets):
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
                    pos.close_time = utcnow()
                    pos.status = TradeStatus.CLOSED
                    pos.trade_r_multiple = (close_price - pos.entry_price) / abs(pos.entry_price - pos.stop_price) if abs(pos.entry_price - pos.stop_price) > 0 else 0
                    pos.close_reason = self._stop_close_reason(pos)

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
                    pos.close_time = utcnow()
                    pos.status = TradeStatus.CLOSED
                    pos.trade_r_multiple = (pos.entry_price - close_price) / abs(pos.entry_price - pos.stop_price) if abs(pos.entry_price - pos.stop_price) > 0 else 0
                    pos.close_reason = self._stop_close_reason(pos)

                    closed_events.append(self._close_position(pos))
                    if pos.zone_id:
                        self.zone_memory[pos.zone_id] = True
                    continue

            # Fixed bracket (stop_loss.management: fixed): the original stop was
            # checked above; the whole position closes at the one take-profit.
            if self.fixed_bracket and pos.targets:
                tp = pos.targets[min(self.fixed_tp_index, len(pos.targets) - 1)]
                is_long = pos.direction == TradeDirection.LONG
                if (current_high >= tp) if is_long else (current_low <= tp):
                    sign = 1.0 if is_long else -1.0
                    risk = abs(pos.entry_price - pos.stop_price)
                    pos.realized_pnl += (tp - pos.entry_price) * sign * pos.position_size
                    pos.close_price = tp
                    pos.close_time = utcnow()
                    pos.status = TradeStatus.CLOSED
                    pos.trade_r_multiple = (tp - pos.entry_price) * sign / risk if risk > 0 else 0
                    pos.close_reason = f"T{self.fixed_tp_index + 1}"
                    closed_events.append(self._close_position(pos))
                    if pos.zone_id:
                        self.zone_memory[pos.zone_id] = True
                continue

            # BP_TYPE_LADDERS=1 -- EXPERIMENTAL, DEFAULT OFF (2026-09-14).
            # Counter-trend trades close 100% at T2 instead of the 50% partial + trail
            # every trade gets today (CLAUDE.md: "Counter-trend: FULL CLOSE at T2 --
            # hard ceiling"). Only this one exit changes; the lecture's full four
            # ladders (trend BE 2R / first profit 4R, etc.) are not implemented.
            if (self.type_ladders and pos.trade_context == 'counter_trend'
                    and len(pos.targets) > 1 and not pos.partial_taken):
                t2 = pos.targets[1]
                is_long = pos.direction == TradeDirection.LONG
                if (current_high >= t2) if is_long else (current_low <= t2):
                    sign = 1.0 if is_long else -1.0
                    risk = abs(pos.entry_price - pos.stop_price)
                    pos.realized_pnl += (t2 - pos.entry_price) * sign * pos.position_size
                    pos.close_price = t2
                    pos.close_time = utcnow()
                    pos.status = TradeStatus.CLOSED
                    pos.trade_r_multiple = (t2 - pos.entry_price) * sign / risk if risk > 0 else 0
                    pos.close_reason = "T2_counter"
                    closed_events.append(self._close_position(pos))
                    if pos.zone_id:
                        self.zone_memory[pos.zone_id] = True
                    logger.info(f"[{pos.symbol}] Counter-trend closed 100% at T2={t2:.4f}")
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
                            pos.close_time = utcnow()
                            pos.status = TradeStatus.CLOSED
                            pos.trade_r_multiple = 3.0
                            pos.close_reason = "T3"
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
                            pos.close_time = utcnow()
                            pos.status = TradeStatus.CLOSED
                            pos.trade_r_multiple = 3.0
                            pos.close_reason = "T3"
                            closed_events.append(self._close_position(pos))
                            if pos.zone_id:
                                self.zone_memory[pos.zone_id] = True
                            break

        return closed_events

    @staticmethod
    def _stop_close_reason(pos: 'Position') -> str:
        """Classify a stop-out: trailing exit, breakeven scratch, or a real stop."""
        if pos.trail_stop_level is not None and pos.current_stop == pos.trail_stop_level:
            return "trail"
        if pos.breakeven_triggered:
            _tol = 1e-9 * max(1.0, abs(pos.entry_price))
            _be_levels = [pos.entry_price]
            if pos.fill_price is not None:
                _be_levels.append(pos.fill_price)
            if any(abs(pos.current_stop - lvl) <= _tol for lvl in _be_levels):
                return "breakeven"
        return "stop"

    @staticmethod
    def _setup_key_of(pos: 'Position') -> str:
        """Setup key of a position; derived from its levels for legacy records
        saved before setup_key existed."""
        return pos.setup_key or make_setup_key(
            pos.symbol, pos.direction, pos.entry_price, pos.stop_price)

    # ================================================================
    # 1h BAR REPLAY (2026-09-27, defects 6/7) -- the live pricing path
    # ================================================================
    # Each run replays the COMPLETED 1h bars that printed since each open
    # order/position was last evaluated, in time order, like a broker working
    # resting orders tick by tick. The strategy is unchanged (weekly zones,
    # daily entries): the 1h bars only establish the ORDER OF EVENTS.
    #
    # Rules, in the order they are applied to one bar:
    #   PENDING
    #     * a bar that STARTED before placed_at is ignored (it began before the
    #       order existed; this also treats the bar containing the placement
    #       conservatively);
    #     * expiry by bar time (pending_order_max_age_days);
    #     * limit long fills when low <= entry at min(entry, open); limit short
    #       when high >= entry at max(entry, open); stop long fills when
    #       high >= entry at max(entry, open); stop short when low <= entry at
    #       min(entry, open) -- a gap through fills at the open;
    #     * on the fill bar only the stop is checked (worst case); no target or
    #       breakeven credit is given for the part of the bar before the fill;
    #     * if not filled: directional drift (E-05) and stop-order invalidation.
    #   ACTIVE
    #     * the stop in force at the START of the bar is checked first (a gap
    #       through exits at the open); if the bar reaches both the stop and a
    #       target, the stop wins;
    #     * then half-T1 breakeven, T1 breakeven, T2 partial / counter-trend
    #       close, T3, trailing. A stop MOVE caused on bar k takes effect from
    #       bar k+1: on bar k the order of "high then low" is unknowable, and
    #       the old path always assumed the worst (armed BE, then scratched).
    # Weekends and holidays produce no bars, so nothing happens then (defect 7:
    # the old path opened and closed trades on Saturday/Sunday against Friday's
    # stale close).

    def last_priced_ts(self, symbol: str) -> Optional[datetime]:
        """Earliest instant from which `symbol` still needs bars: min over its
        open orders/positions of last_priced_ts, or placed_at for an order that
        has never been priced (entry_time for legacy records)."""
        stamps = [
            to_utc(p.last_priced_ts) or to_utc(p.placed_at) or to_utc(p.entry_time)
            for p in self.positions.values()
            if p.symbol == symbol and p.status in (TradeStatus.PENDING, TradeStatus.ACTIVE)
        ]
        stamps = [s for s in stamps if s is not None]
        return min(stamps) if stamps else None

    def oldest_placed_at(self, symbol: str) -> Optional[datetime]:
        stamps = [
            to_utc(p.placed_at) or to_utc(p.entry_time)
            for p in self.positions.values()
            if p.symbol == symbol and p.status in (TradeStatus.PENDING, TradeStatus.ACTIVE)
        ]
        stamps = [s for s in stamps if s is not None]
        return min(stamps) if stamps else None

    def open_symbols(self) -> List[str]:
        """Symbols with at least one PENDING or ACTIVE position."""
        return sorted({p.symbol for p in self.positions.values()
                       if p.status in (TradeStatus.PENDING, TradeStatus.ACTIVE)})

    def replay_bars(self, symbol: str, bars_df, bar_interval: timedelta = timedelta(hours=1)
                    ) -> Dict[str, List[Dict]]:
        """Replay completed bars of ONE symbol. See replay_bars_multi."""
        return self.replay_bars_multi({symbol: bars_df}, bar_interval=bar_interval)

    def replay_bars_multi(self, bars_by_symbol: Dict[str, object],
                          bar_interval: timedelta = timedelta(hours=1)) -> Dict[str, List[Dict]]:
        """Replay completed bars of several symbols merged into ONE time order.

        Calling replay_bars() once per symbol would process all of symbol A's
        week before symbol B's first hour, so the fill-time gates (max open
        positions, the daily/total loss budget, correlation) and the daily-loss
        day roll would see portfolio state out of order. Interleaving by bar
        start keeps them chronological; bars with the same start are taken in
        symbol order, which is deterministic.

        bars_df columns: timestamp (bar START, UTC), open, high, low, close.
        Rows with a non-finite price are skipped. Returns
        {'fills': [...], 'closed': [...], 'cancelled': [...]} event dicts.
        """
        events: Dict[str, List[Dict]] = {'fills': [], 'closed': [], 'cancelled': []}
        if not self.bar_replay:
            logger.warning("replay_bars called with BP_BAR_REPLAY=0 -- ignored "
                           "(the legacy single-bar path prices this run)")
            return events

        rows = []
        for sym, df in (bars_by_symbol or {}).items():
            if df is None or len(df) == 0:
                continue
            try:
                ts_col = df['timestamp'] if 'timestamp' in df.columns else df.index.to_series()
                it = zip(ts_col, df['open'], df['high'], df['low'], df['close'])
            except (KeyError, AttributeError) as exc:
                logger.warning(f"[{sym}] replay: unusable bar frame ({exc}) -- skipped")
                continue
            for ts, o, h, l, c in it:
                start = to_utc(ts)
                if start is None or not _finite(o, h, l, c):
                    continue
                rows.append((start, sym, float(o), float(h), float(l), float(c)))
        rows.sort(key=lambda r: (r[0], r[1]))

        for start, sym, o, h, l, c in rows:
            self._replay_one_bar(sym, start, start + bar_interval, o, h, l, c, events)
        return events

    def _replay_one_bar(self, symbol: str, start: datetime, end: datetime,
                        o: float, h: float, l: float, c: float,
                        events: Dict[str, List[Dict]]) -> None:
        # Daily-loss accounting follows BAR time, not scan time.
        self.maybe_roll_day(start)
        for pos in list(self.positions.values()):
            if pos.symbol != symbol or pos.id not in self.positions:
                continue
            if pos.status not in (TradeStatus.PENDING, TradeStatus.ACTIVE):
                continue
            last = to_utc(pos.last_priced_ts)
            if last is not None and start < last:
                continue                      # already priced through this bar
            if pos.status == TradeStatus.PENDING:
                placed = to_utc(pos.placed_at) or to_utc(pos.entry_time)
                if placed is not None and start < placed:
                    continue                  # bar began before the order existed
                self._replay_pending_bar(pos, start, o, h, l, c, events)
            else:
                self._replay_active_bar(pos, start, o, h, l, c, events)
            pos.last_priced_ts = end

    def _replay_pending_bar(self, pos: 'Position', start: datetime,
                            o: float, h: float, l: float, c: float,
                            events: Dict[str, List[Dict]]) -> None:
        is_long = pos.direction == TradeDirection.LONG
        otype = (pos.order_type or 'limit')
        entry = float(pos.entry_price)

        # Expiry by bar time (the old path used the wall clock at scan time).
        placed = to_utc(pos.placed_at) or to_utc(pos.entry_time)
        max_age = self._pending_expiry_days_for(pos.income_strategy)
        if placed is not None and (start - placed) >= timedelta(days=max_age):
            self._cancel_order(pos, 'expired', placed + timedelta(days=max_age), events,
                               f"unfilled after {max_age:g}d (strategy={pos.income_strategy})")
            return

        if otype == 'stop':
            hit = (h >= entry) if is_long else (l <= entry)
            fill_px = max(entry, o) if is_long else min(entry, o)
        else:
            hit = (l <= entry) if is_long else (h >= entry)
            fill_px = min(entry, o) if is_long else max(entry, o)

        if hit:
            if self.account_blown:
                self._cancel_order(pos, 'cancelled', start, events,
                                   "reached entry but the account is breached")
                return
            # Same gates as the old fill path, evaluated at the fill bar so the
            # portfolio state is the one that exists at that hour.
            ok, reason = self._check_activation_gates(pos.symbol, pos.risk_amount, exclude_id=pos.id)
            if not ok:
                self._cancel_order(pos, 'cancelled', start, events,
                                   f"reached entry but not activated: {reason}")
                return
            pos.status = TradeStatus.ACTIVE
            pos.fill_price = fill_px
            pos.filled_at = start
            pos.entry_time = start
            events['fills'].append({
                'event': 'order_filled', 'position_id': pos.id, 'symbol': pos.symbol,
                'direction': pos.direction.value, 'order_type': otype,
                'entry_price': pos.entry_price, 'fill_price': fill_px,
                'filled_at': start.isoformat(), 'stop_price': pos.stop_price,
                'targets': list(pos.targets), 'risk_amount': pos.risk_amount,
            })
            logger.info(f"[{pos.symbol}] PENDING {otype} FILLED at {fill_px:.5f} "
                        f"(order {entry:.5f}) on bar {start.isoformat()} -> ACTIVE")
            # Worst case on the fill bar: if it also reached the stop, assume
            # the stop came AFTER the fill. If the bar opened beyond the stop the
            # fill itself was at the open, and the stop exits there too.
            stop = float(pos.current_stop)
            if (l <= stop) if is_long else (h >= stop):
                exit_px = min(stop, fill_px) if is_long else max(stop, fill_px)
                self._close_at(pos, exit_px, start, 'stop', events)
            return

        # --- not filled: directional drift (E-05) ---------------------------
        # The old recheck used |close - entry|, so a price that had moved
        # THROUGH the entry towards the stop also counted as "far away" and
        # cancelled the order just as it became a good fill. Only distance on
        # the approach side, moving away, counts now:
        #   limit long waits BELOW price -> away = price rising above entry
        #   stop  long waits ABOVE price -> away = price falling below entry
        if os.environ.get('BP_PENDING_DISTANCE_RECHECK') != '0' and c > 0:
            if otype == 'stop':
                away = (entry - c) if is_long else (c - entry)
            else:
                away = (c - entry) if is_long else (entry - c)
            if away > 0:
                _ed = self.config.get('entry_distance', {}) or {}
                _risk_unit = abs(entry - float(pos.stop_price))
                _r_away = away / _risk_unit if _risk_unit > 0 else 0.0
                _pct_away = away / c * 100
                _max_r = float((_ed.get('max_r_to_entry_pending', {}) or {}).get(
                    pos.income_strategy, _ed.get('default_max_r', 3.0)))
                _max_pct = float((_ed.get('max_pct_to_entry', {}) or {}).get(
                    pos.income_strategy, _ed.get('default_max_pct', 15.0)))
                if (_risk_unit > 0 and _r_away > _max_r) or (_pct_away > _max_pct):
                    self._cancel_order(pos, 'drifted', start, events,
                                       f"{_pct_away:.1f}% / {_r_away:.1f}R away on the approach "
                                       f"side (caps {_max_pct}% / {_max_r}R)")
                    return

        # --- not filled: a stop entry whose stop level trades first ----------
        # E3b buys above a hammer high with the stop under the hammer low. If the
        # low breaks before the high is taken out, the pattern has failed; a
        # real trader pulls the order. BP_STOP_ORDER_INVALIDATE=0 disables.
        if otype == 'stop' and os.environ.get('BP_STOP_ORDER_INVALIDATE') != '0':
            stop = float(pos.stop_price)
            if (l <= stop) if is_long else (h >= stop):
                self._cancel_order(pos, 'invalidated', start, events,
                                   "stop level traded before the stop entry triggered "
                                   "(pattern failed)")

    def _replay_active_bar(self, pos: 'Position', start: datetime,
                           o: float, h: float, l: float, c: float,
                           events: Dict[str, List[Dict]]) -> None:
        is_long = pos.direction == TradeDirection.LONG
        fill = pos.fill_price if pos.fill_price is not None else float(pos.entry_price)
        risk_unit = abs(float(pos.entry_price) - float(pos.stop_price))

        # 1) The stop in force when the bar opened. Checked before any target:
        #    if a bar reaches both, the stop wins (the order inside the bar is
        #    unknown, so assume the worse one).
        stop = float(pos.current_stop)
        if is_long:
            exit_px = o if o <= stop else (stop if l <= stop else None)
        else:
            exit_px = o if o >= stop else (stop if h >= stop else None)
        if exit_px is not None:
            self._close_at(pos, exit_px, start, self._stop_close_reason(pos), events)
            return

        def reached(level: float) -> bool:
            return (h >= level) if is_long else (l <= level)

        def tp_px(level: float) -> float:
            # A resting take-profit fills at its level, or at a better gapped open.
            return max(level, o) if is_long else min(level, o)

        def better(a: Optional[float], b: float) -> float:
            if a is None:
                return b
            return max(a, b) if is_long else min(a, b)

        # Fixed bracket: the original stop (checked above) and one take-profit.
        if self.fixed_bracket and pos.targets:
            tp = float(pos.targets[min(self.fixed_tp_index, len(pos.targets) - 1)])
            if reached(tp):
                self._close_at(pos, tp_px(tp), start, f"T{self.fixed_tp_index + 1}", events)
            return

        new_stop: Optional[float] = None   # applied from the NEXT bar

        # 2) Half-T1 breakeven (Bernd's live practice).
        if self.breakeven_at_half and not pos.breakeven_triggered and pos.targets:
            halfway = (float(pos.entry_price) + float(pos.targets[0])) / 2.0
            if reached(halfway):
                pos.breakeven_triggered = True
                new_stop = better(new_stop, fill)
                logger.info(f"[{pos.symbol}] Half-target BE armed at {halfway:.5f} on "
                            f"{start.isoformat()} (stop -> {fill:.5f} from next bar)")

        # 3) BP_TYPE_LADDERS counter-trend: close 100% at T2 (experimental).
        if (self.type_ladders and pos.trade_context == 'counter_trend'
                and len(pos.targets) > 1 and not pos.partial_taken):
            t2 = float(pos.targets[1])
            if reached(t2):
                self._close_at(pos, tp_px(t2), start, 'T2_counter', events)
                logger.info(f"[{pos.symbol}] Counter-trend closed 100% at T2={t2:.4f}")
                return

        # 4) Targets in order.
        sign = 1.0 if is_long else -1.0
        for i, target in enumerate(pos.targets):
            target = float(target)
            if not reached(target):
                continue
            if i == 0 and not pos.breakeven_triggered:
                pos.breakeven_triggered = True
                new_stop = better(new_stop, fill)
                logger.info(f"[{pos.symbol}] T1 breakeven armed (stop -> {fill:.5f} from next bar)")
            if i == 1 and not pos.partial_taken:
                px = tp_px(target)
                partial_pnl = (px - fill) * sign * pos.position_size * 0.5
                pos.realized_pnl += partial_pnl
                pos.partial_taken = True
                pos.partial_qty = pos.position_size * 0.5
                pos.partial_price = px
                pos.position_size *= 0.5
                # Not added to closed_pnl_total here: it is booked once, with the
                # rest of realized_pnl, in _close_position.
                trail = float(pos.entry_price) + sign * risk_unit   # T1 level
                pos.trail_stop_level = trail
                new_stop = better(new_stop, trail)
                logger.info(f"[{pos.symbol}] Partial 50% at T2={px:.5f}, PnL={partial_pnl:.2f}; "
                            f"trail -> {trail:.5f} from next bar")
            if i == 2:
                self._close_at(pos, tp_px(target), start, 'T3', events)
                return

        # 5) 1R trail behind the bar close once the partial is off (zone-distal
        #    trailing is separate, apply_zone_trailing).
        if pos.partial_taken and pos.trail_stop_level is not None and risk_unit > 0:
            cand = c - sign * risk_unit
            if (cand > pos.trail_stop_level) if is_long else (cand < pos.trail_stop_level):
                pos.trail_stop_level = cand
                new_stop = better(new_stop, cand)

        # Apply the move now; this bar's stop test has already run, so in
        # effect it starts with the next bar. Never loosen a stop.
        if new_stop is not None:
            if (new_stop > pos.current_stop) if is_long else (new_stop < pos.current_stop):
                pos.current_stop = new_stop

    def _close_at(self, pos: 'Position', exit_px: float, when: datetime, reason: str,
                  events: Dict[str, List[Dict]]) -> None:
        """Close the remaining size at `exit_px` on the bar starting `when`."""
        is_long = pos.direction == TradeDirection.LONG
        sign = 1.0 if is_long else -1.0
        fill = pos.fill_price if pos.fill_price is not None else float(pos.entry_price)
        pos.realized_pnl += (exit_px - fill) * sign * pos.position_size
        pos.close_price = exit_px
        pos.close_time = when
        pos.status = TradeStatus.CLOSED
        pos.close_reason = reason
        # R in units of the PLANNED risk, over the whole original size, so a
        # T2 partial plus a trailed runner reports its true blend (the old
        # path reported only the runner's exit, and a flat 3.0 at T3).
        orig_size = pos.position_size + pos.partial_qty
        risk_unit = abs(float(pos.entry_price) - float(pos.stop_price))
        pos.trade_r_multiple = (pos.realized_pnl / (orig_size * risk_unit)
                                if orig_size > 0 and risk_unit > 0 else 0.0)
        ev = self._close_position(pos)
        if pos.zone_id:
            self.zone_memory[pos.zone_id] = True
        events['closed'].append(ev)
        logger.info(f"[{pos.symbol}] CLOSED {pos.direction.value} at {exit_px:.5f} "
                    f"({reason}) on bar {when.isoformat()}: PnL={pos.realized_pnl:.2f} "
                    f"({pos.trade_r_multiple:+.2f}R)")
        breached, why = self.is_breached()
        if breached and not self.account_blown:
            self.account_blown = True
            logger.warning(f"Account breach during replay: {why}")

    def _cancel_order(self, pos: 'Position', reason: str, when: datetime,
                      events: Dict[str, List[Dict]], why: str = "") -> None:
        """Cancel a PENDING order (never filled: no risk, no P&L)."""
        pos.status = TradeStatus.CANCELLED
        pos.close_time = when
        pos.close_reason = reason
        self.trade_history.append(pos)
        del self.positions[pos.id]
        events['cancelled'].append({
            'event': 'order_cancelled', 'position_id': pos.id, 'symbol': pos.symbol,
            'direction': pos.direction.value, 'order_type': pos.order_type,
            'entry_price': pos.entry_price, 'close_reason': reason, 'why': why,
            'close_time': when.isoformat() if when else '',
        })
        logger.info(f"[{pos.symbol}] PENDING {pos.order_type} {pos.id} CANCELLED ({reason}): {why}")

    def expire_stale_pending(self, now: Optional[datetime] = None,
                             grace_days: float = 2.0) -> List[Dict]:
        """Wall-clock BACKSTOP for pending expiry.

        Expiry normally happens inside replay_bars on bar time. A symbol whose
        intraday bars never arrive (no 60m history, repeated fetch failures)
        would never be replayed, so its order would rest forever. After the
        normal max age plus `grace_days` (covers a weekend), cancel it anyway.
        """
        now = to_utc(now) if now is not None else utcnow()
        events: Dict[str, List[Dict]] = {'fills': [], 'closed': [], 'cancelled': []}
        for pos in list(self.positions.values()):
            if pos.status != TradeStatus.PENDING:
                continue
            placed = to_utc(pos.placed_at) or to_utc(pos.entry_time)
            if placed is None:
                continue
            max_age = self._pending_expiry_days_for(pos.income_strategy)
            if (now - placed) >= timedelta(days=max_age + grace_days):
                self._cancel_order(pos, 'expired', now, events,
                                   f"no bars replayed; wall-clock age exceeds {max_age:g}d "
                                   f"+ {grace_days:g}d grace")
        return events['cancelled']

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
            'close_reason': pos.close_reason,
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
        # E-04 (2026-08-26): with 0 decided trades this returned 0.0, which renders
        # identically to "0 of 7 won". None means "no data yet" and every consumer
        # now renders it as n/a with the scratch count.
        _decided = self.winning_trades + self.losing_trades
        win_rate = (self.winning_trades / _decided) if _decided > 0 else None
        closed = [p for p in self.trade_history if p.status == TradeStatus.CLOSED]
        avg_r = sum(p.trade_r_multiple for p in closed) / max(1, len(closed))

        # Fundingpips-style "Trading Objectives" block ──────────────────────
        today_loss = max(0.0, self.today_starting_equity - self.balance)
        total_loss = max(0.0, self.initial_balance - self.balance)
        breached, breach_reason = self.is_breached()

        # Challenge clock + progress toward profit_target_pct. days_elapsed is
        # None until challenge_started_at is set (first save after a reset).
        # Defect 10: challenge_started_at was written as naive IST local time and
        # compared with the runner's naive UTC clock -> "Day -1 since reset".
        # Both sides are aware UTC now; a legacy naive stamp is read as UTC.
        days_elapsed = None
        if self.challenge_started_at:
            started = to_utc(self.challenge_started_at)
            if started is not None:
                days_elapsed = max(0, (utcnow() - started).days)

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
            'win_rate': (round(win_rate, 4) if win_rate is not None else None),
            'decided_trades': _decided,
            'scratch_trades': self.scratch_trades,
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

    def get_trade_history(self, limit: int = 50, include_cancelled: bool = False) -> List[Dict]:
        """Return recent trade history, mapping internal field names to the
        keys the dashboard expects.

        2026-08-26: CANCELLED orders are excluded by default. `trade_history`
        receives them from four sites -- age expiry, activation-gate rejection
        at fill time, E-05 distance drift, and (historically) nothing else --
        but a cancelled order was NEVER FILLED: no risk was taken and its P&L is
        structurally 0.00. Rendering it in CLOSED THIS SCAN / TRACK RECORD made
        it read as a scratch trade. That is where the log's "0.00 USD SCRATCH"
        rows with a NEGATIVE peak R came from (AUDUSD=X, CADCHF=X, GBPCAD=X) --
        they were never trades. Pass include_cancelled=True to audit them.
        """
        src = self.trade_history if include_cancelled else [
            t for t in self.trade_history if t.status != TradeStatus.CANCELLED
        ]
        out = []
        for t in src[-limit:]:
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
        self.current_date = utcnow().strftime('%Y-%m-%d')

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
