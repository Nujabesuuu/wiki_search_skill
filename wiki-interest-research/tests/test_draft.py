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
    assert "recurs around the same date every year" in text
    assert "small (median 5 views per day)" in text
    assert "no dedicated article" in d["missing"][0]
    assert any("not countries" in x for x in d["limits"])
    assert d["ranking"][0].startswith("Ranking by the stated criteria (momentum 40%")


def test_narrative_draft_passes_verification_once_recommendation_is_filled():
    s = _summary()
    d = build_draft(s)
    n = copy.deepcopy(d["narrative_draft"])
    out = verify_narrative(n, s)
    assert out["ok"], out["errors"]    # the code-written draft always passes its own verifier


def test_direct_answer_and_precomputed_comparisons():
    d = build_draft(_summary())
    assert d["direct_answer"].startswith("Interest in intermittent fasting: on Ukrainian-language Wikipedia (uk) it is clearly growing")
    assert "no dedicated article, so there is no data" in d["direct_answer"]
    # 8178 / 2555 = 3.20x, +220%
    assert d["comparisons"][0].startswith("Largest audience: Czech-language Wikipedia (cs)")
    assert "Czech-language Wikipedia (cs) has 3.20x the monthly views of Ukrainian-language Wikipedia (uk) (+220%)" in d["comparisons"][1]


def test_answer_markdown_is_complete_with_placeholders():
    d = build_draft(_summary())
    md = d["answer_markdown"]
    assert md.startswith("**Interest in intermittent fasting")
    assert "**Recommendation:** Of the compared options, start with" in md and "PDF_PATH" in md and "not countries" in md
    assert "Do not" not in md    # no agent instructions leak into the user-facing text


def test_overall_sentence_only_generalises_when_all_agree():
    from wiki_interest.draft import overall_sentence
    s = _summary()
    assert "no single overall trend" in overall_sentence(s["results"])
    for r in s["results"]:
        r["direction"] = "down"
    assert overall_sentence(s["results"]).startswith("Across all compared languages")


def test_ambiguous_topic_named_first():
    s = _summary()
    s["topics"][0].update({"ambiguous": True, "alternatives": ["Q925: mercury — chemical element"]})
    d = build_draft(s)
    assert d["direct_answer"].startswith("Note: 'intermittent fasting' has several meanings; this analyses")
    assert any("Analyse another meaning" in x for x in d["answer_markdown"].split("\n"))
