# SimuHome HVAC 最小适配试验规格

日期：2026-09-26  
阶段：运行前的预注册规格；当前没有 SimuHome 运行结果。  
目的：判断 SimuHome 的 HVAC 与房间状态动力学，能否补强 HomeCoord-Bench 的协调事件实验台。

## 问题与边界

这不是重做 HomeCoord 的多 Agent 调度器，也不是复现 SimuHome 论文分数。SimuHome 只候选承担房间／设备状态及其随虚拟时间的变化；HomeCoord 保留 proposal 产生时间、Agent 身份、协调策略、同一高层 proposal 下的命令分组和统一过程轨迹。

首轮只考察同一台 HVAC 上的 `cool` 与 `off` 两种相反高层操作。家庭请求、任务目标、冲突标签与安全判据由 HomeCoord 自己定义；SimuHome 不提供这些多 Agent 标注。EV／热水器容量、开窗、天气、住户事件和动作运行中取消不进入这次适配试验。我们自己写的 reset 输入和 proposal command bundle 放在 `homecoord_bench/simulator_adapter/hvac_trial_inputs_v0.1.json`；它不是从 SimuHome benchmark episode 改造的样本，目前也未执行。

上游 README 标示 CC BY-NC-ND 4.0，且提醒当前公开数据快照和论文表格数据不同。若要运行，先固定仓库 commit、配置与数据版本，保留上游原样，通过单独的 HomeCoord 适配器调用；不复制或修改上游实现，不把其 episode 并入本项目数据。若项目的研究／发布用途与许可条款不明确，停止分发上游材料，仅保留接口兼容性研究记录。代码可运行不等于许可已审核通过。

本次通过 GitHub API 只读核对的版本是 `holi-lab/SimuHome@83d28837b69f0cbf1bc02ed5334cb8b561a9d54d`（main 分支当前指向的 commit，README 更新于 2026-04-08）。该 commit 的 `pyproject.toml` 要求 Python `>=3.13`；当前 Codex 工作区可用 Python 为 3.12.14，因此当前运行环境不能直接安装此版本。Git over HTTPS 也因本地 Git 缺少 `remote-https` helper 未能建立源码检出。两点均是本机工具链限制，不代表 SimuHome 本身无法运行；本轮仍只完成只读源码审查与本地离线工作。

## 实验前冻结项

每个原始运行目录须保存 `run_manifest.json`，记录：

- SimuHome 仓库 URL、精确 commit SHA、README 中声明许可的版本、运行配置和 episode/config 标识；
- Python 与依赖锁定版本、随机种子、tick interval、初始房间／设备状态；
- HomeCoord commit、适配器版本、每个 proposal 的计划执行 tick；
- 运行类型为 `simulator_adapter_pilot`，并注明未调用 LLM、未接真实设备。

没有精确 commit、初始配置或完整逐事件日志的结果不可用于跨运行比较。禁止用作者仓库当前 snapshot 的结果声称复现论文 Table 1。

## 试验卡

| 卡片 | 固定操作 | 重复 | 主要核验 |
|---|---|---:|---|
| A. reset 与状态回环 | 同一 HVAC 配置 reset；读取初态；执行一条已校验的 `cool` workflow；按固定 tick 前进并逐 tick 读温度／设备状态 | 3 次同种子 | reset 初态一致；命令被接受；模式／设定值状态可读；温度单位与状态路径明确；温度变化是否可重复 |
| B. 顺序反事实 | 同一初态分别提交 `cool → off` 和 `off → cool`；proposal 达到时刻、tick 和底层 command bundle 均冻结；运行至相同终止 tick | 每种顺序 3 次 | 记录实际应用顺序；终态模式／设定值与房间温度；任何队列顺序漂移；同顺序重放差异 |
| C. 外层时钟对齐 | 固定 tick interval；HomeCoord 在 tick 0、1、2 产生带时间戳的事件，SimuHome 每步推进一次；每步两边记录虚拟时间 | 3 次同种子 | 无倒退／跳 tick；状态快照与目标 tick 对齐；每个 HomeCoord proposal 的提交与设备状态变化可因果关联 |

共 12 条运行轨迹：A 卡 3 条、B 卡两种顺序各 3 条（6 条）、C 卡 3 条。它们是同一受控配置的重复，不是 12 个独立任务，也不提供 benchmark 覆盖规模证据。

## 高层动作映射

- 静态核对的固定版本将 HVAC 的 OnOff、Thermostat、FanControl cluster 都挂在 endpoint 1；恒温器 setpoint 以 0.01°C 整数表示，制冷 `SystemMode=3`，且写模式／设定值前设备必须已开机。房间温度聚合值在当前源码中也以相同量级的整数保存（例如 29°C 对应约 2900）。这些是源码表示，不是校准后的物理量。
- 一个 HomeCoord `cool` proposal 映射为一个稳定的 `proposal_id`，其下挂同一个 `command_bundle_id` 和四个有序底层步骤：开机、设置制冷模式、将制冷设定值调到 24°C、设置非零风扇档位。初始输入把制热设定值放在 22°C、制冷设定值放在 26°C，保证先验死区合法。`off` 映射为单条关闭命令。步骤均通过 workflow 顺序执行；它们属于一条高层 Agent 决策，不按四次 Agent 决策计数。
- 一个 `off` proposal 映射为一条 HVAC 关闭命令。
- 评测的冲突单位是高层 proposal 对；workflow 内部子命令不计作额外 Agent 决策。每条子命令仍需独立记录提交、队列顺序、执行结果和状态快照。
- 固定版本的 workflow 是单 Home API 队列中的顺序步骤，并会在同一 workflow 启动过程中递归执行；步骤间不经过模拟设备运行时间。首轮把完整 bundle 当作一个已排程高层操作，另行保留底层步骤轨迹。若状态回读／workflow 结果不能证明 proposal 先后，则 B 卡不能声称比较了两个原子 proposal 的顺序，应标记为不通过／需改写任务。

