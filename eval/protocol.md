# Frozen Evaluation Protocol (p1.1)

Research question: does a boosted model beat a linear baseline on a noisy
nonlinear regression benchmark?

- Metric: `dev_metric` = R² on the frozen dev split (higher is better).
- Baseline to beat: **0.6041** (linear OLS model, node N3).
- Data: `data/dataset.csv` (400 rows, 7 features, nonlinear + noise, seed
  20260717), split by `data/split.json` (train/dev 8:2). FROZEN.
  (`data/train.jsonl` is retained as the v1.0 toy set.)
- Comparability key: every experiment manifest must carry an identical
  `(data_hash, split_hash, protocol_version, seed)` four-tuple, else the result
  is not comparable to the baseline.

This file is the protocol contract. Its sha256 is `protocol_version`. Do not edit
after N2 freezes the harness.
