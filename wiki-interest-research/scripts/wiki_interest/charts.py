"""PNG charts (matplotlib, headless). Styling follows a validated categorical palette:
fixed slot order, colour follows the series (not its rank), 2px lines, recessive grid,
one y-axis only, legend for >=2 series plus direct end labels for <=4, hatching as a
non-colour cue for low confidence."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from .i18n import labels  # noqa: E402
from .langs import lang_name  # noqa: E402

PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e1"
MAX_SERIES = len(PALETTE)

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 8.5, "axes.edgecolor": MUTED, "axes.labelcolor": INK2,
    "xtick.color": INK2, "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
    "axes.titlesize": 9.5, "axes.titleweight": "bold", "axes.titlecolor": INK, "axes.titlelocation": "left",
    "legend.frameon": False, "legend.fontsize": 7.5, "figure.dpi": 100, "savefig.dpi": 220,
})


def series_label(r: dict, multi_topic: bool) -> str:
    if multi_topic:
        return f"{r['topic']} · {r['lang']}"
    return f"{lang_name(r['lang'])} ({r['lang']})"


def _short_month(m: str) -> str:
    return f"{m[5:]}/{m[2:4]}"


def trend_chart(results: list[dict], chart_months: list[str], colors: dict[str, str], path: Path,
                lang: str, multi_topic: bool) -> Path:
    L = labels(lang)
    fig, ax = plt.subplots(figsize=(4.4, 3.0))
    ends = []
    values_all = []
    for r in results:
        idx = [r["_months"].index(m) for m in chart_months if m in r["_months"]]
        ys = [r["_monthly_per_million"][i] for i in idx]
        xs = list(range(len(idx)))
        color = colors[f"{r['topic']}|{r['lang']}"]
        ax.plot(xs, ys, color=color, linewidth=2, label=series_label(r, multi_topic), solid_capstyle="round")
        values_all += [y for y in ys if y]
        if ys and ys[-1] is not None:
            ends.append((ys[-1], series_label(r, multi_topic)))
    if values_all and max(values_all) / max(min(values_all), 1e-9) > 30:
        ax.set_yscale("log")
    ticks = list(range(0, len(chart_months), max(1, len(chart_months) // 6)))
    ax.set_xticks(ticks, [_short_month(chart_months[i]) for i in ticks])
    ax.set_ylabel(L["trend_axis"])
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.set_title(L["trend_title"], fontsize=8.5, wrap=True)
    if len(results) >= 2:
        ax.legend(loc="upper left", bbox_to_anchor=(0, -0.12), ncol=min(4, len(results)), handlelength=1.2)
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return path


def growth_chart(results: list[dict], colors: dict[str, str], path: Path, lang: str, multi_topic: bool) -> Path:
    L = labels(lang)
    rows = [r for r in results if r["metrics"]["growth_yoy_pct"] is not None]
    rows = sorted(rows, key=lambda r: r["metrics"]["growth_yoy_pct"])
    fig, ax = plt.subplots(figsize=(4.4, 0.9 + 0.36 * max(len(rows), 1)))
    for i, r in enumerate(rows):
        g = r["metrics"]["growth_yoy_pct"]
        weak = r["confidence"] in ("Low", "Insufficient")
        ax.barh(i, g, height=0.62, color=colors[f"{r['topic']}|{r['lang']}"],
                hatch="////" if weak else None, edgecolor="white", linewidth=0.8,
                alpha=0.55 if weak else 1.0)
        conf = L[r["confidence"]]
        ax.annotate(f"{g:+.1f}%  ·  {conf}", xy=(g, i), xytext=(4 if g >= 0 else -4, 0),
                    textcoords="offset points", va="center", ha="left" if g >= 0 else "right",
                    fontsize=7.5, color=INK)
    ax.axvline(0, color=INK2, linewidth=0.8)
    ax.set_yticks(range(len(rows)), [series_label(r, multi_topic) for r in rows])
    lo = min([0] + [r["metrics"]["growth_yoy_pct"] for r in rows])
    hi = max([0] + [r["metrics"]["growth_yoy_pct"] for r in rows])
    pad = max(12.0, (hi - lo) * 0.45)
    ax.set_xlim(lo - (pad if lo < 0 else 2), hi + pad)
    ax.set_xlabel(L["growth_axis"])
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.set_title(L["growth_title"], fontsize=8.5)
    if any(r["confidence"] in ("Low", "Insufficient") for r in rows):
        ax.legend(handles=[Patch(facecolor="white", edgecolor=INK2, hatch="////", label=L["low_conf_legend"])],
                  loc="upper left", bbox_to_anchor=(0, -0.28 if len(rows) < 4 else -0.15))
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return path


def views_chart(results: list[dict], chart_months: list[str], colors: dict[str, str], path: Path,
                lang: str, multi_topic: bool) -> Path:
    """Absolute monthly views (audience size). Not in the PDF; handy for chat answers."""
    fig, ax = plt.subplots(figsize=(4.4, 3.0))
    for r in results:
        idx = [r["_months"].index(m) for m in chart_months if m in r["_months"]]
        ax.plot(range(len(idx)), [r["_monthly_views"][i] for i in idx], linewidth=2,
                color=colors[f"{r['topic']}|{r['lang']}"], label=series_label(r, multi_topic))
    ticks = list(range(0, len(chart_months), max(1, len(chart_months) // 6)))
    ax.set_xticks(ticks, [_short_month(chart_months[i]) for i in ticks])
    ax.set_ylabel("views / month")
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_title("Monthly pageviews incl. redirects (audience size)", fontsize=8.5)
    if len(results) >= 2:
        ax.legend(loc="upper left", bbox_to_anchor=(0, -0.12), ncol=min(4, len(results)))
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return path


def make_charts(results: list[dict], chart_months: list[str], colors: dict[str, str], out_dir: Path,
                lang: str) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    plotted = [r for r in results if r["confidence"] != "Insufficient" or r["metrics"]["views_avg_month"] > 0]
    plotted = plotted[:MAX_SERIES]
    if not plotted:
        return {}
    multi = len({r["topic"] for r in plotted}) > 1
    return {
        "trend": str(trend_chart(plotted, chart_months, colors, out_dir / "trend.png", lang, multi)),
        "growth": str(growth_chart(plotted, colors, out_dir / "growth.png", lang, multi)),
        "views": str(views_chart(plotted, chart_months, colors, out_dir / "views.png", lang, multi)),
    }
