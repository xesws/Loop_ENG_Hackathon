# AGENTS.md — OOAA · Graph Supervisor for Auto-Research

Guidance for AI coding agents working in this repository. Read this before
touching anything. `CLAUDE.md` is the human-facing companion doc (Chinese);
where they differ on rules, treat both as binding.

## Project overview

OOAA is an asynchronous, graph-native supervision layer for multi-agent
auto-research. A research plan is a directed graph whose nodes are typed
`fast` / `long` / `reactive` and whose edges are typed `artifact` (hard
dependency, gates readiness) / `stream` (subscription, never blocks) /
`back_edge` (metered iteration loop, removed from the DAG and budgeted by
`max_laps`). Scheduling uses a ready-set plus resource slots `{gpu: 1, cpu: 3}`;
there is no graph-wide barrier.

The supervisor's job: judge progress of long-running nodes (hung / plateau /
zombie), enforce acceptance and comparability gates, propagate taint along
artifact edges, apply a five-rung escalation ladder
(`bounce → blame_routing → downstream_invalidation → graph_surgery → fuse`),
and keep an anytime report self-consistent.

Core thesis: **never trust what an agent says; only observe whether the world
state changed** (file fingerprints, metric trajectories, exit codes).

Context: built for an AWS Builder Loft hackathon demo (2026-07-17). Tonight's
goal is a fully mocked, deterministic, offline run; the live stage
(RealWorker, dashboard, prompt-injection traps) comes later, and **the mock
path must always stay runnable** — it is the demo's final fallback.

Current milestone status (per `git log`): M0 (skeleton: schema, fs,
incidents, clock) and M1 (normalizer, gates, supervisor detectors/ladder,
unit suite) are done. The orchestrator, workers, `run.py`, scenarios, and
dashboard are M2+ work and **do not exist yet** — see "Planned but missing"
below.

## Build and test commands

There is no build step and no packaging metadata (no `pyproject.toml`,
`requirements.txt`, or similar). Dependencies are expected to be installed in
the environment: Python 3.11+, `networkx`, `pyyaml`, `pytest`
(`rich` optional). Verified working on Python 3.13.5 / networkx 3.5 /
pytest 8.3.4.

```bash
pytest -q                                   # full suite (36 tests, ~0.1s)
python eval/selfcheck.py                    # N0 acceptance: frozen data/protocol exist
python eval/score.py --who baseline         # acceptance harness (needs NODE_DIR env)
python scripts/sim_train.py --profile rise_cross   # mock trainer (writes ./metrics.jsonl, ./ckpt/)
```

Planned entry points (after M2/M3, not yet present):

```bash
python run.py --mock --scenario {green|trap_b|plateau|hung}
python run.py --replay runs/<ts>/replay.jsonl
```

## Repository layout

```
graph/       schema.py        frozen data contract: enums, Node/Edge/Graph/Manifest,
                              load_plan(), validate() — every module reads this
             normalizer.py    networkx Tarjan SCC over artifact-only subgraph;
                              demotes undeclared 2-cycles to metered back_edges,
                              rejects SCCs >2, sets topo_order
             plan_cached.json cached 10-node research plan fixture (N0..N7)
core/        supervisor.py    SINGLE authority for status transitions + incident
                              writes; detectors, gate judging, cascade/taint, verdict
             gates.py         acceptance_gate (subprocess exit code only) and
                              comparability_gate (four-tuple); pure functions
             incidents.py     Incident + append-only IncidentLog (incidents.jsonl)
             clock.py         TickClock — the only source of time (logical ticks)
runtime/     fs.py            fingerprints (sha256 scope hash), atomic writes,
                              JSONL tail, manifest I/O, frozen_fields()
eval/        protocol.md      frozen protocol contract (p1); its sha256 IS
                              protocol_version — do not edit
             score.py         frozen scoring/acceptance harness, exit-code driven
             selfcheck.py     N0's acceptance argv
scripts/     sim_train.py     deterministic mock trainer; profiles:
                              rise_cross (beats baseline), rise_plateau, hang
data/        train.jsonl      frozen toy text-to-SQL data
             split.json       frozen split (seed 42)
tests/       pytest suite + conftest.py (mk_graph / mk_sup fixtures)
conftest.py  root conftest puts repo root on sys.path (intentionally empty)
pytest.ini   asyncio_mode=auto, testpaths=tests, -p no:cacheprovider
dashboard/   empty (dashboard/index.html comes later; may stay a shell tonight)
scenarios/   empty (scenario definitions come with the orchestrator)
runs/        gitignored run-output directory (incidents.jsonl, state.json, …)
```

