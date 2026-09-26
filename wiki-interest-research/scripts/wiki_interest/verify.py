"""Guardrail between the agent's prose and the data.

The agent writes the narrative (any language); this module checks it before a report is
rendered:
  1. every number in the text must match a computed value (rounding, locale formats,
     k/thousand suffixes and pairwise ratios are understood);
  2. every finding carries a machine-readable `claim` that must be allowed by the confidence
     of the series it is about (no "strong growth" on Low-confidence data);
  3. lengths are bounded so the report fits one page.
Errors are returned with hints (nearest real values) so a small model can fix them in one pass.
"""
from __future__ import annotations

import itertools
import re

NEUTRAL_CLAIMS = {"context", "comparison"}
# Intensifiers that overstate moderate/weak evidence (stems; en, uk, pl, cs, de, es, fr).
INTENSIFIERS = ["clearly", "sharply", "dramatic", "significantly", "genuinely", "real trend", "not random",
                "not noise", "consistently", "steep", "massive", "huge", "booming", "collaps", "plummet", "soar",
                "виразн", "різк", "значн", "суттєв", "не випадков", "стрімк", "драматичн", "обвал", "беззаперечн",
                "wyraźn", "gwałtown", "znacząc", "dramatycz", "výrazn", "prudk", "značn", "dramatick",
                "deutlich", "drastisch", "dramatisch", "massiv", "claramente", "drástic", "dramátic", "enorme",
                "nettement", "fortement", "drastique", "spectaculaire"]
ALL_CLAIMS = {"strong_growth", "growth", "possible_growth", "stable", "possible_decline", "decline",
              "strong_decline", "insufficient_data", "no_article"} | NEUTRAL_CLAIMS
LIMITS = {"title": 90, "headline": 240, "finding": 300, "recommendation": 420, "next_step": 170}
MAX_FINDINGS, MAX_NEXT = 5, 4

_SUFFIX = {"k": 1e3, "тис": 1e3, "тыс": 1e3, "tys": 1e3, "tis": 1e3, "mil": 1e3, "tsd": 1e3,
           "m": 1e6, "mln": 1e6, "млн": 1e6, "mio": 1e6, "mn": 1e6, "x": 1.0, "×": 1.0, "раз": 1.0}
_NUM_RE = re.compile(
    r"(?<![\w.,])([-+−–]?)(\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)*)"
    r"(?:\s?(k|тис|тыс|tys|tis|mil|tsd|mln|млн|mio|mn|m|x|×|рази?)\.?(?![\w]))?(?![\w])", re.IGNORECASE)
_PRIMARY = {"growth_yoy_pct", "growth_yoy_raw_pct", "growth_yoy_no_spikes_pct", "trend_per_year_pct",
            "views_avg_month", "views_per_million", "growth_recent_3m_pct", "median_daily_views"}
_ISO_DATE = re.compile(r"\b(20\d\d|19\d\d)-(0[1-9]|1[0-2])(?:-(\d\d))?\b")
_SLASH_MONTH = re.compile(r"\b(0?[1-9]|1[0-2])/(\d\d|20\d\d)\b")
_DMY = re.compile(r"\b\d{1,2}[./]\d{1,2}[./](?:19|20)?\d\d\b")
_WORDY_DATE = re.compile(r"\b\d{1,2}\.?\s+[^\W\d_]{3,}\.?,?\s+(?:19|20)\d\d\b|"
                         r"\b[^\W\d_]{3,}\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+(?:19|20)\d\d\b")


# ---------------------------------------------------------------- numbers

def _interpretations(token: str) -> list[tuple[float, int]]:
    """All plausible (value, decimals) readings of a locale-formatted number."""
    t = re.sub(r"[   ]", "", token)
    out = []
    if "." in t and "," in t:
        dec = "." if t.rfind(".") > t.rfind(",") else ","
        grp = "," if dec == "." else "."
        s = t.replace(grp, "").replace(dec, ".")
        out.append(s)
    elif "," in t or "." in t:
        sep = "," if "," in t else "."
        parts = t.split(sep)
        if len(parts) == 2:
            out.append(parts[0] + "." + parts[1])            # decimal reading
        if all(len(p) == 3 for p in parts[1:]) and 1 <= len(parts[0]) <= 3:
            out.append("".join(parts))                       # thousands reading
    else:
        out.append(t)
    vals = []
    for s in out:
        try:
            vals.append((float(s), len(s.split(".")[1]) if "." in s else 0))
        except ValueError:
            pass
    return vals


