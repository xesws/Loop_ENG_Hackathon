"""Live planner — one LLM call turns a research question into a validated graph.

Uses OpenRouter (OpenAI-compatible) over stdlib urllib (no new deps). Model comes
from env LIVE_MODEL (default a cheap model); the API key comes from env
OPENROUTER_API_KEY and is never hardcoded or printed. On ANY failure — no key,
network error, unparseable output, or schema/normalizer rejection — it falls back
to the cached plan so the caller always ends up with a valid graph.
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

from graph import normalizer, schema

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-4o-mini"

_SYSTEM = (
    "You are a research-graph planner for an async, graph-native auto-research "
    "supervisor. You output ONLY a single JSON object (no prose, no markdown "
    "fences) describing the task graph for the user's research question."
)


def _user_prompt(question: str, template_json: str, feedback: str | None = None) -> str:
    fb = ""
    if feedback:
        fb = ("\n\nYour PREVIOUS attempt was rejected by the validator with:\n"
              f"{feedback}\nFix ONLY these problems; output the corrected JSON object.\n\n")
    return (
        f"Research question:\n{question}\n\n" + fb +
        "Produce the task graph as JSON with EXACTLY this structure (same keys, the "
        "same node ids N0..N7, the same `kind`/`resource`/`compute`/`triggers`/"
        "`spawn_only` wiring, the same `edges` and `resources`). You MAY rewrite "
        "`research_question` to the user's question and adapt each node's `role` and "
        "`seed`/`expected_score` to fit the question, but do NOT add or remove nodes "
        "or edges and keep N4 a long node with its compute block. Output ONLY the "
        "JSON object.\n\nTemplate to adapt:\n" + template_json
    )


def _extract_json(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1]
        if t.startswith("json"):
            t = t[4:]
    i, j = t.find("{"), t.rfind("}")
    if i == -1 or j == -1:
        raise ValueError("no JSON object in model output")
    return t[i:j + 1]


def _call_llm(question: str, template_json: str, model: str, api_key: str,
              timeout: int = 60, feedback: str | None = None) -> tuple[str, float | None]:
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": _SYSTEM},
                     {"role": "user", "content": _user_prompt(question, template_json,
                                                              feedback)}],
        "temperature": 0.2,
        "max_tokens": 1600,
    }
    req = urllib.request.Request(
        OPENROUTER_URL, data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json",
                 "X-Title": "OOAA-planner"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    if "error" in data:
        raise RuntimeError(str(data["error"])[:200])
    content = data["choices"][0]["message"]["content"]
    cost = data.get("usage", {}).get("cost")
    return content, cost


def generate_plan(question: str, run_dir: Path, cached_path: Path) -> dict:
    """One live LLM call -> validated plan_live.json (falls back to cached).
    Returns a result dict (source/model/cost/valid/error/out)."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / "plan_live.json"
    cached = Path(cached_path).read_text(encoding="utf-8")
    model = os.environ.get("LIVE_MODEL") or DEFAULT_MODEL
    api_key = os.environ.get("OPENROUTER_API_KEY")
    result = {"source": "live", "model": model, "cost": None, "valid": False,
              "question": question, "out": str(out)}
    try:
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY unset")
        content, cost = _call_llm(question, cached, model, api_key)
        result["cost"] = cost
        obj = json.loads(_extract_json(content))
        out.write_text(json.dumps(obj, indent=2), encoding="utf-8")
        g = schema.load_plan(out)                 # parse
        errs = schema.validate(g)                 # structural validation
        if errs:
            raise ValueError("schema errors: " + "; ".join(errs[:5]))
        normalizer.normalize(g)                   # DAG / back-edge check
        result["valid"] = True
        return result
    except Exception as e:                         # graceful fallback
        out.write_text(cached, encoding="utf-8")
        result.update(source="fallback_cached", valid=True, error=str(e)[:300])
        return result


def _validate_live_plan(out: Path) -> str | None:
    """None if the plan file loads+validates+normalizes, else the error text."""
    try:
        g = schema.load_plan(out)
        errs = schema.validate(g)
        if errs:
            return "schema errors: " + "; ".join(errs[:5])
        normalizer.normalize(g)
        return None
    except Exception as e:
        return str(e)[:300]


def _last_good_plan(search_dir: Path, exclude: Path) -> Path | None:
    """Most recent previously generated plan that still passes validation —
    the 'last successful generation' fallback after three strikes."""
    search_dir = Path(search_dir)
    if not search_dir.exists():
        return None
    for cand in sorted(search_dir.glob("*/plan_live.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True):
        if cand.resolve() == Path(exclude).resolve():
            continue
        if _validate_live_plan(cand) is None:
            return cand
    return None


def generate_plan_retry(question: str, run_dir: Path, cached_path: Path,
                        max_attempts: int = 3,
                        search_dir: Path | None = None) -> dict:
    """M12: live planner with error-feedback retries. Each rejection (parse /
    schema / normalizer) is fed back into the next attempt's prompt (携错重试).
    After `max_attempts` strikes: fall back to the most recent successful
    generation under `search_dir` (annotated fallback_last_good), else to the
    cached plan (fallback_cached). Every hop is recorded in the result dict."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / "plan_live.json"
    cached = Path(cached_path).read_text(encoding="utf-8")
    model = os.environ.get("LIVE_MODEL") or DEFAULT_MODEL
    api_key = os.environ.get("OPENROUTER_API_KEY")
    result = {"source": "live", "model": model, "cost": 0.0, "valid": False,
              "question": question, "out": str(out), "attempts": 0, "errors": []}
    feedback = None
    try:
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY unset")
        for attempt in range(1, max(1, int(max_attempts)) + 1):
            result["attempts"] = attempt
            try:
                content, cost = _call_llm(question, cached, model, api_key,
                                          feedback=feedback)
                result["cost"] = round((result["cost"] or 0.0) + (cost or 0.0), 6)
                obj = json.loads(_extract_json(content))
                out.write_text(json.dumps(obj, indent=2), encoding="utf-8")
                err = _validate_live_plan(out)
                if err is None:
                    result["valid"] = True
                    return result
                raise ValueError(err)
            except Exception as e:
                feedback = str(e)[:300]
                result["errors"].append(f"attempt {attempt}: {feedback}")
        raise RuntimeError("planner strikes out: " + (feedback or "?"))
    except Exception as e:
        last = _last_good_plan(search_dir or (run_dir.parent), out)
        if last is not None:
            out.write_text(last.read_text(encoding="utf-8"), encoding="utf-8")
            result.update(source="fallback_last_good", valid=True,
                          error=str(e)[:300], last_good=str(last))
        else:
            out.write_text(cached, encoding="utf-8")
            result.update(source="fallback_cached", valid=True, error=str(e)[:300])
        return result
