from datetime import date, timedelta

import numpy as np
import pytest

from wiki_interest.analyze import analyze_series, last_complete_month, make_window
from wiki_interest.resolve import Article

WINDOW = make_window(24, end="2026-08")
DAYS = [WINDOW.start_day + timedelta(days=i) for i in range((WINDOW.end_day - WINDOW.start_day).days + 1)]
ART = [Article("cs", "Test", "Q1")]


def bundle(values, desktop_share=0.3, desktop_override=None):
    total = {d: int(v) for d, v in zip(DAYS, values) if v}
    desk = {d: int(v * desktop_share) for d, v in total.items()}
    desk.update(desktop_override or {})
    return {"total": total, "main": dict(total), "main_desktop": desk}


def totals(growth_per_year=0.0):
    return {m: int(1e8 * (1 + growth_per_year) ** (i / 12)) for i, m in enumerate(WINDOW.months)}


def noisy(level, growth_per_year=0.0, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(len(DAYS)) / 365
    return np.maximum(0, level * (1 + growth_per_year) ** t * (1 + rng.normal(0, 0.05, len(DAYS))))


def run(values, tot=None, **kw):
    return analyze_series("topic", "cs", ART, bundle(values, **kw), tot or totals(), WINDOW)


def test_window_extends_short_requests_to_24_months():
    w = make_window(12, end="2026-08")
    assert len(w.months) == 24 and len(w.chart_months) == 12
    assert w.months[-1] == "2026-08" and w.months[0] == "2024-09"
    assert any("minimum" in n for n in w.notes)


def test_window_clipped_at_data_start():
    w = make_window(200, end="2026-08")
    assert w.months[0] == "2015-07"
    assert w.notes


def test_last_complete_month_waits_for_data_publication():
    assert last_complete_month(date(2026, 9, 26)) == "2026-08"
    assert last_complete_month(date(2026, 9, 2)) == "2026-07"


def test_steady_growth_is_high_confidence_strong():
    r = run(noisy(200, 0.25))
    assert r["direction"] == "up"
    assert r["confidence"] == "High", r["checks"]
    assert r["claim_strength"] == "strong"
    assert r["metrics"]["growth_yoy_pct"] == pytest.approx(25, abs=3)
    assert "strong_growth" in r["allowed_claims"]


def test_growth_driven_by_one_viral_day_is_not_trusted():
    v = noisy(100, 0.0)
    v[-100] = 60000  # one viral day in the last 12 months
    r = run(v)
    assert r["metrics"]["growth_yoy_raw_pct"] > 20
    assert abs(r["metrics"]["growth_yoy_no_spikes_pct"]) < 5
    assert r["confidence"] == "Low"
    assert "has_spikes" in r["flags"]
    assert r["allowed_claims"] == ["possible_growth"]


def test_growth_explained_by_wiki_wide_traffic_is_neutralised_not_penalised():
    r = run(noisy(200, 0.20), tot=totals(0.20))
    assert r["metrics"]["growth_yoy_raw_pct"] > 15
    assert r["direction"] == "flat"
    assert "wiki_traffic_shift" in r["flags"]
    assert r["confidence"] == "High", r["checks"]


def test_decline_in_share_while_raw_views_flat():
    r = run(noisy(200, 0.0), tot=totals(0.30))
    assert r["direction"] == "down"


def test_tiny_article_is_insufficient():
    r = run(noisy(2, 0.5))
    assert r["confidence"] == "Insufficient"
    assert r["claim_strength"] == "none"
    assert r["allowed_claims"] == ["insufficient_data"]


def test_low_volume_downgrades_but_does_not_block():
    r = run(noisy(15, 0.4))
    assert r["confidence"] in ("Medium", "Low")
    assert any(c["name"] == "volume" and not c["ok"] for c in r["checks"])


def test_new_article_growth_is_not_trusted():
    v = noisy(300, 0.0)
    v[:200] = 0  # article created ~7 months into the window
    r = run(v)
    assert "article_created_recently" in r["flags"]
    assert r["confidence"] in ("Low", "Insufficient")


def test_desktop_only_spike_flagged_as_bot():
    v = noisy(300, 0.0)
    v[400] = 20000
    r = run(v, desktop_override={DAYS[400]: 19900})
    assert "possible_bot_traffic" in r["flags"]
    assert r["spikes"][0]["desktop_share_pct"] >= 99


def test_flat_noise_is_stable():
    r = run(noisy(500, 0.0, seed=3))
    assert r["direction"] == "flat"
    assert r["allowed_claims"] == ["stable"]


def test_series_exported_for_charts():
    r = run(noisy(200, 0.1))
    assert len(r["_months"]) == 24 == len(r["_monthly_per_million"])
