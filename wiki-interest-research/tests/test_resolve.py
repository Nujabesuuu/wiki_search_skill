import pytest

from wiki_interest.cache import Cache
from wiki_interest.langs import LanguageError, normalize_lang, parse_langs
from wiki_interest.net import NotFound
from wiki_interest.resolve import ResolveError, Resolver

ENTITIES = {
    "Q1666254": {"labels": {"en": {"value": "intermittent fasting"}},
                 "descriptions": {"en": {"value": "diet cycling between fasting and eating"}},
                 "sitelinks": {"enwiki": {"title": "Intermittent fasting"}, "cswiki": {"title": "Přerušovaný půst"},
                               "ukwiki": {"title": "Інтервальне голодування"}}},
    "Q999": {"labels": {"en": {"value": "Fasting (disambiguation)"}},
             "descriptions": {"en": {"value": "Wikimedia disambiguation page"}},
             "sitelinks": {"enwiki": {"title": "Fasting (disambiguation)"}}},
    "Q16745106": {"labels": {"en": {"value": "English as a Second Language"}},
                  "descriptions": {"en": {"value": "a TV show segment"}},
                  "sitelinks": {"enwiki": {"title": "ESL (Community)"}}},
    "Q130192": {"labels": {"en": {"value": "English as a second or foreign language"}},
                "descriptions": {"en": {"value": "use of English by non-native speakers"}},
                "sitelinks": {"dewiki": {"title": "Englisch als Zweitsprache"}, "enwiki": {"title": "ESL"}}},
    "Q308": {"labels": {"en": {"value": "Mercury"}}, "descriptions": {"en": {"value": "planet"}},
             "sitelinks": {f"{l}wiki": {"title": "Merkur"} for l in ["de", "fr", "pl", "cs", "uk", "es", "it"]}},
    "Q925": {"labels": {"en": {"value": "mercury"}}, "descriptions": {"en": {"value": "chemical element"}},
             "sitelinks": {f"{l}wiki": {"title": "Quecksilber"} for l in ["de", "fr", "pl", "cs", "uk", "es"]}},
    "Q1860": {"labels": {"en": {"value": "English"}}, "descriptions": {"en": {"value": "West Germanic language"}},
              "sitelinks": {"plwiki": {"title": "Język angielski"}}},
    "Q1063556": {"labels": {"en": {"value": "English as a second or foreign language"}},
                 "descriptions": {"en": {"value": "use of English by non-native speakers"}},
                 "sitelinks": {"plwiki": {"title": "Angielski jako język obcy"}}},
}


class FakeClient:
    def __init__(self):
        self.calls = []

    def get_json(self, url, params=None):
        p = params or {}
        self.calls.append((url, p))
        action = p.get("action")
        if action == "wbsearchentities":
            if p["search"] == "intermittent fasting":
                return {"search": [{"id": "Q999", "label": "Fasting"}, {"id": "Q1666254", "label": "intermittent fasting"}]}
            if p["search"] == "English as a second language":
                return {"search": [{"id": "Q16745106", "label": "English as a Second Language"},
                                   {"id": "Q130192", "label": "English as a second or foreign language"}]}
            if p["search"] == "mercury":
                return {"search": [{"id": "Q925", "label": "mercury"}, {"id": "Q308", "label": "Mercury"}]}
            return {"search": []}
        if action == "wbgetentities":
            ids = p["ids"].split("|")
            if p.get("props") == "labels":
                return {"entities": {i: {"labels": {"pl": {"value": "post przerywany"}}} for i in ids}}
            return {"entities": {i: ENTITIES.get(i, {"missing": ""}) for i in ids}}
        if action == "query" and p.get("list") == "search":
            return {"query": {"search": [{"title": "Głodówka"}, {"title": "Dieta"}]}}
        if action == "query":
            title = p["titles"]
            if title == "Nonexistent":
                return {"query": {"pages": [{"title": title, "missing": True}]}}
            reds = [{"title": "IF diet"}, {"title": "5:2 diet"}] if "fasting" in title.lower() else []
            return {"query": {"pages": [{"title": title, "redirects": reds}]}}
        raise NotFound(url)


@pytest.fixture
def resolver(tmp_path):
    return Resolver(FakeClient(), Cache(tmp_path / "c.sqlite"))


def test_skips_disambiguation_and_maps_sitelinks(resolver):
    t = resolver.resolve_topic("intermittent fasting", ["cs", "uk", "en"])
    assert t.items[0]["qid"] == "Q1666254"
    assert t.articles["cs"][0].title == "Přerušovaný půst"
    en = t.articles["en"][0]
    assert en.redirects == ["IF diet", "5:2 diet"] and en.redirects_total == 2


def test_missing_language_is_reported_with_suggestions(resolver):
    t = resolver.resolve_topic("intermittent fasting", ["pl", "cs"])
    assert "pl" not in t.articles
    assert t.missing["pl"]["suggestions"] == ["Głodówka", "Dieta"]
    assert "--article 'pl:<Title>'" in t.missing["pl"]["hint"]


def test_manual_article_fills_missing_language(resolver):
    t = resolver.resolve_topic("intermittent fasting", ["pl"], manual={"pl": ["Głodówka"]})
    assert t.articles["pl"][0].title == "Głodówka" and t.articles["pl"][0].source == "manual"
    assert not t.missing


def test_basket_topic_with_qids(resolver):
    t = resolver.resolve_topic("English learning=Q1860,Q1063556", ["pl"])
    assert t.label == "English learning"
    assert [a.title for a in t.articles["pl"]] == ["Język angielski", "Angielski jako język obcy"]


def test_qid_topic_uses_wikidata_label(resolver):
    assert resolver.resolve_topic("Q1666254", ["cs"]).label == "intermittent fasting"


def test_unknown_topic_raises_actionable_error(resolver):
    with pytest.raises(ResolveError, match="QID"):
        resolver.resolve_topic("zzqqxx", ["en"])


def test_results_are_cached(resolver):
    resolver.resolve_topic("intermittent fasting", ["cs"])
    n = len(resolver.client.calls)
    resolver.resolve_topic("intermittent fasting", ["cs"])
    assert len(resolver.client.calls) == n


@pytest.mark.parametrize("raw,code", [("Polish", "pl"), ("польська", "pl"), ("CS", "cs"),
                                      ("uk.wikipedia", "uk"), ("zh-yue", "zh-yue"), ("čeština", "cs")])
def test_normalize_lang(raw, code):
    assert normalize_lang(raw) == code


def test_parse_langs_dedupes_and_rejects_garbage():
    assert parse_langs("pl, cs Polish") == ["pl", "cs"]
    with pytest.raises(LanguageError):
        parse_langs("Klingon language")


def test_prefers_item_with_articles_in_requested_langs_over_better_search_rank(resolver):
    t = resolver.resolve_topic("English as a second language", ["de"])
    assert t.items[0]["qid"] == "Q130192"
    assert not t.ambiguous


def test_equally_good_concepts_are_flagged_ambiguous(resolver):
    t = resolver.resolve_topic("mercury", ["de", "fr"])
    assert t.ambiguous
    assert {t.items[0]["qid"], t.alternatives[0]["qid"]} == {"Q308", "Q925"}
