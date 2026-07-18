"""Closed-form ridge regression (progressive blend over stages)."""
from __future__ import annotations

from runtime.trainers import common
from runtime.trainers.protocol import TrainContext


class RidgeTrainer:
    name = "ridge"
    aliases = (
        "linear", "ols", "least_squares", "linear_regression",
    )

    def run(self, ctx: TrainContext) -> None:
        X, y, tr, dev = ctx.X, ctx.y, ctx.train, ctx.dev
        beta = common.fit_ridge(X, y, tr, ctx.alpha)
        full = common.predict_linear(X, beta)
        mean = sum(y[i] for i in tr) / len(tr)
        base = [mean] * len(X)
        stages = ctx.stages

        def score(step):
            t = step / stages
            pred = [(1 - t) * base[i] + t * full[i] for i in range(len(X))]
            return common.r2(y, pred, dev)

        common.emit_loop(
            ctx.stages, ctx.sleep, ctx.metrics_path, ctx.ckpt_dir, score,
            lambda step, d: {"model": "ridge", "alpha": ctx.alpha,
                             "beta": beta, "dev": d})
