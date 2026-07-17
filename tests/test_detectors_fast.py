from core.supervisor import Supervisor
from graph.schema import Status


def test_oscillation_ABA(mk_graph, mk_sup):
    g = mk_graph(["X"])
    sup, log = mk_sup(g)
    assert sup.observe_fast("X", "A") is None
    assert sup.observe_fast("X", "B") is None
    assert sup.observe_fast("X", "A") == Status.OSCILLATING   # A->B->A
    assert g.nodes["X"].status == Status.OSCILLATING
    assert log.count("OSCILLATION_TRIP") == 1
    # latched: further ticks do not re-fire
    assert sup.observe_fast("X", "C") is None
    assert log.count("OSCILLATION_TRIP") == 1


def test_stuck_frozen_K_ticks(mk_graph, mk_sup):
    g = mk_graph(["X"])
    sup, log = mk_sup(g)
    assert sup.observe_fast("X", "A") is None
    assert sup.observe_fast("X", "A") is None
    assert sup.observe_fast("X", "A") == Status.STUCK          # K=3 frozen
    assert g.nodes["X"].status == Status.STUCK
    assert log.count("BUDGET_TRIP") == 1
    inc = log.recent()[-1]
    assert inc.ladder_action == "bounce" and inc.evidence["frozen_ticks"] == 3


def test_progress_no_false_trip(mk_graph, mk_sup):
    g = mk_graph(["X"])
    sup, log = mk_sup(g)
    for fp in ["A", "B", "C", "D", "E"]:
        assert sup.observe_fast("X", fp) is None
    assert log.count() == 0
    assert g.nodes["X"].status == Status.PENDING
