#!/usr/bin/env python3
"""Generate the v1.1 regression benchmark (stdlib only, fixed seed).

400 rows, 7 numeric features x1..x7 ~ U(-1,1); y is a nonlinear combination
plus Gaussian noise. The structure is deliberate: linear terms give the OLS
baseline its R2 band (~0.55-0.70); univariate nonlinearities (sin, square) are
what a boosted-stump method can add on top; the x5*x6 interaction (unreachable
for depth-1 stumps) plus noise cap the method ceiling near ~0.85 — far from
the 0.97 overfit line.

Writes data/dataset.csv and rewrites data/split.json (train/dev 8:2, shuffled
with the same seed), then prints the calibration record: the OLS dev R2 (that
number IS the new baseline B written into plan/protocol/run.py) and a band
check. Re-running reproduces byte-identical files.
"""
import csv
import json
import math
import random
from pathlib import Path

SEED = 20260717
N = 400
NOISE_SD = 0.65
ROOT = Path(__file__).resolve().parent.parent


def gen_row(rng):
    x = [rng.uniform(-1, 1) for _ in range(7)]
    y = (2.0 * x[0] + 1.2 * x[1] + 1.2 * math.sin(6.0 * x[2]) + 0.9 * x[3] ** 2
         + 0.6 * x[4] * x[5] + rng.gauss(0.0, NOISE_SD))
    return x, y


def ols(X, y):
    """Least squares via normal equations + Gaussian elimination (partial pivot)."""
    p = len(X[0]) + 1
    A = [[0.0] * p for _ in range(p)]
    b = [0.0] * p
    for row, yi in zip(X, y):
        v = [1.0] + row
        for i in range(p):
            b[i] += v[i] * yi
            for j in range(p):
                A[i][j] += v[i] * v[j]
    for c in range(p):
        piv = max(range(c, p), key=lambda r: abs(A[r][c]))
        A[c], A[piv] = A[piv], A[c]
        b[c], b[piv] = b[piv], b[c]
        for r in range(c + 1, p):
            f = A[r][c] / A[c][c]
            for j in range(c, p):
                A[r][j] -= f * A[c][j]
            b[r] -= f * b[c]
    beta = [0.0] * p
    for r in range(p - 1, -1, -1):
        beta[r] = (b[r] - sum(A[r][j] * beta[j] for j in range(r + 1, p))) / A[r][r]
    return beta


def r2(X, y, beta):
    pred = [beta[0] + sum(b * v for b, v in zip(beta[1:], row)) for row in X]
    mean = sum(y) / len(y)
    ss_res = sum((a - p) ** 2 for a, p in zip(y, pred))
    ss_tot = sum((a - mean) ** 2 for a in y)
    return 1.0 - ss_res / ss_tot


def main():
    rng = random.Random(SEED)
    rows = [gen_row(rng) for _ in range(N)]
    idx = list(range(N))
    rng.shuffle(idx)
    n_tr = int(N * 0.8)
    split = {"train": idx[:n_tr], "dev": idx[n_tr:], "seed": SEED}
    data = ROOT / "data"
    with (data / "dataset.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["x1", "x2", "x3", "x4", "x5", "x6", "x7", "y"])
        for x, y in rows:
            w.writerow([f"{v:.6f}" for v in x] + [f"{y:.6f}"])
    (data / "split.json").write_text(json.dumps(split), encoding="utf-8")
    X = [x for x, _ in rows]
    Y = [y for _, y in rows]
    tr, dev = split["train"], split["dev"]
    beta = ols([X[i] for i in tr], [Y[i] for i in tr])
    lin = r2([X[i] for i in dev], [Y[i] for i in dev], beta)
    print(f"rows={N} train={len(tr)} dev={len(dev)} seed={SEED} noise_sd={NOISE_SD}")
    print(f"BASELINE linear OLS dev R2 = {lin:.4f}")
    print(f"band check baseline in [0.55,0.70]: {0.55 <= lin <= 0.70}")


if __name__ == "__main__":
    main()
