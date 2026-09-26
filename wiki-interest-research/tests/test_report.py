import json
from datetime import timedelta

import numpy as np
import pytest
from pypdf import PdfReader

from wiki_interest.analyze import analyze_series, make_window
from wiki_interest.rank import parse_weights, rank
from wiki_interest.report import build_report
from wiki_interest.resolve import Article


@pytest.fixture
def study(tmp_path):
    w = make_window(24, end="2026-08")
    days = [w.start_day + timedelta(days=i) for i in range((w.end_day - w.start_day).days + 1)]
    rng = np.random.default_rng(0)
    results = []
    for lang, growth in (("uk", 0.3), ("pl", -0.1)):
        v = 300 * (1 + growth) ** (np.arange(len(days)) / 365) * (1 + rng.normal(0, 0.05, len(days)))
        total = {d: int(x) for d, x in zip(days, v)}
        bundle = {"total": total, "main": total, "main_desktop": {d: x // 3 for d, x in total.items()}}
        totals = {m: 10**8 for m in w.months}
        results.append(analyze_series("астрономія", lang, [Article(lang, "Астрономія")], bundle, totals, w))
    summary = {"status": "partial", "study": str(tmp_path), "generated": "2026-09-26", "window": w.to_dict(),
               "topics": [{"label": "астрономія", "items": ["Q333: astronomy — science"]}], "results": results,
               "missing": [{"topic": "астрономія", "lang": "cs", "suggestions": []}],
               "ranking": rank(results, parse_weights(None)), "ranking_weights": parse_weights(None),
               "notes": [], "note_codes": [{"code": "ambiguous", "params": {}}]}
    (tmp_path / "summary.json").write_text(json.dumps(summary, ensure_ascii=False), "utf-8")
    (tmp_path / "study.json").write_text(json.dumps({"colors": {"астрономія|uk": "#2a78d6",
                                                                "астрономія|pl": "#eb6834"}}), "utf-8")
    g_uk = results[0]["metrics"]["growth_yoy_pct"]
    narrative = {"title": "Інтерес до астрономії у Вікіпедії",
                 "headline": f"Інтерес до астрономії в українській Вікіпедії зростає: {g_uk}% за рік.",
                 "findings": [{"text": f"Українська частка зросла на {g_uk}%.", "about": ["uk"],
                               "claim": results[0]["allowed_claims"][0]},
                              {"text": "Чеської статті немає.", "about": ["cs"], "claim": "no_article"}],
                 "recommendation": "Перевірити попит на курс лендингом.", "next_steps": ["Запустити опитування"]}
    (tmp_path / "n.json").write_text(json.dumps(narrative, ensure_ascii=False), "utf-8")
    return tmp_path


def test_report_is_one_page_and_contains_cyrillic(study):
    out, code = build_report(study, study / "n.json", "uk")
    assert code == 0 and out["pages"] == 1, out
    reader = PdfReader(out["report"])
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text()
    assert "Головний висновок".upper() in text.upper()
    assert "статті немає" in text          # missing-language row in table
    assert "Метод і обмеження" in text      # code-generated caveats in report language
    assert "неоднозначна" in text           # localised note


def test_rejected_narrative_produces_no_pdf(study):
    bad = json.loads((study / "n.json").read_text("utf-8"))
    bad["headline"] = "Інтерес зріс на 77% за рік."
    (study / "bad.json").write_text(json.dumps(bad, ensure_ascii=False), "utf-8")
    out, code = build_report(study, study / "bad.json", "uk")
    assert code == 3 and out["status"] == "rejected"
    assert not (study / "report-uk.pdf").exists()


def test_check_only_and_unsupported_language(study):
    out, code = build_report(study, study / "n.json", "uk", check_only=True)
    assert code == 0 and out["verified"]
    out, code = build_report(study, study / "n.json", "it")
    assert code == 0 and "English labels" in out["warnings"][0]


def test_invalid_json_gives_actionable_error(study):
    (study / "broken.json").write_text("{'headline': 1,}", "utf-8")
    out, code = build_report(study, study / "broken.json", "en")
    assert code == 2 and "double quotes" in out["hint"]


def test_non_english_report_requires_title(study):
    n = json.loads((study / "n.json").read_text("utf-8"))
    del n["title"]
    (study / "nt.json").write_text(json.dumps(n, ensure_ascii=False), "utf-8")
    out, code = build_report(study, study / "nt.json", "uk")
    assert code == 3 and any(e["field"] == "title" for e in out["errors"])
