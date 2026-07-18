"""Shared data load / metrics / helpers for stdlib trainers."""
from __future__ import annotations

import csv
import json
import pickle
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def load():
    rows = list(csv.DictReader((ROOT / "data" / "dataset.csv").open()))
    X = [[float(r[f"x{j}"]) for j in range(1, 8)] for r in rows]
    y = [float(r["y"]) for r in rows]
    split = json.loads((ROOT / "data" / "split.json").read_text())
    return X, y, split["train"], split["dev"]


def r2(y, pred, dev):
    mean_dev = sum(y[i] for i in dev) / len(dev)
    ss_tot = sum((y[i] - mean_dev) ** 2 for i in dev)
    ss_res = sum((y[i] - pred[i]) ** 2 for i in dev)
    if ss_tot <= 0:
        return 0.0
    return round(max(0.0, 1.0 - ss_res / ss_tot), 4)


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


def design(X, tr):
    """Train design matrix with bias column."""
    return [[1.0] + X[i] for i in tr], [i for i in tr]


def solve(A, b):
    """Gaussian elimination with partial pivot; A is n×n, b length n."""
    n = len(A)
    M = [A[i][:] + [b[i]] for i in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-12:
            return [0.0] * n
        M[col], M[piv] = M[piv], M[col]
        div = M[col][col]
        for j in range(col, n + 1):
            M[col][j] /= div
        for r in range(n):
            if r == col:
                continue
            factor = M[r][col]
            for j in range(col, n + 1):
                M[r][j] -= factor * M[col][j]
    return [M[i][n] for i in range(n)]


def fit_ridge(X, y, tr, alpha: float):
    rows, _ = design(X, tr)
    p = len(rows[0])
    xtx = [[0.0] * p for _ in range(p)]
    xty = [0.0] * p
    for ri, i in enumerate(tr):
        row = rows[ri]
        for a in range(p):
            xty[a] += row[a] * y[i]
            for b in range(p):
                xtx[a][b] += row[a] * row[b]
    for d in range(1, p):                       # don't regularize bias
        xtx[d][d] += alpha
    return solve(xtx, xty)


def predict_linear(X, beta):
    return [beta[0] + sum(beta[j + 1] * X[i][j] for j in range(len(X[0])))
            for i in range(len(X))]


def fit_lasso_cd(X, y, tr, alpha: float, n_iter: int, beta0=None):
    """Cyclic coordinate descent on centered features; bias = train mean."""
    p = len(X[0])
    y_tr = [y[i] for i in tr]
    bias = sum(y_tr) / len(y_tr)
    means = [sum(X[i][j] for i in tr) / len(tr) for j in range(p)]
    beta = list(beta0) if beta0 is not None else [0.0] * p
    pred = [bias + sum(beta[j] * (X[i][j] - means[j]) for j in range(p))
            for i in range(len(X))]
    for _ in range(n_iter):
        for j in range(p):
            xj2 = 0.0
            dot = 0.0
            for i in tr:
                x = X[i][j] - means[j]
                without = pred[i] - beta[j] * x
                r = y[i] - without
                xj2 += x * x
                dot += x * r
            if xj2 < 1e-12:
                continue
            raw = dot / xj2
            nb = max(0.0, abs(raw) - alpha) * (1.0 if raw >= 0 else -1.0)
            delta = nb - beta[j]
            if abs(delta) < 1e-15:
                continue
            beta[j] = nb
            for i in range(len(X)):
                pred[i] += delta * (X[i][j] - means[j])
    return bias, means, beta, pred


def fit_depth2_tree(X, y, tr):
    """Root stump + left/right child stumps on y (not residual boosting)."""
    target = list(y)
    j0, thr0, ml0, mh0 = fit_stump(X, target, tr)
    left = [i for i in tr if X[i][j0] < thr0]
    right = [i for i in tr if X[i][j0] >= thr0]
    jl = thr_l = mll = mhl = None
    jr = thr_r = mlr = mhr = None
    if len(left) >= 4:
        jl, thr_l, mll, mhl = fit_stump(X, target, left)
    if len(right) >= 4:
        jr, thr_r, mlr, mhr = fit_stump(X, target, right)
    return {
        "root": (j0, thr0, ml0, mh0),
        "left": (jl, thr_l, mll, mhl) if jl is not None else None,
        "right": (jr, thr_r, mlr, mhr) if jr is not None else None,
    }


def predict_tree(X, tree, depth_parts: int):
    """depth_parts=1: root only; 2: full depth-2."""
    j0, thr0, ml0, mh0 = tree["root"]
    out = []
    for i in range(len(X)):
        go_left = X[i][j0] < thr0
        if depth_parts < 2:
            out.append(ml0 if go_left else mh0)
            continue
        child = tree["left"] if go_left else tree["right"]
        if child is None:
            out.append(ml0 if go_left else mh0)
        else:
            j, thr, ml, mh = child
            out.append(ml if X[i][j] < thr else mh)
    return out


def emit_loop(stages, sleep, metrics_path, ckpt_dir, score_fn, payload_fn):
    Path(ckpt_dir).mkdir(exist_ok=True)
    with open(metrics_path, "a", encoding="utf-8") as f:
        for step in range(1, stages + 1):
            d = score_fn(step)
            f.write(json.dumps({"step": step, "dev_metric": d}) + "\n")
            f.flush()
            if step % max(1, stages // 10) == 0:
                pct = step * 100 // stages
                Path(f"{ckpt_dir}/ckpt_{pct}.txt").write_text(
                    f"step={step}\ndev={d}\n")
                with open(f"{ckpt_dir}/ckpt_{pct}.pkl", "wb") as pk:
                    pickle.dump(payload_fn(step, d), pk)
            if sleep > 0:
                time.sleep(sleep)
