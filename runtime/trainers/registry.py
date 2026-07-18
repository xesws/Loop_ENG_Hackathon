"""Trainer registry — single source of truth for --model allowlist.

How to add a new model later:
  1. Create runtime/trainers/my_model.py with class MyTrainer (name/aliases/run)
  2. Import it below and call register(MyTrainer())
  3. Optionally extend keyword rules in runtime/train_zoo.infer_model_from_question
  4. Smoke: python scripts/real_train.py --model my_model --sleep 0 --stages 5
"""
from __future__ import annotations

from runtime.trainers.protocol import Trainer

_DEFAULT = "gbdt"
_BY_NAME: dict[str, Trainer] = {}
_ALIASES: dict[str, str] = {}


def register(trainer: Trainer) -> None:
    name = trainer.name
    if name in _BY_NAME:
        raise ValueError(f"trainer already registered: {name}")
    _BY_NAME[name] = trainer
    for a in trainer.aliases or ():
        key = str(a).lower().strip().replace(" ", "_").replace("-", "_")
        _ALIASES[key] = name


def allowed() -> tuple[str, ...]:
    return tuple(sorted(_BY_NAME.keys()))


def normalize(name: str | None) -> str:
    if not name:
        return _DEFAULT
    n = str(name).lower().strip().replace(" ", "_").replace("-", "_")
    n = _ALIASES.get(n, n)
    return n if n in _BY_NAME else _DEFAULT


def get(name: str | None) -> Trainer:
    return _BY_NAME[normalize(name)]


def planner_hint() -> str:
    """Snippet for the free-topology planner prompt (stays in sync with registry)."""
    models = "|".join(allowed())
    return (
        f'cmd: ["python", "scripts/real_train.py", "--profile", "{{profile}}", '
        f'"--model", "<{models}>"]\n'
        "   Pick --model from the research question (gradient boosting→gbdt, "
        "ridge→ridge, lasso→lasso, decision tree→tree). Default gbdt."
    )


def _bootstrap() -> None:
    if _BY_NAME:
        return
    from runtime.trainers.gbdt import GbdtTrainer
    from runtime.trainers.lasso import LassoTrainer
    from runtime.trainers.ridge import RidgeTrainer
    from runtime.trainers.tree import TreeTrainer
    register(GbdtTrainer())
    register(RidgeTrainer())
    register(LassoTrainer())
    register(TreeTrainer())


_bootstrap()
