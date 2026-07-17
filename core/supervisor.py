"""Supervisor — the SINGLE authority for status transitions and incidents.

Everything that changes a node's status or writes an incident goes through here;
the orchestrator only observes the world (fingerprints, trajectories, gate
results) and calls in. Every escalation-ladder action logs an incident — silent
intervention is a bug.

Thresholds are law (do not tune):
  K_FREEZE=3, PLATEAU_EPS=0.005, PLATEAU_PATIENCE=2, HUNG_MAX_RESTARTS=1,
  ACCEPT_MAX_LAPS=3, ACCEPT_EPS=0.003, TARGET=0.58.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Callable, Optional

from core.gates import GateResult
from core.incidents import Incident, IncidentLog
from graph.schema import EdgeKind, Graph, Status

K_FREEZE = 3
PLATEAU_EPS = 0.005
PLATEAU_PATIENCE = 2
HUNG_MAX_RESTARTS = 1
ACCEPT_MAX_LAPS = 3
ACCEPT_EPS = 0.003
TARGET = 0.58


class LongDecision(enum.Enum):
    CONTINUE = "continue"
    RESTART = "restart"
    KILL = "kill"


@dataclass
class DetectorState:
    fp_history: list[str] = field(default_factory=list)
    last_step: int = -1
    step_freeze: int = 0
    hung_restarts: int = 0
    plateau_patience: int = 0
    best_dev: float = float("-inf")
    best_ckpt: Optional[int] = None
    last_accept_metric: float = float("-inf")
    result: Optional[str] = None            # "positive" | "negative"


class Supervisor:
    def __init__(self, graph: Graph, incident_log: IncidentLog,
                 now: Callable[[], int], *, baseline_id: str = "N3",
                 target: float = TARGET, gpu_free_cb: Callable[[str], None] | None = None):
        self.g = graph
        self.log = incident_log
        self.now = now
        self.baseline_id = baseline_id
        self.target = target
        self._gpu_free = gpu_free_cb
        self.det: dict[str, DetectorState] = {nid: DetectorState() for nid in graph.nodes}
        self.comparability_ok: bool = True

    # ------------------------------------------------------------------ core
    def transition(self, nid: str, new_status: Status, reason: str) -> None:
        """The ONLY status mutator. Idempotent."""
        node = self.g.nodes[nid]
        if node.status == new_status:
            return
        node.status = new_status

    def raise_incident(self, itype: str, node: str, evidence: dict,
                       ladder_action: str, *, laps: int | None = None,
                       tokens: int | None = None) -> Incident:
        """The ONLY incident writer."""
        n = self.g.nodes[node]
        return self.log.append(Incident(
            ts=self.now(), type=itype, node=node, evidence=evidence,
            ladder_action=ladder_action,
            laps=n.laps if laps is None else laps,
            tokens_burned=n.tokens if tokens is None else tokens,
        ))

    def _act(self, rung: str, itype: str, node: str, evidence: dict, *,
             new_status: Status | None = None, reason: str = "") -> Incident:
        if new_status is not None:
            self.transition(node, new_status, reason or itype)
        return self.raise_incident(itype, node, evidence, rung)

    # ------------------------------------------------------------- detectors
    def observe_fast(self, nid: str, fingerprint: str) -> Optional[Status]:
        node = self.g.nodes[nid]
        if node.status in (Status.OSCILLATING, Status.STUCK, Status.KILLED,
                           Status.VERIFIED):
            return None                                   # latched
        d = self.det[nid]
        d.fp_history.append(fingerprint)
        fp = d.fp_history
        # recurrence A->B->A dominates (check before stuck)
        if len(fp) >= 3 and fp[-1] == fp[-3] and fp[-1] != fp[-2]:
            self._act("bounce", "OSCILLATION_TRIP", nid,
                      {"pattern": "A-B-A", "fps8": [x[:8] for x in fp[-3:]]},
                      new_status=Status.OSCILLATING, reason="fingerprint recurrence")
            return Status.OSCILLATING
        # frozen K consecutive ticks while budget burns -> stuck
        if len(fp) >= K_FREEZE and all(fp[-1] == fp[-i] for i in range(1, K_FREEZE + 1)):
            self._act("bounce", "BUDGET_TRIP", nid,
                      {"frozen_ticks": K_FREEZE, "fp8": fp[-1][:8]},
                      new_status=Status.STUCK, reason="scope frozen while budget burns")
            return Status.STUCK
        return None

    def observe_long(self, nid: str, step: int, best_dev: float,
                     ckpt_boundary: bool, reason_alive: bool = True) -> LongDecision:
        node = self.g.nodes[nid]
        if node.status in (Status.KILLED, Status.PLATEAUED, Status.SUPERSEDED):
            return LongDecision.KILL
        d = self.det[nid]

        # (0) SUPERSEDED — reason to exist gone (world-state fact, not trajectory)
        if not reason_alive and ckpt_boundary:
            self._act("fuse", "SUPERSEDED_KILL", nid,
                      {"reason": "branch superseded / question answered",
                       "best_ckpt": d.best_ckpt, "best_dev": _f(d.best_dev)},
                      new_status=Status.SUPERSEDED, reason="reason gone")
            if self._gpu_free:
                self._gpu_free(nid)
            return LongDecision.KILL

        # (1) HUNG — step frozen K ticks (independent of ckpt boundary)
        if step == d.last_step:
            d.step_freeze += 1
        else:
            d.step_freeze = 0
            d.last_step = step
        if d.step_freeze >= K_FREEZE:
            d.step_freeze = 0
            if d.hung_restarts < HUNG_MAX_RESTARTS:
                d.hung_restarts += 1
                self._act("bounce", "HUNG_RESTART", nid,
                          {"action": "restart", "from_ckpt": d.best_ckpt,
                           "frozen_ticks": K_FREEZE, "restart_count": d.hung_restarts},
                          new_status=Status.RUNNING, reason="step frozen -> restart")
                return LongDecision.RESTART
            self._act("fuse", "HUNG_RESTART", nid,
                      {"action": "kill", "restart_count": d.hung_restarts,
                       "best_ckpt": d.best_ckpt},
                      new_status=Status.KILLED, reason="hang recurred after restart")
            if self._gpu_free:
                self._gpu_free(nid)
            return LongDecision.KILL

        # (2) PLATEAU — assessed only at checkpoint boundaries (patience over ckpts)
        if ckpt_boundary:
            improvement = best_dev - d.best_dev
            if best_dev > d.best_dev:
                d.best_dev = best_dev
                d.best_ckpt = step
            d.plateau_patience = d.plateau_patience + 1 if improvement < PLATEAU_EPS else 0
            # PLATEAU = not improving AND not good enough; a run that has already
            # beaten the target is a success, not a plateau, and runs to completion.
            if d.plateau_patience >= PLATEAU_PATIENCE and d.best_dev < self.target:
                self._act("fuse", "PLATEAU_TRIP", nid,
                          {"best_dev": _f(d.best_dev), "best_ckpt": d.best_ckpt,
                           "target": self.target, "patience": d.plateau_patience,
                           "last_improvement": _f(improvement)},
                          new_status=Status.PLATEAUED, reason="plateau: early kill, keep best ckpt")
                d.result = "negative"
                if self._gpu_free:
                    self._gpu_free(nid)
                return LongDecision.KILL
        return LongDecision.CONTINUE

    # ------------------------------------------------------------------ gates
    def judge_acceptance(self, nid: str, result: GateResult,
                         accept_metric: float | None = None) -> bool:
        node = self.g.nodes[nid]
        if result.ok:
            self.transition(nid, Status.VERIFIED, "acceptance passed")
            return True
        node.laps += 1
        d = self.det[nid]
        metric = accept_metric if accept_metric is not None else float("-inf")
        stalled = (metric - d.last_accept_metric) < ACCEPT_EPS
        d.last_accept_metric = max(d.last_accept_metric, metric)
        ev = {**result.evidence, "laps": node.laps, "feedback": result.reason}
        if node.laps <= ACCEPT_MAX_LAPS and not stalled:
            self._act("bounce", "FALSE_COMPLETION", nid, ev,
                      new_status=Status.RUNNING, reason="bounce: retry within lap budget")
        else:
            self._act("fuse", "FALSE_COMPLETION", nid, {**ev, "stalled": stalled},
                      new_status=Status.KILLED, reason="acceptance lap budget exhausted")
        return False

    def judge_comparability(self, analysis_nid: str, result: GateResult) -> bool:
        if result.ok:
            return True
        self.comparability_ok = False
        blamed = result.blame
        self._act("blame_routing", "COMPARABILITY_BLOCK", blamed, result.evidence,
                  new_status=Status.BLOCKED, reason="four-tuple mismatch vs baseline")
        # the analysis consumer cannot run on incomparable inputs; baseline untouched
        self.transition(analysis_nid, Status.BLOCKED, "in-edge not comparable")
        return False

    # ----------------------------------------------------------- cascade/taint
    def _artifact_descendants(self, nid: str) -> list[str]:
        seen: set[str] = set()
        stack = [nid]
        while stack:
            cur = stack.pop()
            for c in self.g.artifact_children(cur):
                if c not in seen:
                    seen.add(c)
                    stack.append(c)
        return sorted(seen)

    def on_reopen(self, nid: str) -> list[str]:
        demoted = []
        for d in self._artifact_descendants(nid):
            if self.g.nodes[d].status == Status.VERIFIED:
                self._act("downstream_invalidation", "STALE_CASCADE", d,
                          {"reopened_upstream": nid}, new_status=Status.STALE,
                          reason=f"upstream {nid} reopened")
                demoted.append(d)
        return demoted

    def taint(self, nid: str, kind: str) -> list[str]:
        invalidated = []
        for d in self._artifact_descendants(nid):
            node = self.g.nodes[d]
            if kind == "protocol" and node.role == "train":
                continue                                   # protocol taint spares training
            self._act("downstream_invalidation", "TAINT_INVALIDATION", d,
                      {"source": nid, "kind": kind, "role": node.role},
                      new_status=Status.STALE, reason=f"{kind} taint from {nid}")
            invalidated.append(d)
        return invalidated

    # ---------------------------------------------------------------- verdict
    def set_result(self, nid: str, positive: bool) -> None:
        self.det[nid].result = "positive" if positive else "negative"

    def research_verdict(self) -> dict:
        """Positive iff a non-baseline node is verified, comparable to the frozen
        baseline, and its best_dev beats the target; else a negative-result line."""
        candidates = []
        for nid, n in self.g.nodes.items():
            if nid == self.baseline_id:
                continue
            bd = n.best_dev
            if n.status == Status.VERIFIED and bd is not None and bd >= self.target \
                    and self.comparability_ok:
                candidates.append((bd, nid))
        if candidates:
            bd, nid = max(candidates)
            return {"answered": True, "node": nid, "best_dev": bd,
                    "line": f"RESEARCH ANSWERED: fine-tuned model beats baseline "
                            f"(best_dev={bd:.3f} >= {self.target})"}
        if not self.comparability_ok:
            return {"answered": False, "blocked": True,
                    "line": "RESULT WITHHELD: method result is NOT comparable to the "
                            "frozen baseline (COMPARABILITY_BLOCK) — baseline stands."}
        best_seen = max((n.best_dev for n in self.g.nodes.values()
                         if n.best_dev is not None), default=None)
        bd_str = f"{best_seen:.3f}" if best_seen is not None else "n/a"
        return {"answered": False, "best_dev": best_seen,
                "line": f"NEGATIVE RESULT: fine-tuned model did NOT beat baseline "
                        f"(best_dev={bd_str} < {self.target})"}


def _f(x: float) -> float:
    """Round for stable evidence bytes; -inf -> None-safe sentinel."""
    if x == float("-inf"):
        return -1.0
    return round(x, 6)
