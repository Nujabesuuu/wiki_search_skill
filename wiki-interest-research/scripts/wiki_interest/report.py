"""One-page, shareable PDF: agent narrative (verified) + charts + comparison table +
code-generated method & limitations in the report language."""
from __future__ import annotations

import json
import time
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

import matplotlib
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .charts import INK, INK2, MUTED, make_charts, series_label
from .i18n import SUPPORTED, labels, note_text
from .langs import lang_name
from .verify import verify_narrative

_FONT_DIR = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
pdfmetrics.registerFont(TTFont("DejaVu", str(_FONT_DIR / "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(_FONT_DIR / "DejaVuSans-Bold.ttf")))
pdfmetrics.registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold")

PAGE_W, PAGE_H = A4
MARGIN = 1.3 * cm
TAKEAWAY_BG = colors.HexColor("#f0f4fb")
RULE = colors.HexColor("#d9d8d3")


def _styles(scale: float) -> dict[str, ParagraphStyle]:
    def st(name, size, bold=False, color=INK, lead=1.28, space=0):
        return ParagraphStyle(name, fontName="DejaVu-Bold" if bold else "DejaVu", fontSize=size * scale,
                              leading=size * scale * lead, textColor=colors.HexColor(color), alignment=TA_LEFT,
                              spaceAfter=space)
    return {"title": st("title", 15, True, space=2), "sub": st("sub", 7.8, color=INK2),
            "h": st("h", 9.2, True, space=2), "head": st("head", 10.4, True), "body": st("body", 8.4),
            "cell": st("cell", 7.6), "cellb": st("cellb", 7.6, True), "small": st("small", 6.6, color=INK2)}


def _p(text: str, style) -> Paragraph:
    return Paragraph(escape(text), style)


def _fmt_int(v) -> str:
    return "–" if v is None else f"{int(v):,}".replace(",", " ")


def _fmt_pct(v) -> str:
    return "–" if v is None else f"{v:+.1f}%"


def _table(summary: dict, L: dict, S: dict, colors_map: dict, width: float, lang: str) -> Table:
    multi = len({r["topic"] for r in summary["results"]} | {m["topic"] for m in summary["missing"]}) > 1
    head = [L["col_option"], L["col_views"], L["col_share"], L["col_growth"], L["col_trend"], L["col_conf"]]
    rows = [[Paragraph(f"<b>{escape(h)}</b>", S["cell"]) for h in head]]
    order = {x["lang"] + "|" + x["topic"]: x.get("rank") or 99 for x in summary["ranking"]}
    results = sorted(summary["results"], key=lambda r: order.get(r["lang"] + "|" + r["topic"], 99))
    style = [("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor(INK2)),
             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 1.6),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 1.6), ("ALIGN", (1, 1), (4, -1), "RIGHT")]
    for r in results:
        m = r["metrics"]
        color = colors_map.get(f"{r['topic']}|{r['lang']}", MUTED)
        name = series_label(r, multi, lang)
        rows.append([Paragraph(f'<font color="{color}">■</font> {escape(name)}', S["cell"]),
                     _p(_fmt_int(m["views_avg_month"]), S["cell"]),
                     _p("–" if m["views_per_million"] is None else f"{m['views_per_million']:g}", S["cell"]),
                     Paragraph(f"<b>{_fmt_pct(m['growth_yoy_pct'])}</b>", S["cell"]),
                     _p(_fmt_pct(m["trend_per_year_pct"]), S["cell"]),
                     _p(L[r["confidence"]], S["cell"])])
    for mi in summary["missing"]:
        name = f"{mi['topic']} · {mi['lang']}" if multi else f"{lang_name(mi['lang'], lang)} ({mi['lang']})"
        rows.append([_p(f"□ {name}", S["cell"]), _p(L["missing"], S["cell"]), _p("–", S["cell"]),
                     _p("–", S["cell"]), _p("–", S["cell"]), _p("–", S["cell"])])
    for i in range(2, len(rows), 2):
        style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#f7f7f5")))
    col = [0.27, 0.19, 0.12, 0.14, 0.12, 0.16]
    t = Table(rows, colWidths=[c * width for c in col], repeatRows=1)
    t.setStyle(TableStyle(style))
    return t


def _bullets(items: list[str], S: dict) -> list:
    return [Paragraph(f"•&nbsp;&nbsp;{escape(x)}", S["body"]) for x in items]


def _story(summary: dict, narrative: dict, lang: str, charts: dict, colors_map: dict, scale: float,
           chart_h: float) -> list:
    L = labels(lang)
    S = _styles(scale)
    width = PAGE_W - 2 * MARGIN
    topics = ", ".join(dict.fromkeys([t["label"] for t in summary["topics"]]))
    langs = ", ".join(dict.fromkeys([r["lang"] for r in summary["results"]] + [m["lang"] for m in summary["missing"]]))
    w = summary["window"]
    title = narrative.get("title") or f"{L['report_title']}: {topics}"
    concepts = "; ".join(i.split(": ", 1)[-1] + f" ({i.split(':')[0]})" for t in summary["topics"] for i in t["items"])
    story = [_p(title, S["title"]),
             _p(f"{L['window']}: {w['start']} – {w['end']}  ·  {langs}  ·  {summary.get('generated', '')}", S["sub"]),
             _p(f"Wikidata: {concepts}", S["sub"]),
             Spacer(1, 5)]

    box = [[_p(L["takeaway"].upper(), S["small"])], [_p(narrative.get("headline", ""), S["head"])]]
    if narrative.get("recommendation"):
        box += [[Spacer(1, 2)], [Paragraph(f"<b>{escape(L['recommendation'])}:</b> "
                                           f"{escape(narrative['recommendation'])}", S["body"])]]
    tb = Table(box, colWidths=[width])
    tb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TAKEAWAY_BG),
                            ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                            ("TOPPADDING", (0, 0), (0, 0), 6), ("BOTTOMPADDING", (0, -1), (-1, -1), 7),
                            ("TOPPADDING", (0, 1), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -2), 1),
                            ("LINEBEFORE", (0, 0), (0, -1), 2.5, colors.HexColor("#2a78d6"))]))
    story += [tb, Spacer(1, 6)]

    imgs = []
    for key in ("trend", "growth"):
        if charts.get(key):
            img = Image(charts[key])
            ratio = img.imageHeight / img.imageWidth
            iw = width / 2 - 4
            ih = min(iw * ratio, chart_h)
            img.drawWidth, img.drawHeight = ih / ratio, ih
            imgs.append(img)
    if imgs:
        ct = Table([imgs], colWidths=[width / 2] * len(imgs))
        ct.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
        story += [ct, Spacer(1, 4)]

    story += [_p(L["comparison"], S["h"]), _table(summary, L, S, colors_map, width, lang)]
    if sum(1 for x in summary["ranking"] if x.get("rank")) >= 2:
        wt = ", ".join(f"{L['w_' + k]} {round(v * 100)}%" for k, v in summary["ranking_weights"].items() if v)
        story.append(_p(f"{L['ranked_by']}: {wt}", S["small"]))
    story.append(Spacer(1, 6))

    findings = [f["text"] for f in narrative.get("findings", []) if isinstance(f, dict) and f.get("text")]
    if findings:
        story += [_p(L["findings"], S["h"]), *_bullets(findings, S), Spacer(1, 5)]
    if narrative.get("next_steps"):
        story += [_p(L["next_steps"], S["h"]), *_bullets(narrative["next_steps"], S), Spacer(1, 5)]

    notes = " ".join(note_text(lang, n["code"], n["params"]) for n in summary.get("note_codes", []))
    story += [Table([[""]], colWidths=[width], rowHeights=[2],
                    style=[("LINEABOVE", (0, 0), (-1, 0), 0.5, RULE)]),
              _p(L["method"], S["h"]),
              _p(f"{L['method_text']} {L['limits_text']} {notes}".strip(), S["small"]),
              Spacer(1, 3),
              _p(f"{L['source']} {summary.get('generated', '')} · wikimedia.org/api/rest_v1/metrics/pageviews · "
                 f"study: {Path(summary['study']).name}", S["small"])]
    return story


