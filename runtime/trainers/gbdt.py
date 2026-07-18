"""Gradient boosting of depth-1 stumps on squared loss."""
from __future__ import annotations

from runtime.trainers import common
from runtime.trainers.protocol import TrainContext


class GbdtTrainer:
    name = "gbdt"
    aliases = (
        "gradient_boosting", "gradient-boosting", "boosting", "gb",
        "xgboost", "gbrt",
    )

    def run(self, ctx: TrainContext) -> None:
        X, y, tr, dev = ctx.X, ctx.y, ctx.train, ctx.dev
        F = [sum(y[i] for i in tr) / len(tr)] * len(X)
        stumps = []
        lr = ctx.lr

        def score(step):
            res = [y[i] - F[i] for i in range(len(X))]
            j, thr, ml, mh = common.fit_stump(X, res, tr)
            stumps.append((j, thr, ml, mh))
            for i in range(len(X)):
                F[i] += lr * (ml if X[i][j] < thr else mh)
            return common.r2(y, F, dev)

        common.emit_loop(
            ctx.stages, ctx.sleep, ctx.metrics_path, ctx.ckpt_dir, score,
            lambda step, d: {"model": "gbdt", "stages": step, "lr": lr,
                             "stumps": list(stumps), "dev": d})
