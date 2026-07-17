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
        self._swap_feed(_ReplayFeed(path, adv_s=tick_ms / 1000.0))
        self.status.update(state="playing", scenario="(replay)", banner=None)

    def _play_scenario(self, scenario: str, tick_ms: int):
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
        self._swap_feed(_ReplayFeed(Path(max(files, key=os.path.getmtime)),
                                    adv_s=tick_ms / 1000.0))
        self.status.update(state="playing")
        while not self.feed.done:
            time.sleep(0.1)
        time.sleep(2.5)                       # hold the final frame

    def run_one(self, scenario: str, tick_ms: int):
        def worker():
            self._play_scenario(scenario, tick_ms)
            self.status.update(state="idle", banner=None)
        threading.Thread(target=worker, daemon=True).start()

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
    plan = REPO / "graph" / "plan_cached.json"
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
                self._send(plan.read_bytes(), "application/json")
            elif path == "/demo/status":
                self._json(ctl.status_snapshot())
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


def _live_task(node_id: str) -> str:
    return (
        f"You are node {node_id} of an auto-research pipeline, working in your "
        f"sandbox directory (your cwd). The repo root is {REPO}.\n"
        f"Read-only inputs: {REPO}/data/dataset.csv (400 rows, features x1..x7, "
        f"target y) and {REPO}/data/split.json (train/dev row indices).\n"
        "Goal: establish a BASELINE dev_metric (R^2 on the dev split) for a "
        "LINEAR least-squares model on x1..x7, then emit results.json in your cwd.\n"
        "Write a SMALL python script that fits OLS (normal equations) on the "
        "train rows and prints R^2 on the dev rows. BUDGET YOUR STEPS: emit the "
        "whole computation as ONE command (a single python3 -c \"...\" or one "
        "printf block writing the file at once) — never write a file line by "
        "line. A correct answer lands roughly in [0.55, 0.70].\n"
        "Emit the manifest (with the correct frozen hashes) by running:\n"
        f"  python {REPO}/eval/make_manifest.py --node {node_id} --score <SCORE> --out results.json\n"
        "Use ABSOLUTE paths for repo files. Allowed commands: ls, cat, head, python, echo.\n"
        "When results.json is written and valid, reply DONE."
    )


def _manifest_ok(path: Path) -> bool:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return (isinstance(d.get("score"), (int, float)) and 0.0 <= d["score"] <= 1.0
            and all(k in d for k in ("data_hash", "split_hash", "protocol_version", "seed")))


def _run_live_node(node_id: str) -> int:
    from core.gates import acceptance_gate
    from runtime.real_worker import LiveAgentWorker
    ts = time.strftime("%Y%m%d-%H%M%S") + "-live-" + node_id
    run_dir = REPO / "runs" / ts
    scope = run_dir / node_id
    scope.mkdir(parents=True, exist_ok=True)
    try:
        worker = LiveAgentWorker(max_steps=15)
    except RuntimeError as e:
        print(f"live worker unavailable: {e}")
        return 1
    res = worker.run_node(_live_task(node_id), scope, lambda: _manifest_ok(scope / "results.json"))
    accept = {"N3": ["python", "eval/score.py", "--who", "baseline"],
              "N4": ["python", "eval/score.py", "--who", "method"]}.get(
                  node_id, ["python", "eval/selfcheck.py"])
    gr = acceptance_gate(accept, cwd=REPO, env_extra={"NODE_DIR": str(scope)})
    print(f"\n=== LIVE {node_id} (model={res['model']}) ===")
    for t in res["transcript"]:
        print(f"  [{t['step']}] $ {t['cmd']}")
    print(f"steps={res['steps']}  cost=${res['cost']}  manifest_ok={res['done']}  "
          f"acceptance={'PASS' if gr.ok else 'FAIL'}")
    print(f"run_dir: {run_dir}")
    return 0 if (res["done"] and gr.ok) else 1


def _n1_task() -> str:
    return (
        "You are node N1 (data) of an auto-research pipeline, working in your "
        f"sandbox directory (your cwd). The repo root is {REPO}.\n"
        f"Read-only inputs: {REPO}/data/dataset.csv (400 rows, features x1..x7, "
        f"target y) and {REPO}/data/split.json (train/dev row indices).\n"
        "Goal: inspect the data and write data_notes.txt in your cwd with: the "
        "row count, the feature column names, and the train/dev sizes.\n"
        "Use ABSOLUTE paths for repo files. Allowed commands: ls, cat, head, "
        "python, echo. When data_notes.txt is written, reply DONE."
    )


