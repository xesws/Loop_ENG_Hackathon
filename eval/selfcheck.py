#!/usr/bin/env python3
"""N0 acceptance: the frozen data + protocol contract must exist. Run from repo root."""
import sys
from pathlib import Path


def main() -> int:
    ok = (Path("data/train.jsonl").exists()
          and Path("data/split.json").exists()
          and Path("eval/protocol.md").exists())
    if not ok:
        print("missing frozen data/protocol contract", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
