"""Topic -> Wikidata item(s) -> article per language (+ its redirects).

A *topic* is a user-facing label backed by one or more Wikidata items ("basket"), e.g.
"English learning=Q1860,Q1063556". Language-specific overrides come from explicit
`lang:Title` articles. A language without an article is a first-class result
(`missing`), returned with in-wiki search suggestions instead of being imputed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .cache import Cache
from .langs import dbname
from .net import Client, NotFound

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
MAX_REDIRECTS = 50
_QID_RE = re.compile(r"^Q\d+$", re.I)
_NON_TOPIC_HINTS = ("disambiguation", "wikimedia list", "wikimedia category", "wikimedia template",
                    "family name", "given name", "album by", "single by", "song by", "film directed",
                    "scientific article", "scholarly article", "episode of", "television series",
                    "podcast", "book by", "novel by", "painting by", "video game", "academic journal",
                    "scientific journal", "magazine", "periodical", "radio program")


def wiki_api(lang: str) -> str:
    return f"https://{lang}.wikipedia.org/w/api.php"


class ResolveError(LookupError):
    pass


@dataclass
class Article:
    lang: str
    title: str                      # canonical title (spaces)
    qid: str | None = None
    redirects: list[str] = field(default_factory=list)
    redirects_total: int = 0
    source: str = "wikidata"         # wikidata | manual


@dataclass
class ResolvedTopic:
    label: str
    items: list[dict]                       # [{qid, label, description}]
    alternatives: list[dict]                # other search candidates, for disambiguation
    articles: dict[str, list[Article]]      # lang -> articles in the basket
    missing: dict[str, dict]                # lang -> {suggestions, hint}
    ambiguous: bool = False                 # several distinct concepts match the text equally well


class Resolver:
    def __init__(self, client: Client, cache: Cache):
        self.client = client
        self.cache = cache

    # ---------------------------------------------------------------- helpers
    def _cached(self, key: str, url: str, params: dict) -> dict:
        hit = self.cache.get_json(key)
        if hit is not None:
            return hit
        data = self.client.get_json(url, {**params, "format": "json"})
        self.cache.put_json(key, data)
        return data

    def search_items(self, text: str, lang: str = "en", limit: int = 7) -> list[dict]:
        data = self._cached(f"wbsearch:{lang}:{text.lower()}", WIKIDATA_API, {
            "action": "wbsearchentities", "search": text, "language": lang, "uselang": "en",
            "type": "item", "limit": limit})
        return [{"qid": r["id"], "label": r.get("label", ""), "description": r.get("description", "")}
                for r in data.get("search", [])]

    def get_entities(self, qids: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for i in range(0, len(qids), 50):
            chunk = qids[i:i + 50]
            data = self._cached(f"wbget:{'|'.join(chunk)}", WIKIDATA_API, {
                "action": "wbgetentities", "ids": "|".join(chunk),
                "props": "labels|descriptions|sitelinks", "languages": "en"})
            for qid, ent in data.get("entities", {}).items():
                if "missing" in ent:
                    continue
                out[qid] = {
                    "qid": qid,
                    "label": ent.get("labels", {}).get("en", {}).get("value", qid),
                    "description": ent.get("descriptions", {}).get("en", {}).get("value", ""),
                    "sitelinks": {k: v["title"] for k, v in ent.get("sitelinks", {}).items()},
                }
        return out

    def labels_in(self, qid: str, lang: str) -> str | None:
        data = self._cached(f"wblabel:{qid}:{lang}", WIKIDATA_API, {
            "action": "wbgetentities", "ids": qid, "props": "labels", "languages": lang})
        return data.get("entities", {}).get(qid, {}).get("labels", {}).get(lang, {}).get("value")

    def search_wiki(self, lang: str, query: str, limit: int = 5) -> list[str]:
        try:
            data = self._cached(f"srch:{lang}:{query.lower()}:{limit}", wiki_api(lang), {
                "action": "query", "list": "search", "srsearch": query, "srlimit": limit,
                "srnamespace": 0, "srwhat": "text"})
        except NotFound:
            return []
        return [r["title"] for r in data.get("query", {}).get("search", [])]

    def canonical_and_redirects(self, lang: str, title: str) -> tuple[str | None, list[str], int]:
        """Follow the title if it is itself a redirect; return (canonical, redirects, total)."""
        data = self._cached(f"redir:{lang}:{title}", wiki_api(lang), {
            "action": "query", "titles": title, "redirects": 1, "prop": "redirects",
            "rdnamespace": 0, "rdlimit": "max", "formatversion": 2})
        pages = data.get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing") or pages[0].get("invalid"):
            return None, [], 0
        page = pages[0]
        reds = [r["title"] for r in page.get("redirects", [])]
        return page["title"], reds[:MAX_REDIRECTS], len(reds)

    # ---------------------------------------------------------------- items
    def pick_item(self, text: str, langs: list[str]) -> tuple[dict, list[dict]]:
        """Best Wikidata item for free text + the alternatives an agent can switch to."""
        order = ["en"] + [l for l in langs if l != "en"]
        if not text.isascii():
            order = [l for l in langs if l != "en"] + ["en"]
        candidates: list[dict] = []
        for lang in order:
            candidates = self.search_items(text, lang)
            if candidates:
                break
        if not candidates:
            raise ResolveError(f"No Wikidata item found for '{text}'. Try an English name or a QID (e.g. Q333).")
        ents = self.get_entities([c["qid"] for c in candidates])
        wanted = {dbname(l) for l in langs}
        viable = []
        for rank, c in enumerate(candidates):
            e = ents.get(c["qid"])
            if not e:
                continue
            desc = (e["description"] or c["description"]).lower()
            if any(h in desc for h in _NON_TOPIC_HINTS):
                continue
            e = {**e, "coverage": len(wanted & set(e["sitelinks"])), "n_sitelinks": len(e["sitelinks"])}
            exact = text.lower() in (c["label"].lower(), e["label"].lower())
            # Prefer the item that actually has articles in the requested wikis (a TV episode called
            # "English as a Second Language" loses to the concept), then exact label, then the more
            # widely covered concept (planet Mercury beats the car brand), then search rank.
            viable.append(((-e["coverage"], not exact, -e["n_sitelinks"], rank), e))
        if not viable:
            raise ResolveError(f"'{text}' only matched disambiguation/list/media pages. Pass a QID instead.")
        viable.sort(key=lambda t: t[0])
        best = viable[0][1]
        alts = [{"qid": e["qid"], "label": e["label"], "description": e["description"],
                 "articles_in_requested_langs": e["coverage"]} for _, e in viable[1:5]]
        best["ambiguous"] = any(e["coverage"] == best["coverage"] and k[1] is False
                                for k, e in viable[1:] if e["n_sitelinks"] >= best["n_sitelinks"] / 5)
        return best, alts

    def parse_topic(self, spec: str) -> tuple[str, list[str]]:
        """'label=part1,part2' | 'Q123' | 'free text' -> (label, parts)."""
        if "=" in spec:
            label, rest = spec.split("=", 1)
            parts = [p.strip() for p in rest.split(",") if p.strip()]
            return label.strip(), parts
        return spec.strip(), [spec.strip()]

    def resolve_topic(self, spec: str, langs: list[str],
                      manual: dict[str, list[str]] | None = None) -> ResolvedTopic:
        label, parts = self.parse_topic(spec)
        items, alternatives, ambiguous = [], [], False
        qids = [p.upper() for p in parts if _QID_RE.match(p)]
        ents = self.get_entities(qids) if qids else {}
        for p in parts:
            if _QID_RE.match(p):
                e = ents.get(p.upper())
                if not e:
                    raise ResolveError(f"Wikidata item {p} does not exist.")
            else:
                e, alts = self.pick_item(p, langs)
                if len(parts) == 1:
                    alternatives, ambiguous = alts, bool(e.get("ambiguous"))
            items.append(e)
        if label.upper() in ents and len(parts) == 1:
            label = ents[label.upper()]["label"]

        manual = manual or {}
        articles: dict[str, list[Article]] = {}
        missing: dict[str, dict] = {}
        for lang in langs:
            found: list[Article] = []
            seen: set[str] = set()
            candidates = [(it["sitelinks"].get(dbname(lang)), it["qid"], "wikidata") for it in items]
            candidates += [(t, None, "manual") for t in manual.get(lang, [])]
            for title, qid, source in candidates:
                if not title:
                    continue
                canonical, reds, total = self.canonical_and_redirects(lang, title)
                if not canonical or canonical in seen:
                    continue
                seen.add(canonical)
                found.append(Article(lang, canonical, qid, reds, total, source))
            if found:
                articles[lang] = found
            else:
                query = self.labels_in(items[0]["qid"], lang) or items[0]["label"]
                suggestions = self.search_wiki(lang, query)
                missing[lang] = {
                    "suggestions": suggestions,
                    "hint": (f"No {lang} article is linked to {', '.join(i['qid'] for i in items)}. "
                             f"If one of the suggestions is a real equivalent, re-run with "
                             f"--article '{lang}:<Title>'. Otherwise report the gap: "
                             f"no dedicated article is itself a signal of low coverage."),
                }
        return ResolvedTopic(
            label=label,
            items=[{"qid": i["qid"], "label": i["label"], "description": i["description"]} for i in items],
            alternatives=alternatives, articles=articles, missing=missing, ambiguous=ambiguous)
