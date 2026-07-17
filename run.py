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
    p.add_argument("--scenario",
                   choices=["green", "trap_b", "plateau", "hung", "trap_scope",
                            "trap_stale", "trap_taint"])
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
    sup = Supervisor(g, log, now=clock.now, baseline_id="N3", target=0.58)
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


class _ReplayFeed:
    """Steps through a replay.jsonl at `adv_s` per frame and synthesizes a
    state.json frame per tick (nodes snapshot + accumulated incidents). Holds the
    last frame. adv_s is the demo pacing knob (reused for --tick-ms)."""
    def __init__(self, path: Path, adv_s: float = 0.5):
        self.lines = [json.loads(ln) for ln in Path(path).read_text().splitlines()
                      if ln.strip()]
        self.adv_s = adv_s
        self.idx = 0

    def start(self):
        def loop():
            while self.idx < len(self.lines) - 1:
                time.sleep(self.adv_s)
                self.idx += 1
        threading.Thread(target=loop, daemon=True).start()

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

    def load_direct(self, path: Path, tick_ms: int = 500):
        self.feed = _ReplayFeed(path, adv_s=tick_ms / 1000.0)
        self.feed.start()
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
        self.feed = _ReplayFeed(Path(max(files, key=os.path.getmtime)),
                                adv_s=tick_ms / 1000.0)
        self.feed.start()
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
                self._json(ctl.status)
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


def main() -> int:
    a = parse_args()
    if a.plan is not None:
        return _run_planner(a.plan)
    if a.serve:
        return serve(a.port, a.replay)
    if a.replay:
        from core.replay import replay_render
        return replay_render(Path(a.replay))
    if a.live:
        from runtime.worker import RealWorker
        try:
            RealWorker()      # raises: live path (mini-swe-agent) is tomorrow's work
        except NotImplementedError as e:
            print(f"--live is not wired tonight: {e}", file=sys.stderr)
        return 1
    if not a.mock:
        raise SystemExit("specify a mode: --mock --scenario X | --replay FILE | "
                         "--serve [--replay FILE] | --live")
    if not a.scenario:
        raise SystemExit("--mock requires --scenario")
    result = asyncio.run(run_mock(a.scenario, a.plan_file))
    return 0 if result.quiesced else 2


if __name__ == "__main__":
    sys.exit(main())
