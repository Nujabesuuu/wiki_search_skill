import copy

import pytest

from wiki_interest.verify import extract_numbers, verify_narrative


def result(lang, growth, views, per_million, conf, allowed, direction):
    return {"topic": "intermittent fasting", "lang": lang, "articles": [f"Article {lang}", "5:2 diet"],
            "confidence": conf, "allowed_claims": allowed, "direction": direction, "redirects_included": 3,
            "spikes": [{"peak_views": 5080, "peak_ratio": 36.3}],
            "metrics": {"views_avg_month": views, "median_daily_views": 5.0, "views_per_million": per_million,
                        "growth_yoy_pct": growth, "growth_yoy_raw_pct": growth - 5, "growth_yoy_no_spikes_pct": growth,
                        "growth_recent_3m_pct": None, "trend_per_year_pct": growth, "trend_p_value": 0.0094,
                        "top5_days_share_pct": 9.6, "wiki_traffic_yoy_pct": -12.6}}


SUMMARY = {
    "window": {"months": 24, "analysis_months": 24},
    "topics": [{"label": "intermittent fasting", "items": ["Q1666254: intermittent fasting — diet"]}],
    "results": [result("cs", -47.7, 8178, 3.08, "Medium", ["decline", "possible_decline"], "down"),
                result("uk", 25.3, 2555, 12.4, "High", ["strong_growth", "growth", "possible_growth"], "up")],
    "missing": [{"topic": "intermittent fasting", "lang": "pl", "suggestions": ["Głodówka lecznicza"]}],
    "ranking_weights": {"growth": 0.4, "volume": 0.25, "share": 0.2, "confidence": 0.15},
}

GOOD = {
    "headline": "Інтерес в українській Вікіпедії зростає (+25,3 %), у чеській падає (−47.7%).",
    "findings": [
        {"text": "Czech: about 8,200 views a month, share down 47.7% year over year.", "about": ["cs"], "claim": "decline"},
        {"text": "Ukrainian share grew 25.3% (12.4 views per million) — 3.2x the Czech share.", "about": ["uk"],
         "claim": "strong_growth"},
        {"text": "Polish Wikipedia has no article on this topic (closest: Głodówka lecznicza).", "about": ["pl"],
         "claim": "no_article"},
    ],
    "recommendation": "Validate demand in Ukrainian first; 8.2 тис. переглядів у чеській — мала база. Ignore the 5:2 diet noise.",
    "next_steps": ["Run a landing-page test in uk for 2 weeks", "Re-check in 12 months"],
}


def test_good_narrative_passes():
    out = verify_narrative(GOOD, SUMMARY)
    assert out["ok"], out["errors"]


def test_invented_number_is_rejected_with_nearest_hint():
    bad = copy.deepcopy(GOOD)
    bad["headline"] = "Interest in Ukrainian grew 35% last year."
    out = verify_narrative(bad, SUMMARY)
    assert not out["ok"]
    err = out["errors"][0]
    assert err["field"] == "headline" and "35" in err["problem"]
    assert "growth_yoy_pct(uk)=25.3" in err["hint"]


def test_overclaim_on_weaker_series_is_rejected():
    bad = copy.deepcopy(GOOD)
    bad["findings"][0]["claim"] = "strong_decline"
    out = verify_narrative(bad, SUMMARY)
    assert any("not supported" in e["problem"] and "Allowed: decline" in e["hint"] for e in out["errors"])


def test_trend_claim_on_missing_article_is_rejected():
    bad = copy.deepcopy(GOOD)
    bad["findings"][2]["claim"] = "growth"
    assert not verify_narrative(bad, SUMMARY)["ok"]


def test_unknown_series_and_claim_rejected():
    bad = copy.deepcopy(GOOD)
    bad["findings"][0]["about"] = ["de"]
    bad["findings"][1]["claim"] = "booming"
    problems = " ".join(e["problem"] for e in verify_narrative(bad, SUMMARY)["errors"])
    assert "'de' is not in this study" in problems and "unknown claim 'booming'" in problems


def test_length_and_structure_limits():
    bad = copy.deepcopy(GOOD)
    bad["headline"] = "x" * 400
    bad["findings"] = bad["findings"] * 2
    fields = {e["field"] for e in verify_narrative(bad, SUMMARY)["errors"]}
    assert {"headline", "findings"} <= fields


def test_missing_required_fields():
    out = verify_narrative({"findings": []}, SUMMARY)
    fields = {e["field"] for e in out["errors"]}
    assert {"headline", "recommendation", "findings"} <= fields


def test_warns_when_missing_language_not_discussed():
    n = copy.deepcopy(GOOD)
    n["findings"] = n["findings"][:2]
    out = verify_narrative(n, SUMMARY)
    assert out["ok"] and "pl" in out["warnings"][0]


@pytest.mark.parametrize("text,value", [
    ("8 178 views", 8178), ("8,178", 8178), ("8.178", 8178), ("47,7 %", 47.7), ("−47.7%", 47.7),
    ("8.2k", 8200), ("8,2 тис.", 8200), ("1.2 млн", 1_200_000), ("3.2x", 3.2),
])
def test_number_formats(text, value):
    nums = extract_numbers(text, [])
    assert any(abs(r[0] - value) < 1e-6 for r in nums[0]["readings"]), nums


def test_protected_titles_dates_and_qids_are_ignored():
    text = "Article Q1666254 '5:2 diet' peaked on 2025-04-14 and in 04/25."
    assert extract_numbers(text, ["5:2 diet"]) == []
