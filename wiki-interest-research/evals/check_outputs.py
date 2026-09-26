"""Objective checks for one eval run directory.

Usage: python evals/check_outputs.py RUN_DIR --lang uk [--needs-report]
RUN_DIR must contain final_answer.md (the agent's last chat answer) and the study folder(s)
the agent created. Prints JSON; the grader uses it as evidence.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from wiki_interest.verify import _always_ok, _matches, extract_numbers, known_values  # noqa: E402


def pdf_pages(path: Path) -> int:
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(path)).pages)
    except ImportError:
        return len(re.findall(rb"/Type\s*/Page[^s]", path.read_bytes()))


def script_of(text: str) -> str:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "unknown"
    cyr = sum("Ѐ" <= c <= "ӿ" for c in letters) / len(letters)
    return "cyrillic" if cyr > 0.3 else "latin"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--lang", required=True, help="language the user wrote in")
    ap.add_argument("--needs-report", action="store_true")
    a = ap.parse_args()
    run = Path(a.run_dir)
    out: dict = {"run_dir": str(run)}

    summaries = sorted(run.rglob("summary.json"), key=lambda p: p.stat().st_mtime)
    out["studies"] = [str(p.parent) for p in summaries]
    reports = sorted(run.rglob("report-*.pdf"), key=lambda p: p.stat().st_mtime)
    out["reports"] = [{"path": str(p), "pages": pdf_pages(p), "lang": p.stem.split("-", 1)[1]} for p in reports]
    out["narrative_verified"] = bool(list(run.rglob("narrative.verified.json")))

    answer_path = run / "final_answer.md"
    answer = answer_path.read_text("utf-8") if answer_path.exists() else ""
    out["final_answer_chars"] = len(answer)
    expected_script = "cyrillic" if a.lang in ("uk", "ru", "bg", "sr", "be") else "latin"
    out["answer_script"] = script_of(answer)
    out["answer_language_ok"] = out["answer_script"] == expected_script

    if summaries and answer:
        values = []
        protected = []
        for sp in summaries:
            s = json.loads(sp.read_text("utf-8"))
            values += known_values(s)
            protected += [t for r in s["results"] for t in r["articles"]] + [r["topic"] for r in s["results"]]
            protected += [m for x in s["missing"] for m in x.get("suggestions", [])]
            protected += [str(Path(s["study"]).name)]
        # paths and file names contain digits that are not claims
        cleaned = re.sub(r"\S*[/\\]\S*|\S+\.(pdf|png|json|csv)\b", " ", answer)
        nums = extract_numbers(cleaned, protected)
        unmatched = [n["raw"] for n in nums
                     if not any(_always_ok(r) for r in n["readings"])
                     and not any(_matches(r, v) for r in n["readings"] for _, v in values)]
        checked = [n for n in nums if not any(_always_ok(r) for r in n["readings"])]
        out["answer_numbers_checked"] = len(checked)
        out["answer_numbers_unmatched"] = unmatched
    ok = bool(summaries) and out["answer_language_ok"] and not out.get("answer_numbers_unmatched")
    if a.needs_report:
        ok = ok and any(r["pages"] == 1 for r in out["reports"]) and out["narrative_verified"]
    out["all_objective_checks_passed"] = ok
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
