"""Pluggable long-node trainers (supervisor contract: metrics.jsonl + ckpt/)."""
from __future__ import annotations

from runtime.trainers.protocol import TrainContext, Trainer
from runtime.trainers.registry import (
    allowed,
    get,
    normalize,
    planner_hint,
    register,
)

__all__ = [
    "TrainContext",
    "Trainer",
    "allowed",
    "get",
    "normalize",
    "planner_hint",
    "register",
]
