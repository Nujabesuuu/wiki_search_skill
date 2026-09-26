"""Command line entry point. Contract for agents:
- stdout: exactly one JSON object; stderr: progress logs.
- exit 0 ok, 2 bad arguments, 3 data/resolution problem, 4 network problem.
- errors carry a `hint` with the command to try next.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

from . import study as st
from .analyze import make_window, analyze_series
from .cache import Cache
from .charts import make_charts
from .draft import build_draft
from .fetch import Fetcher, UnknownProject
from .i18n import note_text
from .langs import LanguageError, lang_name, parse_langs
from .net import Client, NetworkError
from .rank import CRITERIA_DOC, WeightsError, parse_weights, rank
from .resolve import ResolveError, Resolver

MAX_COMBINATIONS = 40
_AGENT_TIPS = {  # extra advice for the agent only (not printed in the report)
    "basket_uneven": " Prefer comparing languages on the same items (run each item as its own --topic).",
    "ambiguous": " See 'topics[].alternatives'; re-run with --topic <QID> if the wrong concept was picked.",
}


class UsageError(ValueError):
    pass


def log(msg: str) -> None:
    print(f"[wpv] {msg}", file=sys.stderr, flush=True)


def emit(obj: dict, code: int = 0) -> int:
    print(json.dumps(obj, ensure_ascii=False, indent=1))
    return code


class JsonArgParser(argparse.ArgumentParser):
    def error(self, message: str):  # argparse would print plain text; agents parse JSON
        emit({"status": "error", "error": message, "hint": f"Run: scripts/wpv {self.prog.split()[-1]} --help"}, 2)
        sys.exit(2)


# ---------------------------------------------------------------- helpers

def _services():
    client = Client()
    cache = Cache()
    return client, cache, Resolver(client, cache), Fetcher(client, cache)


def _topic_dict(t) -> dict:
    d = {"label": t.label, "items": [f"{i['qid']}: {i['label']} — {i['description']}" for i in t.items]}
    if t.ambiguous:
        d["ambiguous"] = True
        d["alternatives"] = [f"{a['qid']}: {a['label']} — {a['description']}" for a in t.alternatives[:4]]
        d["hint"] = ("Several concepts match this text. If the chosen item is wrong, re-run with "
                     "--topic <QID> (or ask the user which one they mean).")
    return d


def _compact(r: dict) -> dict:
    failed = [c["detail"] for c in r["checks"] if not c["ok"]]
    out = {
        "topic": r["topic"], "lang": r["lang"], "articles": r["articles"],
        "metrics": r["metrics"], "direction": r["direction"], "confidence": r["confidence"],
        "claim_strength": r["claim_strength"], "allowed_claims": r["allowed_claims"],
        "passed_checks": [c["name"] for c in r["checks"] if c["ok"]],
        "failed_checks": failed,
    }
    if r["flags"]:
        out["flags"] = r["flags"]
    if r.get("basket_missing"):
        out["basket_missing"] = r["basket_missing"]
    if r["spikes"]:
        big = max(r["spikes"], key=lambda s: s["extra_views"])
        out["largest_spike"] = {k: big[k] for k in ("peak_date", "peak_views", "peak_ratio", "days",
                                                    "recurring_yearly")}
    return out


def reporting_rules(summary: dict) -> list[str]:
    """Short rules tailored to this result, placed where a small model reads them."""
    rules = [
        "Build your answer from 'draft' (code-written, correct wording): translate it, keep every number and "
        "hedge, do not add new numbers, ratios or causes.",
        "Say 'share of <language> Wikipedia views' for growth_yoy_pct (never 'views fell X%'); raw views are "
        "growth_yoy_raw_pct. growth_yoy_pct already removes wiki-wide traffic changes.",
        "Name results by language edition ('Polish-language Wikipedia'), never as a country.",
        "Never guess causes of spikes or trends (news, events, seasons, algorithms, the user's feed); report only "
        "what 'draft' says.",
        "Do not generalise across languages ('all', 'every') unless every series says the same in 'draft'.",
        "Do not quote p-values; use the plain confidence reasons from 'draft'.",
        "views_per_million is 'views per million pageviews of that wiki' (salience), not per capita.",
        "If you recommend an order of languages/topics, use draft.ranking (it states the weights); if you "
        "deviate, say which criterion you used instead and why.",
    ]
    if not any(x.get("rank") for x in summary["ranking"]) and summary["results"]:
        rules.append("Nothing could be ranked (insufficient data). Do not recommend an order; broaden the topic "
                     "with a basket and re-run once.")
    if any(t.get("ambiguous") for t in summary["topics"]):
        rules.append("Ambiguous topic: name the analysed meaning in your first sentence and offer the alternatives.")
    return rules


def compact_summary(summary: dict) -> dict:
    return {
        "reporting_rules": reporting_rules(summary),
        "draft": summary.get("draft") or build_draft(summary),
        "status": summary["status"],
        "study": summary["study"],
        "window": summary["window"],
        "topics": summary["topics"],
        "results": [_compact(r) for r in summary["results"]],
        "missing": summary["missing"],
        "ranking": summary["ranking"],
        "ranking_weights": summary["ranking_weights"],
        "notes": summary["notes"],
        "files": summary["files"],
        "next": summary["next"],
    }


def _write_csv(path: Path, results: list[dict], totals: dict[str, dict[str, int]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["month", "topic", "lang", "views_incl_redirects", "views_per_million", "wiki_total_views"])
        for r in results:
            for m, v, pm in zip(r["_months"], r["_monthly_views"], r["_monthly_per_million"]):
                w.writerow([m, r["topic"], r["lang"], int(v), "" if pm is None else f"{pm:.4f}",
                            totals[r["lang"]].get(m, "")])


# ---------------------------------------------------------------- commands

def cmd_run(a) -> int:
    t0 = time.time()
    study_dir = Path(a.study) if a.study else None
    cfg = st.load(study_dir) if study_dir and (study_dir / "study.json").exists() else st.StudyConfig()
    if a.topic:
        cfg.topics = list(dict.fromkeys(a.topic))
    for t in a.add_topic or []:
        if t not in cfg.topics:
            cfg.topics.append(t)
    for t in a.remove_topic or []:
        cfg.topics = [x for x in cfg.topics if x.split("=")[0].strip().lower() != t.strip().lower()]
    if a.langs:
        cfg.langs = parse_langs(a.langs)
    if a.add_langs:
        cfg.langs += [l for l in parse_langs(a.add_langs) if l not in cfg.langs]
    if a.remove_langs:
        drop = set(parse_langs(a.remove_langs))
        cfg.langs = [l for l in cfg.langs if l not in drop]
    for art in a.article or []:
        if ":" not in art:
            raise UsageError(f"--article must look like 'pl:Title' or 'pl:Title@topic', got '{art}'")
        if art not in cfg.articles:
            cfg.articles.append(art)
    if a.months:
        cfg.months = a.months
    if a.end:
        cfg.end = a.end
    if a.weights:
        cfg.weights = parse_weights(a.weights)
    if a.no_redirects:
        cfg.redirects = False
    if not cfg.topics or not cfg.langs:
        raise UsageError("Need at least one --topic and --langs, e.g. "
                         "scripts/wpv run --topic \"intermittent fasting\" --langs pl,cs")
    if len(cfg.topics) * len(cfg.langs) > MAX_COMBINATIONS:
        raise UsageError(f"{len(cfg.topics) * len(cfg.langs)} topic x language combinations; the limit is "
                         f"{MAX_COMBINATIONS} per study. Split into several studies.")
    study_dir = (study_dir or st.default_dir(cfg)).resolve()
    weights = parse_weights(cfg.weights)
    window = make_window(cfg.months, cfg.end)

    client, cache, resolver, fetcher = _services()
    log(f"resolving {len(cfg.topics)} topic(s) in {', '.join(cfg.langs)}")
    resolved = [resolver.resolve_topic(spec, cfg.langs, st.manual_articles(cfg, i))
                for i, spec in enumerate(cfg.topics)]
    if not cfg.redirects:
        for t in resolved:
            for arts in t.articles.values():
                for art in arts:
                    art.redirects = []
    reqs = [r for t in resolved for arts in t.articles.values() for r in Fetcher.requests_for(arts)]
    log(f"fetching {len(reqs)} daily series {window.months[0]}..{window.months[-1]} (cached parts are skipped)")
    fetcher.prefetch(reqs, window.start_day, window.end_day)
    langs_with_data = sorted({l for t in resolved for l in t.articles})
    totals = {l: fetcher.project_totals(l, window.months) for l in langs_with_data}

    results, missing = [], []
    for t in resolved:
        for lang in cfg.langs:
            if lang in t.articles:
                bundle = fetcher.article_bundle(t.articles[lang], window.start_day, window.end_day)
                res = analyze_series(t.label, lang, t.articles[lang], bundle, totals[lang], window)
                found = {x.qid for x in t.articles[lang]}
                absent = [i["label"] for i in t.items if i["qid"] not in found]
                if len(t.items) > 1 and absent:
                    res["flags"].append("basket_incomplete")
                    res["basket_missing"] = absent
                results.append(res)
            else:
                missing.append({"topic": t.label, "lang": lang, **t.missing[lang]})

    ranking = rank(results, weights)
    colors = st.assign_colors(cfg, [f"{r['topic']}|{r['lang']}" for r in results])
    study_dir.mkdir(parents=True, exist_ok=True)
    (study_dir / "data").mkdir(exist_ok=True)
    charts = make_charts(results, window.chart_months, colors, study_dir / "charts", "en")
    _write_csv(study_dir / "data" / "monthly.csv", results, totals)
    st.save(study_dir, cfg)

    note_codes = list(window.note_codes)
    if any(t.ambiguous for t in resolved):
        note_codes.append({"code": "ambiguous", "params": {}})
    uneven = sorted({f"{r['lang']}: {', '.join(r['basket_missing'])}" for r in results if r.get("basket_missing")})
    if uneven:
        note_codes.append({"code": "basket_uneven", "params": {"detail": "; ".join(uneven)}})
    if not cfg.redirects:
        note_codes.append({"code": "no_redirects", "params": {}})
    notes = [note_text("en", n["code"], n["params"]) + (_AGENT_TIPS.get(n["code"], "")) for n in note_codes]
    summary = {
        "status": "ok" if not missing else "partial",
        "study": str(study_dir),
        "generated": time.strftime("%Y-%m-%d"),
        "window": window.to_dict(),
        "topics": [_topic_dict(t) for t in resolved],
        "results": results,
        "missing": missing,
        "ranking": ranking,
        "ranking_weights": weights,
        "ranking_criteria": CRITERIA_DOC,
        "notes": notes,
        "note_codes": note_codes,
        "files": {"summary": str(study_dir / "summary.json"), "csv": str(study_dir / "data" / "monthly.csv"),
                  "charts": charts},
        "next": (f"1) Translate draft.answer_markdown into the user's language and save it as answer.md. "
                 f"2) If the user does not write in English, translate draft.narrative_draft into narrative.json and "
                 f"run: scripts/wpv report --study {study_dir} --narrative narrative.json --lang <code> "
                 f"(the English PDF is already built). 3) Run: scripts/wpv check --study {study_dir} --answer answer.md "
                 f"and fix every issue before sending."),
    }
    pdf_en = study_dir / "report-en.pdf"
    summary["files"]["pdf"] = str(pdf_en)
    summary["draft"] = build_draft(summary)
    (study_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), "utf-8")
    # Build the English PDF right away from the verified draft: small models often skip the report step.
    from .report import build_report
    draft_path = study_dir / "narrative.draft.json"
    draft_path.write_text(json.dumps(summary["draft"]["narrative_draft"], ensure_ascii=False, indent=1), "utf-8")
    rep, code = build_report(study_dir, draft_path, "en")
    if code != 0:
        log(f"could not build the English PDF: {rep}")
        summary["files"]["pdf"] = None
        (study_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), "utf-8")
    log(f"done in {time.time() - t0:.1f}s, {client.requests_made} HTTP requests")
    return emit(compact_summary(summary))


def cmd_show(a) -> int:
    path = Path(a.study) / "summary.json"
    if not path.exists():
        raise UsageError(f"No summary at {path}. Run 'scripts/wpv run --study {a.study} ...' first.")
    return emit(compact_summary(json.loads(path.read_text("utf-8"))))


def cmd_resolve(a) -> int:
    langs = parse_langs(a.langs)
    _, _, resolver, _ = _services()
    out = []
    for spec in a.topic:
        t = resolver.resolve_topic(spec, langs)
        d = _topic_dict(t)
        d["articles"] = {l: [{"title": x.title, "redirects": x.redirects_total} for x in arts]
                         for l, arts in t.articles.items()}
        d["missing"] = t.missing
        if not t.ambiguous:
            d["alternatives"] = [f"{x['qid']}: {x['label']} — {x['description']}" for x in t.alternatives[:3]]
        out.append(d)
    return emit({"status": "ok", "topics": out})


def cmd_search(a) -> int:
    lang = parse_langs(a.lang)[0]
    _, _, resolver, _ = _services()
    return emit({"status": "ok", "lang": lang, "query": a.query, "titles": resolver.search_wiki(lang, a.query, a.limit),
                 "hint": f"Use a relevant title with: scripts/wpv run --study <dir> --article '{lang}:<Title>'"})


def cmd_check(a) -> int:
    from .answer_check import check_answer
    study_dir = Path(a.study)
    summary_path = study_dir / "summary.json"
    if not summary_path.exists():
        raise UsageError(f"No summary at {summary_path}. Run 'scripts/wpv run' first.")
    try:
        answer = Path(a.answer).read_text("utf-8")
    except OSError as e:
        raise UsageError(f"Cannot read the answer file: {e}")
    return emit(check_answer(answer, json.loads(summary_path.read_text("utf-8")), study_dir))


def cmd_report(a) -> int:
    from .report import build_report   # heavy import only when needed
    lang = a.lang.strip().lower()
    result, code = build_report(Path(a.study), Path(a.narrative) if a.narrative else None, lang, a.check_only)
    return emit(result, code)


# ---------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    p = JsonArgParser(prog="wpv", description="Wikipedia interest research: compare topics and languages "
                                              "using Wikimedia pageviews. All output is JSON on stdout.")
    sub = p.add_subparsers(dest="cmd", required=True, parser_class=JsonArgParser)

    r = sub.add_parser("run", help="resolve + fetch + analyze + charts (creates or updates a study)",
                       formatter_class=argparse.RawDescriptionHelpFormatter, epilog="""examples:
  scripts/wpv run --topic "intermittent fasting" --langs pl,cs --months 24
  scripts/wpv run --topic astronomy --langs uk --months 36
  scripts/wpv run --topic "English learning=Q130192,Q1860" --langs pl,de,es,tr,uk
  follow-ups on the same study (cache makes them fast):
  scripts/wpv run --study wiki-interest-studies/astronomy-uk --add-langs pl,de
  scripts/wpv run --study <dir> --article "pl:Głodówka lecznicza" --weights volume=0.5,growth=0.5""")
    r.add_argument("--topic", action="append", help="topic: free text, a Wikidata QID, or 'label=part1,part2' "
                                                    "basket (repeat for several topics)")
    r.add_argument("--langs", help="Wikipedia language codes or names, e.g. 'pl,cs' or 'Polish,Czech'")
    r.add_argument("--months", type=int, help="window length in months (default 24; stats use >= 24)")
    r.add_argument("--end", help="last month YYYY-MM (default: last complete month)")
    r.add_argument("--article", action="append", help="add a specific article: 'pl:Title' or 'pl:Title@topic label'")
    r.add_argument("--weights", help="ranking weights, e.g. growth=0.4,volume=0.25,share=0.2,confidence=0.15")
    r.add_argument("--study", help="study directory (created if missing; re-use it for follow-ups)")
    r.add_argument("--add-langs")
    r.add_argument("--remove-langs")
    r.add_argument("--add-topic", action="append")
    r.add_argument("--remove-topic", action="append", help="topic label to remove")
    r.add_argument("--no-redirects", action="store_true", help="do not add views of redirect titles")
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("show", help="print the compact summary of an existing study (no network)")
    s.add_argument("--study", required=True)
    s.set_defaults(func=cmd_show)

    v = sub.add_parser("resolve", help="check which articles a topic maps to (cheap, no pageviews)")
    v.add_argument("--topic", action="append", required=True)
    v.add_argument("--langs", required=True)
    v.set_defaults(func=cmd_resolve)

    q = sub.add_parser("search", help="full-text search inside one Wikipedia (find a proxy article)")
    q.add_argument("--lang", required=True)
    q.add_argument("query")
    q.add_argument("--limit", type=int, default=8)
    q.set_defaults(func=cmd_search)

    o = sub.add_parser("report", help="verify the narrative against the data and render a one-page PDF")
    o.add_argument("--study", required=True)
    o.add_argument("--narrative", help="narrative JSON written by the agent (see SKILL.md)")
    o.add_argument("--lang", default="en", help="report language for labels & caveats (en, uk, pl, cs, de, es, fr)")
    o.add_argument("--check-only", action="store_true", help="only verify the narrative, do not render")
    o.set_defaults(func=cmd_report)

    c = sub.add_parser("check", help="check your chat answer before sending: unknown numbers, country names, "
                                     "generalisations, dropped lines, missing PDF path")
    c.add_argument("--study", required=True)
    c.add_argument("--answer", required=True, help="text/markdown file with the answer you are about to send")
    c.set_defaults(func=cmd_check)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (UsageError, LanguageError, WeightsError) as e:
        return emit({"status": "error", "error": str(e), "hint": "Fix the arguments; see scripts/wpv run --help"}, 2)
    except (ResolveError, UnknownProject) as e:
        return emit({"status": "error", "error": str(e),
                     "hint": "Try scripts/wpv resolve --topic ... --langs ... or a Wikidata QID"}, 3)
    except NetworkError as e:
        return emit({"status": "error", "error": str(e),
                     "hint": "Network/Wikimedia problem. Wait a minute and retry the same command; cached data is kept."}, 4)
