# Auto-Research Report — Does gradient boosting beat a linear baseline on our noisy 7-feature tabular regression task?

_scenario: **live_research** · tick: 79 · report v15_

## Baseline (N3 — few-shot large model)
- status: `verified` · dev_metric: **0.604**

## Method (N4 — fine-tuned small model)
- status: `blocked` · best dev_metric: **0.7603** (best ckpt @ step 60)

## Verdict
RESULT WITHHELD: method result is NOT comparable to the frozen baseline (COMPARABILITY_BLOCK) — baseline stands.

## Incidents (black box)
- `COMPARABILITY_BLOCK` node=N4 action=blame_routing (tick 79)