class _PageCounter:
    pages = 0


def _render(story_fn, path: Path) -> int:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN,
                            bottomMargin=MARGIN, title="Wikipedia interest report", author="wiki-interest-research")
    counter = _PageCounter()

    def on_page(canvas, _doc):
        counter.pages = canvas.getPageNumber()
    doc.build(story_fn(), onFirstPage=on_page, onLaterPages=on_page)
    path.write_bytes(buf.getvalue())
    return counter.pages


def build_report(study_dir: Path, narrative_path: Path | None, lang: str, check_only: bool = False) -> tuple[dict, int]:
    summary_path = study_dir / "summary.json"
    if not summary_path.exists():
        return {"status": "error", "error": f"No summary at {summary_path}",
                "hint": "Run scripts/wpv run ... --study <dir> first."}, 2
    summary = json.loads(summary_path.read_text("utf-8"))
    warnings = []
    if narrative_path is None:
        if check_only:
            return {"status": "error", "error": "--check-only needs --narrative"}, 2
        narrative = {"headline": "", "findings": []}
        warnings.append("No narrative given: the report contains data only. Prefer writing narrative.json.")
    else:
        try:
            narrative = json.loads(narrative_path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            return {"status": "error", "error": f"Cannot read narrative JSON: {e}",
                    "hint": "Write valid JSON (double quotes, no trailing commas)."}, 2
        check = verify_narrative(narrative, summary, lang)
        warnings += check["warnings"]
        if not check["ok"]:
            return {"status": "rejected", "errors": check["errors"], "warnings": warnings,
                    "hint": "Fix these fields in the narrative file and run the same command again."}, 3
    if check_only:
        return {"status": "ok", "verified": True, "warnings": warnings}, 0
    if lang not in SUPPORTED:
        warnings.append(f"Labels/caveats are not translated to '{lang}'; English labels used. "
                        f"Supported: {', '.join(SUPPORTED)}.")

    colors_map = json.loads((study_dir / "study.json").read_text("utf-8")).get("colors", {})
    months = summary["results"][0]["_months"] if summary["results"] else []
    chart_months = months[-summary["window"]["months"]:]
    charts = make_charts(summary["results"], chart_months, colors_map, study_dir / "charts" / lang, lang) \
        if summary["results"] else {}

    out = study_dir / f"report-{lang}.pdf"
    attempts = [(1.0, 6.6 * cm), (0.95, 5.8 * cm), (0.9, 5.0 * cm), (0.85, 4.4 * cm)]
    pages = 0
    for scale, chart_h in attempts:
        pages = _render(lambda: _story(summary, narrative, lang, charts, colors_map, scale, chart_h), out)
        if pages == 1:
            break
    if pages != 1:
        out.unlink(missing_ok=True)
        return {"status": "rejected", "errors": [{"field": "narrative", "problem": "report does not fit on one page",
                                                  "hint": "Use at most 3 findings of ~200 characters and 2 next steps."}]}, 3
    (study_dir / "narrative.verified.json").write_text(json.dumps(narrative, ensure_ascii=False, indent=1), "utf-8")
    return {"status": "ok", "report": str(out), "charts": charts, "pages": 1, "warnings": warnings,
            "generated_at": time.strftime("%Y-%m-%d %H:%M")}, 0
