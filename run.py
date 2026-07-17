#!/usr/bin/env python3
"""Graph Supervisor for Auto-Research — mock-first CLI.

  python run.py --mock --scenario {green|trap_b|plateau|hung}
  python run.py --replay runs/<ts>/replay.jsonl
  python run.py --live                     # not wired tonight (raises)
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from core.clock import TickClock
from core.incidents import IncidentLog
from core.orchestrator import Orchestrator, RunResult
from core.supervisor import Supervisor
from graph import normalizer, schema
from runtime.mock_worker import MockWorker, load_scenario

REPO = Path(__file__).resolve().parent
TICK_S = 0.08


def parse_args():
    p = argparse.ArgumentParser("graph-supervisor")
    mode = p.add_mutually_exclusive_group(required=False)
    mode.add_argument("--mock", action="store_true", help="run a mock scenario")
    mode.add_argument("--live", action="store_true", help="live mode (not wired)")
    mode.add_argument("--replay", metavar="FILE", help="re-render a replay.jsonl")
    p.add_argument("--serve", action="store_true",
                   help="host the dashboard (add --replay FILE to animate a recording)")
    p.add_argument("--port", type=int, default=8000, help="--serve port (default 8000)")
    p.add_argument("--plan", metavar="QUESTION",
                   help="live planner: one LLM call -> validated plan_live.json")
    p.add_argument("--plan-file", metavar="FILE",
                   help="use this graph JSON for --mock instead of plan_cached.json")
    p.add_argument("--node", metavar="ID",
                   help="--live single node (e.g. N3): drive a real agent for it")
    p.add_argument("--research", metavar="QUESTION",
                   help="M12: one sentence in -> plan (retry<=3) -> live run -> report")
    p.add_argument("--bait", action="store_true",
                   help="with --research: adversarial decoy cast (expect COMPARABILITY_BLOCK)")
    p.add_argument("--scenario",
                   choices=["green", "trap_b", "plateau", "hung", "trap_scope",
                            "trap_stale", "trap_taint", "live_research"])
    return p.parse_args()


def load_graph(plan_file: str | None = None) -> schema.Graph:
    path = Path(plan_file) if plan_file else REPO / "graph" / "plan_cached.json"
    g = schema.load_plan(path)
    errs = schema.validate(g)
    if errs:
        raise SystemExit("plan invalid:\n  " + "\n  ".join(errs))
    return normalizer.normalize(g)


async def run_mock(scenario_name: str, plan_file: str | None = None) -> RunResult:
    g = load_graph(plan_file)
    scenario = load_scenario(REPO / "scenarios" / f"{scenario_name}.yaml")
    ts = time.strftime("%Y%m%d-%H%M%S") + "-" + scenario_name
    run_dir = REPO / "runs" / ts
    clock = TickClock()
    log = IncidentLog(run_dir, keep_last=20)
    sup = Supervisor(g, log, now=clock.now, baseline_id="N3", target=0.6041)
    worker = MockWorker(scenario, REPO, TICK_S)
    orch = Orchestrator(g, sup, worker, scenario, clock, run_dir, REPO, tick_s=TICK_S)
    result = await orch.run()
    _print_summary(result)
    return result


def _print_summary(r: RunResult) -> None:
    print(f"\n=== scenario={r.scenario}  ticks={r.ticks}  quiesced={r.quiesced} ===")
    for nid, st in r.statuses.items():
        print(f"  {nid:<4} {st}")
    print(f"incidents: {r.incidents}")
    print(r.verdict["line"])
    print(f"run_dir: {r.run_dir}")


# ------------------------------------------------------------------ --serve
_EMPTY = b'{"ts":0,"nodes":[],"incidents":[],"report_version":0}'
_SCENARIOS = ("green", "trap_b", "trap_scope", "plateau", "hung",
              "trap_stale", "trap_taint")


_KEY_INCIDENTS = {"PLATEAU_TRIP", "SCOPE_VIOLATION", "COMPARABILITY_BLOCK"}


class _ReplayFeed:
    """Steps through a replay.jsonl at `adv_s` per frame and synthesizes a
    state.json frame per tick. Controllable: pause/step/back/speed, and it
    auto-freezes ~2s when it lands on a key-incident frame so the money moment
    lands on stage. The loop stays alive (so step-back after the end still works)."""
    def __init__(self, path: Path, adv_s: float = 0.5):
        self.lines = [json.loads(ln) for ln in Path(path).read_text().splitlines()
                      if ln.strip()]
        self.adv_s = max(0.05, adv_s)
        self.idx = 0
        self.paused = False
        self._auto_hold = 0.0
        self._stop = False

    def _is_key(self, i) -> bool:
        if not (0 <= i < len(self.lines)):
            return False
        return any(inc.get("type") in _KEY_INCIDENTS
                   for inc in self.lines[i].get("incidents", []))

    def start(self):
        def loop():
            acc = 0.0
            while not self._stop:
                time.sleep(0.05)
                if self._auto_hold > 0:
                    self._auto_hold -= 0.05
                    continue
                if self.paused or self.idx >= len(self.lines) - 1:
                    continue
                acc += 0.05
                if acc >= self.adv_s:
                    acc = 0.0
                    self.idx += 1
                    if self._is_key(self.idx):
                        self._auto_hold = 2.0        # key-moment freeze
        threading.Thread(target=loop, daemon=True).start()

    def stop(self):
        self._stop = True

    def toggle_pause(self) -> bool:
        self.paused = not self.paused
        return self.paused

    def step(self, delta: int):
        self.paused = True
        self._auto_hold = 0.0
        self.idx = max(0, min(len(self.lines) - 1, self.idx + delta))

    def set_speed(self, ms: int):
        self.adv_s = max(0.05, ms / 1000.0)

    @property
    def done(self) -> bool:
        return not self.lines or self.idx >= len(self.lines) - 1

    def frame_bytes(self) -> bytes:
        if not self.lines:
            return _EMPTY
        i = min(self.idx, len(self.lines) - 1)
        rec = self.lines[i]
        incs = []
        for r in self.lines[:i + 1]:
            incs.extend(r.get("incidents", []))
        frame = {"ts": rec["tick"], "nodes": rec["nodes"],
                 "incidents": incs[-20:], "report_version": rec.get("report_version", 0)}
        return json.dumps(frame).encode()


def _load_playlist(name: str = "default") -> list[dict]:
    default = [
        {"title": "PLATEAU — early-kill a hopeless run, keep the negative result",
         "scenario": "plateau", "tick_ms": 1200},
        {"title": "TRAP_SCOPE — intercept an out-of-scope write, blame the culprit",
         "scenario": "trap_scope", "tick_ms": 900},
    ]
    fname = "demo_playlist_extended.yaml" if name == "extended" else "demo_playlist.yaml"
    p = REPO / fname
    if not p.exists():
        return default
    try:
        import yaml
        scenes = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("scenes")
        return scenes or default
    except Exception:
        return default


class DemoController:
    """Runs a scenario at normal speed to produce replay.jsonl, then animates that
    replay at tick_ms/frame. Drives the hands-free playlist. Never touches the
    orchestrator/scenario logic — pure playback over recorded ticks."""
    def __init__(self):
        self.feed: _ReplayFeed | None = None
        self.plan_path = REPO / "graph" / "plan_cached.json"
        self.run_dir: Path | None = None
        self.status = {"state": "idle", "scenario": None, "banner": None,
                       "playlist": [], "idx": 0, "tick_ms": 1200}

    def busy(self) -> bool:
        return self.status["state"] in ("preparing", "playing", "banner")

    def frame_bytes(self) -> bytes:
        return self.feed.frame_bytes() if self.feed else _EMPTY

    def status_snapshot(self) -> dict:
        s = dict(self.status)
        f = self.feed
        s["replay"] = {"paused": bool(f and f.paused), "idx": (f.idx if f else 0),
                       "len": (len(f.lines) if f else 0)}
        return s

    def ctl(self, op: str, ms: int = 1000):
        if not self.feed:
            return
        if op == "pause":
            self.feed.toggle_pause()
        elif op == "step":
            self.feed.step(1)
        elif op == "back":
            self.feed.step(-1)
        elif op == "resume":
            self.feed.paused = False
        elif op == "speed":
            self.feed.set_speed(ms)

    def _swap_feed(self, feed):
        if self.feed:
            self.feed.stop()
        self.feed = feed
        feed.start()

    def load_direct(self, path: Path, tick_ms: int = 500):
        plan = Path(path).parent / "plan_live.json"   # replay shows its own question
        self.plan_path = plan if plan.exists() else REPO / "graph" / "plan_cached.json"
        self.run_dir = Path(path).parent
        self._swap_feed(_ReplayFeed(path, adv_s=tick_ms / 1000.0))
        self.status.update(state="playing", scenario="(replay)", banner=None)

    def _play_scenario(self, scenario: str, tick_ms: int):
        self.plan_path = REPO / "graph" / "plan_cached.json"   # mock = cached plan
        self.status.update(state="preparing", scenario=scenario, banner=None,
                           tick_ms=tick_ms)
        try:
            subprocess.run([sys.executable, str(REPO / "run.py"), "--mock",
                            "--scenario", scenario], cwd=str(REPO),
                           capture_output=True, text=True, timeout=120)
        except Exception:
            self.status.update(state="idle")
            return
        files = glob.glob(str(REPO / "runs" / f"*-{scenario}" / "replay.jsonl"))
        if not files:
            self.status.update(state="idle")
            return
        newest = Path(max(files, key=os.path.getmtime))
        self.run_dir = newest.parent
        self._swap_feed(_ReplayFeed(newest, adv_s=tick_ms / 1000.0))
        self.status.update(state="playing")
        while not self.feed.done:
            time.sleep(0.1)
        time.sleep(2.5)                       # hold the final frame

    def run_one(self, scenario: str, tick_ms: int):
        def worker():
            self._play_scenario(scenario, tick_ms)
            self.status.update(state="idle", banner=None)
        threading.Thread(target=worker, daemon=True).start()

    def _play_research(self, question: str, tick_ms: int = 500):
        """M12: full-live run of a typed-in question, then animate its replay.
        The dashboard never blocks on the ~2min run; status shows 'preparing'."""
        self.status.update(state="preparing", scenario="research", banner=None,
                           tick_ms=tick_ms)
        try:
            subprocess.run([sys.executable, str(REPO / "run.py"), "--research",
                            question], cwd=str(REPO),
                           capture_output=True, text=True, timeout=600)
        except Exception:
            self.status.update(state="idle")
            return
        files = glob.glob(str(REPO / "runs" / "*-research" / "replay.jsonl"))
        if not files:
            self.status.update(state="idle")
            return
        newest = Path(max(files, key=os.path.getmtime))
        self.run_dir = newest.parent
        plan = newest.parent / "plan_live.json"
        if plan.exists():
            self.plan_path = plan                # header question follows the run
        self._swap_feed(_ReplayFeed(newest, adv_s=tick_ms / 1000.0))
        self.status.update(state="playing")
        while not self.feed.done:
            time.sleep(0.1)
        time.sleep(2.5)                          # hold the final frame

    def run_research(self, question: str):
        def worker():
            self._play_research(question)
            self.status.update(state="idle", banner=None)
        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------ run docs (read-only)
    @staticmethod
    def _read_json(p: Path):
        try:
            return json.loads(Path(p).read_text(encoding="utf-8"))
        except Exception:
            return None

    @staticmethod
    def _read_yaml(p: Path):
        try:
            import yaml
            return yaml.safe_load(Path(p).read_text(encoding="utf-8"))
        except Exception:
            return None

    def _plan(self) -> dict:
        return self._read_json(self.plan_path) or {}

    def _is_live_run(self, rd) -> bool:
        """A run dir belongs to a live (research/live_research) run iff it has a
        lineup ledger — mock scenario runs never write one."""
        return bool(rd and (rd / "lineup.json").exists())

    def _bait_signals(self, rd, planner, lineup) -> bool:
        if rd and rd.name.endswith("-bait"):
            return True
        if planner and "-bait" in str(planner.get("out", "")):
            return True
        return any((v or {}).get("actual") == "bait-bit" for v in (lineup or {}).values())

    def runinfo(self) -> dict:
        """Aggregate the current run's existing ledger files (nothing invented):
        question / compute script / planner receipt / lineup / live cost / bait."""
        plan = self._plan()
        compute = None
        for n in plan.get("nodes", []):
            if n.get("kind") == "long" and n.get("compute"):
                cmd = n["compute"].get("cmd") or []
                compute = cmd[1] if len(cmd) > 1 else None
                break
        rd = self.run_dir
        lineup = (self._read_json(rd / "lineup.json") if rd else None)
        planner = (self._read_json(rd / "plan_result.json") if rd else None)
        if self._is_live_run(rd):
            # live runs override the long node's compute with the scenario's
            # compute_script (in-memory override — the plan file keeps sim_train)
            sc = self._read_yaml(REPO / "scenarios" / "live_research.yaml")
            compute = (sc or {}).get("compute_script") or compute
        return {"question": plan.get("research_question", ""),
                "compute": compute,
                "bait": self._bait_signals(rd, planner, lineup),
                "run_dir": rd.name if rd else None,
                "planner": planner,
                "lineup": lineup,
                "live_cost": (self._read_json(rd / "live_cost.json") if rd else None)}

    def prompts(self) -> dict:
        """Full prompt texts for the Prompt tab. Briefs of live nodes are rebuilt
        deterministically by runtime.roles builders (pure functions of the plan,
        the question, and the bait flag); a persisted scope/prompt.txt (new runs)
        is served as the original instead. `reconstructed` says which is which.
        Mock/scenario runs never used an LLM — their nodes say so."""
        from graph import schema
        from runtime import roles
        plan = self._plan()
        question = plan.get("research_question", "")
        rd = self.run_dir
        lineup = (self._read_json(rd / "lineup.json") if rd else None) or {}
        planner = (self._read_json(rd / "plan_result.json") if rd else None)
        bait = self._bait_signals(rd, planner, lineup)
        out = {"question": question, "prompts": [], "bait": bait}
        try:
            g = schema.load_plan(self.plan_path)
        except Exception:
            return out
        SCRIPTED = ("(scripted system behavior — no LLM prompt; the artifact is "
                    "written by the system worker)")
        def _live_actual(nid):
            a = (lineup.get(nid) or {}).get("actual", "")
            return a.startswith("live") or a == "bait-bit"
        for nid in sorted(g.nodes):
            node = g.nodes[nid]
            behav = roles.behavior(node)
            entry = {"node": nid, "role": node.role, "behavior": behav,
                     "source": "system", "text": SCRIPTED}
            original = rd and (rd / nid / "prompt.txt").exists()
            if original:
                entry.update(source="original",
                             text=(rd / nid / "prompt.txt").read_text(
                                 encoding="utf-8"))
            elif behav == roles.BASELINE and _live_actual(nid):
                entry.update(source="reconstructed",
                             text=roles.build_baseline_brief(node, REPO, question, 8))
            elif behav == roles.METHOD_MANIFEST and _live_actual(nid):
                man = self._read_json(rd / nid / "results.json") or {}
                entry.update(source="reconstructed",
                             text=roles.build_method_stamp_brief(
                                 nid, REPO, float(man.get("score", 0.0)), bait=bait))
            elif behav == roles.ANALYSIS and _live_actual(nid):
                b = self._read_json(rd / roles.baseline_node(g) / "results.json") or {}
                m = self._read_json(rd / roles.method_node(g) / "results.json") or {}
                entry.update(source="reconstructed",
                             text=("system: You are the analysis node of an "
                                   "auto-research pipeline. Be terse.\n\nuser: "
                                   f"Baseline dev_metric={b.get('score')}, method "
                                   f"dev_metric={m.get('score')}, same frozen "
                                   "data/split/protocol/seed (comparability gate "
                                   "already passed). In 3 sentences: does the "
                                   "method beat the baseline? Cite both numbers."))
            elif behav == roles.REPORT_POLISH and _live_actual(nid):
                entry.update(source="reconstructed",
                             text=("system: You polish research reports for a "
                                   "demo audience.\n\nuser: Keep every number and "
                                   "the verdict line verbatim; tighten to <=10 "
                                   "lines of plain English: <report.md excerpt>"))
            out["prompts"].append(entry)
        # money first: live-agent briefs (baseline/method/analysis/report) before
        # the scripted system rows, so the bait brief is visible without scrolling
        rank = {roles.BASELINE: 0, roles.METHOD_MANIFEST: (-1 if bait else 1),
                roles.ANALYSIS: 2, roles.REPORT_POLISH: 3}
        out["prompts"].sort(key=lambda p: (p["source"] == "system",
                                           rank.get(p["behavior"], 9), p["node"]))
        out["reconstructed"] = any(p["source"] == "reconstructed"
                                   for p in out["prompts"])
        return out

    def run_playlist(self, scenes: list[dict]):
        def worker():
            self.status["playlist"] = [s.get("title", s["scenario"]) for s in scenes]
            for i, sc in enumerate(scenes):
                self.status.update(idx=i, state="banner",
                                   banner=sc.get("title", sc["scenario"]))
                time.sleep(2.0)               # inter-scene title banner
                self._play_scenario(sc["scenario"], int(sc.get("tick_ms", 1200)))
            self.status.update(state="idle", banner=None)
        threading.Thread(target=worker, daemon=True).start()


def serve(port: int, replay_file: str | None) -> int:
    import http.server
    import socketserver

    dash = REPO / "dashboard" / "index.html"
    ctl = DemoController()
    if replay_file:
        ctl.load_direct(Path(replay_file))

    class Handler(http.server.BaseHTTPRequestHandler):
        def _send(self, body: bytes, ctype: str, code: int = 200):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200):
            self._send(json.dumps(obj).encode(), "application/json", code)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                self._send(dash.read_bytes(), "text/html; charset=utf-8")
            elif path == "/state.json":
                self._send(ctl.frame_bytes(), "application/json")
            elif path == "/plan_cached.json":
                self._send(ctl.plan_path.read_bytes(), "application/json")
            elif path == "/demo/status":
                self._json(ctl.status_snapshot())
            elif path == "/runinfo.json":
                self._json(ctl.runinfo())
            elif path == "/prompts.json":
                self._json(ctl.prompts())
            else:
                self.send_error(404)

        def do_POST(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path == "/run":
                scenario = (q.get("scenario") or [""])[0]
                tick_ms = int((q.get("tick_ms") or ["1200"])[0])
                if scenario not in _SCENARIOS:
                    self._json({"error": f"bad scenario {scenario}"}, 400)
                elif ctl.busy():
                    self._json({"error": "a run is already active"}, 409)
                else:
                    ctl.run_one(scenario, tick_ms)
                    self._json({"ok": True, "scenario": scenario})
            elif u.path == "/research":
                question = (q.get("q") or [""])[0].strip()
                if not question:
                    self._json({"error": "missing q"}, 400)
                elif ctl.busy():
                    self._json({"error": "a run is already active"}, 409)
                else:
                    ctl.run_research(question)
                    self._json({"ok": True, "scenario": "research"})
            elif u.path == "/demo":
                if ctl.busy():
                    self._json({"error": "a run is already active"}, 409)
                else:
                    pl = (q.get("playlist") or ["default"])[0]
                    ctl.run_playlist(_load_playlist(pl))
                    self._json({"ok": True, "playlist": pl})
            elif u.path == "/demo/ctl":
                op = (q.get("op") or [""])[0]
                ms = int((q.get("ms") or ["1000"])[0])
                ctl.ctl(op, ms)
                self._json({"ok": True, "op": op})
            else:
                self.send_error(404)

        def log_message(self, *a):
            pass

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    httpd = Server(("127.0.0.1", port), Handler)
    mode = f"replay {replay_file}" if replay_file else "demo mode (buttons + ▶ DEMO)"
    print(f"dashboard: http://127.0.0.1:{port}/   [{mode}]  (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    return 0


def _run_planner(question: str) -> int:
    from graph.planner import generate_plan
    ts = time.strftime("%Y%m%d-%H%M%S") + "-plan"
    result = generate_plan(question, REPO / "runs" / ts,
                           REPO / "graph" / "plan_cached.json")
    print(json.dumps(result, indent=2))
    if result["source"] == "live" and result["valid"]:
        print(f"\nLIVE plan generated + validated -> {result['out']}  "
              f"(cost ${result.get('cost')})")
    else:
        print(f"\nfell back to cached plan -> {result['out']}  "
              f"(reason: {result.get('error')})")
    return 0 if result["valid"] else 1


def _run_live_node(node_id: str) -> int:
    """Single-node live smoke: briefing comes from runtime.roles (role-driven)."""
    from core.gates import acceptance_gate
    from runtime import roles
    from runtime.real_worker import LiveAgentWorker
    g = load_graph()
    node = g.nodes.get(node_id)
    if node is None:
        print(f"unknown node {node_id}")
        return 1
    if roles.is_baseline_node(node):
        task = roles.build_baseline_brief(node, REPO, g.research_question, 15)
        goal = "results.json"
    elif node.role == "data":
        task = roles.build_data_brief(node, REPO, g.research_question)
        goal = "data_notes.txt"
    else:
        print(f"node {node_id} (role={node.role!r}) has no live single-node smoke; "
              "smoke a baseline or data node")
        return 1
    ts = time.strftime("%Y%m%d-%H%M%S") + "-live-" + node_id
    run_dir = REPO / "runs" / ts
    scope = run_dir / node_id
    scope.mkdir(parents=True, exist_ok=True)
    try:
        worker = LiveAgentWorker(max_steps=15)
    except RuntimeError as e:
        print(f"live worker unavailable: {e}")
        return 1
    res = worker.run_node(task, scope,
                          lambda: (scope / goal).exists()
                          and (goal != "results.json" or roles.manifest_ok(scope / goal)))
    gr = acceptance_gate(node.acceptance or ["python", "eval/selfcheck.py"],
                         cwd=REPO, env_extra={"NODE_DIR": str(scope)})
    print(f"\n=== LIVE {node_id} (model={res['model']}) ===")
    for t in res["transcript"]:
        print(f"  [{t['step']}] $ {t['cmd']}")
    print(f"steps={res['steps']}  cost=${res['cost']}  manifest_ok={res['done']}  "
          f"acceptance={'PASS' if gr.ok else 'FAIL'}")
    print(f"run_dir: {run_dir}")
    return 0 if (res["done"] and gr.ok) else 1


def _legacy_enable(live_cfg: dict, g) -> set:
    """Compat shim (the ONLY place legacy id-keyed yaml is read): translate
    live_research.yaml's fast_nodes/flags into role-behavior enablement."""
    from runtime import roles
    enable = set()
    for nid in live_cfg.get("fast_nodes", []):
        node = g.nodes.get(nid)
        if node is None:
            continue
        if roles.is_baseline_node(node):
            enable.add(roles.BASELINE)
        elif node.role == "data":
            enable.add(roles.DATA_INSPECT)
    if live_cfg.get("n4_agent_manifest"):
        enable.add(roles.METHOD_MANIFEST)
    if live_cfg.get("n5_analysis"):
        enable.add(roles.ANALYSIS)
    if live_cfg.get("n6_polish"):
        enable.add(roles.REPORT_POLISH)
    return enable


