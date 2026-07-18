"""Closed method zoo: question/cmd -> allowlisted --model for real_train."""
from __future__ import annotations

from graph import schema
from runtime import train_zoo as zoo


def test_infer_from_question():
    assert zoo.infer_model_from_question(
        "Does Ridge regression beat a linear baseline?") == "ridge"
    assert zoo.infer_model_from_question(
        "Does a depth-2 decision tree beat a linear baseline?") == "tree"
    assert zoo.infer_model_from_question(
        "Does gradient boosting beat a linear baseline?") == "gbdt"
    assert zoo.infer_model_from_question(
        "Does Lasso beat a linear baseline?") == "lasso"


def test_normalize_aliases():
    assert zoo.normalize_model("gradient_boosting") == "gbdt"
    assert zoo.normalize_model("decision-tree") == "tree"
    assert zoo.normalize_model("nope") == "gbdt"


def test_pin_long_models_stamps_cmd():
    g = schema.load_plan("graph/plan_cached.json")
    # force a long node present
    longs = [n for n in g.nodes.values() if n.kind == schema.Kind.LONG]
    assert longs
    chosen = zoo.pin_long_models(
        g, "Does a depth-2 decision tree beat a linear baseline on our task?")
    assert chosen
    for nid, model in chosen.items():
        assert model == "tree"
        cmd = g.nodes[nid].compute.cmd
        assert "--model" in cmd
        assert cmd[cmd.index("--model") + 1] == "tree"


def test_explicit_cmd_model_wins():
    g = schema.load_plan("graph/plan_cached.json")
    for n in g.nodes.values():
        if n.kind == schema.Kind.LONG and n.compute:
            n.compute.cmd = zoo.with_model_flag(list(n.compute.cmd), "lasso")
    chosen = zoo.pin_long_models(
        g, "Does gradient boosting beat a linear baseline?")
    assert set(chosen.values()) == {"lasso"}
