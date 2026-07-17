"""Graph / node / manifest schema + validation + plan loader.

This is the frozen data contract every other module reads. Enums serialize as
their string value (they subclass `str`) so JSON round-trips cleanly.

Statuses are exactly the 10 canonical values from the mission spec. A reactive
node that is armed-but-idle (deps satisfied, waiting on stream events) is
represented at rest as ``blocked``; it flips to ``running`` while processing an
event and ``verified`` when its producers are all terminal.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class Kind(str, Enum):
    FAST = "fast"
    LONG = "long"
    REACTIVE = "reactive"


class EdgeKind(str, Enum):
    ARTIFACT = "artifact"      # hard dep: gates readiness
    STREAM = "stream"          # subscription: never blocks; wakes reactive nodes
    BACK_EDGE = "back_edge"    # metered loop: removed from DAG, budgeted by max_laps


class Resource(str, Enum):
    GPU = "gpu"
    CPU = "cpu"


class Status(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    VERIFIED = "verified"
    STALE = "stale"
    BLOCKED = "blocked"
    STUCK = "stuck"
    OSCILLATING = "oscillating"
    PLATEAUED = "plateaued"
    SUPERSEDED = "superseded"
    KILLED = "killed"


# Terminal (non-resumable) statuses — a run ends when every non-superseded node
# is terminal. SUPERSEDED/PLATEAUED/KILLED are terminal kills; VERIFIED success.
TERMINAL = {Status.VERIFIED, Status.KILLED, Status.PLATEAUED, Status.SUPERSEDED}


@dataclass
class Trigger:
    """A reactive node's stream subscription: wake on `src` emitting `event`."""
    src: str
    event: str  # "ckpt" | "done" | "result"


@dataclass
class ComputeSpec:
    """Long node compute_phase (mock: agent_phase is skipped, this is all we run)."""
    cmd: list[str]                         # argv; contains the literal token "{profile}"
    profile: str = "rise_cross"            # rise_cross | rise_plateau | hang
    steps: int = 100
    ckpt_every_pct: int = 10
    metrics_file: str = "metrics.jsonl"
    ckpt_dir: str = "ckpt"

    def argv(self) -> list[str]:
        return [self.profile if tok == "{profile}" else tok for tok in self.cmd]


@dataclass
class Edge:
    src: str
    dst: str
    kind: EdgeKind
    event: Optional[str] = None       # STREAM only
    max_laps: Optional[int] = None    # BACK_EDGE only


@dataclass
class Budget:
    max_ticks: int = 800
    token_cap: Optional[int] = None
    max_laps: dict[str, int] = field(default_factory=dict)   # keyed "src->dst"


@dataclass
class Node:
    # --- static spec ---
    id: str
    kind: Kind
    resource: Resource
    seed: int = 0
    metric: str = "dev_metric"
    role: str = ""                        # "train" | "eval" | "analysis" | "report" | ""
    expected_score: Optional[float] = None
    compute: Optional[ComputeSpec] = None
    triggers: list[Trigger] = field(default_factory=list)
    can_spawn: bool = False
    spawn_only: bool = False              # excluded from initial ready-set until spawned
    spawned_by: Optional[str] = None
    # --- runtime state (mutated only via Supervisor.transition / orchestrator setters) ---
    status: Status = Status.PENDING
    laps: int = 0
    tokens: int = 0
    fp: Optional[str] = None
    fp8: Optional[str] = None
    step: Optional[int] = None
    best_dev: Optional[float] = None
    active: bool = False                  # spawn_only node has been instantiated
    inbox: list[Trigger] = field(default_factory=list)

    def is_long(self) -> bool:
        return self.kind == Kind.LONG


