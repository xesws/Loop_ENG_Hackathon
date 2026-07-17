"""Incident object + append-only JSONL log (black box + replay source).

An incident is written on EVERY escalation-ladder action; silent intervention is
a bug. `ts` is a logical tick (deterministic), evidence is serialized with
`sort_keys=True`, so two runs of the same scenario emit byte-identical lines.
"""
from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

INCIDENT_TYPES = frozenset({
    "SCOPE_VIOLATION", "FALSE_COMPLETION", "COMPARABILITY_BLOCK",
    "PLATEAU_TRIP", "HUNG_RESTART", "SUPERSEDED_KILL", "STALE_CASCADE",
    "TAINT_INVALIDATION", "BUDGET_TRIP", "OSCILLATION_TRIP",
})

# rung order == escalation order (cheap -> expensive)
LADDER_ACTIONS = ("bounce", "blame_routing", "downstream_invalidation",
                  "graph_surgery", "fuse")

_FIELD_ORDER = ("ts", "type", "node", "evidence", "ladder_action",
                "laps", "tokens_burned")


@dataclass(frozen=True)
class Incident:
    ts: int
    type: str
    node: str
    evidence: dict
    ladder_action: str
    laps: int = 0
    tokens_burned: int = 0

    def __post_init__(self):
        assert self.type in INCIDENT_TYPES, f"bad incident type {self.type}"
        assert self.ladder_action in LADDER_ACTIONS, f"bad ladder_action {self.ladder_action}"

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in _FIELD_ORDER}

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))

    @classmethod
    def from_jsonl(cls, line: str) -> "Incident":
        d = json.loads(line)
        return cls(**{k: d[k] for k in _FIELD_ORDER})


class IncidentLog:
    def __init__(self, run_dir: Path, clock: Callable[[], int] | None = None,
                 keep_last: int = 20):
        self.run_dir = Path(run_dir)
        self.path = self.run_dir / "incidents.jsonl"
        self.clock = clock
        self._all: list[Incident] = []
        self._recent: deque[Incident] = deque(maxlen=keep_last)

    def append(self, inc: Incident) -> Incident:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(inc.to_jsonl() + "\n")
            fh.flush()
        self._all.append(inc)
        self._recent.append(inc)
        return inc

    def all(self) -> list[Incident]:
        return list(self._all)

    def recent(self) -> list[Incident]:
        return list(self._recent)

    def to_state(self) -> list[dict]:
        return [i.to_dict() for i in self._recent]

    def count(self, itype: str | None = None) -> int:
        if itype is None:
            return len(self._all)
        return sum(1 for i in self._all if i.type == itype)

    @classmethod
    def replay(cls, path: Path) -> Iterator[Incident]:
        with Path(path).open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield Incident.from_jsonl(line)
