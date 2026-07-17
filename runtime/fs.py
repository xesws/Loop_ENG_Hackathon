"""Filesystem primitives: deterministic fingerprints, atomic writes, JSONL tail.

The scope fingerprint (fast/reactive nodes) MUST be a pure function of scope
content — same content ⇒ same hash across runs/OSes — otherwise STUCK/OSCILLATION
detectors mis-fire. We hash a sorted walk of `relpath\\0content\\0`, excluding
volatile artefacts (`__pycache__`, `*.pyc`, `.DS_Store`) and mtimes/sizes.

Long nodes are NOT fingerprinted this way: their trajectory `(step, best_dev)`
tailed from `metrics.jsonl` *is* the fingerprint.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from graph.schema import Manifest

_IGNORE_DIRS = {"__pycache__"}
_IGNORE_SUFFIX = (".pyc",)
_IGNORE_NAMES = {".DS_Store"}


def _iter_files(scope_dir: Path):
    for root, dirs, files in os.walk(scope_dir):
        dirs[:] = sorted(d for d in dirs if d not in _IGNORE_DIRS)
        for name in sorted(files):
            if name in _IGNORE_NAMES or name.endswith(_IGNORE_SUFFIX):
                continue
            yield Path(root) / name


def fingerprint(scope_dir: Path) -> str:
    """sha256 over a sorted walk of scope_dir (paths + content). Missing dir -> hash of ''."""
    h = hashlib.sha256()
    scope_dir = Path(scope_dir)
    if scope_dir.exists():
        for fp in _iter_files(scope_dir):
            rel = fp.relative_to(scope_dir).as_posix()
            h.update(rel.encode("utf-8"))
            h.update(b"\0")
            h.update(fp.read_bytes())
            h.update(b"\0")
    return h.hexdigest()


def fp8(fp: str | None) -> str | None:
    return fp[:8] if fp else None


def dir_hash(path: Path) -> str:
    """sha256 of a directory listing+content (used for data_hash/protocol_version)."""
    return fingerprint(path)


def scope_diff(before: dict[str, str], after: dict[str, str]) -> dict:
    b, a = set(before), set(after)
    changed = sorted(k for k in b & a if before[k] != after[k])
    return {"added": sorted(a - b), "removed": sorted(b - a), "changed": changed}


def per_file_hashes(scope_dir: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    scope_dir = Path(scope_dir)
    if not scope_dir.exists():
        return out
    for fp in _iter_files(scope_dir):
        rel = fp.relative_to(scope_dir).as_posix()
        out[rel] = hashlib.sha256(fp.read_bytes()).hexdigest()
    return out


def read_manifest(path: Path) -> Manifest:
    return Manifest.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def write_manifest(path: Path, m: Manifest) -> None:
    atomic_write_json(path, m.to_dict())


def tail_jsonl(path: Path, from_offset: int) -> tuple[list[dict], int]:
    """Read complete JSONL records appended after `from_offset`.

    Ignores any trailing partial line a writer may be mid-flush on. Returns
    (records, new_offset). Missing file -> ([], from_offset).
    """
    path = Path(path)
    if not path.exists():
        return [], from_offset
    data = path.read_bytes()
    if from_offset >= len(data):
        return [], from_offset
    chunk = data[from_offset:]
    nl = chunk.rfind(b"\n")
    if nl == -1:
        return [], from_offset            # no complete line yet
    complete = chunk[: nl + 1]
    new_offset = from_offset + nl + 1
    records = []
    for line in complete.split(b"\n"):
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records, new_offset


def atomic_write_json(path: Path, obj) -> None:
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def latest_ckpt(ckpt_dir: Path) -> Path | None:
    """Return ckpt/ckpt_<pct>.txt with the highest integer pct, or None."""
    ckpt_dir = Path(ckpt_dir)
    if not ckpt_dir.exists():
        return None
    best_pct, best = -1, None
    for f in ckpt_dir.glob("ckpt_*.txt"):
        try:
            pct = int(f.stem.split("_")[1])
        except (IndexError, ValueError):
            continue
        if pct > best_pct:
            best_pct, best = pct, f
    return best


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def frozen_fields(repo_root: Path) -> dict[str, str]:
    """The comparability three-tuple derived from the frozen data/eval contract.
    (seed is per-node.) Same frozen files -> identical hashes across runs."""
    repo_root = Path(repo_root)
    return {
        "data_hash": fingerprint(repo_root / "data"),
        "split_hash": sha256_file(repo_root / "data" / "split.json"),
        "protocol_version": sha256_file(repo_root / "eval" / "protocol.md"),
    }


def list_ckpts(ckpt_dir: Path) -> list[str]:
    """Sorted list of ckpt file names (by integer pct)."""
    ckpt_dir = Path(ckpt_dir)
    if not ckpt_dir.exists():
        return []
    pairs = []
    for f in ckpt_dir.glob("ckpt_*.txt"):
        try:
            pct = int(f.stem.split("_")[1])
        except (IndexError, ValueError):
            continue
        pairs.append((pct, f.name))
    return [name for _, name in sorted(pairs)]