async def run_live_research() -> RunResult:
    """M10 LIVE-10: real data / real long node (real_train) / live agents
    (N1/N3 fast, N4 manifest, N5/N6 one-shot) / real gates. N0/N2 scripted.
    Everything new is gated behind scenarios/live_research.yaml; mock paths and
    plan_cached.json are untouched (graph tweaks are in-memory only)."""
    g = load_graph()
    scenario = load_scenario(REPO / "scenarios" / "live_research.yaml")
    live_cfg = scenario.live or {}
    if scenario.compute_script:
        _apply_compute_override(g, scenario.compute_script)
    ts = time.strftime("%Y%m%d-%H%M%S") + "-live_research"
    run_dir = REPO / "runs" / ts
    print(f"LIVE live_research (M12 role-driven): enable={sorted(_legacy_enable(live_cfg, g))}; "
          f"compute={scenario.compute_script or 'scripts/sim_train.py'}; "
          f"protocol/harness scripted. run_dir={run_dir}")
    result, cost, _ = await _run_live_graph(g, scenario, run_dir,
                                            _legacy_enable(live_cfg, g),
                                            g.research_question)
    _print_summary(result)
    print(f"wall_s={cost['wall_s']:.1f}  live_cost=${cost['cost_usd']:.4f} "
          f"(budget ${cost['budget_usd']})")
    return result


