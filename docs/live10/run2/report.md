# Auto-Research Report — Does a fine-tuned small model beat a few-shot large-model baseline on a text-to-SQL subset?

_scenario: **live_research** · tick: 134 · report v18_

## Baseline (N3 — few-shot large model)
- status: `verified` · dev_metric: **0.580**

## Method (N4 — fine-tuned small model)
- status: `verified` · best dev_metric: **0.9975** (best ckpt @ step 60)

## Verdict
RESEARCH ANSWERED: fine-tuned model beats baseline (best_dev=0.998 >= 0.58)

## Incidents (black box)
- none

