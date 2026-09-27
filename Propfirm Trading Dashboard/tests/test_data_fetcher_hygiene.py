"""BP_data_fetcher price-data hygiene -- synthetic frames only, no network.

Covers the 2026-09-27 live-account audit fixes owned by the data layer:
  D1  Yahoo daily FX Close repair            (BP_FX_CLOSE_REPAIR)
  D2  is_complete column on 1d / 1wk frames
  D3  weekend stub bars + non-finite rows     (BP_DROP_STUB_BARS)
  +   weekly/monthly FX High/Low/Close repair (BP_FX_WEEKLY_REPAIR)
Run:  python -m pytest "Propfirm Trading Dashboard/tests" -q
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import BP_data_fetcher as F  # noqa: E402

LON = "Europe/London"
NY = "America/New_York"


@pytest.fixture(autouse=True)
def _default_switches(monkeypatch):
    for k in ("BP_FX_CLOSE_REPAIR", "BP_DROP_STUB_BARS", "BP_FX_WEEKLY_REPAIR"):
        monkeypatch.delenv(k, raising=False)


def fx_daily(n=60, start="2026-06-01", tz=LON, defect=True, seed=0):
    """Weekday bars at local midnight. True close = next open (24h market);
    the Yahoo defect copies the open into the close."""
    idx = pd.bdate_range(start, periods=n, tz=tz)
    rng = np.random.default_rng(seed)
    opens = 1.10 + np.cumsum(rng.normal(0, 0.003, n))
    true_close = np.r_[opens[1:], opens[-1] + 0.001]
    high = np.maximum(opens, true_close) + 0.002
    low = np.minimum(opens, true_close) - 0.002
    close = opens + 1e-6 if defect else true_close
    df = pd.DataFrame({"timestamp": idx, "open": opens, "high": high, "low": low,
                       "close": close, "volume": 0})
    return df, true_close


def post(df, symbol="EURUSD=X", interval="1d", from_snapshot=True, hourly=None,
         now=None, daily=None):
    now = now if now is not None else pd.Timestamp("2030-01-01", tz="UTC")
    return F.DataFetcher._post_process_frame(df, symbol, interval, from_snapshot,
                                             hourly=hourly, now_utc=now, daily=daily)


def hourly_bars(start_local, closes, tz=LON, flat_last=False):
    idx = pd.date_range(start_local, periods=len(closes), freq="h", tz=tz)
    c = np.asarray(closes, dtype=float)
    o = np.r_[c[0], c[:-1]]
    df = pd.DataFrame({"timestamp": idx, "open": o, "high": np.maximum(o, c) + 1e-4,
                       "low": np.minimum(o, c) - 1e-4, "close": c, "volume": 0.0})
    if flat_last:
        df.loc[df.index[-1], ["open", "high", "low"]] = df["close"].iloc[-1]
    return df


# ---------------------------------------------------------------- D1 --------

def test_close_repair_uses_next_open():
    df, true_close = fx_daily()
    out = post(df)
    np.testing.assert_allclose(out["close"].iloc[:-1], true_close[:-1])
    body = (out["close"] - out["open"]).abs() / (out["high"] - out["low"])
    assert body.iloc[:-1].median() > 0.2        # was ~0 before the repair


def test_close_repair_last_bar_left_and_flagged_incomplete_in_snapshot():
    df, _ = fx_daily()
    out = post(df)
    assert out["close"].iloc[-1] == df["close"].iloc[-1]
    assert not out["is_complete"].iloc[-1]
    assert out["is_complete"].iloc[:-1].all()


def test_close_repair_clamps_into_bar_range():
    df, _ = fx_daily()
    df.loc[11, "open"] = df.loc[10, "high"] + 0.01     # gap above bar 10's high
    out = post(df)
    assert out["close"].iloc[10] == pytest.approx(df["high"].iloc[10])
    assert ((out["close"] <= out["high"] + 1e-12) & (out["close"] >= out["low"] - 1e-12)).all()


def test_close_repair_skips_series_without_the_defect():
    for sym in ("GC=F", "DX-Y.NYB", "BTC-USD"):
        df, _ = fx_daily()
        out = post(df, symbol=sym)
        np.testing.assert_allclose(out["close"], df["close"])


def test_close_repair_only_inside_the_defective_regime():
    good, _ = fx_daily(n=80, start="2010-03-01", defect=False, seed=1)
    bad, _ = fx_daily(n=80, start=str((good["timestamp"].iloc[-1] + pd.Timedelta(days=3)).date()),
                      defect=True, seed=2)
    df = pd.concat([good, bad], ignore_index=True)
    out = post(df)
    # far from the boundary: genuine closes untouched, defective ones repaired
    np.testing.assert_allclose(out["close"].iloc[:50], df["close"].iloc[:50])
    rep = out["close"].iloc[110:159].to_numpy()
    np.testing.assert_allclose(rep, df["open"].iloc[111:160].to_numpy())


def test_close_repair_kill_switch(monkeypatch):
    monkeypatch.setenv("BP_FX_CLOSE_REPAIR", "0")
    df, _ = fx_daily()
    out = post(df)
    np.testing.assert_allclose(out["close"], df["close"])
    assert out["is_complete"].all()             # snapshot, no forced last bar


def test_gap_bar_and_in_progress_bar_take_hourly_close():
    # Thu 24, Fri 25 (complete), Mon 28 Sep 2026 (in progress); BST = UTC+1
    idx = pd.DatetimeIndex(["2026-09-24", "2026-09-25", "2026-09-28"]).tz_localize(LON)
    df = pd.DataFrame({"timestamp": idx, "open": [1.10, 1.11, 1.13],
                       "high": [1.12, 1.125, 1.14], "low": [1.09, 1.105, 1.125],
                       "close": [1.10, 1.11, 1.13], "volume": 0})
    fri = hourly_bars("2026-09-25 00:00", np.linspace(1.11, 1.1205, 22), flat_last=True)
    mon = hourly_bars("2026-09-28 00:00", [1.131, 1.133, 1.142, 1.1415])  # 00:00-03:00 London
    now = pd.Timestamp("2026-09-28 02:30", tz="UTC")                     # 03:30 London
    hourly = F._clean_bars(pd.concat([fri, mon]), "60m", now_utc=now)
    out = post(df, from_snapshot=False, hourly=hourly, now=now)
    # Thu: next Open; Fri: last completed non-stub hour of Friday (not Monday's
    # gap-contaminated Open 1.13, not the flat 22:00 stub)
    assert out["close"].iloc[0] == pytest.approx(1.11)
    assert out["close"].iloc[1] == pytest.approx(fri["close"].iloc[-2])
    # Mon: latest COMPLETED hour (02:00-03:00 London closed at 1.142); the
    # 03:00 bar is still forming. High widened to include it.
    assert out["close"].iloc[2] == pytest.approx(1.142)
    assert out["high"].iloc[2] == pytest.approx(1.142)
    assert list(out["is_complete"]) == [True, True, False]


def test_last_complete_bar_takes_hourly_close_on_the_weekend():
    idx = pd.DatetimeIndex(["2026-09-24", "2026-09-25"]).tz_localize(LON)
    df = pd.DataFrame({"timestamp": idx, "open": [1.10, 1.11], "high": [1.12, 1.125],
                       "low": [1.09, 1.105], "close": [1.10, 1.11], "volume": 0})
    fri = hourly_bars("2026-09-25 00:00", np.linspace(1.11, 1.12, 22))
    now = pd.Timestamp("2026-09-26 12:00", tz="UTC")                     # Saturday
    out = post(df, from_snapshot=False, hourly=F._clean_bars(fri, "60m", now), now=now)
    assert out["close"].iloc[-1] == pytest.approx(1.12)
    assert out["is_complete"].iloc[-1]
    # no hourly data -> close left, bar flagged incomplete
    out2 = post(df, from_snapshot=False, hourly=None, now=now)
    assert out2["close"].iloc[-1] == pytest.approx(1.11)
    assert not out2["is_complete"].iloc[-1]


# ---------------------------------------------------------------- D2 --------

def test_is_complete_live_daily():
    idx = pd.DatetimeIndex(["2026-09-24", "2026-09-25"]).tz_localize(NY)
    df = pd.DataFrame({"timestamp": idx, "open": [1.0, 2.0], "high": [1.5, 2.5],
                       "low": [0.5, 1.5], "close": [1.2, 2.2], "volume": [10, 10]})
    during = pd.Timestamp("2026-09-25 20:00", tz="UTC")     # 16:00 NY on the 25th
    after = pd.Timestamp("2026-09-26 04:00", tz="UTC")      # 00:00 NY on the 26th
    assert list(post(df, "GC=F", from_snapshot=False, now=during)["is_complete"]) == [True, False]
    assert list(post(df, "GC=F", from_snapshot=False, now=after)["is_complete"]) == [True, True]


def test_is_complete_live_weekly_and_absent_elsewhere():
    idx = pd.DatetimeIndex(["2026-09-14", "2026-09-21"]).tz_localize(LON)
    df = pd.DataFrame({"timestamp": idx, "open": [1.0, 2.0], "high": [1.5, 2.5],
                       "low": [0.5, 1.5], "close": [1.2, 2.2], "volume": 0})
    sunday = pd.Timestamp("2026-09-27 12:00", tz="UTC")
    monday = pd.Timestamp("2026-09-27 23:00", tz="UTC")     # 00:00 London Monday
    assert list(post(df, "GC=F", "1wk", False, now=sunday)["is_complete"]) == [True, False]
    assert list(post(df, "GC=F", "1wk", False, now=monday)["is_complete"]) == [True, True]
    assert "is_complete" not in post(df, "GC=F", "1mo", False, now=sunday).columns
    assert "is_complete" not in post(df, "GC=F", "60m", False, now=sunday).columns


def test_is_complete_snapshot_is_history():
    idx = pd.date_range("2026-09-21", periods=5, freq="D")   # naive, like a pin
    df = pd.DataFrame({"timestamp": idx, "open": 1.0, "high": 1.5, "low": 0.5,
                       "close": 1.2, "volume": 5})
    out = post(df, "GC=F", from_snapshot=True, now=pd.Timestamp("2026-09-22", tz="UTC"))
    assert out["is_complete"].all()


# ---------------------------------------------------------------- D3 --------

def test_drop_weekend_stubs_daily():
    df, _ = fx_daily(n=20, start="2026-09-01")
    last = df.iloc[-1]
    sat = {"timestamp": pd.Timestamp("2026-09-26", tz=LON), "open": last.close,
           "high": last.close + 1e-5, "low": last.close, "close": last.close + 1e-5,
           "volume": 0}                                   # near-flat, like EURUSD's
    sun = {"timestamp": pd.Timestamp("2026-09-27", tz=LON), "open": 1.1, "high": 1.1,
           "low": 1.1, "close": 1.1, "volume": 0}        # exactly flat, like NZDUSD's
    df = pd.concat([df, pd.DataFrame([sat, sun])], ignore_index=True)
    out = post(df, "EURUSD=X", from_snapshot=True)
    assert (pd.DatetimeIndex(out["timestamp"]).dayofweek < 5).all()
    assert len(out) == 20
    assert list(out.index) == list(range(20))           # labels reset


def test_weekend_bars_with_volume_or_real_range_are_kept():
    idx = pd.date_range("2026-09-21", periods=7, freq="D", tz="UTC")   # Mon..Sun
    df = pd.DataFrame({"timestamp": idx, "open": 100.0, "high": 105.0, "low": 95.0,
                       "close": 101.0, "volume": 1e9})
    assert len(post(df, "BTC-USD")) == 7                # crypto trades weekends
    df["volume"] = 0
    assert len(post(df, "BTC-USD")) == 7                # full-range bars are not stubs


def test_drop_nonfinite_rows():
    df, _ = fx_daily(n=20, start="2026-09-01", defect=False)
    df.loc[5, "close"] = np.nan
    df.loc[9, "high"] = np.inf
    out = post(df, "GC=F")
    assert len(out) == 18
    assert np.isfinite(out[["open", "high", "low", "close"]].to_numpy()).all()


def test_stub_kill_switch_keeps_rows(monkeypatch):
    monkeypatch.setenv("BP_DROP_STUB_BARS", "0")
    df, _ = fx_daily(n=20, start="2026-09-01", defect=False)
    df.loc[5, "close"] = np.nan
    stub = {"timestamp": pd.Timestamp("2026-09-27", tz=LON), "open": 1.1, "high": 1.1,
            "low": 1.1, "close": 1.1, "volume": 0}
    df = pd.concat([df, pd.DataFrame([stub])], ignore_index=True)
    assert len(post(df, "GC=F")) == 21


def test_stub_dropped_before_close_repair():
    """The weekend stub's Open is stale; it must not become Friday's close."""
    idx = pd.DatetimeIndex(["2026-09-24", "2026-09-25", "2026-09-26"]).tz_localize(LON)
    df = pd.DataFrame({"timestamp": idx, "open": [1.10, 1.11, 1.1234],
                       "high": [1.12, 1.125, 1.1235], "low": [1.09, 1.105, 1.1234],
                       "close": [1.10, 1.11, 1.1235], "volume": 0})
    out = post(df, from_snapshot=True)
    assert len(out) == 2
    assert out["close"].iloc[-1] == pytest.approx(1.11)   # untouched, not 1.1234
    assert not out["is_complete"].iloc[-1]


def test_intraday_weekend_stub_uses_strict_rule():
    idx = pd.DatetimeIndex(["2026-09-27 17:00", "2026-09-27 18:00", "2026-09-28 09:00"]).tz_localize(NY)
    df = pd.DataFrame({"timestamp": idx, "open": [100.0, 100.1, 100.2],
                       "high": [100.0, 100.3, 100.4], "low": [100.0, 100.0, 100.1],
                       "close": [100.0, 100.2, 100.3], "volume": 0})
    out = post(df, "DX-Y.NYB", "60m")
    assert list(out["open"]) == [100.1, 100.2]       # flat Sunday pre-open bar dropped


# ------------------------------------------------- weekly / monthly FX -------

def weekly_from(daily, corrupt_weeks=()):
    ts = pd.DatetimeIndex(daily["timestamp"])
    wk = (ts - pd.to_timedelta(ts.dayofweek, unit="D")).normalize()
    g = daily.groupby(wk)
    w = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(),
                      "low": g["low"].min(), "close": g["close"].last(), "volume": 0})
    w.index.name = "timestamp"
    w = w.reset_index()
    for i in corrupt_weeks:      # Yahoo: Low and Close pushed to a bogus print
        bogus = w.loc[i, "low"] - 5 * (w.loc[i, "high"] - w.loc[i, "low"])
        w.loc[i, ["low", "close"]] = bogus
    return w


def test_weekly_fx_low_and_close_rebuilt_from_daily(monkeypatch):
    monkeypatch.setenv("BP_FX_WEEKLY_REPAIR", "1")   # opt-in since 2026-09-27
    daily, true_close = fx_daily(n=40, start="2026-06-01", defect=False)
    wk_true = weekly_from(daily)
    wk = weekly_from(daily, corrupt_weeks=(2, 5))
    out = post(wk, "GBPAUD=X", "1wk", daily=daily)
    np.testing.assert_allclose(out["low"], wk_true["low"])
    np.testing.assert_allclose(out["high"], wk_true["high"])
    np.testing.assert_allclose(out["close"], wk_true["close"])
    np.testing.assert_allclose(out["open"], wk["open"])


def test_weekly_valid_close_is_kept_and_partial_first_week_untouched(monkeypatch):
    monkeypatch.setenv("BP_FX_WEEKLY_REPAIR", "1")   # opt-in since 2026-09-27
    daily, _ = fx_daily(n=40, start="2026-06-01", defect=False)
    wk = weekly_from(daily, corrupt_weeks=(0, 3))
    wk.loc[4, "close"] = (wk.loc[4, "high"] + wk.loc[4, "low"]) / 2   # in range: keep
    sub = daily.iloc[2:].reset_index(drop=True)          # daily starts mid-week 0
    out = post(wk, "GBPAUD=X", "1wk", daily=sub)
    assert out["low"].iloc[0] == wk["low"].iloc[0]         # not covered -> untouched
    assert out["low"].iloc[3] > wk["low"].iloc[3]          # covered -> rebuilt
    assert out["close"].iloc[4] == wk["close"].iloc[4]


def test_weekly_repair_kill_switch_and_non_fx(monkeypatch):
    daily, _ = fx_daily(n=40, start="2026-06-01", defect=False)
    wk = weekly_from(daily, corrupt_weeks=(2,))
    assert post(wk, "GC=F", "1wk", daily=daily)["low"].iloc[2] == wk["low"].iloc[2]
    monkeypatch.setenv("BP_FX_WEEKLY_REPAIR", "0")
    assert post(wk, "GBPAUD=X", "1wk", daily=daily)["low"].iloc[2] == wk["low"].iloc[2]


# ------------------------------------------------- fetch_ohlcv wiring --------

def _pin_raw(tmp_path, symbol, df):
    key = F.DataFetcher._ohlcv_snap_key(symbol, "1d", "5y", False)
    path = tmp_path / f"{key}.csv"
    out = df.copy()
    out["timestamp"] = pd.DatetimeIndex(out["timestamp"]).tz_localize(None)
    out.to_csv(path, index=False)
    return path


def test_snapshot_read_repairs_on_load_and_leaves_file_untouched(tmp_path):
    df, true_close = fx_daily()
    path = _pin_raw(tmp_path, "EURUSD=X", df)
    before = path.read_bytes()
    f = F.DataFetcher(ohlcv_snapshot_mode="read", ohlcv_snapshot_dir=str(tmp_path))
    out = f.fetch_ohlcv("EURUSD=X", "1d", period="5y")
    np.testing.assert_allclose(out["close"].iloc[:-1], true_close[:-1])
    assert out["is_complete"].iloc[:-1].all() and not out["is_complete"].iloc[-1]
    assert path.read_bytes() == before


def test_write_mode_pins_raw_and_returns_repaired(tmp_path, monkeypatch):
    df, true_close = fx_daily()
    raw = df.copy()
    monkeypatch.setattr(F.DataFetcher, "_fetch_one", lambda self, *a, **k: raw.copy())
    f = F.DataFetcher(ohlcv_snapshot_mode="write", ohlcv_snapshot_dir=str(tmp_path))
    out = f.fetch_ohlcv("EURUSD=X", "1d", period="5y")
    np.testing.assert_allclose(out["close"].iloc[:-1], true_close[:-1])
    pinned = pd.read_csv(tmp_path / (F.DataFetcher._ohlcv_snap_key("EURUSD=X", "1d", "5y", False) + ".csv"))
    np.testing.assert_allclose(pinned["close"], raw["close"])
    assert "is_complete" not in pinned.columns


def test_live_mode_fetches_hourly_once_per_symbol(monkeypatch):
    now = pd.Timestamp("2026-09-26 12:00", tz="UTC")                   # Saturday
    monkeypatch.setattr(F, "_utcnow", lambda: now)
    daily, _ = fx_daily(n=40, start="2026-08-17")
    daily = daily[pd.DatetimeIndex(daily["timestamp"]) <= pd.Timestamp("2026-09-25", tz=LON)]
    fri_open = float(daily["open"].iloc[-1])                           # last bar: Fri 25 Sep
    fri = hourly_bars("2026-09-25 00:00", np.linspace(fri_open, fri_open + 0.001, 22))
    calls = []

    def fake(self, symbol, interval, period, start, end, retries):
        calls.append(interval)
        return (fri if interval == "60m" else daily).copy()

    monkeypatch.setattr(F.DataFetcher, "_fetch_one", fake)
    f = F.DataFetcher()
    a = f.fetch_ohlcv("EURUSD=X", "1d", period="5y")
    f.fetch_ohlcv("EURUSD=X", "1d", period="15y")
    assert calls.count("60m") == 1
    last = a.iloc[-1]
    assert last["close"] == pytest.approx(fri_open + 0.001)
    assert last["is_complete"]


def test_clean_ohlcv_frame_public_helper():
    df, true_close = fx_daily()
    out = F.clean_ohlcv_frame(df, "EURUSD=X", "1d")
    np.testing.assert_allclose(out["close"].iloc[:-1], true_close[:-1])


def test_interval_timedelta():
    assert F._interval_timedelta("60m") == pd.Timedelta(hours=1)
    assert F._interval_timedelta("1h") == pd.Timedelta(hours=1)
    assert F._interval_timedelta("1d") == pd.Timedelta(days=1)
    assert F._interval_timedelta("1wk") == pd.Timedelta(days=7)
    assert F._interval_timedelta("1mo") is None
