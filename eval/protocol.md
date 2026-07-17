# Frozen Evaluation Protocol (p1)

Research question: does a fine-tuned small model beat a few-shot large-model
baseline on a text-to-SQL subset?

- Metric: `dev_metric` = execution accuracy on the frozen dev split (higher is better).
- Baseline to beat: **0.58** (few-shot large model, node N3).
- Data: `data/train.jsonl`, split by `data/split.json` (seed 42). FROZEN.
- Comparability key: every experiment manifest must carry an identical
  `(data_hash, split_hash, protocol_version, seed)` four-tuple, else the result
  is not comparable to the baseline.

This file is the protocol contract. Its sha256 is `protocol_version`. Do not edit
after N2 freezes the harness.
