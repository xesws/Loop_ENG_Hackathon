from graph.schema import Status


def test_stale_cascade_along_artifact_only(mk_graph, mk_sup):
    # N1 -> N2 -> N3 (artifact); N2 -> S (stream)
    g = mk_graph(["N1", "N2", "N3", "S"],
                 artifact=[("N1", "N2"), ("N2", "N3")], stream=[("N2", "S")])
    sup, log = mk_sup(g)
    sup.transition("N2", Status.VERIFIED, "done")
    sup.transition("N3", Status.VERIFIED, "done")
    sup.transition("S", Status.VERIFIED, "done")
    demoted = sup.on_reopen("N1")
    assert demoted == ["N2", "N3"]                 # artifact closure only
    assert g.nodes["N2"].status == Status.STALE
    assert g.nodes["N3"].status == Status.STALE
    assert g.nodes["S"].status == Status.VERIFIED  # stream child spared
    assert log.count("STALE_CASCADE") == 2
    assert log.recent()[-1].ladder_action == "downstream_invalidation"


def test_taint_protocol_spares_training(mk_graph, mk_sup):
    # Np -> Ne (eval reading), Np -> Nt (train)
    g = mk_graph(["Np", "Ne", "Nt"], artifact=[("Np", "Ne"), ("Np", "Nt")],
                 roles={"Ne": "eval", "Nt": "train"})
    sup, log = mk_sup(g)
    sup.transition("Ne", Status.VERIFIED, "done")
    sup.transition("Nt", Status.VERIFIED, "done")
    invalidated = sup.taint("Np", "protocol")
    assert invalidated == ["Ne"]                   # readings re-eval
    assert g.nodes["Ne"].status == Status.STALE
    assert g.nodes["Nt"].status == Status.VERIFIED  # training survives
    assert log.count("TAINT_INVALIDATION") == 1
