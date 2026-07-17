# LIVE-10 REPORT — M10（30 分钟冲刺，硬停 12:15）

分支 `live10`。目标：scenario=live_research，四个"真"——真数据（`data/`
现有 6 行 text-to-SQL 子集 + split.json）、真长节点（`scripts/real_train.py`
staged GBDT 取代 sim）、真 worker（N1/N3/N4agent/N5 live，N0/N2 脚本化，N6
单次调用润色）、真门（验收+可比性+污染原样生效）。模型 `z-ai/glm-5.2`
（OpenRouter），API 预算 ≤$3，单节点 max_steps ≤8，lap 预算 ≤2。
mock ▶DEMO 主线零改动（圣物）。

## 时长分解表（第 1 跑，runs/20260717-120240-live_research，总墙钟 135.5s）

| 阶段 | 内容 | 墙钟（约） |
|---|---|---|
| N0/N2 | 脚本化（mock） | ~3s |
| N1 live agent | 数据巡检 → data_notes.txt（2 类信息齐） | ~6s |
| N4 real_train | staged GBDT 60 stages ×1.8s（paced） | ~108s |
| N3 live agent | baseline manifest score=0.58（与 N4 训练重叠） | ~8s |
| N4agent | live manifest（make_manifest，code_sha=live-agent） | ~15s |
| N5/N6 one-shot | 第 1 跑失败（空 completion/路径 bug），第 2 跑前已修 | ~2s |
| **合计** | **exit 0，quiesced，8 节点全 verified** | **135.5s（≤5.5min 目标）** |

## 阵容成色表

