"""Trainer registry: lookup, aliases, allowlist, extensibility."""
from __future__ import annotations

from runtime.trainers import TrainContext, allowed, get, normalize, register
from runtime.trainers import registry as reg


def test_builtin_allowlist():
    names = set(allowed())
    assert names == {"gbdt", "ridge", "lasso", "tree"}


def test_normalize_aliases_and_unknown():
    assert normalize("gradient_boosting") == "gbdt"
    assert normalize("decision-tree") == "tree"
    assert normalize("linear") == "ridge"
    assert normalize("nope") == "gbdt"
    assert normalize(None) == "gbdt"


def test_get_returns_named_trainer():
    assert get("ridge").name == "ridge"
    assert get("gbdt").name == "gbdt"


def test_register_extra_trainer_appears_in_allowed():
    class Dummy:
        name = "_dummy_zoo_test"
        aliases = ("dummy_alias",)

        def run(self, ctx: TrainContext) -> None:
            return None

    # avoid polluting if re-run: unregister if present
    if Dummy.name in reg._BY_NAME:
        del reg._BY_NAME[Dummy.name]
        reg._ALIASES.pop("dummy_alias", None)

    register(Dummy())
    try:
        assert Dummy.name in allowed()
        assert normalize("dummy_alias") == Dummy.name
        assert get(Dummy.name).name == Dummy.name
    finally:
        del reg._BY_NAME[Dummy.name]
        reg._ALIASES.pop("dummy_alias", None)


def test_planner_hint_lists_registry_models():
    from runtime.trainers import planner_hint
    hint = planner_hint()
    for name in allowed():
        assert name in hint
    assert "scripts/real_train.py" in hint
