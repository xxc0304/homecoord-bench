# 小规模验证 v1：独立实现审查

2026-10-05。结论：**28配置、84条主运行及72对统计均符合已冻结设计；本批新入口、已提交轨迹和统计结果通过限定实现审查。** 未发现须修正项。作者的测试通过及旧适配器验收未被用作本次验收替代品。

本审查仅覆盖两个F2晚到模板、容量3/6、三种既有确定性政策及预定单因素扰动。不能据此宣布策略普遍更优、LLM必要、真实家庭有效、跨执行阶段稳健或预约机制因果作用。

## 核查结果与证据

| 对象 | 结论 | 独立证据与实现位置 |
|---|---|---|
| 冻结与物化输入 | 符合设计 | 11份获准材料与此前独立设计审计相同；冻结各锁匹配。28份输入从旧源独立重建，仅发生获准变化，核对派生及最终SHA。[verify_freeze](https://github.com/xxc0304/homecoord-bench/blob/main/homecoord_bench/task_revision/small_validation_execution_v1.py#L43) |
| 12条新基线 | 符合设计 | 完整calls含request/decision、全部trace字段及顺序逐一与旧同政策比较，仅去除两个外层身份字段；未递归掩码。[exact_baseline](https://github.com/xxc0304/homecoord-bench/blob/main/homecoord_bench/task_revision/small_validation_execution_v1.py#L128) |
| 扰动前门禁 | 符合设计 | 每次扰动重新build_gate，读取四份基线并校验完整复现和代码/冻结绑定；不是信任passed标志。[verify_gate](https://github.com/xxc0304/homecoord-bench/blob/main/homecoord_bench/task_revision/small_validation_execution_v1.py#L194) |
| 公开输入与能力 | 符合设计 | 84条逐发布状态重建，完整request逐字段核对独立白名单；336条decision从公开工具能力独立构造一致，无因素标签或未来请求通道。[recount](https://github.com/xxc0304/homecoord-bench/blob/main/homecoord_bench/task_revision/f2_aggregation_v1.py#L67) |
| 真实执行与回执 | 符合设计 | 每次启动核对授权、前提、状态版本、成本及提案；完成匹配task/agent/proposal/target/operation、周期和效果，最终状态与版本一致。[recount](https://github.com/xxc0304/homecoord-bench/blob/main/homecoord_bench/task_revision/f2_aggregation_v1.py#L67) |
| 命令、拒绝与重试 | 符合设计 | 每次启动/拒绝有唯一匹配预约，S≥预约创建+C；重试关联此前拒绝、唯一排队与retry_scheduled；拒绝时实际负载、状态版本正确。[clock_evidence](https://github.com/xxc0304/homecoord-bench/blob/main/homecoord_bench/task_revision/small_validation_execution_v1.py#L70) |
| 容量与观察终点 | 符合设计 | 实际开始至完成半开区间独立积分，无超容量；预约不算实际负载；物理周期均闭合，没有在截止处截断。[recount](https://github.com/xxc0304/homecoord-bench/blob/main/homecoord_bench/task_revision/f2_aggregation_v1.py#L67) |
| 固定分母与自身时钟 | 符合设计 | 逐任务R/P/S/F与下标保存；E=4、early=3、water=1；84行全部字段独立重计一致，时延F−自身R。[recount](https://github.com/xxc0304/homecoord-bench/blob/main/homecoord_bench/task_revision/f2_aggregation_v1.py#L67) |
| 72对与共同K | 符合设计 | 预列身份、白名单、分层固定分母、共同K和各任务值全部独立重算一致；当前K=E，失败/空K规则另由负测试核查。[compare](https://github.com/xxc0304/homecoord-bench/blob/main/homecoord_bench/task_revision/f2_aggregation_v1.py#L306) |
| 结果重现 | 符合设计 | 禁用新模拟器后完整statistics产物复现；先完成独立重计再作作者实现复现，无原result作为统计答案。[statistics](https://github.com/xxc0304/homecoord-bench/blob/main/homecoord_bench/task_revision/small_validation_execution_v1.py#L200) |

0ms同刻证据：`config_19.json` /runs/0（F2-02紧容量、GateRetryRule、command=0），300ms的e3/e6/e9先返回提案，e5/e8/e11预约；e13/e15实际开始，e16因实际负载3加清洁需求2超过容量3拒绝，e17排队。零命令延迟允许同刻开始，不允许在返回或预约之前开始。引擎队列优先级为状态/完成0、发布1、响应3、启动4；同阶段保持插入顺序。全部0ms轨迹的状态版本、实际容量及重试对应通过独立事件核查。

## 逐配置结论

下面每行覆盖三条策略轨迹，均为“符合设计”。简写G=GateRetryRule、C=ConstraintCoordinator、D=DeadlineAwareCoordinator。water事件写作发布/返回/开始/完成的**0起始事件下标**，顺序G、C、D。完整预约/拒绝/重试事件证据与逐任务下标见机器审计的configurations数组；每行绑定文件及/run索引0/1/2，不只用配置级总分判定。

| 文件（配置ID见完整输入） | 配置 ID | G/C/D结论 | water事件下标 G；C；D |
|---|---|---|---|
| [config_00.json](https://github.com/xxc0304/homecoord-bench/blob/main/docs/small_validation_execution_v1_20261005/config_00.json) | `F2R1-D-F2-01-competition-late|SV1|baseline:0` | 符合设计／符合设计／符合设计 | 19/20/34/35；17/18/26/27；17/18/27/28 |
| [config_01.json](https://github.com/xxc0304/homecoord-bench/blob/main/docs/small_validation_execution_v1_20261005/config_01.json) | `F2R1-D-F2-01-competition-late|SV1|water_budget_offset_ms:-30000` | 符合设计／符合设计／符合设计 | 19/20/34/35；17/18/26/27；17/18/27/28 |
| [config_02.json](https://github.com/xxc0304/homecoord-bench/blob/main/docs/small_validation_execution_v1_20261005/config_02.json) | `F2R1-D-F2-01-competition-late|SV1|water_budget_offset_ms:30000` | 符合设计／符合设计／符合设计 | 19/20/34/35；17/18/26/27；17/18/27/28 |
| [config_03.json](https://github.com/xxc0304/homecoord-bench/blob/main/docs/small_validation_execution_v1_20261005/config_03.json) | `F2R1-D-F2-01-competition-late|SV1|water_release_offset_ms:-30000` | 符合设计／符合设计／符合设计 | 19/20/34/35；17/18/26/27；17/18/27/28 |
| [config_04.json](https://github.com/xxc0304/homecoord-bench/blob/main/docs/small_validation_execution_v1_20261005/config_04.json) | `F2R1-D-F2-01-competition-late|SV1|water_release_offset_ms:30000` | 符合设计／符合设计／符合设计 | 19/20/34/35；17/18/26/27；17/18/27/28 |
| [config_05.json](https://github.com/xxc0304/homecoord-bench/blob/main/docs/small_validation_execution_v1_20261005/config_05.json) | `F2R1-D-F2-01-competition-late|SV1|command_latency_ms:0` | 符合设计／符合设计／符合设计 | 19/20/34/35；17/18/26/27；17/18/27/28 |
| [config_06.json](https://github.com/xxc0304/homecoord-bench/blob/main/docs/small_validation_execution_v1_20261005/config_06.json) | `F2R1-D-F2-01-competition-late|SV1|command_latency_ms:500` | 符合设计／符合设计／符合设计 | 19/20/34/35；17/18/26/27；17/18/27/28 |
| [config_07.json](https://github.com/xxc0304/homecoord-bench/blob/main/docs/small_validation_execution_v1_20261005/config_07.json) | `F2R1-D-F2-01-no_competition-late|SV1|baseline:0` | 符合设计／符合设计／符合设计 | 19/20/24/25；19/20/24/25；19/20/24/25 |
| [config_08.json](https://github.com/xxc0304/homecoord-bench/blob/main/docs/small_validation_execution_v1_20261005/config_08.json) | `F2R1-D-F2-01-no_competition-late|SV1|water_budget_offset_ms:-30000` | 符合设计／符合设计／符合设计 | 19/20/24/25；19/20/24/25；19/20/24/25 |
| [config_09.json](https://github.com/xxc0304/homecoord-bench/blob/main/docs/small_validation_execution_v1_20261005/config_09.json) | `F2R1-D-F2-01-no_competition-late|SV1|water_budget_offset_ms:30000` | 符合设计／符合设计／符合设计 | 19/20/24/25；19/20/24/25；19/20/24/25 |
| [config_10.json](https://github.com/xxc0304/homecoord-bench/blob/main/docs/small_validation_execution_v1_20261005/config_10.json) | `F2R1-D-F2-01-no_competition-late|SV1|water_release_offset_ms:-30000` | 符合设计／符合设计／符合设计 | 19/20/24/25；19/20/24/25；19/20/24/25 |
| [config_11.json](https://github.com/xxc0304/homecoord-bench/blob/main/docs/small_validation_execution_v1_20261005/config_11.json) | `F2R1-D-F2-01-no_competition-late|SV1|water_release_offset_ms:30000` | 符合设计／符合设计／符合设计 | 19/20/24/25；19/20/24/25；19/20/24/25 |
| [config_12.json](https://github.com/xxc0304/homecoord-bench/blob/main/docs/small_validation_execution_v1_20261005/config_12.json) | `F2R1-D-F2-01-no_competition-late|SV1|command_latency_ms:0` | 符合设计／符合设计／符合设计 | 19/20/24/25；19/20/24/25；19/20/24/25 |
| [config_13.json](https://github.com/xxc0304/homecoord-bench/blob/main/docs/small_validation_execution_v1_20261005/config_13.json) | `F2R1-D-F2-01-no_competition-late|SV1|command_latency_ms:500` | 符合设计／符合设计／符合设计 | 19/20/24/25；19/20/24/25；19/20/24/25 |
| [config_14.json](https://github.com/xxc0304/homecoord-bench/blob/main/docs/small_validation_execution_v1_20261005/config_14.json) | `F2R1-D-F2-02-competition-late|SV1|baseline:0` | 符合设计／符合设计／符合设计 | 19/20/31/32；17/18/26/28；17/18/26/28 |
| [config_15.json](https://github.com/xxc0304/homecoord-bench/blob/main/docs/small_validation_execution_v1_20261005/config_15.json) | `F2R1-D-F2-02-competition-late|SV1|water_budget_offset_ms:-30000` | 符合设计／符合设计／符合设计 | 19/20/31/32；17/18/26/28；17/18/26/28 |
| [config_16.json](https://github.com/xxc0304/homecoord-bench/blob/main/docs/small_validation_execution_v1_20261005/config_16.json) | `F2R1-D-F2-02-competition-late|SV1|water_budget_offset_ms:30000` | 符合设计／符合设计／符合设计 | 19/20/31/32；17/18/26/28；17/18/26/28 |
| [config_17.json](https://github.com/xxc0304/homecoord-bench/blob/main/docs/small_validation_execution_v1_20261005/config_17.json) | `F2R1-D-F2-02-competition-late|SV1|water_release_offset_ms:-30000` | 符合设计／符合设计／符合设计 | 19/20/31/32；17/18/26/28；17/18/26/28 |
| [config_18.json](https://github.com/xxc0304/homecoord-bench/blob/main/docs/small_validation_execution_v1_20261005/config_18.json) | `F2R1-D-F2-02-competition-late|SV1|water_release_offset_ms:30000` | 符合设计／符合设计／符合设计 | 19/20/31/32；17/18/26/28；17/18/26/28 |
| [config_19.json](https://github.com/xxc0304/homecoord-bench/blob/main/docs/small_validation_execution_v1_20261005/config_19.json) | `F2R1-D-F2-02-competition-late|SV1|command_latency_ms:0` | 符合设计／符合设计／符合设计 | 19/20/31/32；17/18/26/28；17/18/26/28 |
| [config_20.json](https://github.com/xxc0304/homecoord-bench/blob/main/docs/small_validation_execution_v1_20261005/config_20.json) | `F2R1-D-F2-02-competition-late|SV1|command_latency_ms:500` | 符合设计／符合设计／符合设计 | 19/20/31/32；17/18/26/28；17/18/26/28 |
| [config_21.json](https://github.com/xxc0304/homecoord-bench/blob/main/docs/small_validation_execution_v1_20261005/config_21.json) | `F2R1-D-F2-02-no_competition-late|SV1|baseline:0` | 符合设计／符合设计／符合设计 | 19/20/24/27；19/20/24/27；19/20/24/27 |
| [config_22.json](https://github.com/xxc0304/homecoord-bench/blob/main/docs/small_validation_execution_v1_20261005/config_22.json) | `F2R1-D-F2-02-no_competition-late|SV1|water_budget_offset_ms:-30000` | 符合设计／符合设计／符合设计 | 19/20/24/27；19/20/24/27；19/20/24/27 |
| [config_23.json](https://github.com/xxc0304/homecoord-bench/blob/main/docs/small_validation_execution_v1_20261005/config_23.json) | `F2R1-D-F2-02-no_competition-late|SV1|water_budget_offset_ms:30000` | 符合设计／符合设计／符合设计 | 19/20/24/27；19/20/24/27；19/20/24/27 |
| [config_24.json](https://github.com/xxc0304/homecoord-bench/blob/main/docs/small_validation_execution_v1_20261005/config_24.json) | `F2R1-D-F2-02-no_competition-late|SV1|water_release_offset_ms:-30000` | 符合设计／符合设计／符合设计 | 19/20/24/26；19/20/24/26；19/20/24/26 |
| [config_25.json](https://github.com/xxc0304/homecoord-bench/blob/main/docs/small_validation_execution_v1_20261005/config_25.json) | `F2R1-D-F2-02-no_competition-late|SV1|water_release_offset_ms:30000` | 符合设计／符合设计／符合设计 | 19/20/24/27；19/20/24/27；19/20/24/27 |
| [config_26.json](https://github.com/xxc0304/homecoord-bench/blob/main/docs/small_validation_execution_v1_20261005/config_26.json) | `F2R1-D-F2-02-no_competition-late|SV1|command_latency_ms:0` | 符合设计／符合设计／符合设计 | 19/20/24/27；19/20/24/27；19/20/24/27 |
| [config_27.json](https://github.com/xxc0304/homecoord-bench/blob/main/docs/small_validation_execution_v1_20261005/config_27.json) | `F2R1-D-F2-02-no_competition-late|SV1|command_latency_ms:500` | 符合设计／符合设计／符合设计 | 19/20/24/27；19/20/24/27；19/20/24/27 |

## 初步发现能否采用

可采用为本批局部研究发现，措辞已与轨迹对应：

- 84条均完成四服务、超容量为0。紧容量42条中只有2条四服务全部按时；容量足42条全部按时。这是网格清单计数，不是池化成绩、策略排名或独立随机样本。
- 全部24对预算扰动的四任务绝对开始和完成时刻不变。预算放宽可改变期限判定，不应称执行加速。
- 全部12对紧容量发布扰动中，四任务绝对执行时刻不变；water自身响应随R变化反向移动30秒。容量足的12对中，water绝对执行平移30秒、自身响应不变。自身响应改善不等于资源调度改善。
- 全部24对命令扰动按时主率差为0，但真实执行时刻会改变；重试路径可累积命令成本，不能把每份等待都当作单次命令延迟。

F2-02紧容量GateRetryRule的定位例：config_14基线、config_16预算+30000、config_18发布+30000、config_19命令0、config_20命令500，均/runs/0，water发布e19、返回e20、启动e31、完成e32。完成分别420500、420500、420500、420300、421300ms；自身响应分别300500、300500、270500、300300、301300ms；迟到分别500、0、0、300、1300ms。预算或发布修改使期限达标但绝对完成不变；0ms命令仍迟到300ms。

## 验证范围与限制

独立脚本完成2637条检查，零失败；逐事件重建84运行、完整独立重计72对及findings_evidence全部配对字段。新材料manifest与作者保护锁均核对，217项原设计保护材料未变。

实际重跑75项测试通过：新入口22、静态计划9、设计检查8、F2适配器26、F2统计合同10。作者报告的76项中，有一项会新增六次仿真，本次明确跳过；0/500ms合同直接审已保存轨迹。因此本次未调用模型/API、未运行新仿真或保留实验、未改冻结材料、未上传。

当前84条全部完成，空K、未完成分母及缺值拒绝未在本批主轨迹自然出现；这些边界覆盖来自代码审查和负测试，不能称本批已经提供全部失败场景轨迹。同样，保存材料与代码门禁能证明输入/结果一致及预定执行规则，不能独立重建每次生成的真实墙钟执行历史。

本次确认的是已提交新入口和统计正确，以及局部发现的证据边界。后续“未启动预约保留/重排”须另行设计合同及对照，本次不包含该机制消融。未建立双人独立审查，也未回写作者验收标志。

[独立机器审计](docs/review_evidence/2026-10-01_to_2026-10-06/SMALL_VALIDATION_V1_EXECUTION_AUDIT_20261005.json) · [独立复核脚本](docs/review_evidence/2026-10-01_to_2026-10-06/work/audit_small_validation_execution.py)
