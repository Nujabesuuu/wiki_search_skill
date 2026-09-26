import pytest

from wiki_interest.rank import WeightsError, parse_weights, rank


def row(lang, growth, views, per_million, conf="High"):
    return {"topic": "t", "lang": lang, "confidence": conf,
            "metrics": {"growth_yoy_no_spikes_pct": growth, "growth_yoy_pct": growth,
                        "views_avg_month": views, "views_per_million": per_million}}


RESULTS = [row("pl", 30, 2000, 5.0), row("cs", 5, 20000, 8.0), row("sk", -10, 500, 1.0, "Low"),
           row("uk", None, 3, 0.1, "Insufficient")]


def test_default_weights_prefer_momentum():
    ranked = rank(RESULTS, parse_weights(None))
    assert [r["lang"] for r in ranked] == ["pl", "cs", "sk", "uk"]
    assert ranked[0]["rank"] == 1 and ranked[0]["strongest_factor"] == "growth"
    assert ranked[-1]["rank"] is None and "insufficient" in ranked[-1]["note"]


def test_custom_weights_can_prefer_audience_size():
    ranked = rank(RESULTS, parse_weights("volume=1"))
    assert ranked[0]["lang"] == "cs"


def test_weights_normalised_and_validated():
    w = parse_weights("growth=2,volume=2")
    assert w == {"growth": 0.5, "volume": 0.5, "share": 0.0, "confidence": 0.0}
    with pytest.raises(WeightsError, match="Allowed"):
        parse_weights("price=1")
    with pytest.raises(WeightsError):
        parse_weights("growth=0")


def test_single_option_gets_rank_one():
    ranked = rank([row("pl", 10, 100, 1.0)], parse_weights(None))
    assert ranked[0]["rank"] == 1 and ranked[0]["score"] == 0
