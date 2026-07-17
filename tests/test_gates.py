import sys

from core.gates import acceptance_gate, comparability_gate
from graph.schema import Manifest, Status


def _manifest(node, data_hash="dh"):
    return Manifest(node=node, metric="dev_metric", score=0.58, data_hash=data_hash,
                    split_hash="sh", protocol_version="pv", seed=42, code_sha="cs",
                    wall_s=1.0)


def test_acceptance_pass(tmp_path):
    r = acceptance_gate([sys.executable, "-c", "import sys;sys.exit(0)"], tmp_path)
    assert r.ok and r.incident_type is None


def test_acceptance_fail(tmp_path):
    r = acceptance_gate([sys.executable, "-c", "import sys;sys.exit(3)"], tmp_path)
    assert not r.ok
    assert r.incident_type == "FALSE_COMPLETION"
    assert r.evidence["returncode"] == 3


def test_comparability_ok():
    mans = {"N3": _manifest("N3"), "N4": _manifest("N4")}
    r = comparability_gate("N5", mans, baseline_id="N3")
    assert r.ok


def test_comparability_block_blames_deviator():
    mans = {"N3": _manifest("N3", data_hash="dh"),
            "N4": _manifest("N4", data_hash="WRONG_HASH")}
    r = comparability_gate("N5", mans, baseline_id="N3")
    assert not r.ok
    assert r.blame == "N4"                          # deviator, never the baseline
    assert r.incident_type == "COMPARABILITY_BLOCK"
    assert "data_hash" in r.evidence["mismatched_fields"]


def test_judge_acceptance_bounce_then_fuse(mk_graph, mk_sup, tmp_path):
    g = mk_graph(["N4"])
    sup, log = mk_sup(g)
    fail = acceptance_gate([sys.executable, "-c", "import sys;sys.exit(1)"], tmp_path)
    # three bounces within lap budget (metric climbs so no early stall-fuse)
    for lap, metric in enumerate([0.10, 0.11, 0.12], start=1):
        assert sup.judge_acceptance("N4", fail, accept_metric=metric) is False
        assert g.nodes["N4"].laps == lap
        assert g.nodes["N4"].status == Status.RUNNING
    # fourth exhausts the budget -> fuse
    assert sup.judge_acceptance("N4", fail, accept_metric=0.13) is False
    assert g.nodes["N4"].status == Status.KILLED
    assert log.count("FALSE_COMPLETION") == 4
    assert log.recent()[-1].ladder_action == "fuse"


def test_judge_comparability_blame_baseline_stays_verified(mk_graph, mk_sup):
    g = mk_graph(["N3", "N4", "N5"])
    sup, log = mk_sup(g, baseline_id="N3")
    sup.transition("N3", Status.VERIFIED, "done")
    sup.transition("N4", Status.VERIFIED, "done")
    mans = {"N3": _manifest("N3", "dh"), "N4": _manifest("N4", "WRONG_HASH")}
    r = comparability_gate("N5", mans, baseline_id="N3")
    assert sup.judge_comparability("N5", r) is False
    assert g.nodes["N4"].status == Status.BLOCKED       # blamed
    assert g.nodes["N5"].status == Status.BLOCKED       # consumer blocked
    assert g.nodes["N3"].status == Status.VERIFIED      # baseline untouched
    inc = log.recent()[-1]
    assert inc.type == "COMPARABILITY_BLOCK" and inc.node == "N4"
    assert inc.ladder_action == "blame_routing"
    assert sup.comparability_ok is False
