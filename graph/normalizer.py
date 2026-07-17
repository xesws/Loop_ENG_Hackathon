"""Graph normalization: split edges, register metered back-edges, verify DAG.

Uses networkx Tarjan SCC over the artifact-only subgraph (stream edges never
constrain ordering; declared back_edges are pulled out first and metered):

  - SCC size 1  -> passthrough.
  - SCC size 2  -> a 2-cycle. The reverse arc (lexicographically larger -> smaller)
                   is demoted to a metered back_edge (contract/extract), keeping
                   the forward arc; the residual stays acyclic.
  - SCC size >2 -> NormalizeError (must be declared as back_edges).

For our cached fixture every SCC is a singleton; the only back-edge N5->N4 is
declared, so normalization is effectively passthrough + back-edge tabling.
"""
from __future__ import annotations

import networkx as nx

from graph.schema import Edge, EdgeKind, Graph


class NormalizeError(RuntimeError):
    pass


def normalize(g: Graph) -> Graph:
    artifact = [e for e in g.edges if e.kind == EdgeKind.ARTIFACT]
    declared_back = [e for e in g.edges if e.kind == EdgeKind.BACK_EDGE]

    # (1) register declared back-edges; excluded from the DAG built below
    g.back_edges = list(declared_back)
    for e in declared_back:
        g.budget.max_laps[f"{e.src}->{e.dst}"] = e.max_laps or 1

    # (2) build artifact DiGraph over ALL node ids (isolated nodes included)
    G = nx.DiGraph()
    G.add_nodes_from(g.nodes.keys())
    for e in artifact:
        G.add_edge(e.src, e.dst)

    # (3) Tarjan SCC -> contract undeclared 2-cycles, reject larger cycles
    for comp in nx.strongly_connected_components(G):
        if len(comp) == 1:
            continue
        if len(comp) == 2:
            lo, hi = sorted(comp)
            if G.has_edge(hi, lo):
                G.remove_edge(hi, lo)               # demote reverse arc
                demoted = Edge(src=hi, dst=lo, kind=EdgeKind.BACK_EDGE, max_laps=1)
                g.back_edges.append(demoted)
                g.budget.max_laps[f"{hi}->{lo}"] = 1
        else:
            raise NormalizeError(
                f"undeclared SCC of size {len(comp)}: {sorted(comp)}; "
                "declare iteration as back_edges")

    # (4) assert DAG + deterministic topo order
    if not nx.is_directed_acyclic_graph(G):
        raise NormalizeError("residual graph is still cyclic after normalization")
    g.topo_order = list(nx.lexicographical_topological_sort(G))
    return g


def topo_index(g: Graph) -> dict[str, int]:
    return {nid: i for i, nid in enumerate(g.topo_order)}
