"""Anytime report — regenerated from the verified-set on every relevant event.

Pull the plug at any tick and report.md is a coherent snapshot of currently
verified knowledge. Killing a node still leaves a valid report.
"""
from __future__ import annotations

from pathlib import Path

from core.supervisor import Supervisor
from graph.schema import Graph, Status
from runtime.fs import atomic_write_text


def _method_line(sup: Supervisor, nid: str) -> str:
    n = sup.g.nodes[nid]
    d = sup.det.get(nid)
    bd = n.best_dev
    bd_s = f"{bd:.4f}" if bd is not None else "n/a"
    ck = f" (best ckpt @ step {d.best_ckpt})" if d and d.best_ckpt is not None else ""
    return f"- status: `{n.status.value}` · best dev_metric: **{bd_s}**{ck}"


def render(graph: Graph, sup: Supervisor, run_dir: Path, scenario: str,
           tick: int, version: int) -> None:
    g = graph
    lines: list[str] = []
    lines.append(f"# Auto-Research Report — {g.research_question}")
    lines.append("")
    lines.append(f"_scenario: **{scenario}** · tick: {tick} · report v{version}_")
    lines.append("")

    # Baseline section (N3)
    n3 = g.nodes.get("N3")
    lines.append("## Baseline (N3 — few-shot large model)")
    if n3 is not None:
        base = n3.expected_score
        lines.append(f"- status: `{n3.status.value}` · dev_metric: "
                     f"**{base:.3f}**" if base is not None else f"- status: `{n3.status.value}`")
    lines.append("")

    # Method / final section (N4)
    lines.append("## Method (N4 — fine-tuned small model)")
    lines.append(_method_line(sup, "N4"))
    lines.append("")

    # Verdict (research_verdict already handles the comparability-blocked case)
    lines.append("## Verdict")
    lines.append(sup.research_verdict()["line"])
    lines.append("")

    # Ablation (N7) if it was spawned
    n7 = g.nodes.get("N7")
    if n7 is not None and n7.active:
        lines.append("## Ablation (N7 — spawned by graph surgery)")
        lines.append(f"- status: `{n7.status.value}` "
                     "(dynamically inserted to explain the plateau)")
        lines.append("")

    # Incident black box
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