def _apply_compute_override(g, script: str) -> None:
    """Point the (single) long node's compute at `script` — kind-keyed, not id."""
    for n in g.nodes.values():
        if n.kind == schema.Kind.LONG and n.compute:
            n.compute.cmd[1] = script


async def _run_live_graph(g, scenario, run_dir: Path, enable: set,
                          question: str, bait: bool = False):
    """Shared live execution for live_research / --research: RoleWorker dispatch
    by (kind, role), role-wired live hooks, lineup + cost ledgers. tick_s=0.8 so
    the hung law (K_FREEZE=3 ticks) >> 1.8s stage cadence; 1200 ticks = 960s cap."""
    from runtime import roles
    live_cfg = scenario.live or {}
    tick_s = 0.8
    g.budget.max_ticks = 1200
    for k in list(g.budget.max_laps):
        g.budget.max_laps[k] = min(g.budget.max_laps[k],
                                   int(live_cfg.get("max_laps", 2)))
    run_dir = Path(run_dir)
    clock = TickClock()
    log = IncidentLog(run_dir, keep_last=20)
    sup = Supervisor(g, log, now=clock.now, baseline_id=roles.baseline_node(g),
                     target=0.6041)
    tracker = {"cost": 0.0}
    lineup: dict = {}
    worker = roles.RoleWorker(MockWorker(scenario, REPO, tick_s), enable, live_cfg,
                              tracker, lineup, question, REPO, bait=bait)
    orch = Orchestrator(
        g, sup, worker, scenario, clock, run_dir, REPO, tick_s=tick_s,
        long_manifest_hook=(roles.method_manifest_hook(live_cfg, tracker, lineup,
                                                       REPO, bait=bait)
                            if roles.METHOD_MANIFEST in enable else None),
        n5_hook=(roles.analysis_hook(tracker, lineup, roles.baseline_node(g),
                                     roles.method_node(g))
                 if roles.ANALYSIS in enable else None),
        n6_hook=(roles.report_polish_hook(tracker, lineup)
                 if roles.REPORT_POLISH in enable else None))
    t0 = time.time()
    result = await orch.run()
    wall = time.time() - t0
    if roles.REPORT_POLISH in enable:
        # N6 fires mid-run; re-polish against the FINAL render so the archived
        # polished report never quotes a stale intermediate verdict line.
        roles.report_polish_hook(tracker, lineup)("N6", run_dir, None)
    cost = {"model": os.environ.get("LIVE_MODEL") or "default",
            "cost_usd": round(tracker["cost"], 6), "wall_s": round(wall, 1),
            "budget_usd": live_cfg.get("api_budget_usd", 3.0)}
    (run_dir / "live_cost.json").write_text(json.dumps(cost, indent=2),
                                            encoding="utf-8")
    (run_dir / "lineup.json").write_text(json.dumps(lineup, indent=2),
                                         encoding="utf-8")
    return result, cost, lineup


