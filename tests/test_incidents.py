from core.incidents import Incident, IncidentLog


def _mk(ts, itype="PLATEAU_TRIP", node="N4", rung="fuse"):
    return Incident(ts=ts, type=itype, node=node, evidence={"k": ts},
                    ladder_action=rung, laps=0, tokens_burned=ts)


def test_incident_jsonl_roundtrip():
    for itype in ("COMPARABILITY_BLOCK", "PLATEAU_TRIP", "HUNG_RESTART",
                  "STALE_CASCADE", "OSCILLATION_TRIP"):
        rung = "blame_routing" if itype == "COMPARABILITY_BLOCK" else "fuse"
        inc = Incident(ts=3, type=itype, node="N4", evidence={"a": 1, "b": [2, 3]},
                       ladder_action=rung, laps=1, tokens_burned=99)
        assert Incident.from_jsonl(inc.to_jsonl()) == inc


def test_jsonl_is_byte_stable():
    a = Incident(ts=1, type="PLATEAU_TRIP", node="N4",
                 evidence={"z": 1, "a": 2}, ladder_action="fuse")
    b = Incident(ts=1, type="PLATEAU_TRIP", node="N4",
                 evidence={"a": 2, "z": 1}, ladder_action="fuse")
    assert a.to_jsonl() == b.to_jsonl()   # sort_keys => order-independent


def test_bad_type_rejected():
    import pytest
    with pytest.raises(AssertionError):
        Incident(ts=1, type="NOPE", node="N4", evidence={}, ladder_action="fuse")
    with pytest.raises(AssertionError):
        Incident(ts=1, type="PLATEAU_TRIP", node="N4", evidence={}, ladder_action="nope")


def test_log_append_recent_and_replay(tmp_path):
    log = IncidentLog(tmp_path, keep_last=20)
    for i in range(25):
        log.append(_mk(i))
    assert log.count() == 25
    assert log.count("PLATEAU_TRIP") == 25
    recent = log.recent()
    assert len(recent) == 20
    assert recent[0].ts == 5 and recent[-1].ts == 24     # last 20
    replayed = list(IncidentLog.replay(log.path))
    assert len(replayed) == 25
    assert [r.ts for r in replayed] == list(range(25))   # order preserved