Planned but missing (do not assume they exist; per CLAUDE.md's fixed layout):
`run.py`, `core/orchestrator.py`, `runtime/worker.py`, `runtime/mock_worker.py`.
Note: `PROMPT.md` and `loop_hackathon_workbook.md` are referenced by CLAUDE.md
as authority docs but are not committed to the repo.

## Architecture and key invariants

- **Supervisor is the only mutator.** All node status transitions go through
  `Supervisor.transition()` and all incidents through `Supervisor.raise_incident()`.
  The (future) orchestrator only observes world state and calls in. Every
  escalation-ladder action must persist an incident — silent intervention is a bug.
- **Determinism by logical time.** Decisions are functions of world state and
  the logical tick, never of wall clock. `time.time()` is banned everywhere
  except deriving a pseudo-wall (`ticks * TICK_S`) for a manifest's `wall_s`.
  Acceptance gates run with `PYTHONHASHSEED=0`. Incident lines are serialized
  with `sort_keys=True` so identical scenarios produce byte-identical logs
  (guarded by `tests/test_determinism.py`).
- **Comparability four-tuple.** Results are comparable to the baseline iff
  `(data_hash, split_hash, protocol_version, seed)` match exactly; no float
  equality anywhere. `data_hash`/`split_hash`/`protocol_version` derive from
  the frozen files via `runtime/fs.py::frozen_fields()`.
- **Fingerprints.** Long-node fingerprint = its `(step, best_dev)` trajectory
  tailed from `metrics.jsonl`. Fast/reactive fingerprint = sha256 over a
  sorted walk of the node's scope dir (content + relative paths; mtimes,
  sizes, `__pycache__`, `*.pyc`, `.DS_Store` excluded) — must be a pure
  function of content across runs and OSes.
- **Taint/cascade.** Propagates along artifact edges only, never stream edges.
  Protocol taint invalidates readings but spares `role == "train"` nodes.
  Reopening a node demotes its verified artifact-descendants to `stale`.
- **Kills happen at checkpoint boundaries** and keep the best checkpoint
  (`best_ckpt`/`best_dev` retained in detector state).
- **Statuses** are the 10 canonical values in `graph/schema.py::Status`;
  terminal = `{verified, killed, plateaued, superseded}`. A reactive node at
  rest is `blocked`; it flips to `running` while handling a stream event.
- **Acceptance = exit code.** `acceptance_gate` runs the node's acceptance
  argv (30s timeout); only the exit code is a signal. stdout/stderr are
  evidence, never parsed.
- **state.json schema freezes after M1** — the dashboard will read only it.

### Thresholds are law (do not tune)

Defined in `core/supervisor.py`:
`K_FREEZE=3`, `PLATEAU_EPS=0.005`, `PLATEAU_PATIENCE=2`,
`HUNG_MAX_RESTARTS=1`, `ACCEPT_MAX_LAPS=3`, `ACCEPT_EPS=0.003`, `TARGET=0.58`.

### Escalation ladder and incident types

Ladder rungs in escalation order (cheap → expensive): `bounce`,
`blame_routing`, `downstream_invalidation`, `graph_surgery`, `fuse`.
Incident types (closed set, asserted in `core/incidents.py`):
`SCOPE_VIOLATION`, `FALSE_COMPLETION`, `COMPARABILITY_BLOCK`, `PLATEAU_TRIP`,
`HUNG_RESTART`, `SUPERSEDED_KILL`, `STALE_CASCADE`, `TAINT_INVALIDATION`,
`BUDGET_TRIP`, `OSCILLATION_TRIP`.

## Code style guidelines

- Python 3.11+ with `asyncio`; `from __future__ import annotations` at top.
- `dataclass` + full type hints; enums subclass `str` so JSON round-trips.
- Identifiers and code comments in **English**; human-facing docs may be Chinese.
- `core/supervisor.py` target: under 300 lines.
- Fail loudly: raise or write an incident — never swallow errors silently.
- Keep modules small and single-purpose; pure functions where possible
  (gates and fs are pure; supervisor holds all mutable state).
- No hidden global state.

## Testing instructions

- Run everything with `pytest -q` from the repo root (root `conftest.py`
  makes `graph`/`core`/`runtime` importable; `pytest.ini` sets
  `asyncio_mode = auto`, so async tests need no marker).
- Suite layout mirrors modules: `test_schema`, `test_normalizer`,
  `test_gates`, `test_incidents`, `test_clock`, `test_detectors_fast`,
  `test_detectors_long`, `test_cascade_taint`, `test_verdict`,
  `test_determinism`.
- Shared fixtures live in `tests/conftest.py`: `mk_graph` builds synthetic
  graphs, `mk_sup` builds a `Supervisor` + `IncidentLog` against a `tmp_path`
  run dir with a frozen `now=lambda: 0` clock.
- `tests/test_determinism.py` is the golden guard: identical scripted
  supervision sequences must emit byte-identical `incidents.jsonl`. Any change
  that perturbs incident serialization, thresholds, or detector semantics
  breaks it — that is intentional.
- Definition of done for the hackathon (per CLAUDE.md): the acceptance
  commands in `PROMPT.md` (not committed) must really pass, with output pasted
  into `FINAL_REPORT.md`. Any scenario wall time over 120 s is a bug.

## Security and dependency constraints (iron rules)

Violating any of these is a bug:

1. Zero network access, zero LLM/API calls on the mock path — everything is
   mocked, deterministic, and offline.
2. Dependency whitelist: stdlib + `networkx` + `pyyaml` + `pytest`
   (+ optional `rich`). **No** LangChain/LangGraph, docker, web frameworks,
   or databases. Do not add dependencies; there is deliberately no lockfile.
3. State transitions and incidents only via the supervisor API.
4. Do not redesign the product, add unlisted features, or fork an
   auto-research framework; when specs are silent, choose the smaller
   implementation.
5. `eval/protocol.md` and `data/` are frozen contracts — their hashes feed
   the comparability four-tuple; editing them silently invalidates results.

## Git conventions

- One commit per milestone, message format `M<n>: <what was done>`
  (e.g. `M1: normalizer (Tarjan) + gates + supervisor detectors/ladder + unit suite`).
- Work directly on `main`. Never force push.
- `runs/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.DS_Store` are gitignored.
