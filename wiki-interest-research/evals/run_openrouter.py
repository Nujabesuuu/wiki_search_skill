"""Minimal tool-calling agent to run an eval scenario on any OpenRouter model.

It mimics how skill-aware agents work: the model first sees only the skill's name and
description (progressive disclosure) and must read SKILL.md itself, then acts with three tools
(bash, read_file, write_file). Multi-turn scenarios send the next user message after the
model gives a final answer.

Usage:
  OPENROUTER_API_KEY=... python evals/run_openrouter.py --model qwen/qwen3.8-27b:free \
      --eval-id astronomy-uk-trust --out ../eval-workspace/qwen/astronomy-uk-trust
The key can also live in a .env file next to the repo root (never commit it).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
EVALS_FILE = SKILL_DIR / "evals" / "evals.json"
API = "https://openrouter.ai/api/v1/chat/completions"

TOOLS = [
    {"type": "function", "function": {
        "name": "bash", "description": "Run a shell command in the working directory and return stdout+stderr.",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "read_file", "description": "Read a text file (absolute or relative to the working directory).",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file", "description": "Create or overwrite a text file.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                       "required": ["path", "content"]}}},
]


def api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    repo_skill = Path(__file__).resolve().parents[1]
    for env in (repo_skill.parent / ".env", repo_skill / ".env"):
        if not key and env.exists():
            m = re.search(r"^OPENROUTER_API_KEY=(.+)$", env.read_text(), re.M)
            key = m.group(1).strip() if m else None
    if not key:
        sys.exit("OPENROUTER_API_KEY is not set")
    return key


def frontmatter() -> tuple[str, str]:
    text = (SKILL_DIR / "SKILL.md").read_text("utf-8")
    name = re.search(r"^name:\s*(.+)$", text, re.M).group(1).strip()
    desc = re.search(r"^description:\s*(.+)$", text, re.M).group(1).strip()
    return name, desc


def call(model: str, messages: list, key: str) -> dict:
    body = json.dumps({"model": model, "messages": messages, "tools": TOOLS, "temperature": 0.2}).encode()
    for attempt in range(6):
        req = urllib.request.Request(API, data=body, headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/Nujabesuuu/wiki_search_skill", "X-Title": "wiki-interest-research evals"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = json.loads(r.read())
            if "choices" in data:
                return data
            err = data.get("error", data)
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", "replace")[:400]
            if e.code not in (429, 500, 502, 503, 504):
                raise RuntimeError(f"HTTP {e.code}: {err}")
        wait = 15 * (attempt + 1)
        print(f"  retry in {wait}s: {str(err)[:160]}", file=sys.stderr)
        time.sleep(wait)
    raise RuntimeError("OpenRouter kept failing")


def run_tool(name: str, args: dict, workdir: Path) -> str:
    try:
        if name == "bash":
            p = subprocess.run(args["command"], shell=True, cwd=workdir, capture_output=True, text=True, timeout=900)
            out = (p.stdout + ("\n[stderr]\n" + p.stderr if p.stderr.strip() else "")) + f"\n[exit {p.returncode}]"
        elif name == "read_file":
            path = Path(args["path"])
            out = (path if path.is_absolute() else workdir / path).read_text("utf-8")
        elif name == "write_file":
            path = Path(args["path"])
            path = path if path.is_absolute() else workdir / path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(args["content"], "utf-8")
            out = f"wrote {len(args['content'])} chars to {path}"
        else:
            out = f"unknown tool {name}"
    except Exception as e:  # the model should see failures and recover
        out = f"ERROR: {type(e).__name__}: {e}"
    if len(out) > 14000:
        out = out[:9000] + "\n...[truncated]...\n" + out[-4000:]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--eval-id", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--skill-dir", help="skill copy under test (default: this repo's skill). Use a copy without "
                                        "evals/ and tests/ so the model cannot read expected answers.")
    a = ap.parse_args()
    global SKILL_DIR
    scenario = next(e for e in json.loads(EVALS_FILE.read_text("utf-8"))["evals"] if e["id"] == a.eval_id)
    if a.skill_dir:
        SKILL_DIR = Path(a.skill_dir).resolve()
    workdir = Path(a.out).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    key = api_key()
    name, desc = frontmatter()
    system = (f"You are an autonomous assistant with shell access. Working directory: {workdir}\n"
              f"Available Agent Skills (read the SKILL.md before using a skill):\n"
              f"- name: {name}\n  description: {desc}\n  location: {SKILL_DIR}/SKILL.md\n"
              "Act with tools. When the user's request is complete, reply with your final answer and no tool call.")
    messages = [{"role": "system", "content": system}]
    transcript, answers, usage = [], [], {"prompt_tokens": 0, "completion_tokens": 0, "requests": 0}
    t0 = time.time()
    for turn in scenario["turns"]:
        messages.append({"role": "user", "content": turn})
        for step in range(a.max_steps):
            data = call(a.model, messages, key)
            usage["requests"] += 1
            for k in ("prompt_tokens", "completion_tokens"):
                usage[k] += (data.get("usage") or {}).get(k, 0)
            msg = data["choices"][0]["message"]
            clean = {"role": "assistant", "content": msg.get("content") or ""}
            if msg.get("tool_calls"):
                clean["tool_calls"] = msg["tool_calls"]
            messages.append(clean)
            transcript.append({"assistant": clean})
            if not msg.get("tool_calls"):
                answers.append(clean["content"])
                break
            for tc in msg["tool_calls"]:
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = run_tool(tc["function"]["name"], args, workdir)
                print(f"  [{step}] {tc['function']['name']}: {json.dumps(args, ensure_ascii=False)[:140]}", file=sys.stderr)
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
                transcript.append({"tool": tc["function"]["name"], "args": args, "result": result[:3000]})
            time.sleep(3.5)   # free tier: ~20 requests/minute
        else:
            answers.append("[max steps reached without a final answer]")
    (workdir / "final_answer.md").write_text(answers[-1] if answers else "", "utf-8")
    (workdir / "final_answers.json").write_text(json.dumps(answers, ensure_ascii=False, indent=1), "utf-8")
    (workdir / "transcript.json").write_text(json.dumps(transcript, ensure_ascii=False, indent=1), "utf-8")
    (workdir / "timing.json").write_text(json.dumps({**usage, "duration_s": round(time.time() - t0, 1),
                                                     "model": a.model}, indent=1))
    print(json.dumps({"model": a.model, "eval": a.eval_id, **usage}), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
