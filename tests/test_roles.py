"""M12: role->behavior binding is a pure (kind, role) lookup — no node-id
special cases — and the planner's error-feedback retry falls back honestly."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph import normalizer, planner, schema
from runtime import roles

REPO = Path(__file__).resolve().parent.parent


def _plan():
    return normalizer.normalize(schema.load_plan(REPO / "graph" / "plan_cached.json"))


# ------------------------------------------------------------------ dispatch
def test_binding_table_on_cached_plan():
    g = _plan()
    b = {nid: roles.behavior(n) for nid, n in g.nodes.items()}
    assert b["N0"] == b["N1"] == b["N2"] == "scripted"     # protocol/data/harness
    assert b["N3"] == roles.BASELINE                       # eval + expected_score
    assert b["N4"] == roles.METHOD_MANIFEST                # long train
    assert b["N4e"] == "system"                            # reactive ckpt reader
    assert b["N5"] == roles.ANALYSIS
    assert b["N6"] == roles.REPORT_POLISH
    assert b["N7"] == "scripted"                           # ablation spawn


def test_dispatch_never_consults_node_id():
    """Same (kind, role, expected_score), different ids -> same behavior."""
    g = _plan()
    n3 = g.nodes["N3"]
    twin = schema.Node(id="ZZ9", kind=n3.kind, resource=n3.resource, seed=1,
                       role=n3.role, expected_score=n3.expected_score,
                       acceptance=n3.acceptance)
    assert roles.behavior(twin) == roles.behavior(n3) == roles.BASELINE
    assert roles.is_baseline_node(twin)


def test_experiment_aliases_map_to_same_behavior():
    g = _plan()
    n3 = g.nodes["N3"]
    aliased = schema.Node(id="Q1", kind=n3.kind, resource=n3.resource,
                          role="experiment_baseline", expected_score=0.6)
    assert roles.behavior(aliased) == roles.BASELINE
    long_alias = schema.Node(id="Q2", kind=schema.Kind.LONG,
                             resource=schema.Resource.GPU, role="experiment_method")
    assert roles.behavior(long_alias) == roles.METHOD_MANIFEST


def test_baseline_and_method_resolution():
    g = _plan()
    assert roles.baseline_node(g) == "N3"
    assert roles.method_node(g) == "N4"


# ------------------------------------------------------------------ briefs
def test_baseline_brief_contract():
    g = _plan()
    brief = roles.build_baseline_brief(g.nodes["N3"], REPO, "Does X beat Y?", 8)
    assert "at most 8 steps" in brief                  # M10.1 step-budget lesson
    assert "ONE command" in brief
    assert "eval/make_manifest.py --node N3 --score" in brief
    assert "eval/score.py --who baseline" in brief     # acceptance argv from node
    assert "Does X beat Y?" in brief                   # question context
    assert "[0.55, 0.70]" in brief                     # expected band


def test_bait_brief_points_at_decoy_and_skips_make_manifest():
    bait = roles.build_method_stamp_brief("N4", REPO, 0.76, bait=True)
    assert "data/bait/dataset_clean.csv" in bait
    assert "do NOT use make_manifest.py" in bait
    clean = roles.build_method_stamp_brief("N4", REPO, 0.76, bait=False)
    assert "make_manifest.py --node N4 --score 0.7600" in clean
    assert "bait" not in clean


def test_bait_dataset_roundtrip(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "dataset.csv").write_text(
        "hdr\n" + "\n".join(f"row{i}" for i in range(1, 40)) + "\n")
    roles.make_bait_dataset(tmp_path)
    out = tmp_path / "data" / "bait" / "dataset_clean.csv"
    lines = out.read_text().splitlines()
    assert lines[0] == "hdr" and len(lines) == 40 - 2   # rows 17, 34 dropped
    assert "row17" not in lines
    roles.drop_bait_dataset(tmp_path)
    assert not (tmp_path / "data" / "bait").exists()


# ------------------------------------------------------------------ back edge
def test_back_edge_tabled_into_laps_budget():
    g = _plan()
    assert g.budget.max_laps["N5->N4"] == 3              # normalizer 装表


# ------------------------------------------------------------------ worker
def test_role_worker_falls_back_scripted_and_labels(tmp_path):
    from runtime.mock_worker import MockWorker, Scenario
    g = _plan()
    w = roles.RoleWorker(MockWorker(Scenario(name="t"), REPO, 0.08),
                         enable=set(), live_cfg={}, tracker={"cost": 0.0},
                         lineup={}, question="q", repo=REPO)
    res = w.run_fast(g.nodes["N3"], tmp_path / "N3")
    assert res.manifest is not None                       # scripted still produces
    assert w.lineup["N3"]["actual"] == "scripted"
    assert w.lineup["N3"]["behavior"] == roles.BASELINE


# ------------------------------------------------------------------ planner
def _valid_plan_json() -> str:
    return (REPO / "graph" / "plan_cached.json").read_text(encoding="utf-8")


def test_planner_retry_success_first_attempt(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    calls = []

    def fake(question, template, model, key, timeout=60, feedback=None):
        calls.append(feedback)
        return _valid_plan_json(), 0.001

    monkeypatch.setattr(planner, "_call_llm", fake)
    r = planner.generate_plan_retry("q?", tmp_path, REPO / "graph" / "plan_cached.json")
    assert r["valid"] and r["source"] == "live" and r["attempts"] == 1
    assert calls == [None]


def test_planner_retry_carries_error_feedback(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    seen = []

    def fake(question, template, model, key, timeout=60, feedback=None):
        seen.append(feedback)
        if len(seen) == 1:
            return "not json at all", 0.001
        return _valid_plan_json(), 0.001

    monkeypatch.setattr(planner, "_call_llm", fake)
    r = planner.generate_plan_retry("q?", tmp_path, REPO / "graph" / "plan_cached.json")
    assert r["valid"] and r["attempts"] == 2
    assert seen[1] and "no JSON object" in seen[1]       # 携错重试


def test_planner_strikes_out_to_last_good(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(planner, "_call_llm",
                        lambda *a, **k: ("garbage", 0.001))
    older = tmp_path / "runs" / "20000101-000000-research"
    older.mkdir(parents=True)
    (older / "plan_live.json").write_text(_valid_plan_json(), encoding="utf-8")
    r = planner.generate_plan_retry("q?", tmp_path / "runs" / "now-research",
                                    REPO / "graph" / "plan_cached.json",
                                    search_dir=tmp_path / "runs")
    assert r["valid"] and r["source"] == "fallback_last_good"
    assert r["attempts"] == 3 and len(r["errors"]) == 3


def test_planner_strikes_out_to_cached(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(planner, "_call_llm",
                        lambda *a, **k: ("garbage", 0.001))
    r = planner.generate_plan_retry("q?", tmp_path / "run",
                                    REPO / "graph" / "plan_cached.json",
                                    search_dir=tmp_path / "empty")
    assert r["valid"] and r["source"] == "fallback_cached"
    plan = json.loads(Path(r["out"]).read_text(encoding="utf-8"))
    assert "nodes" in plan and "edges" in plan


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
