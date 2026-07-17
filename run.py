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
import sys
import time
from pathlib import Path

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
    p.add_argument("--scenario",
                   choices=["green", "trap_b", "plateau", "hung", "trap_scope"])
    return p.parse_args()


def load_graph() -> schema.Graph:
    g = schema.load_plan(REPO / "graph" / "plan_cached.json")
    errs = schema.validate(g)
    if errs:
        raise SystemExit("plan invalid:\n  " + "\n  ".join(errs))
    return normalizer.normalize(g)


async def run_mock(scenario_name: str) -> RunResult:
    g = load_graph()
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
class _ReplayFeed:
    """Steps through a replay.jsonl at ~2Hz and synthesizes a state.json frame
    per tick (nodes snapshot + accumulated incidents). Holds the last frame."""
    def __init__(self, path: Path, adv_s: float = 0.5):
        self.lines = [json.loads(ln) for ln in Path(path).read_text().splitlines()
                      if ln.strip()]
        self.adv_s = adv_s
        self.idx = 0

    def start(self):
        import threading

        def loop():
            while self.idx < len(self.lines) - 1:
                time.sleep(self.adv_s)
                self.idx += 1
        threading.Thread(target=loop, daemon=True).start()

    def frame_bytes(self) -> bytes:
        if not self.lines:
            return b'{"ts":0,"nodes":[],"incidents":[],"report_version":0}'
        i = min(self.idx, len(self.lines) - 1)
        rec = self.lines[i]
        incs = []
        for r in self.lines[:i + 1]:
            incs.extend(r.get("incidents", []))
        frame = {"ts": rec["tick"], "nodes": rec["nodes"],
                 "incidents": incs[-20:], "report_version": rec.get("report_version", 0)}
        return json.dumps(frame).encode()


_EMPTY = b'{"ts":0,"nodes":[],"incidents":[],"report_version":0}'


def serve(port: int, replay_file: str | None) -> int:
    import http.server
    import socketserver

    dash = REPO / "dashboard" / "index.html"
    plan = REPO / "graph" / "plan_cached.json"
    feed = None
    if replay_file:
        feed = _ReplayFeed(Path(replay_file))
        feed.start()

    def state_bytes() -> bytes:
        if feed:
            return feed.frame_bytes()
        files = glob.glob(str(REPO / "runs" / "*" / "state.json"))
        if not files:
            return _EMPTY
        try:
            return Path(max(files, key=os.path.getmtime)).read_bytes()
        except OSError:
            return _EMPTY

    class Handler(http.server.BaseHTTPRequestHandler):
        def _send(self, body: bytes, ctype: str):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                self._send(dash.read_bytes(), "text/html; charset=utf-8")
            elif path == "/state.json":
                self._send(state_bytes(), "application/json")
            elif path == "/plan_cached.json":
                self._send(plan.read_bytes(), "application/json")
            else:
                self.send_error(404)

        def log_message(self, *a):
            pass

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    httpd = Server(("127.0.0.1", port), Handler)
    mode = f"replay {replay_file}" if replay_file else "live (follows newest runs/*/state.json)"
    print(f"dashboard: http://127.0.0.1:{port}/   [{mode}]  (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    return 0


def main() -> int:
    a = parse_args()
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
    result = asyncio.run(run_mock(a.scenario))
    return 0 if result.quiesced else 2


if __name__ == "__main__":
    sys.exit(main())
