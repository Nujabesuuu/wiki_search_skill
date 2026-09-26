"""Pure statistics used by the analysis layer. No I/O, no network.

Conventions: monthly series are numpy float arrays ordered oldest -> newest.
Growth values are fractions (0.25 == +25 %); callers convert to percent for display.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Mapping, Sequence

import numpy as np

# A day is a spike when it is at least SPIKE_RATIO x the local (29-day median) baseline
# AND at least SPIKE_MIN_EXTRA views above it (so tiny articles do not flag noise).
SPIKE_RATIO = 3.0
SPIKE_MIN_EXTRA = 20.0
BASELINE_WINDOW = 29


# ---------------------------------------------------------------- months

def month_range(start: str, end: str) -> list[str]:
    """Inclusive list of 'YYYY-MM' strings."""
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def month_bounds(month: str) -> tuple[date, date]:
    y, m = map(int, month.split("-"))
    first = date(y, m, 1)
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return first, nxt - timedelta(days=1)


def to_monthly(daily: Mapping[date, float], start_month: str, end_month: str) -> tuple[list[str], np.ndarray]:
    """Sum daily views into calendar months. Days absent from `daily` count as 0
    (the pageviews API omits days without views)."""
    months = month_range(start_month, end_month)
    index = {m: i for i, m in enumerate(months)}
    values = np.zeros(len(months))
    for d, v in daily.items():
        i = index.get(f"{d.year:04d}-{d.month:02d}")
        if i is not None:
            values[i] += v
    return months, values


# ---------------------------------------------------------------- growth

def yoy(y: np.ndarray, window: int = 12) -> float | None:
    """Growth of the last `window` months vs the same months one year earlier."""
    y = np.asarray(y, dtype=float)
    if len(y) < 12 + window:
        return None
    recent = y[-window:].sum()
    base = y[-12 - window:-12].sum()
    if base <= 0:
        return None
    return float(recent / base - 1)


def cagr(y: np.ndarray) -> float | None:
    """Annualised growth between the mean of the first 12 and the last 12 months."""
    y = np.asarray(y, dtype=float)
    if len(y) < 24:
        return None
    first, last = y[:12].mean(), y[-12:].mean()
    if first <= 0 or last <= 0:
        return None
    years = (len(y) - 12) / 12
    return float((last / first) ** (1 / years) - 1)


def theil_sen_slope(y: np.ndarray) -> float:
    """Median of pairwise slopes; robust to outliers (x = 0..n-1)."""
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 2:
        return 0.0
    i, j = np.triu_indices(n, k=1)
    return float(np.median((y[j] - y[i]) / (j - i)))


def log_trend_pct_per_year(y: np.ndarray) -> float:
    """Robust exponential trend: Theil-Sen slope on log monthly values, as annual growth fraction."""
    y = np.asarray(y, dtype=float)
    offset = max(1.0, 0.01 * float(np.mean(y))) if np.any(y <= 0) else 0.0
    slope = theil_sen_slope(np.log(y + offset))
    return float(math.exp(12 * slope) - 1)


# ---------------------------------------------------------------- significance

def _mk_s_var(y: np.ndarray) -> tuple[float, float]:
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 2:
        return 0.0, 0.0
    i, j = np.triu_indices(n, k=1)
    s = float(np.sign(y[j] - y[i]).sum())
    _, counts = np.unique(y, return_counts=True)
    ties = sum(t * (t - 1) * (2 * t + 5) for t in counts if t > 1)
    var = (n * (n - 1) * (2 * n + 5) - ties) / 18.0
    return s, var


def _p_from_s_var(s: float, var: float) -> float:
    if var <= 0 or s == 0:
        return 1.0
    z = (s - 1) / math.sqrt(var) if s > 0 else (s + 1) / math.sqrt(var)
    return float(math.erfc(abs(z) / math.sqrt(2)))


def mann_kendall(y: np.ndarray) -> tuple[float, float]:
    """Mann-Kendall monotonic trend test. Returns (S, two-sided p-value)."""
    s, var = _mk_s_var(y)
    return s, _p_from_s_var(s, var)


def seasonal_mann_kendall(y: np.ndarray, period: int = 12) -> tuple[float, float]:
    """Seasonal Mann-Kendall (Hirsch 1982): compares each calendar month only with itself,
    so regular yearly seasonality is not mistaken for a trend. Needs >= 2 full periods,
    otherwise falls back to the plain test."""
    y = np.asarray(y, dtype=float)
    if len(y) < 2 * period:
        return mann_kendall(y)
    s_total, var_total = 0.0, 0.0
    for k in range(period):
        s, var = _mk_s_var(y[k::period])
        s_total += s
        var_total += var
    return s_total, _p_from_s_var(s_total, var_total)


# ---------------------------------------------------------------- spikes

def rolling_median(values: np.ndarray, window: int = BASELINE_WINDOW) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    n, half = len(values), window // 2
    if n == 0:
        return values.copy()
    padded = np.pad(values, half, mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, window)[:n]
    return np.median(windows, axis=1)


def _spike_mask(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    values = np.asarray(values, dtype=float)
    base = rolling_median(values)
    mask = (values >= SPIKE_RATIO * np.maximum(base, 1.0)) & (values - base >= SPIKE_MIN_EXTRA)
    return mask, base


def detect_spikes(days: Sequence[date], values: np.ndarray, limit: int = 5) -> list[dict]:
    """Bursts of attention (news, viral links, bots). Consecutive spike days are merged.
    Returns the `limit` largest events by extra views, ordered by date."""
    values = np.asarray(values, dtype=float)
    mask, base = _spike_mask(values)
    events, i = [], 0
    while i < len(values):
        if not mask[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(values) and mask[j + 1]:
            j += 1
        seg = slice(i, j + 1)
        peak = i + int(np.argmax(values[seg]))
        events.append({
            "start": days[i].isoformat(),
            "days": j - i + 1,
            "peak_date": days[peak].isoformat(),
            "peak_views": int(values[peak]),
            "peak_ratio": round(float(values[peak] / max(base[peak], 1.0)), 1),
            "extra_views": int((values[seg] - base[seg]).sum()),
        })
        i = j + 1
    events = sorted(events, key=lambda e: -e["extra_views"])[:limit]
    return sorted(events, key=lambda e: e["start"])


def winsorize_spikes(values: np.ndarray) -> np.ndarray:
    """Replace spike days by their local baseline: 'what if the bursts never happened'."""
    values = np.asarray(values, dtype=float)
    mask, base = _spike_mask(values)
    out = values.copy()
    out[mask] = base[mask]
    return out


def top_days_share(values: np.ndarray, k: int = 5) -> float:
    values = np.asarray(values, dtype=float)
    total = values.sum()
    if total <= 0:
        return 0.0
    return float(np.sort(values)[-k:].sum() / total)


def mark_recurring(spikes: list[dict], days: Sequence[date], values: np.ndarray, window: int = 7,
                   ratio: float = 2.0) -> list[dict]:
    """Flag spikes that repeat about a year earlier/later (+-`window` days), e.g. the start of
    the school year. Those are seasonality, not news, and the agent must not call them events."""
    values = np.asarray(values, dtype=float)
    base = np.maximum(rolling_median(values), 1.0)
    index = {d: i for i, d in enumerate(days)}
    for sp in spikes:
        peak = date.fromisoformat(sp["peak_date"])
        recurring = False
        for years in (-2, -1, 1, 2):
            center = peak + timedelta(days=365 * years)
            idx = [index[center + timedelta(days=k)] for k in range(-window, window + 1)
                   if center + timedelta(days=k) in index]
            if idx and max(values[i] / base[i] for i in idx) >= ratio:
                recurring = True
                break
        sp["recurring_yearly"] = recurring
    return spikes
