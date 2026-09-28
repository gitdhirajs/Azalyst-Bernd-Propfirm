"""Set-and-forget management (stop_loss.management: fixed, user decision 2026-09-27).

The stop never moves and 100% of the position closes at T2. No breakeven,
no partial, no trailing.

Run from the dashboard folder:
    python -m pytest tests -p no:cacheprovider -q
"""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from BP_paper_trader import PaperTrader, TradeStatus               # noqa: E402
from test_paper_trader_replay import bars, cfg, hist, signal       # noqa: E402


def fixed_cfg(target=2):
    c = cfg()
    c["stop_loss"] = {"management": "fixed", "take_profit_target": target,
                      "breakeven_at_half_target": True}   # must be ignored in fixed mode
    return c


@pytest.fixture(autouse=True)
def _default_env(monkeypatch):
    for k in ("BP_BAR_REPLAY", "BP_PENDING_DISTANCE_RECHECK", "BP_STOP_ORDER_INVALIDATE",
              "BP_SETUP_KEY_DEDUP", "BP_TYPE_LADDERS"):
        monkeypatch.delenv(k, raising=False)


def filled(trader):
    """Long EURUSD limit 1.1000, stop 1.0950, T1 1.1050, T2 1.1100; filled on the first bar."""
    pid = trader.submit_signal(signal())
    trader.replay_bars("EURUSD=X", bars("2026-07-30T11:00Z", [(1.1010, 1.1012, 1.0998, 1.1005)]))
    assert trader.positions[pid].status == TradeStatus.ACTIVE
    return pid


def test_fixed_config_is_fixed_at_t2():
    # The live default became scale_out on 2026-09-28; `management: fixed` in
    # the live file must still give the 2026-09-27 set-and-forget bracket.
    live = yaml.safe_load((Path(__file__).resolve().parents[1] / "BP_config.yaml").read_text(encoding="utf-8"))
    live["stop_loss"]["management"] = "fixed"
    t = PaperTrader(live)
    assert t.fixed_bracket and not t.scale_out and t.fixed_tp_index == 1


def test_return_to_entry_after_half_t1_does_not_close():
    t = PaperTrader(fixed_cfg())
    pid = filled(t)
    # Half-T1 (1.1025) reached, then price trades back through entry: the old
    # ladder scratched here at $0. The stop stays at 1.0950, so the trade lives.
    t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [
        (1.1005, 1.1030, 1.1004, 1.1028),
        (1.1028, 1.1029, 1.0980, 1.0985),
    ]))
    p = t.positions[pid]
    assert p.status == TradeStatus.ACTIVE
    assert p.current_stop == pytest.approx(1.0950)
    assert not p.breakeven_triggered


def test_closes_100_percent_at_t2_for_2r():
    t = PaperTrader(fixed_cfg())
    pid = filled(t)
    t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [
        (1.1005, 1.1060, 1.1000, 1.1055),   # T1 passes: nothing happens
        (1.1055, 1.1105, 1.1050, 1.1100),   # T2 reached: full close
    ]))
    p = hist(t, pid)
    assert p.status == TradeStatus.CLOSED
    assert p.close_reason == "T2"
    assert p.close_price == pytest.approx(1.1100)
    assert p.trade_r_multiple == pytest.approx(2.0)
    assert not p.partial_taken and p.partial_qty == 0
    assert p.realized_pnl == pytest.approx((1.1100 - 1.1000) * 10000.0)


def test_original_stop_is_a_full_loss():
    t = PaperTrader(fixed_cfg())
    pid = filled(t)
    t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [
        (1.1005, 1.1040, 1.1000, 1.1030),   # half-T1 reached (no breakeven)
        (1.1030, 1.1031, 1.0945, 1.0948),   # original stop
    ]))
    p = hist(t, pid)
    assert p.close_reason == "stop"
    assert p.trade_r_multiple == pytest.approx(-1.0)


def test_bar_touching_stop_and_t2_counts_the_stop():
    t = PaperTrader(fixed_cfg())
    pid = filled(t)
    t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [(1.1005, 1.1110, 1.0940, 1.1000)]))
    assert hist(t, pid).close_reason == "stop"


def test_gap_beyond_t2_fills_at_the_better_open():
    t = PaperTrader(fixed_cfg())
    pid = filled(t)
    t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [(1.1120, 1.1130, 1.1115, 1.1125)]))
    p = hist(t, pid)
    assert p.close_reason == "T2" and p.close_price == pytest.approx(1.1120)


def test_short_closes_at_t2():
    t = PaperTrader(fixed_cfg())
    pid = t.submit_signal(signal(direction="short", entry=1.1000, stop=1.1050,
                                 targets=(1.0950, 1.0900, 1.0850)))
    t.replay_bars("EURUSD=X", bars("2026-07-30T11:00Z", [
        (1.0990, 1.1002, 1.0985, 1.0995),   # fill (high reaches 1.1000)
        (1.0995, 1.0996, 1.0930, 1.0940),   # T1 passes
        (1.0940, 1.0945, 1.0895, 1.0900),   # T2
    ]))
    p = hist(t, pid)
    assert p.close_reason == "T2" and p.trade_r_multiple == pytest.approx(2.0)


def test_take_profit_target_setting_is_respected():
    t = PaperTrader(fixed_cfg(target=3))
    pid = filled(t)
    t.replay_bars("EURUSD=X", bars("2026-07-30T12:00Z", [(1.1005, 1.1105, 1.1000, 1.1100)]))
    assert t.positions[pid].status == TradeStatus.ACTIVE      # T2 is not the target
    t.replay_bars("EURUSD=X", bars("2026-07-30T13:00Z", [(1.1100, 1.1155, 1.1095, 1.1150)]))
    assert hist(t, pid).close_reason == "T3"


def test_legacy_single_bar_path_is_fixed_too(monkeypatch):
    monkeypatch.setenv("BP_BAR_REPLAY", "0")
    t = PaperTrader(fixed_cfg())
    pid = t.submit_signal(signal(price_at_zone=True, pending_order=True))
    assert t.positions[pid].status == TradeStatus.ACTIVE
    # A daily candle that reaches half-T1 and trades back to entry: no scratch.
    t.update_positions({"EURUSD=X": {"high": 1.1030, "low": 1.0990, "close": 1.1000,
                                     "bid": 1.1000, "ask": 1.1000}})
    assert t.positions[pid].status == TradeStatus.ACTIVE
    t.update_positions({"EURUSD=X": {"high": 1.1105, "low": 1.1000, "close": 1.1100,
                                     "bid": 1.1100, "ask": 1.1100}})
    p = hist(t, pid)
    assert p.close_reason == "T2" and p.trade_r_multiple == pytest.approx(2.0)
