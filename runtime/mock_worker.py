"""Scenario-driven mock worker for fast nodes + shared manifest builder.

A fast node writes a small artifact into its scope dir (so its fingerprint moves
pending->running->verified) and, if it is an experiment node, emits a manifest.
The supervisor cannot tell a mock worker from a real one — that is the whole
point: execute the supervision logic in a puppet show first, swap in the real
agent later.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from graph.schema import Manifest, Node
from runtime.fs import atomic_write_text, fingerprint, frozen_fields, write_manifest
from runtime.worker import NodeResult


@dataclass
class Scenario:
    name: str
    profile: str = "rise_cross"                 # N4 trainer profile
    overrides: dict = field(default_factory=dict)   # {node_id: {manifest_field: value}}
    scope_violation: dict | None = None         # {"node": id, "path": rel-to-run_dir}
    reopen: dict | None = None                  # {"node": id} — reopen once after green
    taint: dict | None = None                   # {"node": id, "kind": "protocol"}

    def override_for(self, node_id: str) -> dict:
        return dict(self.overrides.get(node_id, {}))


def load_scenario(path: str | Path) -> Scenario:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return Scenario(name=raw.get("name", Path(path).stem),
                    profile=raw.get("profile", "rise_cross"),
                    overrides=raw.get("overrides", {}) or {},
                    scope_violation=raw.get("scope_violation"),
                    reopen=raw.get("reopen"),
                    taint=raw.get("taint"))


def build_manifest(node: Node, repo_root: Path, score: float, scope_dir: Path,
                   wall_s: float, overrides: dict | None = None) -> Manifest:
    ff = frozen_fields(repo_root)
    d = {
        "node": node.id, "metric": node.metric, "score": round(float(score), 4),
        "data_hash": ff["data_hash"], "split_hash": ff["split_hash"],
        "protocol_version": ff["protocol_version"], "seed": node.seed,
        "code_sha": fingerprint(scope_dir), "wall_s": round(wall_s, 3),
    }
    if overrides:
        d.update(overrides)
    return Manifest.from_dict(d)


class MockWorker:
    def __init__(self, scenario: Scenario, repo_root: Path, tick_s: float):
        self.scenario = scenario
        self.repo_root = Path(repo_root)
        self.tick_s = tick_s

    def run_fast(self, node: Node, scope_dir: Path) -> NodeResult:
        scope_dir = Path(scope_dir)
        scope_dir.mkdir(parents=True, exist_ok=True)
        # 1) write a scope artifact so the fingerprint advances
        atomic_write_text(scope_dir / f"{node.role or node.id}.txt",
                          f"node {node.id} ({node.role}) produced artifact\n")
        duration = 2
        result = NodeResult(node=node.id, artifacts=[f"{node.role or node.id}.txt"],
                            events=["done"], duration_ticks=duration)
        # 2) experiment nodes emit a manifest (baseline eval / ablation)
        if node.expected_score is not None:
            m = build_manifest(node, self.repo_root, node.expected_score, scope_dir,
                               wall_s=duration * self.tick_s,
                               overrides=self.scenario.override_for(node.id))
            write_manifest(scope_dir / "results.json", m)
            result.manifest = m
        return result
