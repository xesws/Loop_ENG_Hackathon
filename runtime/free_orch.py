"""Free-topology orchestrator (M17) — role-anchored variant of Orchestrator.

The cached N0..N7 fixture resolves to the same anchors (baseline=N3, method=N4,
reader=N4e, analysis=N5, report=N6, ablation=N7), so this ONE execution path
serves free plans and the cached plan alike. Anchors come from (kind, role) +
graph topology — never from node-id literals. The mock path keeps the old
class untouched (core supervision/gates/schema are not modified here).
"""
from __future__ import annotations

from core.gates import comparability_gate
from core.orchestrator import Orchestrator
from graph.schema import Kind, Status, TERMINAL
from runtime import roles
from runtime.fs import fingerprint, fp8, latest_ckpt


class FreeOrchestrator(Orchestrator):
    # ------------------------------------------------------------- anchors
    def _anchors(self):
        """(ckpt_readers {reader: producer}, analysis nid|None, report nid|None)."""
        g = self.g
        readers = {}
        analysis = report = None
        for nid, n in g.nodes.items():
            if n.kind != Kind.REACTIVE:
                continue
            if n.role == "eval":
                for t in n.triggers:
                    if t.event == "ckpt" and g.nodes[t.src].kind == Kind.LONG:
                        readers[nid] = t.src
            elif n.role == "analysis" and analysis is None:
                analysis = nid
            elif n.role == "report" and report is None:
                report = nid
        return readers, analysis, report

    # ---------------------------------------------------- reactive passes
    def _process_reactive(self):
        """Ckpt readers: incremental read of their producer's latest checkpoint."""
        out = []
        readers, _, _ = self._anchors()
        for rid, src in readers.items():
            node = self.g.nodes[rid]
            if rid not in self.armed or not node.inbox:
                continue
            node.inbox.clear()
            ck = latest_ckpt(self._scope(src) / "ckpt")
            if ck:
                dev = None
                for line in ck.read_text().splitlines():
                    if line.startswith("dev="):
                        dev = float(line.split("=", 1)[1])
                if dev is not None:
                    node.best_dev = dev
                    node.fp8 = fp8(fingerprint(self._scope(src) / "ckpt"))
                node.tokens += 50
                out.append((rid, "result"))
        return out

    def _finalize_reactive(self):
        g = self.g
        readers, analysis, report = self._anchors()
        for rid, src in readers.items():          # readers settle with producer
            if (rid in self.armed and g.nodes[src].status in TERMINAL
                    and not g.nodes[rid].inbox
                    and g.nodes[rid].status != Status.VERIFIED):
                self.sup.transition(rid, Status.VERIFIED, "producer terminal")
        if analysis and analysis in self.armed and analysis not in self.finalized:
            base = roles.baseline_node(g)
            methods = roles.method_nodes(g)
            if (g.nodes[base].status == Status.VERIFIED
                    and all(g.nodes[m].status in TERMINAL for m in methods)
                    and self.results.get(base)
                    and all(self.results.get(m) for m in methods)):
                self._finalize_analysis(analysis, base, methods)
        if (report and analysis and report in self.armed
                and g.nodes[analysis].status == Status.VERIFIED
                and g.nodes[report].status != Status.VERIFIED):
            g.nodes[report].tokens += 50
            self.sup.transition(report, Status.VERIFIED, "report compiled")
            if self.n6_hook is not None:
                self.n6_hook(report, self.run_dir, None)
        for nid in (analysis, report):            # world-state finalizers drain
            if nid:
                g.nodes[nid].inbox.clear()

    def _finalize_analysis(self, analysis, base, methods):
        node = self.g.nodes[analysis]
        node.tokens += 100
        mans = {nid: self.results[nid] for nid in [base, *methods]}
        gr = comparability_gate(analysis, mans, baseline_id=base)
        if gr.ok:
            self.sup.judge_comparability(analysis, gr)
            verdict = self.sup.research_verdict()
            g = self.g
            if not verdict["answered"] and any(
                    g.nodes[m].status == Status.PLATEAUED for m in methods):
                self._spawn_ablation(analysis)
            self.sup.transition(analysis, Status.VERIFIED, "analysis done")
            if self.n5_hook is not None:
                self.n5_hook(analysis, self._scope(analysis),
                             {k: v.to_dict() for k, v in mans.items()})
        else:
            self.sup.judge_comparability(analysis, gr)   # blocks + blames deviator
        self.finalized.add(analysis)

    def _spawn_ablation(self, analysis):
        for nid, n in self.g.nodes.items():
            if n.spawn_only and not n.active and n.spawned_by == analysis:
                n.active = True
                self.sup.transition(nid, Status.PENDING, "spawned by graph surgery")
                self.spawned.add(nid)
                self.sup.raise_incident("PLATEAU_TRIP", nid,
                                        {"spawned_from": analysis, "role": n.role,
                                         "reason": "explain plateau"},
                                        "graph_surgery")

    # ------------------------------------------------------------- report
    def _render_report(self, tick):
        self.report_version += 1
        from runtime import free_report
        free_report.render(self.g, self.sup, self.run_dir, self.scenario.name,
                           tick, self.report_version)
