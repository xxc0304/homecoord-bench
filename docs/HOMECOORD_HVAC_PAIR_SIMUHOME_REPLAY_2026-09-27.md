# HomeCoord HVAC 配对任务的 SimuHome 回放

日期：2026-09-27  
状态：两批适配层回放完成；仅用于核对动作状态映射和评测器边界。

## 试验范围

将已有 `paired_task_batch_v1_probe.json` 中 C1-HVAC、重复 1 的 DeepSeek `deepseek-flash` 决策记录，分别输入 HomeCoord 的 `IndependentMultiAgent` 和 `ConstraintCoordinator`，再把被接受的高层 HVAC 动作回放到固定版本 SimuHome。每个冲突／对照条件与架构组合运行 3 次，共 12 条轨迹。此次回放没有调用模型 API，也没有连接真实设备；三个重复是固定提案下的模拟器技术重复，不是三次独立模型采样。

两批回放使用同一任务、状态映射和 1 ms 模拟 tick。第二批只减少了同一高层 HVAC 动作中多余的“命令前状态读取”，并单独保存结果；它没有改变评测标准，也没有替换第一批记录。

## 结果

| 条件与架构 | HomeCoord 目标成功 | SimuHome 设备状态代理成功 | 可观察结果 |
|---|---:|---:|---|
| 冲突：IndependentMultiAgent | 0/3 | 0/3 | 制冷和关机都执行，终态 HVAC 关闭；温度仍接近初值 |
| 冲突：ConstraintCoordinator | 3/3 | 0/3 | 协调器接受制冷、拒绝关机；HVAC 保持开启，但短时室温仍约为 29°C，没有进入 episode 的 23–25°C 区间 |
| 对照：IndependentMultiAgent | 3/3 | 3/3 | 两种架构均执行关机，目标状态吻合 |
| 对照：ConstraintCoordinator | 3/3 | 3/3 | 与 IndependentMultiAgent 一致 |

这里“SimuHome 设备状态代理成功”只检查终态开关状态；冲突组的物理目标代理还要求 HVAC 开启且模拟室温进入 23–25°C。它不是经设备校准的现实成功率。

第一批和减少读取后的第二批均为 12/12 条 JSONL 轨迹结构有效、4 个重复组中 1 个逐状态完全确定性一致。减少读取没有改善精确重复率。剩余差异主要是 1 ms tick 与 HTTP 请求耗时／后台时钟推进不同步，造成命令观测 tick 和内置温度公式末值有细微变化。不同重复里的开关终态及冲突／对照判定稳定，但不能据此声称逐轨迹确定性。

## 对评测器的诊断

这批回放暴露了一个具体的环境建模差异：生成这批配对输出时使用的旧版 `run_closed_loop_episode` 会在高层动作生效时写入完整效果，包括“室温达到目标”；SimuHome 则按时间演化 HVAC 与房间温度。因此协调器在该 HomeCoord 旧评测路径中可被判为目标成功，而设备状态虽正确，SimuHome 的室温在 6 秒动作区间后仍远离目标。当前离散事件路径 `run_event_simulation` 已能把显式的 `start_effects` 和 `completion_effects` 分开，并把最终效果放在动作完成时；但若只给出一个 `effects` 快照，它仍是在完成时一次跳变，而且 `environment_effects` 未被执行。此次配对回放并未改用或重新评测这套离散事件执行路径。此处证明的是本批旧版评测与 SimuHome 的目标／完成语义尚未对齐，不是整个 HomeCoord runtime 均忽略动作生命周期，也不是协调算法效果或 SimuHome 的真实物理结论。

此外，SimuHome 的 HVAC 命令会立即改变设备状态，而 HomeCoord 轨迹里的 6 秒制冷时长只保留在事件时间线上。现有 SimuHome workflow 的计划时间按整秒输入，不能准确重现这批毫秒级动作时间；直接命令的提交时刻又会受本机 API 和后台 tick 影响。当前适配层因此足以检查命令映射与离散设备终态，不足以评估该 episode 的毫秒级因果时序或热任务完成时间。

## 可复现文件

- 第一批脚本、结果与轨迹：`homecoord_bench/simulator_adapter/replay_homecoord_hvac_pair_to_simuhome.py`、`homecoord_bench/results/homecoord_hvac_pair_simuhome_replay_20260927.json`、`homecoord_bench/results/homecoord_hvac_pair_simuhome_replay_traces/`。
- 减少状态读取后的复测：`homecoord_bench/simulator_adapter/replay_homecoord_hvac_pair_to_simuhome_v2.py`、`homecoord_bench/results/homecoord_hvac_pair_simuhome_replay_v2_20260927.json`、`homecoord_bench/results/homecoord_hvac_pair_simuhome_replay_v2_traces/`。
- 两批 JSONL 合同审计分别为 `homecoord_bench/results/homecoord_hvac_pair_simuhome_replay_trace_audit_20260927.json` 和 `homecoord_bench/results/homecoord_hvac_pair_simuhome_replay_v2_trace_audit_20260927.json`。

审计通过表示轨迹结构、命令关联和逻辑顺序满足日志合同；审计中的重复不一致仍保留为误差证据。上游 README 声明 CC BY-NC-ND 4.0；本地研究没有分发上游代码或 episode，对外发布衍生材料前仍需核实许可与机构政策。

## 下一步

先让 HomeCoord 与模拟器共享同一套明确的动作生命周期语义：动作提交、设备状态改变、持续作用、目标条件满足和完成回报分别记录。之后再决定哪些连续状态任务能用 SimuHome 作为后端，哪些仍留在 HomeCoord 的抽象事件环境。候选任务的动作持续时间、状态效果和冲突／对照公平性需逐条审核；不能用这 12 条 HVAC 回放替代 M01–M20 审核或完整多 Agent 实验。
