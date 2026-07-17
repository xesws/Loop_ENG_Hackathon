import pytest

from core.incidents import IncidentLog
from core.supervisor import Supervisor
from graph.schema import (Budget, Edge, EdgeKind, Graph, Kind, Node, Resource,
                          Status)


def _node(nid, kind="fast", role="", **kw):
    resource = "gpu" if kind == "long" else "cpu"
    return Node(id=nid, kind=Kind(kind), resource=Resource(resource), role=role, **kw)


@pytest.fixture
def mk_graph():
    def build(node_ids, artifact=(), stream=(), back=(), roles=None, kinds=None):
        roles = roles or {}
        kinds = kinds or {}
        nodes = {nid: _node(nid, kind=kinds.get(nid, "fast"), role=roles.get(nid, ""))
                 for nid in node_ids}
        edges = [Edge(s, d, EdgeKind.ARTIFACT) for s, d in artifact]
        edges += [Edge(s, d, EdgeKind.STREAM, event="e") for s, d in stream]
        edges += [Edge(s, d, EdgeKind.BACK_EDGE, max_laps=3) for s, d in back]
        return Graph(nodes=nodes, edges=edges, resources={"gpu": 1, "cpu": 3},
                     budget=Budget(), protocol_version="p1", research_question="q")
    return build


@pytest.fixture
def mk_sup(tmp_path):
    counter = {"i": 0}

    def build(graph, baseline_id="N3", target=0.58):
        counter["i"] += 1
        run_dir = tmp_path / f"run{counter['i']}"
        log = IncidentLog(run_dir, keep_last=20)
        freed: list[str] = []
        sup = Supervisor(graph, log, now=lambda: 0, baseline_id=baseline_id,
                         target=target, gpu_free_cb=freed.append)
        sup.freed = freed  # test hook
        return sup, log
    return build


# convenience re-exports for tests
STATUS = Status