def extract_numbers(text: str, protected: list[str]) -> list[dict]:
    """Numbers in `text` except inside protected strings (article titles, topic labels, QIDs)."""
    for p in sorted(protected, key=len, reverse=True):
        if p:
            text = text.replace(p, " ")
    text = _ISO_DATE.sub(" ", text)
    text = _WORDY_DATE.sub(" ", text)
    text = _DMY.sub(" ", text)
    text = _SLASH_MONTH.sub(" ", text)
    found = []
    for m in _NUM_RE.finditer(text):
        token, suffix = m.group(2), (m.group(3) or "").lower()
        mult = _SUFFIX.get(suffix, 1.0)
        readings = [(v * mult, d, mult) for v, d in _interpretations(token)]
        if readings:
            found.append({"raw": m.group(0).strip(), "readings": readings})
    return found


def known_values(summary: dict) -> list[tuple[str, float]]:
    vals: list[tuple[str, float]] = []
    by_label = {}
    for r in summary["results"]:
        tag = f"{r['lang']}" if len({x["topic"] for x in summary["results"]}) == 1 else f"{r['topic']}@{r['lang']}"
        for k, v in r["metrics"].items():
            if v is not None:
                vals.append((f"{k}({tag})", float(v)))
        for sp in r.get("spikes", []):
            vals.append((f"spike_peak_views({tag})", float(sp["peak_views"])))
            vals.append((f"spike_ratio({tag})", float(sp["peak_ratio"])))
        vals.append((f"articles({tag})", float(len(r["articles"]))))
        vals.append((f"redirects({tag})", float(r.get("redirects_included", 0))))
        by_label[tag] = r["metrics"]
    # pairwise comparisons people naturally write: "3.2x more views", "40% higher share"
    for (a, ma), (b, mb) in itertools.permutations(by_label.items(), 2):
        for key in ("views_avg_month", "views_per_million", "median_daily_views"):
            x, y = ma.get(key), mb.get(key)
            if x and y:
                vals.append((f"ratio {key} {a}/{b}", x / y))
                vals.append((f"diff% {key} {a} vs {b}", (x / y - 1) * 100))
        for key in ("growth_yoy_pct", "growth_yoy_raw_pct", "trend_per_year_pct"):
            x, y = ma.get(key), mb.get(key)
            if x is not None and y is not None:
                vals.append((f"gap pp {key} {a}-{b}", x - y))
    w = summary["window"]
    for k in ("months", "analysis_months"):
        vals.append((f"window_{k}", float(w[k])))
        vals.append((f"window_{k}_years", w[k] / 12))
    for k, v in summary.get("ranking_weights", {}).items():
        vals.append((f"weight_{k}", float(v)))
        vals.append((f"weight_{k}_pct", float(v) * 100))
    vals.append(("n_languages", float(len({r["lang"] for r in summary["results"]} |
                                          {m["lang"] for m in summary["missing"]}))))
    return vals


def _matches(reading: tuple[float, int, float], value: float) -> bool:
    x, decimals, mult = reading
    v = abs(value)
    tol = 0.5 * 10 ** (-decimals) * mult + 1e-9
    if abs(x - v) <= tol:
        return True
    # "about 8,200 views" for 8,178: allow 1% for large rounded figures
    return v >= 1000 and abs(x - v) / v <= 0.01


def _always_ok(reading: tuple[float, int, float]) -> bool:
    x, decimals, mult = reading
    if decimals == 0 and mult == 1 and (x <= 12 or 2015 <= x <= 2035 or x in (24, 36, 48, 60, 100)):
        return True     # small counts ("3 languages", "12 months"), years, "per 100"
    return False


