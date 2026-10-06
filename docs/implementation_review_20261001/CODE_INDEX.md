# Phase B评分与执行代码索引

仅索引实际使用的代码；原文件未修改，主要源码SHA-256见manifest。两个版本分开标识，不以新审计程序冒充旧生产评分。

| 文件 | 作用及重点 |
|---|---|
| [evaluate.py](../../homecoord_bench/evaluate.py) | 旧通用评分、匹配服务、最终目标、冲突与期限；读取时区分投影动作与真实完成事件。 |
| [task_response_metrics.py](../../homecoord_bench/runtime/task_response_metrics.py) | 真实action_started/action_completed，按各task自身release计算等待、完成时延、迟到；缺失保持null。 |
| [旧event_simulator](../../homecoord_bench/runtime/event_simulator.py) | F1队列/同刻顺序、实际状态、公共门控、legacy投影和逐任务评分汇总。 |
| [event_simulator_v3](../../homecoord_bench/task_revision/event_simulator_v3.py) | 依赖等待、实际完成回执释放和启动再检查；不是默认CLI入口。 |
| [execution.py](../../homecoord_bench/runtime/execution.py) | 动作grounding和容量调度工具。 |
| [tool_contract.py](../../homecoord_bench/runtime/tool_contract.py) | 严格工具身份、操作、参数和前提校验。 |
| [protocol.py](../../homecoord_bench/runtime/protocol.py) | 实际request序列化、局部状态、可用动作、评估提示开关与协议校验。 |
| [PublicModeClient](../../homecoord_bench/probe_c3_multimode_20260930.py) | F1脚本从公开工具取prepare服务动作及声明成本，不调用模型。 |
| [dry_run.py](../../homecoord_bench/runtime/dry_run.py) / [FixedProposals](../../homecoord_bench/task_revision/milestone.py) | 依赖答案模板脚本和300ms逻辑延迟，不能称模型推理。 |
| [dependency_contract.py](../../homecoord_bench/task_revision/dependency_contract.py) | DAG静态校验与支持范围。 |
| [dependency_audit.py](../../homecoord_bench/task_revision/dependency_audit.py) | 有效回执及等待/阻断重计；其中metrics也引用生产汇总。 |
| [lifecycle_audit.py](../../homecoord_bench/task_revision/lifecycle_audit.py) | 状态/完成/预约释放/暴露审计，由依赖审计调用。本轮不扩张到生命周期任务验收。 |
| [phase_b_packet.py](../../homecoord_bench/task_revision/phase_b_packet.py) | 本轮Capture、recount、历史对照和包生成器。recount不调用生产逐任务评分函数。 |

manifest还记录episode_validation、scheduling_oracle、lifecycle_contract等实际支持文件。本索引及README为导航说明，不是完整代码副本；若源文件后来变化，必须先核对manifest，不沿用本轮通过结论。
