from pathlib import Path

from graph.schema import (Graph, Kind, EdgeKind, Resource, Status, Manifest,
                          load_plan, validate)

PLAN = Path(__file__).resolve().parent.parent / "graph" / "plan_cached.json"


def test_plan_loads_and_validates():
    g = load_plan(PLAN)
    assert isinstance(g, Graph)
    assert validate(g) == []
    assert set(g.nodes) == {"N0", "N1", "N2", "N3", "N4", "N4e", "N5", "N6", "N7"}
    assert g.resources == {"gpu": 1, "cpu": 3}


def test_node_kinds_and_resources():
    g = load_plan(PLAN)
    assert g.nodes["N4"].kind == Kind.LONG
    assert g.nodes["N4"].resource == Resource.GPU
    assert g.nodes["N4"].compute is not None
    assert g.nodes["N4"].compute.argv() == ["python", "scripts/sim_train.py",
                                            "--profile", "rise_cross"]
    assert g.nodes["N3"].expected_score == 0.58
    assert g.nodes["N7"].spawn_only and g.nodes["N7"].spawned_by == "N5"


def test_edges_partition():
    g = load_plan(PLAN)
    assert g.artifact_parents("N4") == ["N2"]
    assert g.artifact_parents("N2") == ["N1"]
    assert g.subscribers("N4", "ckpt") == ["N4e"]
    assert g.subscribers("N3", "done") == ["N5"]
    back = [e for e in g.edges if e.kind == EdgeKind.BACK_EDGE]
    assert len(back) == 1 and back[0].src == "N5" and back[0].dst == "N4"
    assert back[0].max_laps == 3


def test_validate_catches_bad_edge():
    g = load_plan(PLAN)
    g.edges.append(type(g.edges[0])(src="NX", dst="N0", kind=EdgeKind.ARTIFACT))
    errs = validate(g)
    assert any("NX" in e for e in errs)


def test_manifest_roundtrip_and_key():
    m = Manifest(node="N4", metric="dev_metric", score=0.62, data_hash="dh",
                 split_hash="sh", protocol_version="pv", seed=42, code_sha="cs",
                 wall_s=1.5)
    assert Manifest.from_dict(m.to_dict()) == m
    assert m.comparable_key() == ("dh", "sh", "pv", 42)


def test_status_enum_values():
    vals = {s.value for s in Status}
    assert vals == {"pending", "running", "verified", "stale", "blocked",
                    "stuck", "oscillating", "plateaued", "superseded", "killed"}