## 统一时间与逐事件日志

SimuHome 是虚拟时间来源；HomeCoord 不用墙钟 sleep 模拟虚拟 tick。每次 `fast_forward_to` 或等价推进前后，记录两边的 tick 与后端当前时间。HTTP 往返墙钟耗时单独记为 `adapter_wall_latency_ms`，不得混入模拟世界内的 Agent 推理延迟或设备物理时长。

每次运行保存一个 JSONL 文件，每行至少包括：

`run_id, scenario_id, schedule_id, seq, event_type, homecoord_tick, backend_time, agent_id, task_id, proposal_id, command_bundle_id, command_id, command_order, status, state_digest, room_temperature_c, hvac_mode, cooling_setpoint_c`

字段为空时写 `null`。必需事件类型：`reset`、`state_snapshot`、`proposal_scheduled`、`command_submitted`、`command_result`、`tick_advanced`、`run_finished`。必须保存原始后端状态响应或无损副本，`state_digest` 不能替代原始状态。

本地审计脚本 `python homecoord_bench/audit_simulator_adapter_trace.py run1.jsonl run2.jsonl ...` 检查通用轨迹结构、虚拟时间单调性、proposal 与底层 command 的归属、执行次序证据以及相同配置重复运行的重放一致性。每行还需带统一 metadata：`schema_version, run_id, scenario_id, schedule_id, backend_revision, random_seed, tick_ms`；运行首尾都必须有状态 digest。它验证日志是否足以回答问题，不验证 SimuHome 的物理真实性。

## 成功与停止标准

适配试点只有在以下条件全部满足时才通过：

1. 3 次同种子 reset 的初始 HVAC 与房间状态逐字段一致；
2. 每个高层 proposal 均可追溯到已完成或明确失败的命令 bundle，命令应用顺序可从后端状态或执行回执独立观察；
3. HomeCoord tick 与后端虚拟时钟可一一对应，无法同步的偏差不超过一个预先冻结的 tick，且无后台自动推进造成的竞态；
4. 每种固定 schedule 的三次同配置运行在同 tick 得到完全相同的离散 HVAC 状态，并在温度数值误差不超过 `0.01 °C` 范围内一致；
5. `cool` 至少产生可观测的 HVAC 状态变化；温度是否变化、变化方向、首次变化 tick 和幅度如实报告，不预设其必须达到目标温度；
6. trace auditor 对 12 条轨迹返回零结构错误、零顺序不明、零 tick 倒退、零重放差异。

如温度动力学在当前 tick 范围内没有可测变化，环境仍可能提供真实设备状态，但这次试验不能宣称验证了房间热动力学。若命令顺序、时钟或 reset 不可控，则不纳入 HomeCoord 主指标；退回当前独立事件仿真台或只把 SimuHome 作为定性环境参考。不得调规则直到得到预期冲突结果。

## 报告口径

报告分别列出：设备命令提交到回执的墙钟时间、模拟 tick 数、HVAC 首次状态变化 tick、室温首次可测变化 tick、达到任务目标的 tick、任务服务与安全判定。没有 LLM 的 A–C 试验不能回答模型 API 延迟；没有真实设备或校准数据的室温曲线不能当作真实家庭物理效果。HomeCoord 与 SimuHome 指标不得直接合并成一个总分。

## 当前未完成项

- 尚未固定 SimuHome commit 与 Python 依赖；
- 尚未对许可证能否支持具体科研运行、结果分发进行法律／机构确认；
- 尚未下载、安装或运行上游模拟器；
- 目前没有任何 A–C 卡片的实测轨迹或过关结果。

本规格的下一步是实现一个单独的 HTTP 适配器并用冻结配置执行 A 卡。只有 A 卡通过后才继续 B、C，不先消耗模型 API 额度。

## 2026-09-27 执行状态补记

上面的状态和“下一步”是 2026-09-26 预注册时的原始记录，现由执行结果覆盖：SimuHome commit、隔离运行时和 A–C 试点均已固定并完成。A–C 共 12 条轨迹全部达到本规格内的状态／时间／重放检查。随后为判明短时细微漂移的意义，增加了 D 空闲对照（3 条）及 E 一小时制冷／空闲对照（共 6 条）；A–E 共 21 条轨迹经 JSONL 审计均有效，7 个配置／顺序组均确定性一致。

实测值、根因分析和方法边界见 `docs/SIMUHOME_HVAC_RUNTIME_PILOT_2026-09-27.md`。简要结论：HVAC 状态动作和长时模拟室温响应可运行，但没有真实设备校准，也没有多 Agent 并发。许可证的对外发布适用性仍未确认。原始试验规格保留不改，以区分预注册 A–C 与后续 D/E 探索性控制。