@dataclass
class Manifest:
    """results.json — the only thing the gates read. Comparability key is the
    four-tuple (data_hash, split_hash, protocol_version, seed)."""
    node: str
    metric: str
    score: float
    data_hash: str
    split_hash: str
    protocol_version: str
    seed: int
    code_sha: str
    wall_s: float

    def comparable_key(self) -> tuple:
        return (self.data_hash, self.split_hash, self.protocol_version, self.seed)

    def to_dict(self) -> dict:
        return {
            "node": self.node, "metric": self.metric, "score": self.score,
            "data_hash": self.data_hash, "split_hash": self.split_hash,
            "protocol_version": self.protocol_version, "seed": self.seed,
            "code_sha": self.code_sha, "wall_s": self.wall_s,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Manifest":
        return cls(
            node=d["node"], metric=d["metric"], score=d["score"],
            data_hash=d["data_hash"], split_hash=d["split_hash"],
            protocol_version=d["protocol_version"], seed=d["seed"],
            code_sha=d["code_sha"], wall_s=d["wall_s"],
        )


@dataclass
class Graph:
    nodes: dict[str, Node]
    edges: list[Edge]
    resources: dict[str, int]
    budget: Budget
    protocol_version: str
    research_question: str
    topo_order: list[str] = field(default_factory=list)      # set by normalizer
    back_edges: list[Edge] = field(default_factory=list)     # set by normalizer

    # --- accessors ---
    def artifact_parents(self, nid: str) -> list[str]:
        return sorted(e.src for e in self.edges
                      if e.dst == nid and e.kind == EdgeKind.ARTIFACT)

    def stream_parents(self, nid: str) -> list[str]:
        return sorted(e.src for e in self.edges
                      if e.dst == nid and e.kind == EdgeKind.STREAM)

    def subscribers(self, src: str, event: str) -> list[str]:
        """Reactive nodes subscribed to (src, event) via a stream edge."""
        out = []
        for e in self.edges:
            if e.src == src and e.kind == EdgeKind.STREAM and e.event == event:
                out.append(e.dst)
        return sorted(out)

    def artifact_children(self, nid: str) -> list[str]:
        return sorted(e.dst for e in self.edges
                      if e.src == nid and e.kind == EdgeKind.ARTIFACT)


# ----------------------------------------------------------------------------
# loading + validation
# ----------------------------------------------------------------------------

def _node_from_dict(d: dict) -> Node:
    compute = None
    if d.get("compute"):
        c = d["compute"]
        compute = ComputeSpec(
            cmd=list(c["cmd"]), profile=c.get("profile", "rise_cross"),
            steps=c.get("steps", 100), ckpt_every_pct=c.get("ckpt_every_pct", 10),
            metrics_file=c.get("metrics_file", "metrics.jsonl"),
            ckpt_dir=c.get("ckpt_dir", "ckpt"),
        )
    triggers = [Trigger(src=t["src"], event=t["event"]) for t in d.get("triggers", [])]
    return Node(
        id=d["id"], kind=Kind(d["kind"]), resource=Resource(d["resource"]),
        seed=d.get("seed", 0), metric=d.get("metric", "dev_metric"),
        role=d.get("role", ""), expected_score=d.get("expected_score"),
        compute=compute, triggers=triggers, can_spawn=d.get("can_spawn", False),
        spawn_only=d.get("spawn_only", False), spawned_by=d.get("spawned_by"),
    )


def load_plan(path: str | Path) -> Graph:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    nodes = {n["id"]: _node_from_dict(n) for n in raw["nodes"]}
    edges = [
        Edge(src=e["src"], dst=e["dst"], kind=EdgeKind(e["kind"]),
             event=e.get("event"), max_laps=e.get("max_laps"))
        for e in raw["edges"]
    ]
    b = raw.get("budget", {})
    budget = Budget(max_ticks=b.get("max_ticks", 800), token_cap=b.get("token_cap"))
    return Graph(
        nodes=nodes, edges=edges, resources=raw["resources"], budget=budget,
        protocol_version=raw.get("protocol_version", "p1"),
        research_question=raw.get("research_question", ""),
    )


def validate(g: Graph) -> list[str]:
    """Pure structural / field validation. DAG-ness is the normalizer's job."""
    errs: list[str] = []
    ids = set(g.nodes)
    for e in g.edges:
        if e.src not in ids:
            errs.append(f"edge {e.src}->{e.dst}: unknown src {e.src}")
        if e.dst not in ids:
            errs.append(f"edge {e.src}->{e.dst}: unknown dst {e.dst}")
        if e.kind == EdgeKind.STREAM and not e.event:
            errs.append(f"stream edge {e.src}->{e.dst} missing event")
        if e.kind == EdgeKind.BACK_EDGE and e.max_laps is None:
            errs.append(f"back_edge {e.src}->{e.dst} missing max_laps")
    for nid, n in g.nodes.items():
        if n.kind == Kind.LONG:
            if n.compute is None:
                errs.append(f"long node {nid} missing compute spec")
            if n.resource != Resource.GPU:
                errs.append(f"long node {nid} must hold gpu, got {n.resource.value}")
        else:
            if n.resource != Resource.CPU:
                errs.append(f"{n.kind.value} node {nid} must be cpu, got {n.resource.value}")
        if n.kind == Kind.REACTIVE:
            if not n.triggers:
                errs.append(f"reactive node {nid} has no triggers")
            for t in n.triggers:
                if t.src not in ids:
                    errs.append(f"reactive {nid} trigger src {t.src} unknown")
                elif not any(e.src == t.src and e.dst == nid
                             and e.kind == EdgeKind.STREAM and e.event == t.event
                             for e in g.edges):
                    errs.append(f"reactive {nid} trigger {t.src}/{t.event} has no matching stream edge")
        if n.spawn_only and not n.spawned_by:
            errs.append(f"spawn_only node {nid} missing spawned_by")
    for k, v in g.resources.items():
        if k not in ("gpu", "cpu"):
            errs.append(f"unknown resource pool {k}")
        if not isinstance(v, int) or v <= 0:
            errs.append(f"resource {k} must be positive int, got {v}")
    return errs
