import copy

from wiki_interest.draft import build_draft
from wiki_interest.verify import verify_narrative
from test_verify import SUMMARY


def _summary():
    s = copy.deepcopy(SUMMARY)
    for r in s["results"]:
        r["checks"] = [{"name": "volume", "ok": r["lang"] == "uk", "detail": ""},
                       {"name": "history", "ok": True, "detail": ""}]
        r["spikes"] = [{"peak_date": "2024-09-02", "peak_ratio": 3.6, "peak_views": 400, "recurring_yearly": True}]
    s["ranking"] = [{"topic": "intermittent fasting", "lang": "uk", "rank": 1},
                    {"topic": "intermittent fasting", "lang": "cs", "rank": 2}]
    return s


def test_draft_uses_language_editions_and_hedged_wording():
    d = build_draft(_summary())
    text = " ".join(" ".join(x["lines"]) for x in d["per_series"])
    assert "Czech-language Wikipedia (cs): interest is declining (moderate evidence)" in text
    assert "Ukrainian-language Wikipedia (uk): interest is clearly growing" in text
    assert "share of all Czech-language Wikipedia views changed -47.7% year over year" in text
    assert "seasonal, recurs every year" in text and "Do not guess" in text
    assert "small (median 5 views per day)" in text
    assert "no dedicated article" in d["missing"][0]
    assert any("not a country" in x for x in d["limits"])
    assert d["ranking"][0].startswith("Ranking by the stated criteria (momentum 40%")


def test_narrative_draft_passes_verification_once_recommendation_is_filled():
    s = _summary()
    d = build_draft(s)
    n = copy.deepcopy(d["narrative_draft"])
    out = verify_narrative(n, s)
    assert [e["field"] for e in out["errors"]] == ["recommendation"]   # the agent must write it
    n["recommendation"] = "Validate demand among Ukrainian-speaking readers first."
    assert verify_narrative(n, s)["ok"], verify_narrative(n, s)["errors"]
