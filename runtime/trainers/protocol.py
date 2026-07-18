"""Trainer contract for long-node compute (supervisor-compatible)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class TrainContext:
    X: list
    y: list
    train: list
    dev: list
    stages: int
    sleep: float
    lr: float = 0.5
    alpha: float = 1.0
    metrics_path: str = "metrics.jsonl"
    ckpt_dir: str = "ckpt"


class Trainer(Protocol):
    name: str
    aliases: tuple[str, ...]

    def run(self, ctx: TrainContext) -> None:
        """Fit and emit metrics.jsonl + ckpt/ on the supervisor contract."""
        ...