def _notes_ok(path: Path) -> bool:
    try:
        return path.exists() and path.stat().st_size > 0
    except OSError:
        return False


class _HybridWorker:
    """Full-graph live: drive a real agent for `live_nodes`, mock the rest.
    Falls back to the mock worker if the live agent is unavailable/fails."""
    def __init__(self, mock, live_nodes, max_steps=15, tracker=None):
        self.mock = mock
        self.live_nodes = set(live_nodes)
        self.max_steps = max_steps
        self.tracker = tracker if tracker is not None else {"cost": 0.0}

    def run_fast(self, node, scope_dir):
        if node.id not in self.live_nodes:
            return self.mock.run_fast(node, scope_dir)
        from runtime.fs import read_manifest
        from runtime.real_worker import LiveAgentWorker
        from runtime.worker import NodeResult
        sp = Path(scope_dir)
        sp.mkdir(parents=True, exist_ok=True)
        if node.id == "N1":
            task, goal, check = _n1_task(), "data_notes.txt", _notes_ok
        else:
            task, goal, check = _live_task(node.id), "results.json", _manifest_ok
        try:
            res = LiveAgentWorker(max_steps=self.max_steps).run_node(
                task, sp, lambda: check(sp / goal))
            self.tracker["cost"] += res.get("cost", 0.0)
            if not res.get("done"):
                print(f"[live {node.id}] goal not met; mock fallback", file=sys.stderr)
                return self.mock.run_fast(node, sp)
        except Exception as e:
            print(f"[live {node.id}] unavailable ({e}); mock fallback", file=sys.stderr)
            return self.mock.run_fast(node, sp)
        man = read_manifest(sp / "results.json") if _manifest_ok(sp / "results.json") else None
        return NodeResult(node=node.id, artifacts=[goal], manifest=man,
                          events=["done"], duration_ticks=2)


def _n4_manifest_hook(live_cfg, tracker):
    """N4agent: a live agent stamps N4's manifest (frozen four-tuple via
    make_manifest); returns None -> orchestrator falls back to world-state."""
    def hook(nid, scope, score):
        from runtime.fs import read_manifest
        from runtime.real_worker import LiveAgentWorker
        sp = Path(scope)
        task = (
            f"You are node {nid} (train) of an auto-research pipeline, working in "
            "your sandbox directory (your cwd). Training just finished; "
            f"best dev_metric={score:.4f}.\n"
            "Stamp the results manifest by running:\n"
            f"  python {REPO}/eval/make_manifest.py --node {nid} --score {score:.4f} --out results.json\n"
            "Then reply DONE."
        )
        try:
            res = LiveAgentWorker(max_steps=live_cfg.get("max_steps", 8)).run_node(
                task, sp, lambda: _manifest_ok(sp / "results.json"))
            tracker["cost"] += res.get("cost", 0.0)
            if res.get("done"):
                return read_manifest(sp / "results.json")
        except Exception as e:
            print(f"[live {nid} manifest] unavailable ({e}); world-state fallback",
                  file=sys.stderr)
        return None
    return hook


def _n5_hook(tracker):
    """N5 live: one LLM call turns the two comparable manifests into analysis.md."""
    def hook(nid, scope, manifests):
        from runtime.real_worker import chat_once
        try:
            n3, n4 = manifests["N3"], manifests["N4"]
            text, cost = chat_once(
                "You are the analysis node of an auto-research pipeline. Be terse.",
                f"Baseline N3 dev_metric={n3['score']}, method N4 "
                f"dev_metric={n4['score']}, same frozen data/split/protocol/seed. "
                "In 3 sentences: does the fine-tuned method beat the few-shot "
                "baseline? Cite both numbers.")
            tracker["cost"] += cost
            sp = Path(scope)
            sp.mkdir(parents=True, exist_ok=True)
            (sp / "analysis.md").write_text(text + "\n", encoding="utf-8")
        except Exception as e:
            print(f"[live N5 analysis] unavailable ({e})", file=sys.stderr)
    return hook


def _n6_hook(tracker):
    """N6 live: one LLM call polishes the anytime report (numbers verbatim)."""
    def hook(nid, run_dir, _):
        from runtime.real_worker import chat_once
        try:
            rpt = Path(run_dir) / "report" / "report.md"
            if not rpt.exists():
                rpt = Path(run_dir) / "report.md"
            report = rpt.read_text(encoding="utf-8")
            text, cost = chat_once(
                "You polish research reports for a demo audience.",
                "Keep every number and the verdict line verbatim; tighten to "
                "<=10 lines of plain English:\n\n" + report[:3000])
            tracker["cost"] += cost
            (Path(run_dir) / "report_polished.md").write_text(text + "\n",
                                                              encoding="utf-8")
        except Exception as e:
            print(f"[live N6 polish] unavailable ({e})", file=sys.stderr)
    return hook


