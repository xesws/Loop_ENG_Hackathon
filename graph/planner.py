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


def _user_prompt_free(question: str, example_json: str,
                      feedback: str | None = None) -> str:
    """M17 free-topology planner prompt: ids/count/edges are the LLM's choice;
    only role-completeness and the compute contract are hard constraints."""
    fb = ""
    if feedback:
        fb = ("\n\nYour PREVIOUS attempt was rejected by the validator with:\n"
              f"{feedback}\nFix ONLY these problems; output the corrected JSON object.\n\n")
    return (
        f"Research question:\n{question}\n\n" + fb +
        "Design the task graph as JSON. You are FREE to choose node ids, the node "
        "count, and the edges (any DAG; declare iterations as back_edge with "
        "max_laps). Role vocabulary: protocol | data | harness | experiment | "
        "eval | analysis | report | ablation.\n"
        "HARD constraints (a validator will check each):\n"
        "1. at least one protocol node at the very top (no artifact parents)\n"
        "2. every experiment node is downstream of a harness node (artifact edges)\n"
        "3. every analysis node has >=2 experiment nodes among its transitive inputs\n"
        "4. every long node carries a compute block (cmd/profile/steps/"
        "ckpt_every_pct/metrics_file/ckpt_dir)\n"
        "5. node ids are free-form, node count is free\n"
        "Node keys: id, kind(fast|long|reactive), resource(cpu|gpu; long=gpu, "
        "others=cpu), role, seed, [metric], [expected_score], [acceptance argv], "
        "[compute], [triggers], [can_spawn], [spawn_only], [spawned_by]. A fast "
        "experiment node carrying expected_score + acceptance [\"python\", "
        "\"eval/score.py\", \"--who\", \"baseline\"] is the frozen BASELINE; give "
        "method experiments [\"python\", \"eval/score.py\", \"--who\", \"method\"]. "
        "A reactive eval node with a trigger on a long node's \"ckpt\" event reads "
        "checkpoints. Edge keys: src, dst, kind(artifact|stream|back_edge), "
        "[event], [max_laps]. Top level: nodes, edges, resources{gpu,cpu}, "
        "budget{max_ticks}, protocol_version, research_question.\n"
        "Output ONLY the JSON object.\n\n"
        "One valid example (structure illustration only — do NOT copy its "
        "topology):\n" + example_json
    )


def _ancestors(g, nid) -> set:
    """Transitive artifact parents (hard dependency chain)."""
    seen: set = set()
    stack = list(g.artifact_parents(nid))
    while stack:
        cur = stack.pop()
        if cur not in seen:
            seen.add(cur)
            stack.extend(g.artifact_parents(cur))
    return seen


def _soft_ancestors(g, nid) -> set:
    """Transitive artifact+stream parents (analysis/report feed edges)."""
    seen: set = set()
    stack = list(g.artifact_parents(nid)) + list(g.stream_parents(nid))
    while stack:
        cur = stack.pop()
        if cur not in seen:
            seen.add(cur)
            stack.extend(g.artifact_parents(cur))
            stack.extend(g.stream_parents(cur))
    return seen


def validate_roles(g) -> list:
    """M17 role-completeness law for free plans (planner-side policy, not schema):
    1 protocol-at-top; 2 harness upstream of every experiment; 3 analysis has
    >=2 experiment inputs (via artifact or stream); (4 long-compute is schema's job)."""
    from runtime import roles
    errs: list = []
    protos = [nid for nid, n in g.nodes.items() if n.role == "protocol"]
    if not any(not g.artifact_parents(nid) for nid in protos):
        errs.append("need >=1 protocol node at the very top (no artifact parents)")
    harnesses = {nid for nid, n in g.nodes.items() if n.role == "harness"}
    exps = [nid for nid in g.nodes if roles.is_experiment(g.nodes[nid])]
    for e in exps:
        if not (_ancestors(g, e) & harnesses):
            errs.append(f"experiment {e}: no harness upstream (artifact chain)")
    for nid, n in g.nodes.items():
        if n.kind == schema.Kind.REACTIVE and n.role == "analysis":
            reach = _soft_ancestors(g, nid)
            n_in = sum(1 for e in exps if e in reach)
            if n_in < 2:
                errs.append(f"analysis {nid}: needs >=2 experiment inputs, has {n_in}")
    return errs


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
              timeout: int = 60, feedback: str | None = None,
              free: bool = False) -> tuple[str, float | None]:
    prompt = (_user_prompt_free(question, template_json, feedback) if free
              else _user_prompt(question, template_json, feedback))
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": _SYSTEM},
                     {"role": "user", "content": prompt}],
        # Free topology needs diversity for the M17 GATE; cached adapts stay sticky.
        "temperature": 0.7 if free else 0.2,
        "max_tokens": 3500 if free else 2200,
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


def _validate_live_plan(out: Path, check_roles: bool = False) -> str | None:
    """None if the plan file loads+validates+normalizes, else the error text."""
    try:
        g = schema.load_plan(out)
        errs = schema.validate(g)
        if errs:
            return "schema errors: " + "; ".join(errs[:5])
        normalizer.normalize(g)
        if check_roles:
            rerrs = validate_roles(g)
            if rerrs:
                return "role-completeness errors: " + "; ".join(rerrs[:5])
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
                        search_dir: Path | None = None,
                        free: bool = False) -> dict:
    """M12: live planner with error-feedback retries. Each rejection (parse /
    schema / normalizer) is fed back into the next attempt's prompt (携错重试).
    After `max_attempts` strikes: fall back to the most recent successful
    generation under `search_dir` (annotated fallback_last_good), else to the
    cached plan (fallback_cached). Every hop is recorded in the result dict.
    M17: free=True switches to the free-topology prompt and adds the
    role-completeness validator to each attempt's checks."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / "plan_live.json"
    cached = Path(cached_path).read_text(encoding="utf-8")
    model = os.environ.get("LIVE_MODEL") or DEFAULT_MODEL
    api_key = os.environ.get("OPENROUTER_API_KEY")
    result = {"source": "live", "model": model, "cost": 0.0, "valid": False,
              "question": question, "out": str(out), "attempts": 0,
              "errors": [], "free": free}
    feedback = None
    try:
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY unset")
        for attempt in range(1, max(1, int(max_attempts)) + 1):
            result["attempts"] = attempt
            try:
                if free:
                    content, cost = _call_llm(question, cached, model, api_key,
                                              feedback=feedback, free=True)
                else:
                    content, cost = _call_llm(question, cached, model, api_key,
                                              feedback=feedback)
                result["cost"] = round((result["cost"] or 0.0) + (cost or 0.0), 6)
                obj = json.loads(_extract_json(content))
                out.write_text(json.dumps(obj, indent=2), encoding="utf-8")
                err = _validate_live_plan(out, check_roles=free)
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
