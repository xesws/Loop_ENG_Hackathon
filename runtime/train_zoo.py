"""Closed method zoo for long-node compute.

Maps research-question / plan tokens -> allowlisted --model flags from the
trainer registry. Supervisor contract unchanged: same metrics.jsonl + ckpt
layout, different fit.
"""
from __future__ import annotations

from runtime.trainers import allowed, normalize


def normalize_model(name: str | None) -> str:
    return normalize(name)


def infer_model_from_question(question: str) -> str:
    ql = (question or "").lower()
    if "lasso" in ql:
        return "lasso"
    if "ridge" in ql:
        return "ridge"
    if ("decision tree" in ql or "depth-2" in ql or "depth 2" in ql
            or "depth2" in ql):
        return "tree"
    if ("gradient boosting" in ql or "gbdt" in ql or "xgboost" in ql
            or "gbrt" in ql):
        return "gbdt"
    return "gbdt"


def parse_model_from_cmd(cmd: list | None) -> str | None:
    if not cmd:
        return None
    for i, tok in enumerate(cmd):
        if tok == "--model" and i + 1 < len(cmd):
            return normalize_model(cmd[i + 1])
        if isinstance(tok, str) and tok.startswith("--model="):
            return normalize_model(tok.split("=", 1)[1])
    return None


def _cmd_has_model_flag(cmd: list | None) -> bool:
    if not cmd:
        return False
    return any(t == "--model" or (isinstance(t, str) and t.startswith("--model="))
               for t in cmd)


def infer_model_for_node(node, question: str) -> str:
    """Prefer explicit compute --model, then id/acceptance hints, then question."""
    cmd = getattr(getattr(node, "compute", None), "cmd", None)
    if _cmd_has_model_flag(cmd):
        return parse_model_from_cmd(cmd) or "gbdt"
    blob = f"{getattr(node, 'id', '')} {getattr(node, 'role', '')} "
    acc = getattr(node, "acceptance", None) or []
    blob += " ".join(str(x) for x in acc)
    blob = blob.lower()
    if "lasso" in blob:
        return "lasso"
    if "ridge" in blob:
        return "ridge"
    if "tree" in blob or "decision" in blob:
        return "tree"
    if "boost" in blob or "gbdt" in blob:
        return "gbdt"
    if "linear" in blob and "baseline" not in blob:
        return "ridge"
    return infer_model_from_question(question)


def with_model_flag(cmd: list, model: str) -> list:
    model = normalize_model(model)
    out: list = []
    skip = False
    for tok in cmd:
        if skip:
            skip = False
            continue
        if tok == "--model":
            skip = True
            continue
        if isinstance(tok, str) and tok.startswith("--model="):
            continue
        out.append(tok)
    out.extend(["--model", model])
    return out


def pin_long_models(graph, question: str) -> dict[str, str]:
    """Stamp every long node's compute.cmd with an allowlisted --model.
    Returns {node_id: model} for logging."""
    from graph.schema import Kind
    # touch allowlist so callers fail fast if registry is empty
    assert allowed(), "trainer registry is empty"
    chosen: dict[str, str] = {}
    for nid, n in graph.nodes.items():
        if n.kind != Kind.LONG or n.compute is None:
            continue
        model = infer_model_for_node(n, question)
        n.compute.cmd = with_model_flag(list(n.compute.cmd), model)
        chosen[nid] = model
    return chosen
