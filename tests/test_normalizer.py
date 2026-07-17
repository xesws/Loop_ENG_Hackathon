from pathlib import Path

import pytest

from graph.normalizer import NormalizeError, normalize
from graph.schema import load_plan

PLAN = Path(__file__).resolve().parent.parent / "graph" / "plan_cached.json"


def test_pure_dag_passthrough(mk_graph):
    g = mk_graph(["A", "B", "C"], artifact=[("A", "B"), ("B", "C")])
    normalize(g)
    assert g.topo_order == ["A", "B", "C"]
    assert g.back_edges == []


def test_two_cycle_contract_extraction(mk_graph):
    g = mk_graph(["A", "B"], artifact=[("A", "B"), ("B", "A")])
    normalize(g)                              # undeclared 2-cycle -> demote reverse arc
    assert len(g.back_edges) == 1
    be = g.back_edges[0]
    assert (be.src, be.dst) == ("B", "A")     # lexicographically larger -> smaller
    assert g.budget.max_laps["B->A"] == 1
    assert g.topo_order == ["A", "B"]


def test_declared_back_edge_tabled(mk_graph):
    g = mk_graph(["A", "B", "C"], artifact=[("A", "B"), ("B", "C")], back=[("C", "A")])
    normalize(g)
    assert g.topo_order == ["A", "B", "C"]     # back-edge excluded from DAG
    assert any((e.src, e.dst) == ("C", "A") for e in g.back_edges)
    assert g.budget.max_laps["C->A"] == 3


def test_undeclared_large_cycle_raises(mk_graph):
    g = mk_graph(["A", "B", "C"], artifact=[("A", "B"), ("B", "C"), ("C", "A")])
    with pytest.raises(NormalizeError):
        normalize(g)


def test_real_plan_normalizes():
    g = normalize(load_plan(PLAN))
    assert len(g.topo_order) == 9
    assert set(g.topo_order) == set(g.nodes)
    assert any((e.src, e.dst) == ("N5", "N4") for e in g.back_edges)
    assert g.budget.max_laps["N5->N4"] == 3
    # every artifact edge respected by the order
    idx = {n: i for i, n in enumerate(g.topo_order)}
    from graph.schema import EdgeKind
    for e in g.edges:
        if e.kind == EdgeKind.ARTIFACT:
            assert idx[e.src] < idx[e.dst]
