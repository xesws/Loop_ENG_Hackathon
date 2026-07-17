"""Role-generic anytime report renderer (M17) — same anytime semantics as
core/report.py but sections are anchored by role/topology, not node ids.
Used only by FreeOrchestrator; the mock path's renderer is untouched."""
from __future__ import annotations

from pathlib import Path

from core.supervisor import Supervisor
from graph.schema import Graph
from runtime import roles
from runtime.fs import atomic_write_text


def _fmt(x):
    return f"{x:.4f}" if isinstance(x, (int, float)) else "n/a"


def render(graph: Graph, sup: Supervisor, run_dir: Path, scenario: str,
           tick: int, version: int) -> None:
    g = graph
    base = roles.baseline_node(g)
    methods = roles.method_nodes(g)
    lines: list = [f"# Auto-Research Report — {g.research_question}", "",
                   f"_scenario: **{scenario}** · tick: {tick} · report v{version}_", ""]

    bn = g.nodes[base]
    lines.append(f"## Baseline ({base} — {bn.role})")
    lines.append(f"- status: `{bn.status.value}` · dev_metric: "
                 f"**{_fmt(bn.expected_score)}**")
    lines.append("")
    for m in methods:
        mn = g.nodes[m]
        d = sup.det.get(m)
        ck = (f" (best ckpt @ step {d.best_ckpt})"
              if d and d.best_ckpt is not None else "")
        lines.append(f"## Method ({m} — {mn.role})")
        lines.append(f"- status: `{mn.status.value}` · best dev_metric: "
                     f"**{_fmt(mn.best_dev)}**{ck}")
        lines.append("")
    lines.append("## Verdict")
    lines.append(sup.research_verdict()["line"])
    lines.append("")
    spawned = [nid for nid, n in g.nodes.items() if n.spawn_only and n.active]
    if spawned:
        lines.append("## Ablations (spawned by graph surgery)")
        for nid in spawned:
            lines.append(f"- {nid} ({g.nodes[nid].role}): "
                         f"`{g.nodes[nid].status.value}`")
        lines.append("")
    incs = sup.log.all()
    lines.append("## Incidents (black box)")
    if not incs:
        lines.append("- none")
    else:
        for i in incs:
            lines.append(f"- `{i.type}` node={i.node} action={i.ladder_action} "
                         f"(tick {i.ts})")
    lines.append("")
    out = run_dir / "report" / "report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(out, "\n".join(lines) + "\n")