def _check_numbers(field: str, text: str, values: list[tuple[str, float]], protected: list[str],
                   errors: list[dict]) -> None:
    for num in extract_numbers(text, protected):
        if any(_always_ok(r) for r in num["readings"]):
            continue
        if any(_matches(r, v) for r in num["readings"] for _, v in values):
            continue
        x = num["readings"][0][0]
        key = lambda kv: abs(abs(kv[1]) - x)
        primary = sorted((kv for kv in values if kv[0].split("(")[0] in _PRIMARY), key=key)[:3]
        other = sorted((kv for kv in values if kv[0].split("(")[0] not in _PRIMARY), key=key)[:2]
        errors.append({
            "field": field, "problem": f"number '{num['raw']}' does not match any computed value",
            "hint": "Use values from summary.json exactly (rounding is fine). Closest key metrics: " +
                    ", ".join(f"{k}={v:.4g}" for k, v in primary + other)})


# ---------------------------------------------------------------- claims

def _lookup(summary: dict, ref: str) -> tuple[list[dict], bool]:
    """Resolve 'pl', 'topic@pl' or 'topic|pl' to results; second value = is a missing article."""
    ref = ref.replace("|", "@").strip()
    topic, _, lang = ref.rpartition("@")
    lang = lang.lower()
    res = [r for r in summary["results"] if r["lang"] == lang and (not topic or r["topic"].lower() == topic.lower())]
    miss = [m for m in summary["missing"] if m["lang"] == lang and (not topic or m["topic"].lower() == topic.lower())]
    return res, bool(miss) and not res


