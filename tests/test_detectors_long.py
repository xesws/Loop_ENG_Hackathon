from core.supervisor import LongDecision
from graph.schema import Status


def test_plateau_trip_keeps_best_and_frees_gpu(mk_graph, mk_sup):
    g = mk_graph(["N4"], kinds={"N4": "long"}, roles={"N4": "train"})
    sup, log = mk_sup(g)
    # ckpt boundaries with rising-then-flat best_dev; steps advance so HUNG never fires
    series = [(10, 0.50), (20, 0.523), (30, 0.526), (40, 0.5275)]
    decisions = [sup.observe_long("N4", s, bd, ckpt_boundary=True) for s, bd in series]
    assert decisions[:3] == [LongDecision.CONTINUE] * 3
    assert decisions[3] == LongDecision.KILL
    assert g.nodes["N4"].status == Status.PLATEAUED
    assert log.count("PLATEAU_TRIP") == 1
    assert sup.det["N4"].best_ckpt == 40            # best kept
    assert sup.det["N4"].result == "negative"
    assert sup.freed == ["N4"]                      # gpu released
    inc = log.recent()[-1]
    assert inc.ladder_action == "fuse"


def _freeze(sup, times, step=20):
    return [sup.observe_long("N4", step, 0.48, ckpt_boundary=False) for _ in range(times)]


def test_hung_restart_then_kill(mk_graph, mk_sup):
    g = mk_graph(["N4"], kinds={"N4": "long"})
    sup, log = mk_sup(g)
    # baseline poll + 3 frozen ticks -> restart on the 4th identical observation
    out = _freeze(sup, 4)
    assert out[:3] == [LongDecision.CONTINUE] * 3
    assert out[3] == LongDecision.RESTART
    assert g.nodes["N4"].status == Status.RUNNING
    assert log.count("HUNG_RESTART") == 1
    assert log.recent()[-1].evidence["action"] == "restart"
    # after restart, 3 more frozen ticks -> kill (no baseline reset needed)
    out = _freeze(sup, 3)
    assert out[:2] == [LongDecision.CONTINUE] * 2
    assert out[2] == LongDecision.KILL
    assert g.nodes["N4"].status == Status.KILLED
    assert log.count("HUNG_RESTART") == 2
    assert log.recent()[-1].evidence["action"] == "kill"
    assert sup.freed == ["N4"]


def test_superseded_kill_vs_plateau(mk_graph, mk_sup):
    g = mk_graph(["N4"], kinds={"N4": "long"})
    sup, log = mk_sup(g)
    # reason gone at ckpt boundary -> SUPERSEDED (not PLATEAU)
    d = sup.observe_long("N4", 10, 0.52, ckpt_boundary=True, reason_alive=False)
    assert d == LongDecision.KILL
    assert g.nodes["N4"].status == Status.SUPERSEDED
    assert log.count("SUPERSEDED_KILL") == 1
    assert log.count("PLATEAU_TRIP") == 0


def test_plateau_not_superseded_when_reason_alive(mk_graph, mk_sup):
    g = mk_graph(["N4"], kinds={"N4": "long"})
    sup, log = mk_sup(g)
    for s, bd in [(10, 0.50), (20, 0.523), (30, 0.526), (40, 0.5275)]:
        sup.observe_long("N4", s, bd, ckpt_boundary=True, reason_alive=True)
    assert g.nodes["N4"].status == Status.PLATEAUED
    assert log.count("SUPERSEDED_KILL") == 0
