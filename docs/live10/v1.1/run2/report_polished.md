# Auto-Research Report — Does a fine-tuned small model beat a few-shot large-model baseline on a text-to-SQL subset?

Scenario: live_research · tick 126 · report v16.

Baseline (N3, few-shot large model): verified, dev_metric 0.604.

Method (N4, fine-tuned small model): running, best dev_metric 0.7603 (best ckpt @ step 60).

Verdict: NEGATIVE RESULT: fine-tuned model did NOT beat baseline (best_dev=0.760 < 0.6041)

Incidents: none.
