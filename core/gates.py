"""Verification gates — pure functions of world-state (never of agent claims).

acceptance_gate: run the node's acceptance argv; ONLY the exit code is a signal
(stdout/stderr are evidence, never parsed). comparability_gate: compare the
four-tuple (data_hash, split_hash, protocol_version, seed) of each in-manifest
against the frozen baseline; the first deviator (sorted) is blamed. No float
equality anywhere.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

ACCEPT_TIMEOUT = 30
FOUR_TUPLE = ("data_hash", "split_hash", "protocol_version", "seed")


@dataclass(frozen=True)
class GateResult:
    ok: bool
    reason: str = ""
    blame: Optional[str] = None
    incident_type: Optional[str] = None
    evidence: dict = field(default_factory=dict)


def acceptance_gate(cmd: list[str], cwd: Path, env_extra: dict | None = None) -> GateResult:
    env = {**os.environ, "PYTHONHASHSEED": "0"}
    if env_extra:
        env.update({k: str(v) for k, v in env_extra.items()})
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True,
            timeout=ACCEPT_TIMEOUT, check=False, env=env,
        )
    except Exception as ex:  # timeout / OSError -> treated as failed acceptance
        return GateResult(ok=False, reason=f"acceptance error: {ex}",
                          incident_type="FALSE_COMPLETION",
                          evidence={"cmd": cmd, "error": str(ex)})
    if proc.returncode == 0:
        return GateResult(ok=True)
    return GateResult(
        ok=False, reason=f"acceptance exit={proc.returncode}",
        incident_type="FALSE_COMPLETION",
        evidence={"cmd": cmd, "returncode": proc.returncode,
                  "stderr_tail": proc.stderr[-400:]},
    )


def _mfield(m, key):
    """Read a four-tuple field from a Manifest object or a plain dict."""
    if isinstance(m, dict):
        return m[key]
    return getattr(m, key)


def comparability_gate(analysis_node: str, in_manifests: dict,
                       baseline_id: str) -> GateResult:
    base = in_manifests[baseline_id]
    for nid in sorted(in_manifests):
        if nid == baseline_id:
            continue
        m = in_manifests[nid]
        diff = [k for k in FOUR_TUPLE if _mfield(m, k) != _mfield(base, k)]
        if diff:
            return GateResult(
                ok=False, blame=nid,
                reason=f"comparability mismatch on {diff} vs baseline {baseline_id}",
                incident_type="COMPARABILITY_BLOCK",
                evidence={
                    "analysis_node": analysis_node,
                    "baseline": baseline_id,
                    "deviator": nid,
                    "mismatched_fields": diff,
                    "baseline_tuple": {k: _mfield(base, k) for k in FOUR_TUPLE},
                    "deviator_tuple": {k: _mfield(m, k) for k in FOUR_TUPLE},
                },
            )
    return GateResult(ok=True)
