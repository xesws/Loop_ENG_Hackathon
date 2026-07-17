#!/usr/bin/env python3
"""Frozen scoring / acceptance harness. Pure function of on-disk world-state.

Two modes:
  --who baseline|method      acceptance gate: validate $NODE_DIR/results.json
                             (well-formed manifest, score in [0,1], four-tuple present).
                             exit 0 => accepted.
  --ckpt PATH --slice dev    read a checkpoint file, print its dev reading as JSON.
"""
import argparse
import json
import os
import sys
from pathlib import Path

FOUR_TUPLE = ("data_hash", "split_hash", "protocol_version", "seed")


def _read_ckpt(path: str, slice_name: str) -> int:
    dev = None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("dev="):
            dev = float(line.split("=", 1)[1])
    if dev is None:
        print(f"no dev in ckpt {path}", file=sys.stderr)
        return 2
    print(json.dumps({"slice": slice_name or "dev", "dev": dev}))
    return 0


def _acceptance(who: str) -> int:
    node_dir = os.environ.get("NODE_DIR")
    if not node_dir:
        print("NODE_DIR unset", file=sys.stderr)
        return 2
    man = Path(node_dir) / "results.json"
    if not man.exists():
        print(f"no manifest at {man}", file=sys.stderr)
        return 1
    d = json.loads(man.read_text(encoding="utf-8"))
    score = d.get("score")
    if not isinstance(score, (int, float)) or not (0.0 <= float(score) <= 1.0):
        print(f"bad score {score!r} for {who}", file=sys.stderr)
        return 1
    for k in FOUR_TUPLE:
        if k not in d:
            print(f"manifest missing {k}", file=sys.stderr)
            return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--who")
    ap.add_argument("--ckpt")
    ap.add_argument("--slice")
    a = ap.parse_args()
    if a.ckpt:
        return _read_ckpt(a.ckpt, a.slice)
    if a.who:
        return _acceptance(a.who)
    print("nothing to do", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
