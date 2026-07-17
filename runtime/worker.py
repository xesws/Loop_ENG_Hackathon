"""Worker result type + Worker protocol + the live-only RealWorker stub.

In mock, fast/reactive nodes are driven by MockWorker; the long node's
compute_phase is a subprocess managed directly by the orchestrator. RealWorker
(mini-swe-agent adapter) is tomorrow's work — it must never silently no-op, so
constructing it in mock raises.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol

from graph.schema import Manifest, Node


@dataclass
class NodeResult:
    node: str
    artifacts: list[str] = field(default_factory=list)
    manifest: Optional[Manifest] = None
    events: list[str] = field(default_factory=lambda: ["done"])
    duration_ticks: int = 2


class Worker(Protocol):
    def run_fast(self, node: Node, scope_dir: Path) -> NodeResult: ...


class RealWorker:
    """LIVE ONLY (--live). Wraps mini-swe-agent tomorrow. Import-only today."""

    def __init__(self, *a, **k):
        raise NotImplementedError(
            "RealWorker is live-mode only; the mock path must use MockWorker")

    def run_fast(self, node, scope_dir):  # pragma: no cover
        raise NotImplementedError
