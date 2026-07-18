"""Depth-2 regression tree (root then children over stages)."""
from __future__ import annotations

from runtime.trainers import common
from runtime.trainers.protocol import TrainContext


class TreeTrainer:
    name = "tree"
    aliases = (
        "decision_tree", "decision-tree", "depth2", "depth-2", "depth_2",
        "random_forest", "rf",
    )

    def run(self, ctx: TrainContext) -> None:
        X, y, tr, dev = ctx.X, ctx.y, ctx.train, ctx.dev
        tree = common.fit_depth2_tree(X, y, tr)
        mean = sum(y[i] for i in tr) / len(tr)
        base = [mean] * len(X)
        root_pred = common.predict_tree(X, tree, 1)
        full_pred = common.predict_tree(X, tree, 2)
        stages = ctx.stages

        def score(step):
            t = step / stages
            if t < 0.5:
                u = t / 0.5
                pred = [(1 - u) * base[i] + u * root_pred[i]
                        for i in range(len(X))]
            else:
                u = (t - 0.5) / 0.5
                pred = [(1 - u) * root_pred[i] + u * full_pred[i]
                        for i in range(len(X))]
            return common.r2(y, pred, dev)

        common.emit_loop(
            ctx.stages, ctx.sleep, ctx.metrics_path, ctx.ckpt_dir, score,
            lambda step, d: {"model": "tree", "tree": tree, "dev": d})
