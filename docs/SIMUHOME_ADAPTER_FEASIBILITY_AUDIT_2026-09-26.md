# SimuHome 适配可行性静态审查

日期：2026-09-26  
状态：完成公开源码与配置审查；未下载、安装或运行第三方代码，未调用模型 API。

## 结论

SimuHome 值得作为 HomeCoord-Bench 的**家庭状态与环境动力学后端候选**，但不适合直接替代 HomeCoord 的异步调度时钟和逐事件轨迹。最有希望的小试点是同一空调上的相反命令：HomeCoord 外层仍负责 Agent 提案延迟与协调顺序，SimuHome 负责设备状态和室温随时间演变。C3 容量、通用外部事件及动作中止能力目前无法原样迁移，必须先留在 HomeCoord 的受控仿真中，不能把两边分数直接合并。

> **后续状态：**本文件记录 2026-09-26 静态审查。次日已执行 HVAC 运行适配试点，状态更新见 [`SIMUHOME_HVAC_RUNTIME_PILOT_2026-09-27.md`](SIMUHOME_HVAC_RUNTIME_PILOT_2026-09-27.md)。固定版本的 A–E 共 21 条轨迹全部通过轨迹审计，确认本地 HVAC 状态／时钟／重复性可以运行；静态审查中的“尚未运行”描述是当时状态，不再是当前状态。物理校准、多 Agent 并发和对外许可适用性仍未验证。

## 核查依据