async def run_live_research() -> RunResult:
    """M10 LIVE-10: real data / real long node (real_train) / live agents
    (N1/N3 fast, N4 manifest, N5/N6 one-shot) / real gates. N0/N2 scripted.
    Everything new is gated behind scenarios/live_research.yaml; mock paths and
    plan_cached.json are untouched (graph tweaks are in-memory only)."""
    g = load_graph()
    scenario = load_scenario(REPO / "scenarios" / "live_research.yaml")
    live_cfg = scenario.live or {}
    if scenario.compute_script:
        g.nodes["N4"].compute.cmd[1] = scenario.compute_script
    tick_s = 0.8                       # hung law K_FREEZE=3 ticks >> 1.8s stage cadence
    g.budget.max_ticks = 1200          # 1200 * 0.8s = 960s ceiling (mock: 800*0.08)
    if "N5->N4" in g.budget.max_laps:
        g.budget.max_laps["N5->N4"] = min(g.budget.max_laps["N5->N4"],
                                          int(live_cfg.get("max_laps", 2)))
    ts = time.strftime("%Y%m%d-%H%M%S") + "-live_research"
    run_dir = REPO / "runs" / ts
    clock = TickClock()
    log = IncidentLog(run_dir, keep_last=20)
    sup = Supervisor(g, log, now=clock.now, baseline_id="N3", target=0.6041)
    tracker = {"cost": 0.0}
    worker = _HybridWorker(MockWorker(scenario, REPO, tick_s),
                           live_cfg.get("fast_nodes", ["N1", "N3"]),
                           max_steps=int(live_cfg.get("max_steps", 8)),
                           tracker=tracker)
    orch = Orchestrator(
        g, sup, worker, scenario, clock, run_dir, REPO, tick_s=tick_s,
        long_manifest_hook=(_n4_manifest_hook(live_cfg, tracker)
                            if live_cfg.get("n4_agent_manifest") else None),
        n5_hook=_n5_hook(tracker) if live_cfg.get("n5_analysis") else None,
        n6_hook=_n6_hook(tracker) if live_cfg.get("n6_polish") else None)
    print(f"LIVE live_research: live agents {live_cfg.get('fast_nodes')} + "
          f"N4agent(manifest) + N5/N6 one-shot; N4 compute="
          f"{scenario.compute_script or 'scripts/sim_train.py'}; N0/N2 scripted. "
          f"run_dir={run_dir}")
    t0 = time.time()
    result = await orch.run()
    wall = time.time() - t0
    cost = {"model": os.environ.get("LIVE_MODEL") or "default",
            "cost_usd": round(tracker["cost"], 6), "wall_s": round(wall, 1),
            "budget_usd": live_cfg.get("api_budget_usd", 3.0)}
    (run_dir / "live_cost.json").write_text(json.dumps(cost, indent=2),
                                            encoding="utf-8")
    _print_summary(result)
    print(f"wall_s={wall:.1f}  live_cost=${tracker['cost']:.4f} "
          f"(budget ${cost['budget_usd']})")
    return result


async def run_live_full(live_nodes=("N3",)) -> RunResult:
    g = load_graph()
    scenario = load_scenario(REPO / "scenarios" / "green.yaml")
    ts = time.strftime("%Y%m%d-%H%M%S") + "-live-full"
    run_dir = REPO / "runs" / ts
    clock = TickClock()
    log = IncidentLog(run_dir, keep_last=20)
    sup = Supervisor(g, log, now=clock.now, baseline_id="N3", target=0.6041)
    worker = _HybridWorker(MockWorker(scenario, REPO, TICK_S), live_nodes)
    print(f"LIVE full run: real agent on {sorted(live_nodes)}, mock elsewhere "
          f"(N4 compute=sim_train). run_dir={run_dir}")
    result = await Orchestrator(g, sup, worker, scenario, clock, run_dir, REPO,
                                tick_s=TICK_S).run()
    _print_summary(result)
    return result


def main() -> int:
    a = parse_args()
    if a.live or a.plan is not None:
        from runtime.real_worker import load_dotenv
        load_dotenv()                       # .env defaults (real env wins)
    if a.plan is not None:
        return _run_planner(a.plan)
    if a.serve:
        return serve(a.port, a.replay)
    if a.replay:
        from core.replay import replay_render
        return replay_render(Path(a.replay))
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
