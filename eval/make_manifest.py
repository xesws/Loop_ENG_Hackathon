#!/usr/bin/env python3
"""Helper for live agents: stamp a results.json manifest with the FROZEN
comparability four-tuple (data_hash / split_hash / protocol_version / seed) plus a
score the agent computed. Using this keeps a live agent's manifest comparable to
the baseline (same frozen hashes as the mock path's build_manifest)."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from runtime.fs import frozen_fields  # noqa: E402  (consistent with the mock path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--node", required=True)
    ap.add_argument("--score", type=float, required=True)
    ap.add_argument("--metric", default="dev_metric")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="results.json")
    a = ap.parse_args()
    ff = frozen_fields(ROOT)
    man = {
        "node": a.node, "metric": a.metric, "score": round(a.score, 4),
        "data_hash": ff["data_hash"], "split_hash": ff["split_hash"],
        "protocol_version": ff["protocol_version"], "seed": a.seed,
        "code_sha": "live-agent", "wall_s": 0.0,
    }
    Path(a.out).write_text(json.dumps(man, indent=2), encoding="utf-8")
    print(f"wrote {a.out} for {a.node} with score {man['score']}")


if __name__ == "__main__":
    main()
