import copy

from wiki_interest.answer_check import check_answer, find_country
from test_verify import SUMMARY


def _summary():
    s = copy.deepcopy(SUMMARY)
    s["ranking"] = []
    s["topics"][0]["alternatives"] = ["Q925: mercury — chemical element with atomic number 80"]
    return s


GOOD = ("Interest in intermittent fasting: on Ukrainian-language Wikipedia (uk) it is clearly growing "
        "(+25.3% share of views); on Czech-language Wikipedia (cs) declining (moderate evidence), -47.7%. "
        "Polish-language Wikipedia has no dedicated article. Q925 has atomic number 80 per Wikidata.")


def test_clean_answer_passes():
    out = check_answer(GOOD, _summary())
    assert out["status"] == "ok", out["issues"]


def test_invented_number_and_country_and_generalisation_are_flagged():
    bad = GOOD + " Interest in Poland fell from about 6,672 views. All three markets are declining."
    types = {i["type"] for i in check_answer(bad, _summary())["issues"]}
    assert {"unknown_number", "country_name", "generalisation"} <= types


def test_dropped_series_line_is_flagged():
    out = check_answer("Czech-language Wikipedia: -47.7%.", _summary())
    assert any(i["type"] == "dropped_line" and "uk" in i["text"] for i in out["issues"])


def test_country_patterns_ignore_adjectives():
    assert find_country("Українська частка зросла; Italian-language Wikipedia; Polska Wikipedia", {"uk", "it", "pl"}) is None
    assert find_country("читачі не те саме, що населення України", {"uk"}) == "України"
    assert find_country("popular in Poland", {"pl"}) == "Poland"


def test_missing_report_path_flagged(tmp_path):
    (tmp_path / "report-en.pdf").write_bytes(b"%PDF")
    out = check_answer(GOOD, _summary(), tmp_path)
    assert any(i["type"] == "missing_report_path" for i in out["issues"])
    assert check_answer(GOOD + f" PDF: {tmp_path}/report-en.pdf", _summary(), tmp_path)["status"] == "ok"


def test_country_named_inside_a_wikipedia_caveat_is_fine():
    text = GOOD + " German-language Wikipedia is read in Germany, Austria and Switzerland."
    assert not [i for i in check_answer(text, _summary())["issues"] if i["type"] == "country_name"]
