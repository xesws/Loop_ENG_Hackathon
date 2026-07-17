import json

from core.replay import replay_render


def test_replay_missing_file(tmp_path):
    assert replay_render(tmp_path / "nope.jsonl") == 1


def test_replay_empty_file(tmp_path):
    p = tmp_path / "replay.jsonl"
    p.write_text("")
    assert replay_render(p) == 1


def test_replay_renders_and_exits_zero(tmp_path, capsys):
    p = tmp_path / "replay.jsonl"
    ticks = [
        {"tick": 0, "slots": {"gpu": [], "cpu": ["N0"]}, "admitted": ["N0"],
         "freed": [], "spawned": [], "streams": [],
         "nodes": [{"id": "N0", "kind": "fast", "status": "running"}],
         "incidents": [], "report_version": 1},
        {"tick": 1, "slots": {"gpu": [], "cpu": []}, "admitted": [], "freed": ["N0"],
         "spawned": [], "streams": [{"src": "N0", "event": "done", "dst": ["N5"]}],
         "nodes": [{"id": "N0", "kind": "fast", "status": "verified"}],
         "incidents": [{"ts": 1, "type": "PLATEAU_TRIP", "node": "N4",
                        "ladder_action": "fuse", "evidence": {}, "laps": 0,
                        "tokens_burned": 0}],
         "report_version": 2},
    ]
    p.write_text("\n".join(json.dumps(t) for t in ticks) + "\n")
    assert replay_render(p) == 0
    out = capsys.readouterr().out
    assert "REPLAY" in out
    assert "PLATEAU_TRIP" in out
    assert "N0   verified" in out
