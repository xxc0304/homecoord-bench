# SimuHome HVAC 运行适配试点

日期：2026-09-27  
状态：固定版本本地运行完成；验证了家庭状态、HVAC 命令、虚拟时钟和短／长时热状态响应。该试点不验证真实家庭物理精度，也不包含多 Agent 并发。

## 结论

SimuHome 可以作为 HomeCoord 的**设备与环境状态后端候选**：固定配置 reset、设备命令、顺序工作流、状态回读和虚拟时间快进均能运行并重放。A–E 共 21 条轨迹全部通过本地轨迹审计，7 个配置／顺序重复组全部得到一致状态。

这只是“后端可接入”的证据，不是 HomeCoord 多 Agent benchmark 已在 SimuHome 上验证。整个试点由固定规则提案和串行工作流构成；Agent 异步到达、并发 API、冲突任务真值、deadline、安全策略比较和真实设备都没有接入。因此两边分数仍不能合并，现阶段也不能用此结果支持协调算法优于基线。

## 运行方式与故障定位

- 固定上游版本：`holi-lab/SimuHome@83d28837b69f0cbf1bc02ed5334cb8b561a9d54d`。上游源码和运行依赖放在临时目录，未改写或复制进项目；只使用本项目新建的单 HVAC 配置，不读取或改写上游 600 条 benchmark episode。
- 隔离运行时：官方 Python 3.13.7 embeddable runtime；HomeCoord 工作区原有解释器为 Python 3.12.14。API 仅绑定本机 `127.0.0.1:8765`，试点没有调用 DeepSeek 或其他模型 API，也未连接物理设备。
- 先前“排队后设备状态不变”不能作为一次有效动作。源码检查发现 `/api/workflow/run_now` 立即返回的只是 `accepted/queued`，不会报告后续步骤是否成功；空调 `OnOff.OnOff` 属性只读，开关须调用 `execute_command` 的 `On`／`Off`。运行脚本因此改用可查询状态的定时 workflow，并在目标 tick 后检查 workflow 是否 `completed`、步骤数是否完整和设备状态是否匹配。
- 最初 reset 返回时，房间温度是 2900，但空调的 `LocalTemperature` 默认是 2500，初态不一致。试点输入已把它显式设为 2900，并在每次 reset 时核对两者相同。原始的 `run_now` 入队记录不列入通过轨迹。

## 试验与结果

温度和设定值沿用该实现内部约 100 个原始单位对应 1°C 的编码，但没有拿真实温度计或设备做校准。短时 raw 数值变化不可解释为真实家庭温差。重复数是同一固定配置下的技术重复，不是独立家庭或独立任务。

| 卡片 | 设置与重复 | 可观察结果 | 判定 |
|---|---|---|---|
| A：reset 与制冷状态回环 | 制冷 workflow 在 tick 20 执行，读取 tick 25；3 次 | 每次 workflow 均 `completed`、4/4 步完成；空调开机、`SystemMode=3`、制冷设定值 2400、风扇设置 66。室温状态变化均为 −0.013199 raw units | reset、动作状态和短时重放通过；该时间窗太短，室温变化没有物理解释价值 |
| B：反向命令顺序 | `cool@tick10 → off@tick20` 与 `off@tick10 → cool@tick20`，每种 3 次；tick 15 和 25 读取 | 顺序 A 的终态空调关闭；顺序 B 的终态空调开启。两种顺序三次重复完全相同。室温 raw 变化分别为 −0.036293 与 −0.013199 | 后端可表达同设备相反提案的顺序敏感性；不等同于多 Agent 冲突效果或任务效用结论 |
| C：外层时钟步进探针 | tick interval 1 秒；逐次快进到 tick 1、2、3；3 次 | 三次均精确返回 1、2、3，没有跳 tick 或倒退 | 本地适配时钟回环通过；HomeCoord 的真实事件队列尚未连接 |
| D：短时空闲对照 | 无动作，tick 25；3 次 | 空调始终关闭，温度变化为 0 | A 的短时细微漂移不是空闲状态自身漂移，但量级仍太小，不能据此声称测出真实制冷效果 |
| E：一小时热响应对照 | 无动作与 tick 20 制冷各 3 次，推进至 tick 36000 | 空闲组温度变化均为 0；制冷组均为 −84.651024 raw units（按代码内部比例约 −0.8465°C），终态一致 | 后端长时热状态会受空调动作影响，且可确定性重放；这一变化来自模拟器公式，尚未对现实家庭校准 |

完整结果见 [`simuhome_hvac_pilot_20260927.json`](../homecoord_bench/results/simuhome_hvac_pilot_20260927.json)、[`simuhome_hvac_thermal_response_20260927.json`](../homecoord_bench/results/simuhome_hvac_thermal_response_20260927.json)；21 条逐事件 JSONL 轨迹位于 `homecoord_bench/results/simuhome_hvac_pilot_traces/`。轨迹审计结果是 21/21 结构有效、0 错误，7/7 重复组确定性一致，见 [`simuhome_hvac_trace_audit_20260927.json`](../homecoord_bench/results/simuhome_hvac_trace_audit_20260927.json)。其中记录的 HTTP 墙钟往返包含模拟器按 tick 处理 API 队列的等待时间，不能当成 Agent、模型或真实设备延迟。

## 证据边界和后续工作

1. 本试点只支持“SimuHome 值得保留作家庭状态／动力学后端”的决定。它没有提供多 Agent 异步调度和并发执行接口；这些仍需由 HomeCoord 的外层协调器与统一事件记录承担。
2. 一小时制冷反应只证明当前代码按其内置公式更新状态。要把温度或物理任务成功率用于论文，仍须确认上游动力学假设，并以设备数据、公开测量或领域专家审查校准参数和时间尺度。
3. C3 家庭总功率、开窗等缺少原生对象的场景，以及执行中的取消／恢复仍不适合移入 SimuHome。保持在 HomeCoord 控制的仿真层，并明确标记合成参数，或另找有对应原生支持的测试床。
4. 已完成 C1-HVAC 固定提案回放，结果和评测器边界见 [`HOMECOORD_HVAC_PAIR_SIMUHOME_REPLAY_2026-09-27.md`](HOMECOORD_HVAC_PAIR_SIMUHOME_REPLAY_2026-09-27.md)。它确认离散设备终态映射可用，但 HomeCoord 即时目标效果与 SimuHome 逐步热状态演化尚未对齐，毫秒级 tick 也不能精确重放。下一步应先审核 20 条候选任务的动作效果、持续时间和冲突／对照公平性，再决定哪些适合进入物理状态后端。
5. 上游仓库 README 声明 CC BY-NC-ND 4.0。此次本地运行没有分发上游代码或 episode；对外发布衍生数据、适配器或结果包之前，仍须确认许可和机构政策允许。

复跑入口：`python homecoord_bench/simulator_adapter/run_simuhome_hvac_pilot.py`。它面向一个已在 `127.0.0.1:8765` 启动的固定版本本地 API，会执行 A–E 全部 21 条技术轨迹；脚本、配置、原始响应摘要和审计均留在本地项目，不会上传 GitHub。