async def run_research(question: str, bait: bool = False):
    """M12 real-life path: one sentence in -> planner (error-feedback retry <=3)
    -> schema+normalizer validation -> role-driven live execution -> report."""
    from graph import planner
    from runtime import roles
    ts = time.strftime("%Y%m%d-%H%M%S") + "-research" + ("-bait" if bait else "")
    run_dir = REPO / "runs" / ts
    plan = planner.generate_plan_retry(question, run_dir,
                                       REPO / "graph" / "plan_cached.json")
    (run_dir / "plan_result.json").write_text(json.dumps(plan, indent=2),
                                              encoding="utf-8")
    print(f"planner: source={plan['source']} attempts={plan.get('attempts')} "
          f"cost=${plan.get('cost')} valid={plan['valid']}"
          + (f" error={plan.get('error')}" if plan.get("error") else ""))
    g = load_graph(plan["out"])
    scenario = load_scenario(REPO / "scenarios" / "live_research.yaml")
    if scenario.compute_script:
        _apply_compute_override(g, scenario.compute_script)
    bait_dir = roles.make_bait_dataset(REPO) if bait else None
    try:
        result, cost, lineup = await _run_live_graph(
            g, scenario, run_dir, set(roles.DEFAULT_LIVE_ENABLE), question, bait=bait)
    finally:
        if bait_dir:
            roles.drop_bait_dataset(REPO)       # frozen data_hash must not drift
    _print_summary(result)
    print(f"wall_s={cost['wall_s']:.1f}  live_cost=${cost['cost_usd']:.4f}")
    return result, {"plan": plan, "cost": cost, "lineup": lineup,
                    "run_dir": str(run_dir)}


