# Graph Supervisor for Auto-Research

An asynchronous, **graph-native supervision layer** for multi-agent auto-research.
Multiple agents collaborate on a research question over a task graph; this layer is
the **PI (principal investigator)** that watches the graph and catches agents that
hang, plateau, falsely claim completion, or quietly break comparability — using
**purely programmatic signals** (file hashes, numeric trajectories, manifest
tuples), never an LLM judge.

> Thesis: **don't evaluate what an agent _says_, only whether the _world-state_
> changed.**

Tonight's build is **mock-first**: the runtime path makes zero LLM/API/network
calls, is deterministic and offline, and every scenario finishes in a few seconds.

## Run

```bash
pip install networkx pyyaml pytest      # rich optional
pytest -q                               # unit suite (L0)

python run.py --mock --scenario green    # clean run  -> RESEARCH ANSWERED
python run.py --mock --scenario trap_b   # comparability trap -> COMPARABILITY_BLOCK, blame N4
python run.py --mock --scenario plateau  # plateau -> PLATEAU_TRIP, negative result, spawn N7
python run.py --mock --scenario hung     # (bonus) stall -> HUNG_RESTART then kill

python run.py --replay runs/<ts>/replay.jsonl   # re-render a run, no workers executed
```

Each run writes `runs/<ts>/`: `state.json` (per-tick), `replay.jsonl`,
`incidents.jsonl`, per-node working dirs, and `report/report.md` (anytime report).

## Architecture (10 lines)

1. **graph/** — `plan_cached.json` (the N0–N7 research DAG), `schema.py`
   (dataclasses + `validate`), `normalizer.py` (Tarjan SCC over artifact edges;
   metered back-edges).
2. **Nodes** are `fast | long | reactive`; **edges** are `artifact` (hard dep,
   gates readiness) or `stream` (subscription, never blocks; wakes reactive nodes).
3. **core/orchestrator.py** — asyncio tick loop: ready-set + resource slots
   `{gpu:1, cpu:3}`; long node = a real subprocess (`scripts/sim_train.py`) tailed
   for `(step, best_dev)`; fast/reactive driven by `runtime/mock_worker.py`.
4. **core/supervisor.py** — the *only* status mutator + incident writer. Detectors:
   stuck/oscillation (fast fingerprints), HUNG/PLATEAU/SUPERSEDED (long trajectory).
5. **core/gates.py** — acceptance gate (exit-0) + comparability gate (four-tuple
   `data_hash/split_hash/protocol_version/seed`, blame the deviator).
6. **5-tier escalation ladder** — bounce → blame-routing → downstream-invalidation
   → graph-surgery → fuse; **every rung logs an incident** (silent intervention is
   a bug).
7. **core/incidents.py** — append-only JSONL black box (doubles as replay source).
8. **state.json** (frozen schema) is the single interface for tomorrow's dashboard;
   **report.md** is regenerated from the verified-set on every event (anytime).
9. **Determinism** — logical tick clock (never wall-clock); detectors key on
   step-space trajectories; replay is a pure function of `replay.jsonl`.
10. **Live mode** (`--live`, mini-swe-agent `RealWorker`) is stubbed for tomorrow;
    the mock path stays runnable as the demo fallback.

## The fixture

Question: *"Does a fine-tuned small model beat a few-shot large-model baseline on a
text-to-SQL subset?"* — `N0 protocol → N1 data → N2 freeze-harness → { N3 baseline
(0.58) ∥ N4 finetune (long) } → N4e ckpt-eval → N5 analysis (can_spawn) → N6 report`,
with `N5→N4` a metered back-edge (max 3 laps) and `N7` an ablation N5 spawns at
runtime.
