"""Self-check for the agent's chat answer before it is sent (`wpv check`).

Evaluations showed that a small model translating the code-written draft still drifts in a few
predictable ways: it adds a number it computed itself, names a country instead of a language
edition, generalises across languages ("all markets") when they differ, drops required lines,
or forgets the report path. These are cheap to detect mechanically and language-independent
enough (numbers, paths, country names in several languages), so the agent fixes them in one step.
"""
from __future__ import annotations

import re
from pathlib import Path

from .verify import INTENSIFIERS, _always_ok, _matches, extract_numbers, known_values

# Country names (en / native / uk / de / fr / es / pl) per language edition, as word-bounded patterns
# with explicit case endings, so adjectives ("Українська", "Italian", "Polska Wikipedia") do not match.
_C = {
    "pl": r"Poland|Polsce|Польщ[аіуею]|Polen|Pologne|Polonia",
    "cs": r"Czech Republic|Czechia|Česko|Чехі[яїю]|Tschechien|République tchèque|Chequia",
    "uk": r"Ukraine|Україн(?:а|и|і|у|ою)|Ukrainie|Ukrajin[aěu]|Ucrania",
    "de": r"Germany|Deutschland|Німеччин(?:а|и|і|у|ою)|Niemcz(?:y|ech|ami)|Allemagne|Alemania",
    "fr": r"France|Франці[яїю]|Frankreich|Francj[ai]|Francia",
    "es": r"Spain|España|Іспані[яїю]|Spanien|Hiszpani[ai]|Espagne",
    "it": r"Italy|Italia|Італі[яїю]|Italien|Włoch(?:y|ach|ami)|Italie",
    "tr": r"Turkey|Türkiye|Туреччин(?:а|и|і|у|ою)|Türkei|Turcj[ai]|Turquie|Turquía",
    "pt": r"Portugal|Brazil|Brasil|Португалі[яїю]|Бразилі[яїю]",
    "ru": r"Russia|Росі[яїю]|Russland|Rosj[ai]",
    "nl": r"Netherlands|Nederland|Нідерланд(?:и|ів|ах)", "ro": r"Romania|România|Румуні[яїю]",
    "hu": r"Hungary|Magyarország|Угорщин(?:а|и|і|у|ою)", "sk": r"Slovakia|Slovensko|Словаччин(?:а|и|і|у|ою)",
    "sv": r"Sweden|Sverige|Швеці[яїю]", "ja": r"Japan|Японі[яїю]", "ko": r"Korea|Коре[яїю]",
}
COUNTRY_PATTERNS = {lang: re.compile(rf"\b(?:{p})\b") for lang, p in _C.items()}


def find_country(text: str, langs) -> str | None:
    for lang in langs:
        m = COUNTRY_PATTERNS.get(lang)
        hit = m.search(text) if m else None
        if hit:
            return hit.group(0)
    return None


_GENERAL = re.compile(r"\b(all (?:three|four|five|six|seven|eight|markets|languages|editions|wikis|of them)|"
                      r"every (?:market|language|edition)|across all|in all (?:markets|languages)|"
                      r"(?:усі|всі|усіх|всіх) (?:мов|ринк|розділ|видан)|(?:у|в) (?:всіх|усіх) (?:мов|ринк|розділ|видан))",
                      re.IGNORECASE)
_WIKI = re.compile(r"wikiped|вікіпед|википед", re.IGNORECASE)
_PATHS = re.compile(r"\S*[/\\]\S*|\S+\.(?:pdf|png|json|csv)\b")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def _protected(summary: dict) -> list[str]:
    out = [t for r in summary["results"] for t in r["articles"]] + [r["topic"] for r in summary["results"]]
    out += [s for m in summary["missing"] for s in m.get("suggestions", [])]
    for t in summary["topics"]:   # Wikidata descriptions ("atomic number 80") are not claims
        out += list(t.get("items", [])) + list(t.get("alternatives", []))
    return out