async def run_live_full(live_nodes=("N3",)) -> RunResult:
    from runtime import roles
    g = load_graph()
    scenario = load_scenario(REPO / "scenarios" / "green.yaml")
    ts = time.strftime("%Y%m%d-%H%M%S") + "-live-full"
    run_dir = REPO / "runs" / ts
    clock = TickClock()
    log = IncidentLog(run_dir, keep_last=20)
    sup = Supervisor(g, log, now=clock.now, baseline_id=roles.baseline_node(g),
                     target=0.6041)
    enable = set()
    for nid in live_nodes:                     # legacy id list -> role enablement
        n = g.nodes.get(nid)
        if n and roles.is_baseline_node(n):
            enable.add(roles.BASELINE)
        elif n and n.role == "data":
            enable.add(roles.DATA_INSPECT)
    tracker: dict = {"cost": 0.0}
    worker = roles.RoleWorker(MockWorker(scenario, REPO, TICK_S), enable, {},
                              tracker, {}, g.research_question, REPO)
    print(f"LIVE full run: role enablement {sorted(enable)} (from {sorted(live_nodes)}), "
          f"scripted elsewhere (N4 compute=sim_train). run_dir={run_dir}")
    result = await Orchestrator(g, sup, worker, scenario, clock, run_dir, REPO,
                                tick_s=TICK_S).run()
    _print_summary(result)
    return result


