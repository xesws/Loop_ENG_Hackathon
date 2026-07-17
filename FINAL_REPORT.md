# FINAL REPORT — Graph Supervisor for Auto-Research (mock, demo-ready)

Built in one session to DEMO-READY-IN-MOCK state. The runtime path makes **zero**
LLM/API/network calls; every scenario is deterministic, offline, and finishes in a
few seconds (well under the 120 s budget). The definition of done is executable —
the five acceptance commands below are pasted **verbatim**.

## Built (M0–M5 + stretch)

- **M0** — package skeleton, `graph/schema.py` (dataclasses + 10 canonical statuses
  + `validate`), `graph/plan_cached.json` (N0–N7 async graph), `runtime/fs.py`
  (deterministic scope fingerprint, atomic writes, `tail_jsonl`, ckpt helpers),
  `core/incidents.py` (Incident + JSONL log), `core/clock.py` (logical tick clock).
- **M1** — `graph/normalizer.py` (Tarjan SCC over artifact edges; metered
  back-edges; 2-cycle contract/extract), `core/gates.py` (acceptance + comparability,
  pure), `core/supervisor.py` (single status mutator + incident writer; oscillation/
  stuck/HUNG/PLATEAU/SUPERSEDED detectors; 5-tier ladder; verdict). `state.json`
  schema frozen.
- **M2** — `core/orchestrator.py` (asyncio ready-set + `{gpu:1,cpu:3}` slots, long
  node subprocess, stream dispatch, world-state reactive finalization, `state.json`
  + `replay.jsonl` + anytime `report.md` each tick), `runtime/mock_worker.py`,
  `scripts/sim_train.py`, `eval/` frozen harness + `data/` fixture, `run.py`.
- **M3** — comparability + acceptance gates wired through the ladder; `trap_b`.
- **M4** — plateau end-to-end: `PLATEAU_TRIP` at ~40%, kill keeping best ckpt,
  negative result, gpu freed, `N5` graph-surgery spawns `N7`.
- **M5** — `core/replay.py` + `run.py --replay` (pure re-render, no execution).
- **Stretch** — `hung` scenario (HUNG_RESTART → kill); `RealWorker` import-only stub
  behind `--live`; `dashboard/index.html` stub.

Every milestone was committed on `main` (`git log --oneline`: M0…M5).

## Gaps / cuts (honest)

- **agent_phase is SKIPPED in mock** (by design). The long node runs only its
  `compute_phase` subprocess; the mini-swe-agent `RealWorker` is stubbed behind
  `--live` and raises — it is tomorrow's work.
- **`--live` is not wired** tonight; it prints a clean "not wired" message and
  exits 1.
- **Acceptance-gate bounce loop** (FALSE_COMPLETION → re-run) is implemented and
  unit-tested but no shipped scenario drives a fast-node acceptance failure; the
  demoed failures are comparability (trap_b), plateau, and hung.
- **SCOPE_VIOLATION / stale-cascade / taint** are implemented and unit-tested in the
  supervisor but not wired to a runtime scenario tonight (they are the venue traps
  A and the STALE_CASCADE set piece for tomorrow).
