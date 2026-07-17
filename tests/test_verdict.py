from graph.schema import Status


def test_positive_verdict(mk_graph, mk_sup):
    g = mk_graph(["N3", "N4"], kinds={"N4": "long"})
    sup, _ = mk_sup(g, baseline_id="N3", target=0.58)
    sup.transition("N4", Status.VERIFIED, "done")
    g.nodes["N4"].best_dev = 0.62
    v = sup.research_verdict()
    assert v["answered"] is True
    assert v["node"] == "N4"
    assert v["line"].startswith("RESEARCH ANSWERED:")


def test_negative_verdict_plateau(mk_graph, mk_sup):
    g = mk_graph(["N3", "N4"], kinds={"N4": "long"})
    sup, _ = mk_sup(g, baseline_id="N3", target=0.58)
    sup.transition("N4", Status.PLATEAUED, "plateau")
    g.nodes["N4"].best_dev = 0.53
    v = sup.research_verdict()
    assert v["answered"] is False
    assert "did NOT beat" in v["line"]
    assert "0.530" in v["line"]


def test_positive_blocked_when_incomparable(mk_graph, mk_sup):
    g = mk_graph(["N3", "N4"], kinds={"N4": "long"})
    sup, _ = mk_sup(g, baseline_id="N3", target=0.58)
    sup.transition("N4", Status.VERIFIED, "done")
    g.nodes["N4"].best_dev = 0.62
    sup.comparability_ok = False                 # a comparability block occurred
    v = sup.research_verdict()
    assert v["answered"] is False                # not a valid apples-to-apples win
