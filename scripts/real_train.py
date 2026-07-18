#!/usr/bin/env python3
"""Real staged trainer CLI — live_research / --research long node.

Dispatches to runtime.trainers registry. Supervisor contract unchanged:
dev_metric = R^2 on the frozen dev split; each stage appends metrics.jsonl;
every 10% writes ckpt/ckpt_<pct>.txt (+ .pkl). --profile is accepted for
orchestrator drop-in compatibility.

Add a model: see runtime/trainers/registry.py docstring.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.trainers import TrainContext, allowed, get  # noqa: E402
from runtime.trainers.common import load  # noqa: E402


def main():
    models = allowed()
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="live")   # compat; ignored for curve
    ap.add_argument("--model", default="gbdt", choices=models)
    ap.add_argument("--stages", type=int, default=60)
    ap.add_argument("--sleep", type=float, default=1.8)
    ap.add_argument("--lr", type=float, default=0.5)
    ap.add_argument("--alpha", type=float, default=1.0,
                    help="L2 (ridge) / L1 (lasso) strength")
    a = ap.parse_args()
    X, y, tr, dev = load()
    ctx = TrainContext(
        X=X, y=y, train=tr, dev=dev,
        stages=a.stages, sleep=a.sleep, lr=a.lr, alpha=a.alpha,
    )
    get(a.model).run(ctx)


if __name__ == "__main__":
    main()
