"""Replay renderer: re-render a run's ticks from replay.jsonl WITHOUT executing.

Each replay line is the full post-decide snapshot of a tick, so replay is a pure
function of the file — no worker, no subprocess, no fingerprinting. This is the
demo's ultimate fallback: play the recording, the mechanism is still real.
"""
from __future__ import annotations

import json
from pathlib import Path


def replay_render(path: Path) -> int:
    path = Path(path)
    if not path.exists():
        print(f"replay file not found: {path}")
        return 1
    lines = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()
             if ln.strip()]
    if not lines:
        print("empty replay")
        return 1

    print(f"=== REPLAY {path} ({len(lines)} ticks) — no workers, pure re-render ===")
    all_incidents = []
    for rec in lines:
        parts = []
        if rec.get("admitted"):
            parts.append("admit=" + ",".join(rec["admitted"]))
        if rec.get("freed"):
            parts.append("freed=" + ",".join(rec["freed"]))
        if rec.get("spawned"):
            parts.append("spawn=" + ",".join(rec["spawned"]))
        for s in rec.get("streams", []):
            parts.append(f"{s['src']}/{s['event']}->{','.join(s['dst'])}")
        for i in rec.get("incidents", []):
            all_incidents.append(i)
            parts.append(f"!{i['type']}({i['node']}/{i['ladder_action']})")
        prog = ""
        for n in rec["nodes"]:
            if n.get("kind") == "long" and n.get("step") is not None:
                prog = f"  [{n['id']} step={n['step']} best={n.get('best_dev')}]"
        summary = " ".join(parts) if parts else "(idle)"
        print(f"t{rec['tick']:>3} {summary}{prog}")

    final = lines[-1]["nodes"]
    print("=== final statuses ===")
    for n in final:
        extra = f"  best_dev={n['best_dev']}" if n.get("best_dev") is not None else ""
        print(f"  {n['id']:<4} {n['status']}{extra}")
    print(f"=== incidents replayed: {len(all_incidents)} ===")
    for i in all_incidents:
        print(f"  {i['type']} node={i['node']} action={i['ladder_action']} (ts {i['ts']})")
    return 0