- 论文页面：[SimuHome, ICLR 2026](https://proceedings.iclr.cc/paper_files/paper/2026/hash/43456e781fac3a034842f0807860474a-Abstract-Conference.html)。论文摘要描述 600 个 episode、Matter 风格设备、随时间演化的温湿度，以及四类任务和工作流调度。
- 作者公开仓库：[holi-lab/SimuHome](https://github.com/holi-lab/SimuHome)，本次静态审查版本为 [`83d28837b69f0cbf1bc02ed5334cb8b561a9d54d`](https://github.com/holi-lab/SimuHome/commit/83d28837b69f0cbf1bc02ed5334cb8b561a9d54d)。仓库包含模拟器、REST 客户端和 600 条基准 episode。该版本 README 明确提示：论文实验后模拟器有所增强，当前仓库 episode 快照与论文 Table 1 使用的数据并不完全相同，复跑分数不应期待逐项一致；README 声明 CC BY-NC-ND 4.0，`pyproject.toml` 要求 Python `>=3.13`。
- 客户端接口：[smarthome_client.py@审查 commit](https://github.com/holi-lab/SimuHome/blob/83d28837b69f0cbf1bc02ed5334cb8b561a9d54d/src/clients/smarthome_client.py)、[API routes@审查 commit](https://github.com/holi-lab/SimuHome/blob/83d28837b69f0cbf1bc02ed5334cb8b561a9d54d/src/simulator/api/routes.py)、[request schemas@审查 commit](https://github.com/holi-lab/SimuHome/blob/83d28837b69f0cbf1bc02ed5334cb8b561a9d54d/src/simulator/api/schemas.py)。客户端列出 `reset_simulation`、`get_home_state`、`execute_command`、`write_attribute`、`fast_forward_to`、`get_current_time`、定时工作流、工作流状态和取消接口。
- 时间与工作流行为：[home.py@审查 commit](https://github.com/holi-lab/SimuHome/blob/83d28837b69f0cbf1bc02ed5334cb8b561a9d54d/src/simulator/domain/home.py)。客户端列出虚拟时间推进和工作流状态等接口。
- HVAC 与温度表示：[air_conditioner.py@审查 commit](https://github.com/holi-lab/SimuHome/blob/83d28837b69f0cbf1bc02ed5334cb8b561a9d54d/src/simulator/domain/devices/air_conditioner.py)、[thermostat.py@审查 commit](https://github.com/holi-lab/SimuHome/blob/83d28837b69f0cbf1bc02ed5334cb8b561a9d54d/src/simulator/domain/clusters/thermostat.py)、[temperature.py@审查 commit](https://github.com/holi-lab/SimuHome/blob/83d28837b69f0cbf1bc02ed5334cb8b561a9d54d/src/simulator/domain/aggregators/temperature.py)。温度状态使用约 0.01°C 的整数尺度；制冷模式值为 3，空调制冷还依赖开机和有效风扇设置。
- 当前仓库许可证：README 标示 [CC BY-NC-ND 4.0](https://github.com/holi-lab/SimuHome#license)，并说明可作非商业分享但不允许衍生作品。集成前应按该条款处理归属与发布；不要复制或修改其实现，也不要把其 benchmark 文件并入 HomeCoord 数据集。
- 设备类型清单可见 [设备模型目录](https://github.com/holi-lab/SimuHome/tree/main/src/simulator/domain/devices)；房间级环境聚合器目前列出温度、湿度、PM2.5/颗粒物和照度等，没有家庭总功率聚合器，见 [aggregators](https://github.com/holi-lab/SimuHome/tree/main/src/simulator/domain/aggregators)。

## 与 HomeCoord 需求的对应关系

| HomeCoord 需要 | SimuHome 公开实现所显示的能力 | 判断 |
|---|---|---|
| 家庭共享状态及设备动作 | 可读取整屋／房间／设备状态；可下发 Matter 风格命令和属性写入 | 可作为世界状态后端 |
| 室内环境随动作变化 | 空调、热泵、加湿／除湿、照明等设备模型与温度、湿度、照度等 room state | 适合增加环境接地；具体动作效果与单位仍需试跑校准 |
| 虚拟时间推进 | 支持配置 tick interval、读当前时间、快进到整数 tick；另有按虚拟时间启动 workflow 的接口 | 部分适配；必须确认服务器后台 tick 与外层事件时钟如何同步，否则可能引入时间竞态 |
| 多 Agent 异步提案 | 未见与 HomeCoord 同义的 Agent 提案队列；HTTP 命令最终进入单个 Home 实例的 API 队列，模拟循环每 tick 最多处理 10 个 API 请求 | 应由 HomeCoord 外层生成和排序提案；不能把并发 HTTP 请求等同于并行设备执行 |
| 开始／完成时延 | 普通命令由 API 队列处理；洗衣机等设备可呈现 OperationalState／CountdownTime 等进度属性，但工作流步骤本身是顺序执行的命令序列 | 部分适配；命令接受、设备状态变化、目标达到应分别记时 |
| 可复现事件轨迹 | API 支持状态读取、工作流状态和步骤结果；目前接口不直接导出 HomeCoord 所需的逐 Agent、逐命令统一轨迹 | 需在适配层记录提交、虚拟 tick、状态快照、目标进展和工作流结果 |
| C1 同设备冲突 | 同一空调能接收设定／模式等不同命令 | 最适合作首个适配试点 |
| C2 共享环境变量 | 有环境状态和窗帘／照明／空调等设备；没有明确的“开窗”设备模型 | 可重新设计为可验证的遮光／温度交互，但不能直接沿用现有开窗规则 |
| C3 家庭总功率容量 | 有电气传感器／设备电气属性，但 room state 聚合器清单无家庭总功率；公开接口未显示统一的家庭容量硬约束 | 不支持原样验证；除非测出稳定可用的功率状态，否则容量仍由 HomeCoord 合成模型承担并明确标为合成 |
| C4 状态过期与运行中修复 | 外层可以给每次观测打版本；设备状态可重新读取。工作流可以取消 pending 项，但源码中的 running workflow 不能取消 | 可测“基于旧快照提交”的外层协议；运行中局部中止／修复能力有限 |
| 外部突发事件 | 可用设备属性写入或定时 workflow 安排设备侧变化；没有通用天气、住户到达／离开等外部世界事件注入接口 | 部分／弱支持；合成外部事件不能冒充原生环境动态 |

源码层面还有两个重要时间语义：一是 `Home` 用单个队列处理 API 请求，多个请求可先后进入队列；二是 workflow 到时后将步骤递归顺序执行，完成状态不代表这些步骤之间经历了物理运行时间。待执行 workflow 可取消，已经运行的 workflow 会拒绝取消。因此适配器必须自己为每个 proposal 和 command 打稳定 ID、记录队列顺序，并从设备进度属性判断目标完成。

## 现有 episode 的迁移建议

| HomeCoord 情境 | 映射可行性 | 建议 |
|---|---|---|
| C1-HVAC 冲突 | 高 | 取 SimuHome 含空调的房间状态，构造“继续制冷”与“关闭／改模式”两个独立提案；保持共享目标和安全约束由 HomeCoord 明确定义。记录同一设备两条命令的顺序与后续室温变化。先做无模型 DryRun，暂不引入 DeepSeek。 |
| C1 blinds 冲突 | 中 | 有窗帘控制器，可映射不同窗帘位置或同设备相反动作；需先验证动作更新速度与照度变化，避免把窗帘命令虚构成窗户开合。 |
| C2 HVAC—开窗 | 低／需改写 | 当前目录显示的是窗帘控制器，没有直接开窗设备。若选该后端，应另设计能由已有设备和环境状态支持的共享变量冲突，不能沿用“开窗导致温度变化”的假设。 |
| C3 EV—热水器／照明容量 | 低 | 当前设备目录未列 EV、热水器或灌溉设备，也未发现整屋功率聚合器。不要把现有容量 episode 直接移植；先保留本地容量实验台，或仅在确认设备功率属性随运行状态更新后另做小范围功率探针。 |
| C4 stale state | 中 | 外层 Agent 先读取同一设备状态，模拟延迟后再提交相冲突操作；外层记录 `state_version`。SimuHome 负责真实状态转变，版本和因果轨迹由 HomeCoord 写入。 |
| 雨天／占用变化中断动作 | 低 | 没有通用天气或占用事件接口，且 running workflow 不可取消。第一版不要将其作为 SimuHome 适配验收条件。 |

这些匹配只表示有办法构造实验，不代表 SimuHome 中已存在对应多 Agent ground truth，也不意味着其原有 600 个 episode 能直接作为 HomeCoord 的数据。

### HVAC 最小映射草案

HomeCoord 的 `cool` 提案可映射为一个 SimuHome workflow：开机、把 Thermostat `SystemMode` 设为制冷、将 `OccupiedCoolingSetpoint` 设为低于当前室温的值、设置非零风扇档位；需保持制热／制冷设定值之间至少 0.25°C 的死区。上游 `AirConditioner` 实现在写模式／设定值前要求设备已开机。`off` 提案映射为 OnOff cluster 的 `Off` 命令。`cool` 因而是一条高层 proposal 对应四个有序底层步骤，轨迹须保留共同的 `proposal_id` 和 `command_bundle_id`，不能把底层 API 步数计成多个 Agent 决策。

可以从 SimuHome 某个包含空调的房间状态初始化设备，再把“舒适 Agent 请求制冷”和“能源 Agent 请求关闭空调”做成同刻两个高层 proposal。HomeCoord 决定接受／拒绝顺序，外层适配器按 workflow 的虚拟启动时刻提交命令，之后以房间 `temperature` tick 序列判断目标进展。舒适请求、设备互斥规则和安全标签仍由 HomeCoord 的独立任务定义提供；SimuHome 提供设备与环境状态，并不会自动给出这些多 Agent 标签。

该草案用一个受控 task family 检验是否可行，不代表恒温器行为已校准到真实家庭。deadline 应先依据同一初始状态下的温度轨迹测得，再从 held-out 的等待时间或环境扰动中检验。

## 建议的最小接入试验

若继续推进，优先做 3 条固定任务映射，全部使用本地规则提案、不调用模型 API：

1. **设备状态回环**：reset 一个含空调的配置，读取房间和设备状态，发一条命令，快进若干 tick，再读状态；确认温度变化、单位、复位确定性和目标判定。
2. **相反提案的顺序敏感性**：同一空调上构造两个策略顺序（A→B、B→A），对比即时设备状态与后续温度轨迹；从 HomeCoord 提交队列和响应记录中分开量命令延迟与物理目标进展时间。
3. **同刻任务调度**：让两个提案在同一 HomeCoord 虚拟时间到达，协调策略分别安排接收顺序；核对 SimuHome API 队列实际执行顺序是否与提交记录一致，并重复 reset 测定轨迹是否稳定。

通过条件是 reset 后初始状态可重复、相同 tick 和命令序列可重放、命令次序能从轨迹中确认、温度等环境状态能在快进后读取。若后台 tick 与外层时钟产生不可控竞争，或命令次序不稳定，则保留 SimuHome 作为环境参考而不纳入主指标。这个小试验的目的只是判断**动力学是否能补强 HomeCoord**，不替代后续的数据扩充、人工审核和多策略评测。

## 当前状态与未做事项

- 已从论文官网和作者公开仓库核实仓库、README、API 客户端、路由、schema、Home 时间推进实现、设备及环境聚合器目录。
- 已固定只读审查基线 commit `83d28837b69f0cbf1bc02ed5334cb8b561a9d54d`；此版本 `pyproject.toml` 要求 Python `>=3.13`，当前工作区 Python 为 3.12.14，不能直接运行。通过 GitHub API 可以读源码，但本机 Git 缺少 `remote-https` helper，因此未检出或启动第三方项目。
- 已发现作者 README 提醒公开仓库当前 benchmark 快照与论文 Table 1 数据不完全相同；后续实验必须固定代码／数据版本并避免把复跑结果当论文复现。
- 未 clone、安装或启动 SimuHome；未调用 OpenAI、DeepSeek 或其他模型 API。
- 运行时适配仍需确认 Python 3.13 环境、许可证适用、tick 同步、无模型命令往返、同刻命令次序和 reset 重放。具体预注册试验与自动轨迹契约见 `docs/SIMUHOME_HVAC_MINIMAL_TRIAL_SPEC_2026-09-26.md`；当前本地离线轨迹审计器及合成契约测试不代表后端运行结果。若接入，保留 SimuHome 上游不变，通过 HomeCoord 单独的 HTTP 适配器与轨迹记录连接。