def _description_values(summary: dict) -> list[tuple[str, float]]:
    """Numbers inside Wikidata descriptions ("atomic number 80") may be quoted, also in translation."""
    texts = [x for t in summary["topics"] for x in list(t.get("items", [])) + list(t.get("alternatives", []))]
    return [("wikidata description", r[0]) for text in texts
            for n in extract_numbers(re.sub(r"\bQ\d+\b", " ", text), []) for r in n["readings"]]


def unmatched_numbers(answer: str, summary: dict) -> list[str]:
    values = known_values(summary) + _description_values(summary)
    cleaned = _PATHS.sub(" ", answer)
    return [n["raw"] for n in extract_numbers(cleaned, _protected(summary))
            if not any(_always_ok(r) for r in n["readings"])
            and not any(_matches(r, v) for r in n["readings"] for _, v in values)]


def _mentions(answer: str, value: float) -> bool:
    return any(abs(r[0] - abs(value)) <= 0.051 for n in extract_numbers(_PATHS.sub(" ", answer), []) for r in n["readings"])


def check_answer(answer: str, summary: dict, study_dir: Path | None = None) -> dict:
    issues: list[dict] = []

    for raw in unmatched_numbers(answer, summary):
        issues.append({"type": "unknown_number", "text": raw,
                       "hint": "This number is not in the data. Remove it or copy the exact value from 'draft'."})

    langs = {r["lang"] for r in summary["results"]} | {m["lang"] for m in summary["missing"]}
    for sentence in _sentences(answer):
        # a sentence that talks about Wikipedia itself ("German-language Wikipedia is read in Germany,
        # Austria and Switzerland") is the caveat, not the mistake
        hit = None if _WIKI.search(sentence) else find_country(sentence, langs)
        if hit:
            issues.append({"type": "country_name", "text": sentence[:160],
                           "hint": f"Mentions '{hit}'. The data describes readers of a language edition of "
                                   f"Wikipedia, not a country: rephrase (e.g. 'Polish-language Wikipedia "
                                   f"readers') unless the sentence says exactly that they are not the same."})

    directions = {r["direction"] for r in summary["results"] if r["confidence"] != "Insufficient"}
    if len(directions) > 1:
        for sentence in _sentences(answer):
            if _GENERAL.search(sentence):
                issues.append({"type": "generalisation", "text": sentence[:160],
                               "hint": "The languages move in different directions; do not generalise. Use the "
                                       "'overall' sentence from 'draft'."})

    if not any(r.get("claim_strength") == "strong" or {"strong_growth", "strong_decline"} & set(r["allowed_claims"])
               for r in summary["results"]):
        hits = [w for w in INTENSIFIERS if w in answer.lower()]
        if hits:
            issues.append({"type": "overstatement", "text": ", ".join(hits),
                           "hint": "No series has strong evidence; use the hedged wording from 'draft'."})

    # required lines: every series' headline change, the ranking weights, the report path
    for r in summary["results"]:
        g = r["metrics"]["growth_yoy_pct"]
        if r["confidence"] != "Insufficient" and g is not None and not _mentions(answer, g):
            issues.append({"type": "dropped_line", "text": f"{r['topic']}@{r['lang']}",
                           "hint": f"The share change {g:+.1f}% for {r['lang']} is missing; keep every language line "
                                   f"from 'draft'."})
    if sum(1 for x in summary["ranking"] if x.get("rank")) >= 2:
        top_weight = max(summary["ranking_weights"].values())
        if not _mentions(answer, round(top_weight * 100)):
            issues.append({"type": "dropped_line", "text": "ranking weights",
                           "hint": "State the ranking weights (the 'Ranking by the stated criteria' line in 'draft')."})
    reports = sorted(study_dir.glob("report-*.pdf")) if study_dir else []
    if reports and "report-" not in answer:
        issues.append({"type": "missing_report_path", "text": "",
                       "hint": f"Add the PDF path: {reports[-1]}"})

    return {"status": "ok" if not issues else "issues_found", "issues": issues,
            "hint": "Fix every issue in your answer file and run the check again." if issues
            else "The answer passed the checks. Send it."}