def verify_narrative(narrative: dict, summary: dict, lang: str = "en") -> dict:
    errors: list[dict] = []
    warnings: list[str] = []
    values = known_values(summary)
    protected = [t for r in summary["results"] for t in r["articles"]] + \
                [r["topic"] for r in summary["results"]] + [m["topic"] for m in summary["missing"]] + \
                [s for m in summary["missing"] for s in m.get("suggestions", [])] + \
                [x.split(":")[0] for t in summary["topics"] for x in t["items"]]

    def text_field(name: str, value, limit: int, required: bool = True) -> str:
        if value is None or (isinstance(value, str) and not value.strip()):
            if required:
                errors.append({"field": name, "problem": "missing", "hint": f"'{name}' is required"})
            return ""
        if not isinstance(value, str):
            errors.append({"field": name, "problem": "must be a string", "hint": ""})
            return ""
        if len(value) > limit:
            errors.append({"field": name, "problem": f"too long ({len(value)} > {limit} chars)",
                           "hint": "Shorten it; the report is one page."})
        _check_numbers(name, value, values, protected, errors)
        return value

    text_field("title", narrative.get("title"), LIMITS["title"], required=False)
    text_field("headline", narrative.get("headline"), LIMITS["headline"])
    text_field("recommendation", narrative.get("recommendation"), LIMITS["recommendation"])
    strong_somewhere = any(r.get("claim_strength") == "strong" or "strong_growth" in r["allowed_claims"] or "strong_decline" in r["allowed_claims"] for r in summary["results"])

    def lint(field: str, text, strong_ok: bool) -> None:
        if strong_ok or not isinstance(text, str):
            return
        low = text.lower()
        hits = [w for w in INTENSIFIERS if w in low]
        if hits:
            errors.append({"field": field, "problem": f"overstating words for moderate/weak evidence: {', '.join(hits)}",
                           "hint": "Use the hedged wording from draft (e.g. 'declining (moderate evidence)')."})

    from .answer_check import find_country
    langs = {r["lang"] for r in summary["results"]} | {m["lang"] for m in summary["missing"]}
    texts = {"headline": narrative.get("headline"), "recommendation": narrative.get("recommendation")}
    texts.update({f"findings[{i}].text": f.get("text") for i, f in enumerate(narrative.get("findings") or [])
                  if isinstance(f, dict)})
    for field, text in texts.items():
        hit = find_country(text, langs) if isinstance(text, str) else None
        if hit:
            errors.append({"field": field, "problem": f"names a country ('{hit}')",
                           "hint": "Describe readers of the language edition (e.g. 'Polish-language Wikipedia'), "
                                   "not the country; the report adds the language-vs-country caveat itself."})

    lint("headline", narrative.get("headline"), strong_somewhere)
    lint("recommendation", narrative.get("recommendation"), strong_somewhere)

    findings = narrative.get("findings")
    if not isinstance(findings, list) or not findings:
        errors.append({"field": "findings", "problem": "must be a non-empty list",
                       "hint": 'e.g. [{"text": "...", "about": ["cs"], "claim": "decline"}]'})
        findings = []
    if len(findings) > MAX_FINDINGS:
        errors.append({"field": "findings", "problem": f"{len(findings)} findings; max {MAX_FINDINGS}",
                       "hint": "Keep the 3-4 that matter for the decision."})
    for i, f in enumerate(findings):
        name = f"findings[{i}]"
        if not isinstance(f, dict):
            errors.append({"field": name, "problem": "must be an object with text/about/claim", "hint": ""})
            continue
        text_field(f"{name}.text", f.get("text"), LIMITS["finding"])
        claim = f.get("claim")
        lint(f"{name}.text", f.get("text"), claim in ("strong_growth", "strong_decline"))
        about = f.get("about") or []
        if isinstance(about, str):
            about = [about]
        if claim not in ALL_CLAIMS:
            errors.append({"field": f"{name}.claim", "problem": f"unknown claim '{claim}'",
                           "hint": f"Use one of: {', '.join(sorted(ALL_CLAIMS))}"})
            continue
        if claim not in NEUTRAL_CLAIMS and not about:
            errors.append({"field": f"{name}.about", "problem": "trend claims must say which series they are about",
                           "hint": 'e.g. "about": ["uk"] or ["astronomy@uk"]'})
        for ref in about:
            res, is_missing = _lookup(summary, str(ref))
            if is_missing:
                if claim not in ("no_article", *NEUTRAL_CLAIMS):
                    errors.append({"field": f"{name}.claim", "problem": f"'{ref}' has no article, so '{claim}' "
                                   "cannot be supported", "hint": "Use claim 'no_article' or 'context'."})
                continue
            if not res:
                errors.append({"field": f"{name}.about", "problem": f"'{ref}' is not in this study",
                               "hint": "Use a language code from results/missing, or 'topic@lang'."})
                continue
            if len(res) > 1:
                errors.append({"field": f"{name}.about", "problem": f"'{ref}' is ambiguous (several topics)",
                               "hint": f"Use 'topic@{res[0]['lang']}'."})
                continue
            r = res[0]
            if claim in NEUTRAL_CLAIMS:
                continue
            if claim == "no_article" or claim not in r["allowed_claims"]:
                errors.append({
                    "field": f"{name}.claim",
                    "problem": f"claim '{claim}' is not supported for {r['topic']}@{r['lang']} "
                               f"(direction={r['direction']}, confidence={r['confidence']})",
                    "hint": f"Allowed: {', '.join(r['allowed_claims'])}. Soften the wording to match."})

    steps = narrative.get("next_steps", [])
    if not isinstance(steps, list):
        errors.append({"field": "next_steps", "problem": "must be a list of strings", "hint": ""})
        steps = []
    if len(steps) > MAX_NEXT:
        errors.append({"field": "next_steps", "problem": f"max {MAX_NEXT} items", "hint": ""})
    for i, s in enumerate(steps):
        text_field(f"next_steps[{i}]", s, LIMITS["next_step"])

    draft = (summary.get("draft") or {}).get("narrative_draft") or {}
    if lang != "en" and draft:
        untranslated = [k for k in ("title", "headline") if narrative.get(k) and narrative.get(k) == draft.get(k)]
        untranslated += [f"findings[{i}].text" for i, f in enumerate(findings) if isinstance(f, dict)
                         and f.get("text") in {d["text"] for d in draft.get("findings", [])}]
        for field in untranslated:
            errors.append({"field": field, "problem": f"still the English draft text, but the report language is '{lang}'",
                           "hint": "Translate it into the user's language (keep the numbers)."})
    if lang != "en" and not narrative.get("title"):
        errors.append({"field": "title", "problem": "missing", "hint": "Add a short title in the report language."})

    referenced = {str(a).replace("|", "@").rpartition("@")[2].lower()
                  for f in findings if isinstance(f, dict) for a in (f.get("about") or [])}
    weak = [f"{r['lang']}" for r in summary["results"] if r["confidence"] in ("Low", "Insufficient")]
    unmentioned = [x for x in weak + [m["lang"] for m in summary["missing"]] if x not in referenced]
    if unmentioned:
        warnings.append("Not discussed in findings (low confidence / missing article): "
                        + ", ".join(sorted(set(unmentioned))) + ". The table shows them, but say it in words "
                        "if it affects the recommendation.")
    return {"ok": not errors, "errors": errors, "warnings": warnings}
