# Agent 动作导致在途前提失效：隔离机制探针

日期：2026-09-27  
状态：由两条未双审的 C1 配对草稿派生；只验证指标来源和协调行为，不是物理性能或新算法实验。

制冷任务在内存中增加 `devices.living_hvac != forced_off` 持续前提；能源 Agent 关闭空调的效果分别放在动作开始或完成。冲突臂在制冷期间发出关闭命令，安全臂等制冷完成后才发出。同一固定 300 ms 提案时延、五种策略、每格三次重复，共 60 次 DryRun；不修改源草稿或正式候选。

| 关闭效果时点 | 冲突臂 Independent | 冲突臂 Constraint | 安全臂 Independent | 安全臂 Constraint |
|---|---:|---:|---:|---:|
| 动作启动 | 1 | 0 | 0 | 0 |
| 动作完成 | 1 | 0 | 0 | 0 |

冲突臂 Independent 的失效记录均定位到能源 Agent 的关闭动作，且分别归因于 `action_started` 或 `action_completed`。Constraint 在这两种设定下都推迟了冲突动作；安全臂无需额外处理。全部 20 个配置的三次轨迹与结果各自完全一致。

探针把新增的 `requires` 当作动作运行期间仍需成立的有效性条件；失效只触发记录，不会自动中断动作。结果说明新增指标能辨别 Agent 间状态干扰及其发生阶段。预设的同设备锁或约束协调已能避免本例，不能从中推出需要新协调算法。动作效果时点、持续时间和提案时延均为合成设定；源任务尚未领域双审。

复跑：`python homecoord_bench/probe_agent_caused_inflight_invalidation.py`。逐次结果及源草稿哈希：`homecoord_bench/results/agent_caused_inflight_probe_20260927.json`。
