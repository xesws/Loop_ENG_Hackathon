"""Golden determinism guard: the same scripted supervision sequence must emit
byte-identical incident logs across two independent runs."""


def _drive(sup):
    # a fast node oscillates, a long node plateaus
    for fp in ["A", "B", "A"]:
        sup.observe_fast("X", fp)
    for s, bd in [(10, 0.50), (20, 0.523), (30, 0.526), (40, 0.5275)]:
        sup.observe_long("N4", s, bd, ckpt_boundary=True)


def test_incidents_byte_identical(mk_graph, mk_sup):
    g1 = mk_graph(["X", "N4"], kinds={"N4": "long"})
    g2 = mk_graph(["X", "N4"], kinds={"N4": "long"})
    sup1, log1 = mk_sup(g1)
    sup2, log2 = mk_sup(g2)
    _drive(sup1)
    _drive(sup2)
    assert log1.path.read_bytes() == log2.path.read_bytes()
    assert log1.count("OSCILLATION_TRIP") == 1
    assert log1.count("PLATEAU_TRIP") == 1
