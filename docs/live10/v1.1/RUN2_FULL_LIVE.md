# 全 live 现场 — 零回退绿跑（M10.1 · live_research 第 2 跑）

> 一句话版：prompt 只加了一句步数预算，同一个 agent 阵容就从"降级收口"变成
> "全 live 零回退"——baseline 是 agent 真算的，训练是真 GBDT，门是真过的，
> 结论是稳定复现的。

本跑：`runs/20260717-125000-live_research` · exit 0 · quiesced ·
8/8 verified · incidents 0 · 墙钟 **123.5s** · 花费 **$0.0032**。
与第 1 跑（降级版，见 `N3_INCIDENT.md`）互为对照组：同一场景、同一预算、
同一模型，唯一变量是 N3 任务文本里的一句话。

## 阵容（全部真，无一回退）

| 节点 | 干的活 | 签名 |
|---|---|---|
| N1 data | 巡检 400 行数据集，写 data_notes.txt | 内容全对（400/x1..x7/320+80） |
| N3 baseline | **自写 stdlib OLS**，dev R²=0.60406… → 盖章 0.6041 | code_sha=`live-agent` |
| N4 train | 真 staged GBDT（60 stages，lr=0.5，MSE stump） | metrics.jsonl 0.2393→0.7603 |
| N4agent | 读训练终值，make_manifest 盖章 0.7603 | code_sha=`live-agent` |
| N5 analysis | 一次 LLM 调用出分析（+0.1562 绝对 / ~25.9% 相对） | n5_analysis.md |
| N6 report | 一次 LLM 调用润色 anytime report | report_polished.md |
| N0/N2 | 脚本化（任务书注明的设计内降级） | — |

## 法证（全在 `docs/live10/v1.1/run2/`）

**① 两枚亲签 manifest** — `n3_manifest.json` / `n4_manifest.json`：
code_sha 都是 `live-agent`；四元组
`(data_hash, split_hash, protocol_version, seed)` **逐项相等** ——
可比性门是拿真 manifest 过的，不是旁白说过的。

**② 真训练曲线** — `n4_metrics.jsonl`：60 个 stage 的 dev R² 轨迹
0.2393 → 0.5563(10%) → 0.7076(40%) → 0.7603(100%)，上升后自然饱和；
`n4_ckpt_100.pkl` 是 60 棵 stump 的真 pickle（stages=60, lr=0.5）。

**③ 官方标定对表** — `../calibration.txt`：生成器标定 baseline OLS
R² = 0.6041；agent 跑内自算 0.6040605050126，四舍五入后**一字不差**。
baseline 不是被告知的数字，是被独立复算出来的。

**④ 账本** — `live_cost.json`：$0.003212 / $3.00 预算；123.5s 墙钟
（目标 ≤5.5min，硬上限 6min）。比降级那趟便宜 4 倍——修好 prompt
不只是好看，还省钱。

## 复现性结论

数值与第 1 跑**完全一致**（0.6041 / 0.7603）：real_train 是确定性的，
OLS 是精确解 —— 这本身是一个可讲点：管线里凡是真计算的部分都是
可复现的；LLM 的不确定性被关在"写 notes、写分析、写报告"这些
不改变 verdict 的环节里。结论路径两跑一致：
`RESEARCH ANSWERED: fine-tuned model beats baseline (best_dev=0.760 >= 0.6041)`。

## 如实标注（瑕疵）

- N6 润色保留了 `plan_cached.json` 里的旧研究问题字样（text-to-SQL）——
  那是 plan 元数据，为保 dashboard 演示叙事未在 M10.1 改动；
  数字与 protocol p1.1（回归基准）是新的、自洽的。
- N0/N2 脚本化是任务书注明的设计内配置，不是临时降级。

## 30 秒讲者话术

"第二跑，零回退。baseline 不是我们告诉 agent 的数字——它自己写了个
最小二乘，两步，0.6041，和数据生成器的官方标定一字不差。方法侧是一棵
一棵 stump 真 boosting 出来的 0.7603，checkpoint 是 60 棵树的真 pickle。
两个 manifest 的四元组逐项相等，可比性门是真的过的。而且请注意：
所有'真计算'两跑完全一致——LLM 的不确定性只被允许碰文字，不许碰结论。"
