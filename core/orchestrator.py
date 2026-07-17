"""Async orchestrator: ready-set + resource slots + subprocess long-node + streams.

Six-step tick (cadence ~tick_s; logical time is the tick counter, never wall):
  1 sense  — tail long-node metrics.jsonl, detect new ckpt files
  2 decide — supervisor detectors (kill long nodes ONLY at ckpt boundaries)
  3 free   — reclaim finished/killed slots
  4 flow   — dispatch stream events into reactive inboxes, run reactive passes + spawn
  5 admit  — ready-set (artifact deps verified) into free gpu/cpu slots
  6 persist— rewrite state.json (frozen schema) + append replay.jsonl + render report

Status is mutated ONLY through the supervisor. The orchestrator observes the
world (fingerprints, trajectories, gate results) and reports it.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from core import report as report_mod
from core.gates import acceptance_gate, comparability_gate
from core.supervisor import LongDecision, Supervisor
from graph.schema import Graph, Kind, Status, TERMINAL, Trigger
from runtime.fs import (atomic_write_json, fingerprint, fp8, latest_ckpt,
                        list_ckpts, tail_jsonl, write_manifest)
from runtime.mock_worker import MockWorker, build_manifest

TOKENS_FAST = 500
TOKENS_LONG = 200


@dataclass
class RunResult:
    scenario: str
    ticks: int
    run_dir: Path
    statuses: dict
    incidents: int
    verdict: dict
    quiesced: bool


@dataclass
class _Long:
    proc: object
    offset: int = 0
    seen: set = field(default_factory=set)


class Orchestrator:
    def __init__(self, graph: Graph, sup: Supervisor, worker: MockWorker,
                 scenario, clock, run_dir: Path, repo_root: Path,
                 tick_s: float = 0.08):
        self.g = graph
        self.sup = sup
        self.worker = worker
        self.scenario = scenario
        self.clock = clock
        self.run_dir = Path(run_dir)
        self.repo_root = Path(repo_root)
        self.tick_s = tick_s
        self.max_ticks = graph.budget.max_ticks
        self.cap = {"gpu": graph.resources["gpu"], "cpu": graph.resources["cpu"]}
        self.cpu_running: dict[str, int] = {}      # nid -> done_tick
        self.gpu_node: str | None = None
        self.long: dict[str, _Long] = {}
        self.fast_res: dict[str, object] = {}
        self.results: dict[str, object] = {}       # manifests for gates/verdict
        self.armed: set[str] = set()
        self.finalized: set[str] = set()
        self.spawned: set[str] = set()
        self._scope_checked: set[str] = set()
        self.report_version = 0
        self.topo_idx = {n: i for i, n in enumerate(graph.topo_order)}

    # --------------------------------------------------------------- helpers
    def _scope(self, nid: str) -> Path:
        return self.run_dir / nid

    def _artifact_ready(self, nid: str) -> bool:
        return all(self.g.nodes[p].status == Status.VERIFIED
                   for p in self.g.artifact_parents(nid))

    def _dispatch(self, events, streams):
        for src, ev in events:
            for dst in self.g.subscribers(src, ev):
                self.g.nodes[dst].inbox.append(Trigger(src, ev))
            streams.append((src, ev))

    # ------------------------------------------------------------ long nodes
    async def _start_long(self, nid):
        node = self.g.nodes[nid]
        scope = self._scope(nid)
        (scope / node.compute.ckpt_dir).mkdir(parents=True, exist_ok=True)
        script = self.repo_root / node.compute.cmd[1]
        argv = [sys.executable, str(script), "--profile", self.scenario.profile]
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(scope),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.long[nid] = _Long(proc=proc)
        self.gpu_node = nid

    def _maybe_scope_violation(self, nid) -> bool:
        """Scenario-injected out-of-scope write: the node reaches into another
        node's scope dir. We detect it by containment (the write is not under the
        node's own scope), revert it, and blame the node — all via the supervisor
        API. Returns True if a violation was detected and handled."""
        sv = self.scenario.scope_violation
        if not sv or sv.get("node") != nid or nid in self._scope_checked:
            return False
        self._scope_checked.add(nid)
        leak = (self.run_dir / sv["path"]).resolve()
        leak.parent.mkdir(parents=True, exist_ok=True)
        leak.write_text(f"# out-of-scope write by {nid} (mock injection)\n",
                        encoding="utf-8")
        scope = self._scope(nid).resolve()
        if scope == leak or scope in leak.parents:
            return False                          # actually inside its own scope
        self.sup.raise_incident(
            "SCOPE_VIOLATION", nid,
            {"out_of_scope_path": sv["path"], "own_scope": nid,
             "action": "revert", "detail": "diff landed outside declared scope"},
            "blame_routing")
        try:
            leak.unlink()                         # revert the out-of-bounds write
        except OSError:
            pass
        self.sup.transition(nid, Status.BLOCKED, "scope violation: reverted + blamed")
        return True

    def _sense_long(self, nid, events) -> bool:
        node = self.g.nodes[nid]
        L = self.long[nid]
        scope = self._scope(nid)
        recs, L.offset = tail_jsonl(scope / node.compute.metrics_file, L.offset)
        if recs:
            node.step = recs[-1]["step"]
            m = max(r["dev_metric"] for r in recs)
            node.best_dev = m if node.best_dev is None else max(node.best_dev, m)
        cur = set(list_ckpts(scope / node.compute.ckpt_dir))
        new = cur - L.seen
        L.seen |= cur
        for _ in sorted(new):
            events.append((nid, "ckpt"))
        node.tokens += TOKENS_LONG
        return bool(new)

    def _emit_long_manifest(self, nid):
        node = self.g.nodes[nid]
        scope = self._scope(nid)
        # final tail to pin step/best_dev before writing the manifest
        recs, _ = tail_jsonl(scope / node.compute.metrics_file, 0)
        if recs:
            node.step = recs[-1]["step"]
            node.best_dev = max(r["dev_metric"] for r in recs)
        score = node.best_dev if node.best_dev is not None else 0.0
        m = build_manifest(node, self.repo_root, score, scope,
                           wall_s=(node.step or 0) * self.tick_s,
                           overrides=self.scenario.override_for(nid))
        write_manifest(scope / "results.json", m)
        self.results[nid] = m

    async def _terminate(self, proc):
        try:
            if proc is not None and proc.returncode is None:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=5)
        except Exception:
            pass

    async def _finish_long(self, nid, events, freed, natural: bool):
        L = self.long.pop(nid)
        await self._terminate(L.proc)
        self._emit_long_manifest(nid)             # keeps best ckpt; writes results.json
        node = self.g.nodes[nid]
        if natural and node.acceptance:
            gr = acceptance_gate(node.acceptance, cwd=self.repo_root,
                                 env_extra={"NODE_DIR": str(self._scope(nid))})
            self.sup.judge_acceptance(nid, gr, accept_metric=node.best_dev)
        elif natural:
            self.sup.transition(nid, Status.VERIFIED, "long complete")
        events.append((nid, "done"))
        if self.gpu_node == nid:
            self.gpu_node = None
        freed.append(nid)

    async def _restart_long(self, nid):
        L = self.long.get(nid)
        await self._terminate(L.proc if L else None)
        node = self.g.nodes[nid]
        script = self.repo_root / node.compute.cmd[1]
        argv = [sys.executable, str(script), "--profile", self.scenario.profile]
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(self._scope(nid)),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.long[nid] = _Long(proc=proc, offset=L.offset if L else 0,
                               seen=L.seen if L else set())

    # ------------------------------------------------------------ fast nodes
    def _admit_fast(self, nid, tick, admitted):
        node = self.g.nodes[nid]
        self.sup.transition(nid, Status.RUNNING, "admitted")
        res = self.worker.run_fast(node, self._scope(nid))
        self.fast_res[nid] = res
        node.fp = fingerprint(self._scope(nid))
        node.fp8 = fp8(node.fp)
        self.cpu_running[nid] = tick + res.duration_ticks
        admitted.append(nid)

    def _complete_fast(self, nid, events, freed):
        node = self.g.nodes[nid]
        res = self.fast_res.get(nid)
        del self.cpu_running[nid]
        if res and res.manifest:
            self.results[nid] = res.manifest
        if node.acceptance:
            gr = acceptance_gate(node.acceptance, cwd=self.repo_root,
                                 env_extra={"NODE_DIR": str(self._scope(nid))})
            ok = self.sup.judge_acceptance(
                nid, gr, accept_metric=(res.manifest.score if res and res.manifest else None))
        else:
            self.sup.transition(nid, Status.VERIFIED, "fast complete")
            ok = True
        freed.append(nid)
        if ok:
            for e in (res.events if res else ["done"]):
                events.append((nid, e))

    # -------------------------------------------------------- reactive nodes
    def _arm_reactive(self):
        for nid, node in self.g.nodes.items():
            if node.kind == Kind.REACTIVE and nid not in self.armed:
                if self._artifact_ready(nid):
                    self.armed.add(nid)
                    if node.status == Status.PENDING:
                        self.sup.transition(nid, Status.BLOCKED, "armed")

    def _process_reactive(self) -> list:
        """Event-driven pass: N4e reads each new checkpoint (incremental reading).
        Returns newly emitted (src,event) pairs for the caller to dispatch."""
        out: list = []
        if "N4e" in self.armed and self.g.nodes["N4e"].inbox:
            self._proc_N4e(out)
        return out

    def _proc_N4e(self, out):
        node = self.g.nodes["N4e"]
        node.inbox.clear()
        ck = latest_ckpt(self._scope("N4") / "ckpt")
        if ck:
            dev = None
            for line in ck.read_text().splitlines():
                if line.startswith("dev="):
                    dev = float(line.split("=", 1)[1])
            if dev is not None:
                node.best_dev = dev
                node.fp8 = fp8(fingerprint(self._scope("N4") / "ckpt"))
            node.tokens += 50
            out.append(("N4e", "result"))

    def _finalize_reactive(self):
        """World-state driven terminal transitions for resident reactive nodes:
        a reactive node settles to verified once its producers are terminal."""
        n4 = self.g.nodes["N4"]
        # N4e: verifies once its producer N4 is terminal and no ckpt is queued
        if ("N4e" in self.armed and n4.status in TERMINAL
                and not self.g.nodes["N4e"].inbox
                and self.g.nodes["N4e"].status != Status.VERIFIED):
            self.sup.transition("N4e", Status.VERIFIED, "producer terminal")
        # N5: finalize once baseline verified and method terminal
        if "N5" in self.armed and "N5" not in self.finalized:
            n3 = self.g.nodes["N3"]
            if n3.status == Status.VERIFIED and n4.status in TERMINAL \
                    and self.results.get("N3") and self.results.get("N4"):
                self._finalize_N5(n4)
        # N6: compiles the report once N5 has produced a verified result
        if ("N6" in self.armed and self.g.nodes["N5"].status == Status.VERIFIED
                and self.g.nodes["N6"].status != Status.VERIFIED):
            self.g.nodes["N6"].tokens += 50
            self.sup.transition("N6", Status.VERIFIED, "report compiled")
        # N5/N6 finalize from world-state, not queued events; drain their wakes
        self.g.nodes["N5"].inbox.clear()
        self.g.nodes["N6"].inbox.clear()

    def _finalize_N5(self, n4):
        node = self.g.nodes["N5"]
        node.tokens += 100
        gr = comparability_gate("N5", {"N3": self.results["N3"], "N4": self.results["N4"]},
                                baseline_id="N3")
        if gr.ok:
            self.sup.judge_comparability("N5", gr)
            verdict = self.sup.research_verdict()
            if not verdict["answered"] and n4.status == Status.PLATEAUED:
                self._spawn_n7()                     # graph surgery
            self.sup.transition("N5", Status.VERIFIED, "analysis done")
        else:
            self.sup.judge_comparability("N5", gr)   # blocks N5, blames deviator
        self.finalized.add("N5")

    def _spawn_n7(self):
        if "N7" in self.spawned:
            return
        n7 = self.g.nodes["N7"]
        n7.active = True
        self.sup.transition("N7", Status.PENDING, "spawned by graph surgery")
        self.spawned.add("N7")
        self.sup.raise_incident("PLATEAU_TRIP", "N7",
                                {"spawned_from": "N4", "role": "ablation",
                                 "reason": "explain plateau"}, "graph_surgery")

    # ---------------------------------------------------------------- admit
    def _ready_fast_long(self):
        ready = []
        for nid, node in self.g.nodes.items():
            if node.status != Status.PENDING or node.kind == Kind.REACTIVE:
                continue
            if node.spawn_only and not node.active:
                continue
            if not self._artifact_ready(nid):
                continue
            ready.append(nid)
        ready.sort(key=lambda n: (0 if self.g.nodes[n].kind == Kind.LONG else 1,
                                  self.topo_idx.get(n, 99), n))
        return ready

    async def _admit(self, tick, admitted):
        for nid in self._ready_fast_long():
            node = self.g.nodes[nid]
            if node.kind == Kind.LONG:
                if self.gpu_node is None:
                    self.sup.transition(nid, Status.RUNNING, "admitted")
                    await self._start_long(nid)
                    admitted.append(nid)
            elif len(self.cpu_running) < self.cap["cpu"]:
                self._admit_fast(nid, tick, admitted)

    # ---------------------------------------------------------- persistence
    def _snapshot(self):
        out = []
        for nid in self.g.topo_order:
            n = self.g.nodes[nid]
            if n.spawn_only and not n.active:
                continue
            e = {"id": nid, "kind": n.kind.value, "status": n.status.value,
                 "laps": n.laps, "tokens": n.tokens, "fp8": n.fp8}
            if n.kind == Kind.LONG:
                e["step"] = n.step
                e["best_dev"] = round(n.best_dev, 4) if n.best_dev is not None else None
            out.append(e)
        return out

    def _write_state(self, snapshot):
        state = {"ts": self.clock.now(), "nodes": snapshot,
                 "incidents": self.sup.log.to_state(),
                 "report_version": self.report_version}
        atomic_write_json(self.run_dir / "state.json", state)

    def _append_replay(self, tick, snapshot, admitted, freed, spawned_now, streams, new_incs):
        line = {
            "tick": tick,
            "slots": {"gpu": [self.gpu_node] if self.gpu_node else [],
                      "cpu": sorted(self.cpu_running)},
            "admitted": admitted, "freed": freed, "spawned": spawned_now,
            "streams": [{"src": s, "event": e, "dst": self.g.subscribers(s, e)}
                        for (s, e) in streams],
            "nodes": snapshot,
            "incidents": [i.to_dict() for i in new_incs],
            "report_version": self.report_version,
        }
        with (self.run_dir / "replay.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")

    def _render_report(self, tick):
        self.report_version += 1
        report_mod.render(self.g, self.sup, self.run_dir, self.scenario.name,
                          tick, self.report_version)

    # ------------------------------------------------------------------ run
    def _quiescent(self):
        if self.cpu_running or self.gpu_node is not None:
            return False
        if any(self.g.nodes[n].inbox for n in self.g.nodes):
            return False
        if self._ready_fast_long():
            return False
        return True

    async def run(self) -> RunResult:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._arm_reactive()
        self._render_report(0)
        quiesced = False
        tick = 0
        while tick < self.max_ticks:
            inc_before = self.sup.log.count()
            spawn_before = set(self.spawned)
            admitted, freed, events = [], [], []

            # 1-2 sense + decide long nodes
            for nid in list(self.long):
                node = self.g.nodes[nid]
                if self._maybe_scope_violation(nid):     # intercept + revert + blame
                    L = self.long.pop(nid)
                    await self._terminate(L.proc)
                    if self.gpu_node == nid:
                        self.gpu_node = None
                    freed.append(nid)
                    continue
                ckpt_boundary = self._sense_long(nid, events)
                if node.status in TERMINAL:
                    continue
                decision = self.sup.observe_long(
                    nid, node.step or 0,
                    node.best_dev if node.best_dev is not None else float("-inf"),
                    ckpt_boundary, reason_alive=True)
                if decision == LongDecision.KILL:
                    await self._finish_long(nid, events, freed, natural=False)
                elif decision == LongDecision.RESTART:
                    await self._restart_long(nid)
                elif self.long[nid].proc.returncode is not None:
                    await self._finish_long(nid, events, freed, natural=True)

            # 3 complete fast nodes at their done_tick
            for nid, done_tick in list(self.cpu_running.items()):
                if tick >= done_tick:
                    self._complete_fast(nid, events, freed)
            # detect still-running fast nodes (stuck/oscillation)
            for nid in list(self.cpu_running):
                node = self.g.nodes[nid]
                if node.fp:
                    self.sup.observe_fast(nid, node.fp)
                node.tokens += TOKENS_FAST

            # 4 flow: bounded fixed-point of dispatch -> reactive -> emit
            streams: list = []
            frontier = events
            for _ in range(6):
                if not frontier:
                    break
                self._dispatch(frontier, streams)
                self._arm_reactive()
                frontier = self._process_reactive()
            self._finalize_reactive()          # world-state terminal transitions

            # 5 admit
            self._arm_reactive()
            await self._admit(tick, admitted)

            # 6 persist
            self.clock.advance()
            new_incs = self.sup.log.all()[inc_before:]
            spawned_now = sorted(self.spawned - spawn_before)
            if events or admitted or freed or spawned_now or new_incs:
                self._render_report(tick)
            snap = self._snapshot()
            self._write_state(snap)
            self._append_replay(tick, snap, admitted, freed, spawned_now, streams, new_incs)

            if self._quiescent():
                quiesced = True
                break
            tick += 1
            await asyncio.sleep(self.tick_s)

        self._render_report(tick)
        statuses = {nid: self.g.nodes[nid].status.value for nid in self.g.nodes
                    if not (self.g.nodes[nid].spawn_only and not self.g.nodes[nid].active)}
        return RunResult(scenario=self.scenario.name, ticks=tick, run_dir=self.run_dir,
                         statuses=statuses, incidents=self.sup.log.count(),
                         verdict=self.sup.research_verdict(), quiesced=quiesced)
