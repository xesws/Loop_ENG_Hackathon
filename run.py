#!/usr/bin/env python3
"""Graph Supervisor for Auto-Research — mock-first CLI.

  python run.py --mock --scenario {green|trap_b|plateau|hung}
  python run.py --replay runs/<ts>/replay.jsonl
  python run.py --live                     # not wired tonight (raises)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from core.clock import TickClock
from core.incidents import IncidentLog
from core.orchestrator import Orchestrator, RunResult
from core.supervisor import Supervisor
from graph import normalizer, schema
from runtime.mock_worker import MockWorker, load_scenario

REPO = Path(__file__).resolve().parent
TICK_S = 0.08


def parse_args():
    p = argparse.ArgumentParser("graph-supervisor")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--mock", action="store_true", help="run a mock scenario")
    mode.add_argument("--live", action="store_true", help="live mode (not wired)")
    mode.add_argument("--replay", metavar="FILE", help="re-render a replay.jsonl")
    p.add_argument("--scenario", choices=["green", "trap_b", "plateau", "hung"])
    return p.parse_args()


def load_graph() -> schema.Graph:
    g = schema.load_plan(REPO / "graph" / "plan_cached.json")
    errs = schema.validate(g)
    if errs:
        raise SystemExit("plan invalid:\n  " + "\n  ".join(errs))
    return normalizer.normalize(g)


async def run_mock(scenario_name: str) -> RunResult:
    g = load_graph()
    scenario = load_scenario(REPO / "scenarios" / f"{scenario_name}.yaml")
    ts = time.strftime("%Y%m%d-%H%M%S") + "-" + scenario_name
    run_dir = REPO / "runs" / ts
    clock = TickClock()
    log = IncidentLog(run_dir, keep_last=20)
    sup = Supervisor(g, log, now=clock.now, baseline_id="N3", target=0.58)
    worker = MockWorker(scenario, REPO, TICK_S)
    orch = Orchestrator(g, sup, worker, scenario, clock, run_dir, REPO, tick_s=TICK_S)
    result = await orch.run()
    _print_summary(result)
    return result


def _print_summary(r: RunResult) -> None:
    print(f"\n=== scenario={r.scenario}  ticks={r.ticks}  quiesced={r.quiesced} ===")
    for nid, st in r.statuses.items():
        print(f"  {nid:<4} {st}")
    print(f"incidents: {r.incidents}")
    print(r.verdict["line"])
    print(f"run_dir: {r.run_dir}")


def main() -> int:
    a = parse_args()
    if a.replay:
        from core.replay import replay_render
        return replay_render(Path(a.replay))
    if a.live:
        from runtime.worker import RealWorker
        RealWorker()          # raises: live path is tomorrow's work
        return 1
    if not a.scenario:
        raise SystemExit("--mock requires --scenario")
    result = asyncio.run(run_mock(a.scenario))
    return 0 if result.quiesced else 2


if __name__ == "__main__":
    sys.exit(main())
