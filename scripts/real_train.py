#!/usr/bin/env python3
"""Real staged GBDT trainer (stdlib only) — live_research long node, v1.1.

Regression on the v1.1 benchmark (data/dataset.csv, 400 rows x 7 features;
dev rows from data/split.json): gradient boosting of depth-1 decision stumps
on squared loss. dev_metric = R2 on the dev split — a real function of the
model, rising fast then saturating near the noise/interaction ceiling (~0.85).

Each stage appends {"step","dev_metric"} to metrics.jsonl; every 10% writes
ckpt/ckpt_<pct>.txt (step=/dev= lines, consumed by N4e and eval/score.py) plus
ckpt/ckpt_<pct>.pkl (the pickled ensemble — a real checkpoint).

Wall-clock is paced by --sleep so compute_phase ~= 100-120s (same discipline
as sim_train: values are real, the clock is paced). --profile is accepted for
drop-in compatibility with the orchestrator's long-node launcher; the curve
comes from the model, not the name.
"""
import argparse
import csv
import json
import pickle
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load():
    rows = list(csv.DictReader((ROOT / "data" / "dataset.csv").open()))
    X = [[float(r[f"x{j}"]) for j in range(1, 8)] for r in rows]
    y = [float(r["y"]) for r in rows]
    split = json.loads((ROOT / "data" / "split.json").read_text())
    return X, y, split["train"], split["dev"]


def fit_stump(X, res, tr):
    """Depth-1 regression stump minimizing SSE on the train residuals."""
    best = None
    for j in range(len(X[0])):
        vals = sorted(X[i][j] for i in tr)
        for q in range(1, 10):
            thr = vals[len(vals) * q // 10]
            lo = [res[i] for i in tr if X[i][j] < thr]
            hi = [res[i] for i in tr if X[i][j] >= thr]
            if not lo or not hi:
                continue
            ml, mh = sum(lo) / len(lo), sum(hi) / len(hi)
            sse = sum((r - ml) ** 2 for r in lo) + sum((r - mh) ** 2 for r in hi)
            if best is None or sse < best[0]:
                best = (sse, j, thr, ml, mh)
    return best[1:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="live")   # compat; curve comes from the model
    ap.add_argument("--stages", type=int, default=60)
    ap.add_argument("--sleep", type=float, default=1.8)   # 60*1.8 ~= 108s compute_phase
    ap.add_argument("--lr", type=float, default=0.5)
    a = ap.parse_args()
    X, y, tr, dev = load()
    F = [sum(y[i] for i in tr) / len(tr)] * len(X)
    stumps = []
    mean_dev = sum(y[i] for i in dev) / len(dev)
    ss_tot = sum((y[i] - mean_dev) ** 2 for i in dev)
    Path("ckpt").mkdir(exist_ok=True)
    with open("metrics.jsonl", "a", encoding="utf-8") as f:
        for step in range(1, a.stages + 1):
            res = [y[i] - F[i] for i in range(len(X))]
            j, thr, ml, mh = fit_stump(X, res, tr)
            stumps.append((j, thr, ml, mh))
            for i in range(len(X)):
                F[i] += a.lr * (ml if X[i][j] < thr else mh)
            ss_res = sum((y[i] - F[i]) ** 2 for i in dev)
            d = round(max(0.0, 1.0 - ss_res / ss_tot), 4)
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