| 节点 | 成色 | 证据 |
|---|---|---|
| N0 protocol | 脚本化（注明） | mock worker |
| N1 data | **live agent**（glm-5.2, ≤8 steps） | transcript |
| N2 harness | 脚本化（注明） | mock worker |
| N3 baseline eval | **live agent**（冒烟 2 steps, $0.0004, 验收 PASS） | runs/*-live-N3 |
| N4 train | **真长节点**：staged GBDT（stdlib 手写 stump 提升），metrics/ckpt(.txt+.pkl) 全真；墙钟 paced（同 sim_train 纪律，如实声明） | runs/*-live_research/N4 |
| N4agent | **live agent** 盖章 manifest（make_manifest 冻结四元组），失败回退世界态 | N4/results.json code_sha |
| N4e/N5/N6 | reactive；N5 analysis + N6 polish 各**一次** LLM 调用 | N5/analysis.md, report_polished.md |
| 门 | 验收/可比性/污染**原样生效**；被打回/被拦=正常剧情，照常落黑匣子 | incidents |

## 花费（model=z-ai/glm-5.2 via OpenRouter）

- N3 冒烟：$0.000424（2 steps）
- 第 1 跑：$0.002894（live_cost.json，wall 135.5s）
- 第 2 跑：$0.0045（live_cost.json，wall 156.4s）
- 合计：≈$0.0078 / $3.00 预算（用量 <0.3%）

## 两跑结论路径

- 第 1 跑：exit 0 · quiesced · 8/8 verified · incidents 0 ·
  `RESEARCH ANSWERED: fine-tuned model beats baseline (best_dev=0.998 >= 0.58)`
  （N4 live-agent manifest score=0.9975 vs N3 baseline 0.58，四元组一致过可比性门）
- 第 2 跑：exit 0 · quiesced · 8/8 verified · incidents 0 ·
  `RESEARCH ANSWERED: fine-tuned model beats baseline (best_dev=0.998 >= 0.58)`
  —— **结论路径稳定**（real_train 确定性曲线 + 同一冻结协议，数值亦一致）

## 降级闸门记录

- ⏱11:52 real_train 冒烟：**一次过**（曲线 0.525→0.88 上升且后段饱和，
  ckpt .txt/.pkl 齐）→ 无需回落 sim_train
- ⏱12:00 N3 live 冒烟：**一次过**（验收门 PASS）→ 无需降 mock
- ⏱12:08 第 1 跑：**exit 0**（135.5s ≤ 6min）→ 第 2 跑照常
- 已知瑕疵（如实）：第 1 跑 N5/N6 one-shot 失败（glm 空 completion + N6 读
  report 路径错），当即修复；第 2 跑 N5 analysis 成功（见
  docs/live10/run2/n5_analysis.md）；**N6 polish 跑内仍空 completion**
  （glm-5.2 长输入下 reasoning 吃光 token），单测 max_tokens=2400 成功
  （docs/live10/run2/report_polished.md），根因已定位、跑内预算留待会后调；
  门与 verdict 两跑均不受影响

## 验收（输出原文）

**a. 第 1 跑 exit 0 · 墙钟 ≤6min · report.md 真实数字与结论** ✅
```
=== scenario=live_research  ticks=134  quiesced=True ===
  N0..N6,N4e 全 verified    incidents: 0
RESEARCH ANSWERED: fine-tuned model beats baseline (best_dev=0.998 >= 0.58)
wall_s=135.5  live_cost=$0.0029 (budget $3.0)    EXIT=0
```
report.md（anytime，v18）：baseline 0.580 verified / method 0.9975 verified ·
comparable → fine-tuned beats baseline。run1 墙钟 135.5s = 2分15秒。

**b. 第 2 跑结论路径稳定** ✅
```
=== scenario=live_research  ticks=134  quiesced=True ===  (8/8 verified, incidents 0)
RESEARCH ANSWERED: fine-tuned model beats baseline (best_dev=0.998 >= 0.58)
wall_s=156.4  live_cost=$0.0045    EXIT=0
```

**c. 回归抽查绿 · 默认 ▶DEMO 未被碰** ✅
```
pytest -q                       -> 45 passed, 1 warning in 0.36s
--mock green       -> exit 0    RESEARCH ANSWERED (best_dev=0.720 >= 0.58)
--mock plateau     -> exit 0    NEGATIVE RESULT (0.531 < 0.58), incidents 2
--mock trap_scope  -> exit 0    NEGATIVE RESULT, SCOPE_VIOLATION 落盘, incidents 1
git diff main -- dashboard/ demo_playlist*.yaml graph/plan_cached.json scenarios/{green,plateau,trap_scope,...}.yaml
                                -> 空（圣物零改动；默认 playlist 未碰）
```

## 归档

`docs/live10/`：run1/（9 件）、run2/（11 件）——replay.jsonl、state.json、
report.md、live_cost.json、n4_metrics.jsonl（真 GBDT 曲线）、n3/n4 manifest
（code_sha=live-agent）、n1_data_notes.txt、n5_analysis.md（run2）、
report_polished.md（run2，单测路径）、n4_ckpt_100.pkl（真模型 checkpoint）。

## 铁律确认

- mock 路径零行为改动：orchestrator 三个 hook 默认 None；Scenario 新字段默认
  空；`--live --node` / `--live` 旧路径原样；plan_cached.json 未碰。
- 新增依赖：零（real_train 纯 stdlib：argparse/json/math/pickle/time）。
- 监督阈值一律未调（K_FREEZE/PLATEAU_EPS/ACCEPT_MAX_LAPS 全保持 law 原值；
  lap≤2 作为 live 预算意图写进场景 yaml，回边 max_laps 仅内存改写）。
- real_train 墙钟为 paced（sleep 标定 ≈108s），与 sim_train 同一纪律；曲线、
  checkpoint、模型全为真实训练产物——此处如实声明。
- merge main 由人决定；本分支 live10 已推送。

## 三句讲者话术

1. "同一个监督层，昨晚跑的是提线木偶，现在跑的是真 agent——代码一行没改，
   因为监督层只看世界状态，不听 agent 自报。"
2. "N4 是真训练： staged GBDT 在真实数据子集上跑出真实曲线和真实 pickle
   checkpoint；hung/plateau 检测器读的还是那个 metrics.jsonl。"
3. "门也是真的：live agent 的 manifest 要过和 mock 一模一样的验收门和可比性
   门——被打回就落 incident，这就是'可比的科学'。"

## 回归与验收（收官时填输出原文）

- a. 第 1 跑 exit 0 / 墙钟 ≤6min / report.md 真实数字：TBD
- b. 第 2 跑结论路径稳定：TBD
- c. pytest -q + 3 mock 场景抽查 + ▶DEMO 未碰（git diff 佐证）：TBD

---

# v1.1 — 数据地基修复（M10.1，分支 m10-1）

**为什么换数据（一句）**：v1.0 跑在 6 行玩具数据上，best_dev=0.998 是背题
（dev 2 行、标签可被单一关键词规则完美分离），上台会被笑；v1.1 换成 400 行、
7 特征、带噪声的非线性回归集，让分数落在统计意义上可信的区间。

## 新地基（scripts/make_dataset.py，stdlib random，seed=20260717）

- `data/dataset.csv`：400 行 × (x1..x7, y)；
  `y = 2.0·x1 + 1.2·x2 + 1.2·sin(6·x3) + 0.9·x4² + 0.6·x5·x6 + N(0, 0.65)`
- `data/split.json`：train/dev = 320/80（同一 seed shuffle，字节级可复现）
- 结构设计：线性项喂 baseline；sin/平方喂方法增量；**x5·x6 交互（深度 1
  stump 学不到）+ 噪声把方法上限压在 ~0.85** —— 离 0.97 过拟合红线远
- 标定记录（生成器原文）：
  `BASELINE linear OLS dev R2 = 0.6041`（带 [0.55,0.70] ✓）
  real_train（60 stages, lr=0.5）dev R² = 0.7603（带 [0.75,0.90] ✓，<0.92 ✓）

## 新旧分数对照

| | v1.0（live10） | v1.1（m10-1） |
|---|---|---|
| 数据 | 6 行 text-to-SQL | 400 行带噪声回归 |
| 指标 | execution accuracy | dev R² |
| baseline（N3） | 0.58（告知值） | 0.6041（OLS 实算，live agent 自己跑最小二乘） |
| method（N4） | 0.9975（背题） | ~0.76（GBDT 真实训练上限） |
| 过拟合红线 | — | ≥0.97 判失败（本任务存在理由） |

## 重标定三处（+fixture）

- `graph/plan_cached.json`：N3.expected_score 0.58 → 0.6041
- `eval/protocol.md`：metric=R²、baseline=0.6041、data=dataset.csv
  （protocol_version 哈希随内容换雪，全链路运行时重算，四元组仍一致）
- `scripts/real_train.py`：回归化重写（MSE stump-GBDT），60 stages×1.8s
  节流维持 compute_phase ≈108s，lr 0.3→0.5 使 60 stage 内收敛进带
- fixture：`tests/test_schema.py:24` 断言值 0.58→0.6041（只改 fixture 不改逻辑）
- 监督逻辑/阈值语义零改动（core/ diff 为空）；dashboard 未碰（其 0.58 文案
  成为装饰性陈旧，如实注明）

## 两跑验收（输出原文）

**第 1 跑**（runs/20260717-124401-live_research）：
```
=== scenario=live_research  ticks=66  quiesced=True ===   (8/8 verified, incidents 0)
RESEARCH ANSWERED: fine-tuned model beats baseline (best_dev=0.760 >= 0.6041)
wall_s=153.4  live_cost=$0.0127 (budget $3.0)    EXIT=0
```
如实注明：第 1 跑 N3 agent 八步内逐行写 OLS 脚本、步数耗尽 → mock 回退
（混合阵容合法）。根因定位后任务文本加"步数预算"指引（整脚本一条命令），
单节点复测：agent 2 步算出 R²=0.60406…（与生成器官方值 0.6041 一致）PASS。

**第 2 跑**（runs/20260717-125000-live_research，全 live 无回退）：
```
=== scenario=live_research  ticks=128  quiesced=True ===  (8/8 verified, incidents 0)
RESEARCH ANSWERED: fine-tuned model beats baseline (best_dev=0.760 >= 0.6041)
wall_s=123.5  live_cost=$0.0032 (budget $3.0)    EXIT=0
```
N3 manifest：score=0.6041, code_sha=live-agent（agent 自算 OLS）；
N4 manifest：score=0.7603, code_sha=live-agent；四元组完全一致过可比性门。

**验收五条核对**：exit 0 ×2 ✓ · 墙钟 153.4s/123.5s ≤6min ✓ ·
best_dev=0.760 ∈ [0.65,0.92] ✓ · 严格高于 baseline（0.760 > 0.6041）✓ ·
无 ≥0.97 ✓（方法上限被交互项+噪声结构压在 ~0.85 以下）

## 回归护栏（输出原文）

```
pytest -q  ->  45 passed, 1 warning in 0.32s
green exit 0 / trap_b exit 0 / plateau exit 0 / hung exit 0 /
trap_scope exit 0 / trap_stale exit 0 / trap_taint exit 0   (7/7)
mock green verdict:  RESEARCH ANSWERED (best_dev=0.720 >= 0.6041)
mock plateau verdict: NEGATIVE RESULT (best_dev=0.531 < 0.6041)
git diff -- dashboard/ demo_playlist*.yaml core/  ->  空
```

## v1.1 归档

`docs/live10/v1.1/`：calibration.txt（生成器标定原文）+ run1/、run2/
各 11 件（replay、state、report、live_cost、n4_metrics（真 R² 曲线
0.556→0.760）、n3/n4 manifest、n1 notes、n5 analysis、report_polished、
n4_ckpt_100.pkl）。花费合计 ≈$0.017 / $3.00。merge 留人决定。
