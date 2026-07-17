# M16 — 自由拓扑 + 咬钩：按条款收工（未实施）

**结论：GATE 前提不成立 + 时间窗已过 → 按任务书降级条款"停 B，用录好的视频，
收工"执行。零代码改动；回归全绿。视频素材用 M13 已录的咬钩回放
（`docs/live_chosen/video/bite_cast1_glm-4.5-air/`）。**

## 核查记录（15:56）

1. **"取 exp/sweep 的自由 planner"——不存在。**
   `git show origin/exp/sweep:graph/planner.py`：与 main 同源，同一条
   "same node ids N0..N7 … do NOT add or remove nodes or edges" 约束原文
   就在其中。exp/sweep 是前端 P1–P4 分支（已是 main 祖先），没有自由
   planner 可取。要自由拓扑只能现写：新 prompt + 自由图校验 + 执行锚点
   按角色泛化（orchestrator/report 的 N3..N7 锚点在 core 禁触清单边上，
   需要走"新增不改旧"的变体路线）——是一个真里程碑，不是加分题时间盒。
2. **时间窗**：本任务接手即 15:56，已超 15:50 的 GATE 时刻。剩余 ~9 分钟
   不够"现写 planner + 3 次生成验证（≥2 拓扑不同且 3/3 过校验 exit 0）
   + ≤3 竿钓钩"。按两振/超时条款，不赶半成品。

## 收工回归（15:57，分支 m16-freebite，基于 m15-evidence eafd523）

- `pytest -q`：**58 passed**（m15-evidence 工作树原样，零改动）
- ▶DEMO 冒烟：POST /demo → playlist 2 场景正常 preparing/playing
- 禁区核验：core/、schema、场景、▶DEMO、`docs/live_chosen/bait/`（M13）
  全部未碰；无任何按节点 id 的特判引入（零改动故零风险）

## 若 demo 后要做（备忘）

自由拓扑的正路：planner 新 prompt（去掉 N0..N7 合同，保留"long 必带
compute + experiment 角色齐备"硬约束）→ 校验加"角色完备性"（恰好一个
baseline experiment、一个 long method、reactive analysis/report）→ 执行
锚点角色化（新文件变体，不改 core 旧文件；mock 圣物走旧路径）→ 按角色
注饵（非 baseline 的 experiment 节点，不认 id）。