- **`dashboard/index.html`** is an intentional stub (tomorrow's first venue task).
- **Timing is soft, outcomes are hard**: the exact tick a metrics/ckpt line is first
  observed can shift ±1 tick, but detectors key on step-space trajectories and
  monotone curves, so statuses/incidents are invariant. Replay is hard-deterministic.

## Acceptance — five commands, verbatim output

```
########## $ pytest -q
.............................................                            [100%]
45 passed in 0.12s
# exit=0

########## $ python run.py --mock --scenario green
=== scenario=green  ticks=47  quiesced=True ===
  N0   verified
  N1   verified
  N2   verified
  N3   verified
  N4   verified
  N4e  verified
  N5   verified
  N6   verified
incidents: 0
RESEARCH ANSWERED: fine-tuned model beats baseline (best_dev=0.720 >= 0.58)
run_dir: /Users/tangyiq/dev/OOAA/runs/20260716-234947-green
# exit=0

########## $ python run.py --mock --scenario trap_b
=== scenario=trap_b  ticks=47  quiesced=True ===
  N0   verified
  N1   verified
  N2   verified
  N3   verified
  N4   blocked
  N4e  verified
  N5   blocked
  N6   blocked
incidents: 1
RESULT WITHHELD: method result is NOT comparable to the frozen baseline (COMPARABILITY_BLOCK) — baseline stands.
run_dir: /Users/tangyiq/dev/OOAA/runs/20260716-234951-trap_b
# exit=0
# incidents.jsonl:
# {"evidence":{"analysis_node":"N5","baseline":"N3","deviator":"N4","mismatched_fields":["data_hash"],...},
#  "ladder_action":"blame_routing","node":"N4","ts":47,"type":"COMPARABILITY_BLOCK"}   # N3 stays verified

########## $ python run.py --mock --scenario plateau
=== scenario=plateau  ticks=24  quiesced=True ===
  N0   verified
  N1   verified
  N2   verified
  N3   verified
  N4   plateaued
  N4e  verified
  N5   verified
  N6   verified
  N7   verified
incidents: 2
NEGATIVE RESULT: fine-tuned model did NOT beat baseline (best_dev=0.531 < 0.58)
run_dir: /Users/tangyiq/dev/OOAA/runs/20260716-234955-plateau
# exit=0
# incidents.jsonl:
# {"evidence":{"best_ckpt":40,"best_dev":0.5308,"last_improvement":0.0009,"patience":2,"target":0.58},
#  "ladder_action":"fuse","node":"N4","ts":22,"type":"PLATEAU_TRIP"}
# {"evidence":{"reason":"explain plateau","role":"ablation","spawned_from":"N4"},
#  "ladder_action":"graph_surgery","node":"N7","ts":22,"type":"PLATEAU_TRIP"}

########## $ python run.py --replay runs/20260716-234955-plateau/replay.jsonl
=== REPLAY runs/20260716-234955-plateau/replay.jsonl (25 ticks) — no workers, pure re-render ===
t  0 admit=N0
t  2 admit=N1 freed=N0 N0/done->
t  4 admit=N2 freed=N1 N1/done->
t  6 admit=N4,N3 freed=N2 N2/done->
t  8 freed=N3 N3/done->N5  [N4 step=5 best=0.4721]
t 10 N4/ckpt->N4e N4e/result->N5  [N4 step=11 best=0.5085]
t 14 N4/ckpt->N4e N4e/result->N5  [N4 step=20 best=0.5257]
t 18 N4/ckpt->N4e N4e/result->N5  [N4 step=30 best=0.5299]
t 22 admit=N7 freed=N4 spawn=N7 N4/ckpt->N4e N4/done-> N4e/result->N5 !PLATEAU_TRIP(N4/fuse) !PLATEAU_TRIP(N7/graph_surgery)  [N4 step=40 best=0.5308]
t 24 freed=N7 N7/done->  [N4 step=40 best=0.5308]
=== final statuses ===
  N0 verified · N1 verified · N2 verified · N3 verified · N4 plateaued (best_dev=0.5308)
  N4e verified · N5 verified · N6 verified · N7 verified
=== incidents replayed: 2 ===
  PLATEAU_TRIP node=N4 action=fuse (ts 22)
  PLATEAU_TRIP node=N7 action=graph_surgery (ts 22)
# exit=0
```

(The replay block above is elided to key ticks for readability; the live command
prints all 25 ticks. Full raw capture including every idle tick is reproducible by
re-running the commands.)

## Determinism & bounds

- Logical tick clock everywhere; `time.time()` only for a deterministic pseudo-
  `wall_s = ticks * TICK_S`.
- Incident JSONL uses `sort_keys=True`; graph traversals are `sorted()`-wrapped;
  acceptance subprocess pins `PYTHONHASHSEED=0`.
- Hard `max_ticks=800` (~64 s ceiling) backstop; all four scenarios quiesce in
  24–47 ticks (2–4 s wall).
