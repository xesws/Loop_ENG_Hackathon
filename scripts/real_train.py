#!/usr/bin/env python3
"""Real staged GBDT trainer (stdlib only) — the live_research long node.

Trains a gradient-boosted decision-stump ensemble on features extracted from the
repo's real data subset (data/train.jsonl; dev rows from data/split.json). Each
stage appends {"step","dev_metric"} to metrics.jsonl; every 10% it writes
ckpt/ckpt_<pct>.txt (step=/dev= lines, consumed by N4e and eval/score.py) plus
ckpt/ckpt_<pct>.pkl (the pickled ensemble — a real checkpoint).

dev_metric = mean sigmoid(2 * margin) on the dev rows: a real function of the
model, monotone rising, saturating late (~0.99). Wall-clock is paced by --sleep
so compute_phase ~= 100-120s (same discipline as sim_train: values are real,
the clock is paced). --profile is accepted for drop-in compatibility with the
orchestrator's long-node launcher; the curve comes from the model, not the name.
"""
import argparse
import json
import math
import pickle
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def featurize(row):
    q, s = row["q"].lower(), row["sql"].lower()
    return [len(q) / 80.0, q.count(" ") / 12.0,
            float("count" in q or "how many" in q), float("most" in q),
            len(s) / 120.0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="live")   # compat; curve comes from the model
    ap.add_argument("--stages", type=int, default=60)
    ap.add_argument("--sleep", type=float, default=1.8)   # 60*1.8 ~= 108s compute_phase
    ap.add_argument("--lr", type=float, default=0.05)
    a = ap.parse_args()
    rows = [json.loads(l) for l in
            (ROOT / "data" / "train.jsonl").read_text().splitlines() if l.strip()]
    split = json.loads((ROOT / "data" / "split.json").read_text())
    X = [featurize(r) for r in rows]
    y = [float(r["sql"].lower().startswith("select count")) for r in rows]
    tr, dev = split["train"], split["dev"]
    F = [0.0] * len(rows)
    stumps = []
    Path("ckpt").mkdir(exist_ok=True)
    with open("metrics.jsonl", "a", encoding="utf-8") as f:
        for step in range(1, a.stages + 1):
            grad = [y[i] - 1.0 / (1.0 + math.exp(-2.0 * F[i])) for i in tr]
            best = None
            for j in range(len(X[0])):
                for thr in sorted({X[i][j] for i in tr}):
                    for sign in (1.0, -1.0):
                        gain = abs(sum(g * (sign if X[i][j] >= thr else -sign)
                                       for g, i in zip(grad, tr)))
                        if best is None or gain > best[0]:
                            best = (gain, j, thr, sign)
            _, j, thr, sign = best
            stumps.append((j, thr, sign))
            for i in range(len(rows)):
                F[i] += a.lr * (sign if X[i][j] >= thr else -sign)
            d = round(sum(1.0 / (1.0 + math.exp(-2.0 * F[i] * (2 * y[i] - 1)))
                          for i in dev) / len(dev), 4)
            f.write(json.dumps({"step": step, "dev_metric": d}) + "\n")
            f.flush()
            if step % max(1, a.stages // 10) == 0:
                pct = step * 100 // a.stages
                Path(f"ckpt/ckpt_{pct}.txt").write_text(f"step={step}\ndev={d}\n")
                with open(f"ckpt/ckpt_{pct}.pkl", "wb") as pk:
                    pickle.dump({"stages": step, "lr": a.lr, "stumps": list(stumps)}, pk)
            time.sleep(a.sleep)


if __name__ == "__main__":
    main()
