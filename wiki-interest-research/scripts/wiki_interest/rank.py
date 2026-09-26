"""Rank (topic, language) options by a transparent weighted score.

Each criterion is z-scored across the compared options, then weighted. Weights are the
user's definition of "promising" and can be overridden (e.g. a team that cares about audience
size more than momentum: --weights volume=0.6,growth=0.2,share=0.1,confidence=0.1).
"""
from __future__ import annotations

import math

import numpy as np

DEFAULT_WEIGHTS = {"growth": 0.40, "volume": 0.25, "share": 0.20, "confidence": 0.15}
CRITERIA_DOC = {
    "growth": "YoY growth of normalized interest with spike days removed (momentum)",
    "volume": "log of average monthly views (audience size in that language)",
    "share": "log of views per million pageviews of that wiki (salience relative to wiki size)",
    "confidence": "evidence quality (High=1, Medium=0.6, Low=0.2)",
}
_CONF = {"High": 1.0, "Medium": 0.6, "Low": 0.2}


class WeightsError(ValueError):
    pass


def parse_weights(spec: str | dict | None) -> dict[str, float]:
    if not spec:
        return dict(DEFAULT_WEIGHTS)
    raw = spec if isinstance(spec, dict) else dict(
        part.split("=", 1) for part in str(spec).replace(" ", "").split(",") if part)
    weights = {}
    for k, v in raw.items():
        if k not in DEFAULT_WEIGHTS:
            raise WeightsError(f"Unknown weight '{k}'. Allowed: {', '.join(DEFAULT_WEIGHTS)}")
        try:
            weights[k] = float(v)
        except ValueError:
            raise WeightsError(f"Weight '{k}' must be a number, got '{v}'")
        if weights[k] < 0:
            raise WeightsError("Weights must be >= 0")
    total = sum(weights.values())
    if total <= 0:
        raise WeightsError("At least one weight must be positive")
    return {k: round(weights.get(k, 0.0) / total, 3) for k in DEFAULT_WEIGHTS}


def _features(r: dict) -> dict[str, float]:
    m = r["metrics"]
    growth = m["growth_yoy_no_spikes_pct"]
    if growth is None:
        growth = m["growth_yoy_pct"] or 0.0
    return {
        "growth": float(growth),
        "volume": math.log10(max(m["views_avg_month"], 1)),
        "share": math.log10(max(m["views_per_million"] or 0.0, 1e-3)),
        "confidence": _CONF.get(r["confidence"], 0.0),
    }


def rank(results: list[dict], weights: dict[str, float]) -> list[dict]:
    rankable = [r for r in results if r["confidence"] != "Insufficient"]
    feats = [_features(r) for r in rankable]
    z = {}
    for k in DEFAULT_WEIGHTS:
        col = np.array([f[k] for f in feats], dtype=float)
        sd = col.std()
        z[k] = (col - col.mean()) / sd if len(col) > 1 and sd > 0 else np.zeros(len(col))
    rows = []
    for i, r in enumerate(rankable):
        contrib = {k: float(weights[k] * z[k][i]) for k in DEFAULT_WEIGHTS}
        best = max(contrib, key=contrib.get)
        worst = min(contrib, key=contrib.get)
        rows.append({
            "topic": r["topic"], "lang": r["lang"],
            "score": round(sum(contrib.values()), 2),
            "strongest_factor": best if contrib[best] > 0 else None,
            "weakest_factor": worst if contrib[worst] < 0 else None,
            "confidence": r["confidence"],
        })
    rows.sort(key=lambda x: -x["score"])
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    for r in results:
        if r["confidence"] == "Insufficient":
            rows.append({"topic": r["topic"], "lang": r["lang"], "rank": None, "score": None,
                         "confidence": "Insufficient", "note": "not ranked: insufficient data"})
    return rows
