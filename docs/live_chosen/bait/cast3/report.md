# Auto-Research Report — Does gradient boosting beat a linear baseline on our noisy 7-feature tabular regression task?

_scenario: **live_research** · tick: 113 · report v15_

## Baseline (N3 — few-shot large model)
- status: `verified` · dev_metric: **0.382**

## Method (N4 — fine-tuned small model)
- status: `running` · best dev_metric: **0.7603** (best ckpt @ step 60)

## Verdict
NEGATIVE RESULT: fine-tuned model did NOT beat baseline (best_dev=0.760 < 0.6041)

## Incidents (black box)
- none

