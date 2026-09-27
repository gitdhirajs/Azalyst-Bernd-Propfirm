"""DataFetcher.fetch_bars_since -- the 1h replay feed for the paper trader.

Synthetic frames only (DataFetcher._fetch_one is monkeypatched), no network.
Run:  python -m pytest "Propfirm Trading Dashboard/tests" -q
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import BP_data_fetcher as F  # noqa: E402

NOW = pd.Timestamp("2026-09-25 12:30", tz="UTC")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv("BP_DROP_STUB_BARS", raising=False)
    monkeypatch.setattr(F, "_utcnow", lambda: NOW)


def raw_hourly():
    """What _fetch_one returns for EURUSD=X 60m: London-tz starts, one NaN row,
    one flat zero-volume stub, a duplicate, and the still-forming 12:00Z bar."""
    idx = pd.date_range("2026-09-25 06:00", periods=8, freq="h", tz="Europe/London")
    df = pd.DataFrame({"timestamp": idx,
                       "open": [1.10, 1.11, 1.12, 1.13, 1.14, 1.15, 1.16, 1.17],
                       "high": [1.12, 1.13, 1.14, 1.15, 1.16, 1.17, 1.18, 1.19],
                       "low": [1.09, 1.10, 1.11, 1.12, 1.13, 1.14, 1.15, 1.16],
                       "close": [1.11, 1.12, 1.13, 1.14, 1.15, 1.16, 1.17, 1.18],
                       "volume": 0})
    df.loc[2, "close"] = np.nan                                  # 07:00Z
    df.loc[3, ["open", "high", "low", "close"]] = 1.135          # 08:00Z flat stub
    dup = df.iloc[[5]].copy()                                    # 10:00Z re-sent later
    dup["close"] = 1.165                                         # (the newer print wins)
    return pd.concat([df.sample(frac=1, random_state=0), dup], ignore_index=True)


def patch_fetch(monkeypatch, frames):
    calls = []

    def fake(self, symbol, interval, period, start, end, retries):
        calls.append((symbol, interval, period, start, end))
        v = frames.get(symbol, pd.DataFrame())
        if isinstance(v, Exception):
            raise v
        return v.copy()

    monkeypatch.setattr(F.DataFetcher, "_fetch_one", fake)
    return calls


def test_contract_filters_and_orders(monkeypatch):
    calls = patch_fetch(monkeypatch, {"EURUSD=X": raw_hourly()})
    since = pd.Timestamp("2026-09-25 06:00", tz="UTC")
    out = F.DataFetcher().fetch_bars_since("EURUSD=X", since)
    assert list(out.columns) == F.BAR_COLUMNS
    assert str(out["timestamp"].dt.tz) == "UTC"
    ts = list(out["timestamp"].dt.strftime("%H:%M"))
    # 05:00Z < since; 07:00Z NaN; 08:00Z stub; 12:00Z still forming (ends 13:00Z)
    assert ts == ["06:00", "09:00", "10:00", "11:00"]
    assert out["timestamp"].is_monotonic_increasing and out["timestamp"].is_unique
    assert out.loc[out["timestamp"].dt.hour == 10, "close"].item() == pytest.approx(1.165)
    assert np.isfinite(out[["open", "high", "low", "close"]].to_numpy()).all()
    assert calls[0][1] == "60m" and calls[0][2] == "3d"


def test_since_accepts_naive_and_iso(monkeypatch):
    patch_fetch(monkeypatch, {"EURUSD=X": raw_hourly()})
    f = F.DataFetcher()
    a = f.fetch_bars_since("EURUSD=X", "2026-09-25T09:00:00Z")
    b = f.fetch_bars_since("EURUSD=X", pd.Timestamp("2026-09-25 09:00").to_pydatetime())
    assert list(a["timestamp"]) == list(b["timestamp"])
    assert a["timestamp"].iloc[0] == pd.Timestamp("2026-09-25 09:00", tz="UTC")


def test_stub_kill_switch_keeps_flat_bars(monkeypatch):
    monkeypatch.setenv("BP_DROP_STUB_BARS", "0")
    patch_fetch(monkeypatch, {"EURUSD=X": raw_hourly()})
    out = F.DataFetcher().fetch_bars_since("EURUSD=X", "2026-09-25 06:00Z")
    assert "08:00" in list(out["timestamp"].dt.strftime("%H:%M"))
    assert "07:00" not in list(out["timestamp"].dt.strftime("%H:%M"))   # NaN always dropped


def test_never_raises_returns_empty_with_columns(monkeypatch):
    patch_fetch(monkeypatch, {"EURUSD=X": RuntimeError("boom")})
    for args in (("EURUSD=X", "2026-09-25 06:00Z"), ("EURUSD=X", "not a date"),
                 ("EURUSD=X", "2026-09-25 06:00Z", "7x"), ("EURUSD=X", "2026-09-26 00:00Z")):
        out = F.DataFetcher().fetch_bars_since(*args)
        assert out.empty and list(out.columns) == F.BAR_COLUMNS


def test_primary_only_by_default_proxy_when_allowed(monkeypatch):
    gld = raw_hourly().assign(open=300.0, high=301.0, low=299.0, close=300.5, volume=5)
    calls = patch_fetch(monkeypatch, {"GC=F": pd.DataFrame(), "GLD": gld})
    f = F.DataFetcher()
    assert f.fetch_bars_since("GC=F", "2026-09-25 06:00Z").empty
    assert all(c[0] == "GC=F" for c in calls)                    # never the ETF
    out = f.fetch_bars_since("GC=F", "2026-09-25 06:00Z", allow_proxy=True)
    assert not out.empty and calls[-1][0] == "GLD"


def test_proxy_used_directly_when_the_daily_came_from_it(monkeypatch):
    gld = raw_hourly().assign(volume=5)
    calls = patch_fetch(monkeypatch, {"GC=F": raw_hourly(), "GLD": gld})
    f = F.DataFetcher()
    f._proxy_served[("GC=F", "1d")] = "GLD"
    f.fetch_bars_since("GC=F", "2026-09-25 06:00Z", allow_proxy=True)
    assert [c[0] for c in calls] == ["GLD"]


def test_read_mode_without_pin_is_empty_and_offline(monkeypatch, tmp_path):
    calls = patch_fetch(monkeypatch, {"EURUSD=X": raw_hourly()})
    f = F.DataFetcher(ohlcv_snapshot_mode="read", ohlcv_snapshot_dir=str(tmp_path))
    assert f.fetch_bars_since("EURUSD=X", "2026-09-25 06:00Z").empty
    assert calls == []


def test_write_then_read_round_trip(monkeypatch, tmp_path):
    patch_fetch(monkeypatch, {"EURUSD=X": raw_hourly()})
    w = F.DataFetcher(ohlcv_snapshot_mode="write", ohlcv_snapshot_dir=str(tmp_path))
    a = w.fetch_bars_since("EURUSD=X", "2026-09-25 06:00Z")
    calls = patch_fetch(monkeypatch, {})
    r = F.DataFetcher(ohlcv_snapshot_mode="read", ohlcv_snapshot_dir=str(tmp_path))
    b = r.fetch_bars_since("EURUSD=X", "2026-09-25 06:00Z")
    assert calls == []
    pd.testing.assert_frame_equal(a, b, check_dtype=False)
    assert list(tmp_path.glob("*bars-utc*"))
