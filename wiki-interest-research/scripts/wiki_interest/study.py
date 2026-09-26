"""Study = a directory holding the question's parameters (study.json) and all outputs.
Follow-up requests ("add German", "use 3 years", "weight audience size more") modify the
study and re-run; the SQLite cache makes that nearly free."""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .charts import PALETTE

DEFAULT_ROOT = Path("wiki-interest-studies")


@dataclass
class StudyConfig:
    topics: list[str] = field(default_factory=list)          # topic specs, see resolve.parse_topic
    langs: list[str] = field(default_factory=list)
    articles: list[str] = field(default_factory=list)        # manual 'lang:Title' or 'lang:Title@topic'
    months: int = 24
    end: str | None = None
    weights: dict[str, float] | None = None
    redirects: bool = True
    colors: dict[str, str] = field(default_factory=dict)     # 'topic|lang' -> hex, stable across re-runs


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "study"


def default_dir(cfg: StudyConfig) -> Path:
    topic = cfg.topics[0].split("=")[0] if cfg.topics else "study"
    return DEFAULT_ROOT / slugify(f"{topic}-{'-'.join(cfg.langs)}")


def load(path: Path) -> StudyConfig:
    data = json.loads((path / "study.json").read_text("utf-8"))
    known = StudyConfig.__dataclass_fields__
    return StudyConfig(**{k: v for k, v in data.items() if k in known})


def save(path: Path, cfg: StudyConfig) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "study.json").write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), "utf-8")


def assign_colors(cfg: StudyConfig, keys: list[str]) -> dict[str, str]:
    """Keep existing colours; give new series the next unused palette slot (fixed order)."""
    colors = {k: v for k, v in cfg.colors.items() if k in keys}
    used = set(colors.values())
    free = [c for c in PALETTE if c not in used]
    for k in keys:
        if k not in colors:
            colors[k] = free.pop(0) if free else PALETTE[len(colors) % len(PALETTE)]
    cfg.colors = {**cfg.colors, **colors}
    return colors


def manual_articles(cfg: StudyConfig, topic_index: int) -> dict[str, list[str]]:
    """Manual articles: 'lang:Title' belongs to the first topic, 'lang:Title@<topic label>' to that topic."""
    label = cfg.topics[topic_index].split("=")[0].strip().lower()
    out: dict[str, list[str]] = {}
    for spec in cfg.articles:
        body, _, target = spec.partition("@")
        lang, _, title = body.partition(":")
        if not title.strip():
            continue
        if (target.strip().lower() == label) if target else topic_index == 0:
            out.setdefault(lang.strip().lower(), []).append(title.strip())
    return out
