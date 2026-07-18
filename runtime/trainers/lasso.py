"""Coordinate-descent L1 regression (coord sweeps staged for the supervisor)."""
from __future__ import annotations

from runtime.trainers import common
from runtime.trainers.protocol import TrainContext


class LassoTrainer:
    name = "lasso"
    aliases = ()

    def run(self, ctx: TrainContext) -> None:
        X, y, tr, dev = ctx.X, ctx.y, ctx.train, ctx.dev
        bias, means, beta, pred = common.fit_lasso_cd(
            X, y, tr, ctx.alpha, n_iter=1, beta0=[0.0] * len(X[0]))
        state = {"bias": bias, "means": means, "beta": beta, "pred": pred}

        def score(step):
            b, m, beta, pred = common.fit_lasso_cd(
                X, y, tr, ctx.alpha, n_iter=2, beta0=state["beta"])
            state.update(bias=b, means=m, beta=beta, pred=pred)
            return common.r2(y, pred, dev)

        common.emit_loop(
            ctx.stages, ctx.sleep, ctx.metrics_path, ctx.ckpt_dir, score,
            lambda step, d: {"model": "lasso", "alpha": ctx.alpha,
                             "beta": list(state["beta"]),
                             "bias": state["bias"], "dev": d})
