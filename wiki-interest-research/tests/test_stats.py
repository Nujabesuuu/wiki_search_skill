import math
from datetime import date, timedelta

import numpy as np
import pytest

from wiki_interest import stats


def _days(start: date, n: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


# ---------- monthly aggregation ----------

def test_to_monthly_sums_and_treats_missing_days_as_zero():
    daily = {date(2024, 1, 1): 10, date(2024, 1, 31): 5, date(2024, 2, 15): 7}
    months, values = stats.to_monthly(daily, "2024-01", "2024-03")
    assert months == ["2024-01", "2024-02", "2024-03"]
    assert values.tolist() == [15, 7, 0]


def test_month_range_inclusive():
    assert stats.month_range("2023-11", "2024-02") == ["2023-11", "2023-12", "2024-01", "2024-02"]


# ---------- growth metrics ----------

def test_yoy_compares_last_12_to_previous_12():
    y = np.array([10.0] * 12 + [15.0] * 12)
    assert stats.yoy(y) == pytest.approx(0.5)


def test_yoy_needs_24_months():
    assert stats.yoy(np.ones(23)) is None


def test_yoy_zero_base_is_none():
    assert stats.yoy(np.array([0.0] * 12 + [5.0] * 12)) is None


def test_yoy_window_3_months():
    y = np.array([1.0] * 9 + [10, 10, 10] + [1.0] * 9 + [20, 20, 20])
    assert stats.yoy(y, window=3) == pytest.approx(1.0)


def test_cagr_on_exact_exponential_growth():
    # 10%/year growth, 36 months
    y = np.array([100 * 1.1 ** (i / 12) for i in range(36)])
    assert stats.cagr(y) == pytest.approx(0.10, abs=1e-3)


def test_theil_sen_recovers_slope_despite_outliers():
    x = np.arange(30, dtype=float)
    y = 2.0 * x + 5
    y[[3, 17, 25]] += 500  # outliers must not move the median slope
    assert stats.theil_sen_slope(y) == pytest.approx(2.0)


def test_log_trend_pct_per_year():
    y = np.array([100 * 1.2 ** (i / 12) for i in range(24)])
    assert stats.log_trend_pct_per_year(y) == pytest.approx(0.20, abs=1e-6)


def test_log_trend_handles_zeros():
    y = np.array([0.0, 0, 1, 2, 3, 4, 5, 6])
    assert math.isfinite(stats.log_trend_pct_per_year(y))


# ---------- significance ----------

def test_mann_kendall_detects_monotonic_trend():
    rng = np.random.default_rng(0)
    y = np.arange(36) + rng.normal(0, 2, 36)
    s, p = stats.mann_kendall(y)
    assert s > 0 and p < 0.001


def test_mann_kendall_no_trend_on_noise():
    rng = np.random.default_rng(1)
    _, p = stats.mann_kendall(rng.normal(0, 1, 36))
    assert p > 0.05


def test_mann_kendall_handles_all_ties():
    s, p = stats.mann_kendall(np.ones(20))
    assert s == 0 and p == 1.0


def test_seasonal_mk_ignores_pure_seasonality():
    season = np.tile(np.sin(np.linspace(0, 2 * np.pi, 12, endpoint=False)) * 50 + 100, 3)
    rng = np.random.default_rng(2)
    _, p = stats.seasonal_mann_kendall(season + rng.normal(0, 1, 36))
    assert p > 0.05


def test_seasonal_mk_detects_trend_on_top_of_seasonality():
    season = np.tile(np.sin(np.linspace(0, 2 * np.pi, 12, endpoint=False)) * 50 + 100, 3)
    y = season + np.arange(36) * 3
    s, p = stats.seasonal_mann_kendall(y)
    assert s > 0 and p < 0.01


def test_seasonal_mk_falls_back_when_short():
    y = np.arange(18, dtype=float)
    _, p_seasonal = stats.seasonal_mann_kendall(y)
    _, p_plain = stats.mann_kendall(y)
    assert p_seasonal == p_plain


# ---------- spikes ----------

def test_detect_spikes_finds_isolated_burst_and_merges_consecutive_days():
    days = _days(date(2024, 1, 1), 120)
    values = np.full(120, 100.0)
    values[50] = 5000
    values[51] = 3000
    values[90] = 900
    spikes = stats.detect_spikes(days, values)
    assert [s["start"] for s in spikes] == ["2024-02-20", "2024-03-31"]
    assert spikes[0]["days"] == 2
    assert spikes[0]["peak_views"] == 5000
    assert spikes[0]["peak_ratio"] == pytest.approx(50.0)


def test_detect_spikes_ignores_small_absolute_bumps():
    days = _days(date(2024, 1, 1), 60)
    values = np.full(60, 2.0)
    values[30] = 12  # 6x but only +10 views
    assert stats.detect_spikes(days, values) == []


def test_winsorize_caps_spikes_but_keeps_gradual_growth():
    n = 400
    values = np.linspace(100, 300, n)
    values[200] = 20000
    capped = stats.winsorize_spikes(values)
    assert capped[200] < 1000
    np.testing.assert_allclose(np.delete(capped, 200), np.delete(values, 200))


def test_top_days_share():
    values = np.array([1.0] * 95 + [100.0] * 5)
    assert stats.top_days_share(values, k=5) == pytest.approx(500 / 595)
