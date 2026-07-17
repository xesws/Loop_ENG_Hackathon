# CLAUDE.md — OOAA · Graph Supervisor for Auto-Research

## 这个项目是什么
异步、图原生的 auto-research 多 agent 监督层。研究图上：节点分
fast / long / reactive，边分 artifact（硬依赖）/ stream（订阅，从不阻塞），
调度用 ready-set + 资源槽 {gpu:1, cpu:3}，全图禁止 barrier。
监督层职责：长节点进展裁决（hung / plateau / zombie）、验收门与可比性门、
失效污染面传播、五档处置阶梯（bounce → blame → 下游失效 → 图手术 → 熔断）、
anytime report。
Thesis：不听 agent 说什么，只看世界状态变没变。
背景：明天（7/17）9:30 AWS Builder Loft hackathon 要 demo。今晚目标：mock 全通。

## 权威文档与冲突规则
- `loop_hackathon_workbook.md`：产品语义与上下文；§3.5（异步 v2）优先，
  §3 的 v1 schema 仅在降级档使用
- `PROMPT.md`：今晚任务书——build 顺序、里程碑 M0–M5、验收五条
- 冲突时：范围/顺序/验收听 PROMPT.md；语义细节听 workbook §3.5；
  两边都没写的，一律选更小的实现

## 铁律（违反即 bug）
1. 今晚运行路径零网络、零 LLM/API 调用；一切 mock、确定性、可离线
2. 完成的唯一定义 = PROMPT.md 的五条验收命令真实通过；宣布完成前
   必须亲自跑完五条，并把输出原样贴进 FINAL_REPORT.md
3. 任一场景 wall time 超过 120 秒 = bug
4. 依赖白名单：stdlib + networkx + pyyaml + pytest（+ rich 可选）；
   禁止 LangChain / LangGraph / docker / web 框架 / 数据库
5. 状态转移与事故只能经 supervisor API；禁止隐藏全局态；
   每次阶梯动作必落盘 incident——静默干预是 bug
6. state.json 的 schema 在 M1 后冻结（明天 dashboard 只读它）
7. 不重新设计产品、不加清单外功能、不 fork 任何 auto-research 框架

## 目录结构（不许偏离）
graph/（plan_cached.json, normalizer.py, schema.py）
runtime/（worker.py, mock_worker.py, fs.py）
core/（orchestrator.py, supervisor.py, gates.py, incidents.py）
scripts/sim_train.py   eval/   data/   runs/   scenarios/
dashboard/index.html（今晚可为空壳）   tests/   run.py

## 常用命令
pytest -q
python run.py --mock --scenario {green|trap_b|plateau|hung}
python run.py --replay runs/<ts>/replay.jsonl
git：每个里程碑一次 commit，信息 "M<n>: <做了什么>"；直接在 main 干；
禁止 force push

## 代码约定
Python 3.11+ / asyncio；dataclass + type hints；标识符与注释用英文，
面向人的文档可中文；core/supervisor.py 目标 <300 行；
失败要响（异常或事故落盘），不许静默吞掉

## 关键不变量（速查）
- 可比性四元组：data_hash / split_hash / protocol_version / seed 完全相等
- 长节点指纹 = (step, best_dev) 轨迹；fast 节点指纹 = scope 目录 sha256
- 污染面沿 artifact 边传播、不沿 stream 边；协议坏只废读数、不废训练
- kill 只发生在 checkpoint 边界，保留 best ckpt
- anytime report：任一时刻中断，report.md 必须自洽

## 阶段
- 今晚（mock 阶段）：M0–M5，按 PROMPT.md 走
- 明天会场（live 阶段）：dashboard（读 state.json）、RealWorker
  （mini-swe-agent，--live 旗标）、prompt 注入版陷阱；
  **mock 路径永远保持可跑——它是 demo 的最终兜底**
- 任何门连续失败两次：简化该里程碑（砍范围、不砍验收），记入 FINAL_REPORT.md