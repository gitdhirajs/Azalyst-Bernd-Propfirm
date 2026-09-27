"""draw_chart.py tests (O4, 2026-09-27): temp-dir output, completed bars only,
no crash when mplfinance is missing or data is short."""
import os
import sys
import tempfile
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import draw_chart  # noqa: E402


def _rows(n, incomplete_last=True, with_flag=True):
    """Daily rows shaped like run_scanner's ohlcv_cache (timestamp as str)."""
    rows = []
    t0 = pd.Timestamp("2026-06-01", tz="UTC")
    for i in range(n):
        o = 1.0 + i * 0.001
        r = {"timestamp": str(t0 + pd.Timedelta(days=i)),
             "open": o, "high": o + 0.004, "low": o - 0.004, "close": o + 0.002,
             "volume": 0}
        if with_flag:
            r["is_complete"] = not (incomplete_last and i == n - 1)
        rows.append(r)
    return rows


def _signal(sym="EURUSD=X"):
    return {"symbol": sym, "ltf": "1d", "entry_price": 1.02, "stop_price": 1.01,
            "targets": [1.03, 1.04, float("nan")]}


def test_completed_frame_drops_forming_bar_and_nan_rows():
    rows = _rows(20)
    rows[3]["close"] = float("nan")
    df = draw_chart._completed_frame(rows)
    assert len(df) == 18                      # forming last bar + NaN row gone
    assert df.index.max() < pd.Timestamp(rows[-1]["timestamp"])


def test_missing_is_complete_column_means_all_complete():
    df = draw_chart._completed_frame(_rows(20, with_flag=False))
    assert len(df) == 20


def test_string_flags_are_understood():
    rows = _rows(12)
    for r in rows:
        r["is_complete"] = str(r["is_complete"])   # "True"/"False"
    assert len(draw_chart._completed_frame(rows)) == 11


def test_short_data_returns_none():
    cache = {"EURUSD=X": {"1d": _rows(draw_chart.MIN_BARS)}}   # 1 forming -> too few
    assert draw_chart.generate_chart(_signal(), cache) is None


def test_no_data_returns_none():
    assert draw_chart.generate_chart(_signal(), {}) is None
    assert draw_chart.generate_chart(_signal(), {"EURUSD=X": {"1wk": _rows(40)}}) is None


def test_missing_mplfinance_does_not_crash(monkeypatch):
    monkeypatch.setitem(sys.modules, "mplfinance", None)   # import -> ImportError
    cache = {"EURUSD=X": {"1d": _rows(40)}}
    assert draw_chart.generate_chart(_signal(), cache) is None


def test_chart_written_to_temp_dir():
    pytest.importorskip("mplfinance")
    cache = {"EUR/USD=X^": {"1d": _rows(40)}}
    path = draw_chart.generate_chart(_signal("EUR/USD=X^"), cache)
    try:
        assert path is not None and os.path.exists(path)
        assert Path(path).parent.resolve() == Path(tempfile.gettempdir()).resolve()
        assert Path(path).name.startswith("azalyst_chart_EUR_USD_X")
        assert os.path.getsize(path) > 1000
    finally:
        if path and os.path.exists(path):
            os.remove(path)


def test_kill_switch_draws_forming_bar(monkeypatch):
    monkeypatch.setenv("BP_CHART_COMPLETED_ONLY", "0")
    assert len(draw_chart._completed_frame(_rows(20))) == 20