def main() -> int:
    a = parse_args()
    if a.live or a.plan is not None or a.research is not None:
        from runtime.real_worker import load_dotenv
        load_dotenv()                       # .env defaults (real env wins)
    if a.plan is not None:
        return _run_planner(a.plan)
    if a.serve:
        return serve(a.port, a.replay)
    if a.replay:
        from core.replay import replay_render
        return replay_render(Path(a.replay))
    if a.research is not None:
        if a.bait:                          # 下饵：≤3 竿，咬钩（WITHHELD）即收
            for cast in range(1, 4):
                print(f"\n##### bait cast {cast}/3 #####")
                r, _meta = asyncio.run(run_research(a.research, bait=True))
                if r.verdict.get("blocked"):
                    print(f"BAIT TAKEN on cast {cast}: COMPARABILITY_BLOCK, "
                          "culprit blamed, result WITHHELD")
                    return 0
                print(f"cast {cast}: agent did not bite "
                      f"({r.verdict['line'][:70]}...)")
            print("no bite in 3 casts — recorded honestly")
            return 1
        r, _meta = asyncio.run(run_research(a.research))
        return 0 if r.quiesced else 2
    if a.live:
        if a.node:
            return _run_live_node(a.node)
        if a.scenario == "live_research":
            result = asyncio.run(run_live_research())
            return 0 if result.quiesced else 2
        result = asyncio.run(run_live_full())      # full graph, N3 real agent
        return 0 if result.quiesced else 2
    if not a.mock:
        raise SystemExit("specify a mode: --mock --scenario X | --replay FILE | "
                         "--serve [--replay FILE] | --live")
    if not a.scenario:
        raise SystemExit("--mock requires --scenario")
    result = asyncio.run(run_mock(a.scenario, a.plan_file))
    return 0 if result.quiesced else 2


if __name__ == "__main__":
    sys.exit(main())
