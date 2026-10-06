# C1 v5实现审查结论

审核人：本聊天Codex单一审查者。日期：2026-10-02。只审新阅读照明与隐私窗帘，不沿用此前13配置的验收。

**设计：两个场景及legality／equal_response四种用途均接受。实现：8个配置均须修正，原因是实际请求的配置ID和请求ID泄露未来情境标签；作者重计的correct_disposition还混合了准入正确性和服务完成。主回放的执行、终态拒绝与核心动作计分未发现错误。**

## 设计与证据顺序

先读取设计说明、8个完整输入和manifest，登记[C1_V5_DESIGN_REVIEW_20261002.md](C1_V5_DESIGN_REVIEW_20261002.md)，再读取回放、源码与测试。设计接受的是明确合成居民委托、发布时一次性终态拒绝、单保护请求、已有设备状态的确认维护。两个设备共享一种持续保护机制，规则足够，不批准LLM必要性或真实家庭结论。

legality只作合法性对照，剩余时间6800／1500ms不同；equal_response两臂均为自身发布后1500ms预算。拒绝无完成，不能和完成混算时延。

输入SHA-256：`dfc7b9ca310cbcc993a33af4aa2720ec3e63ff6b07ab18847730f92c3dc5bfd3`。

manifest SHA-256：`88a99bca9c8c68a8a8a4267c157e09dc4356c0ccfd429c960ca1ab522759d2c3`。

manifest声明的三个源码及两个产物哈希全部一致。独立逐事件重放32条主回放，未调用作者audit或生产评分函数生成预期值；原合同、版本、状态、真实完成、服务、期限、null及保护损失核对未发现不一致。实际请求输入则存在下述信息合同违例。主回放结果不是模型试验。

## 发现1：未来情境通过ID进入决策输入

严重性：实现须修正。涉及全部32条主回放的48个实际请求，两个ID字段共96处带有情境／配对标签。

实例：`runs[0].trace.agent_requests[0]`，current_time_ms=0，episode_id为`C1R2-LIGHT-legality-CONFLICT`，request_id为`C1R2-LIGHT-legality-CONFLICT:IndependentMultiAgent:reading_light`。对应SAFE组`runs[4]`的同一高请求在0ms获得SAFE标签。此时相反请求尚未在1200／6500ms发布，但标签已经告诉决策者所属未来冲突／安全情境。BLINDS、equal_response及其他策略同样存在。

没有直接传入exogenous_events、完整task_stream或精确6000ms，不足以证明无未来信息。CONFLICT／SAFE是未来情境提示；legality／equal_response还暴露实验分组。确定性脚本忽略这些标签，不能据此断言存在模型作弊或当前数值收益污染，但实际输入不满足声明的观察合同。

代码位置（路径均相对源仓库homecoord-bench）：

- `homecoord_bench/task_revision/protection_revision.py:18`把情境和预算写入episode_id。
- `homecoord_bench/task_revision/event_simulator_v5.py:981`在本版未开启blind_future_task_arrivals时把完整episode_id写入request_id；:976调用请求构造函数。
- `homecoord_bench/runtime/protocol.py:150`及:154在同一条件下向决策者返回完整episode_id。
- `homecoord_bench/tests/test_protection_v5.py:64`只检查没有exogenous_events和字符串6000。实际重跑该测试仍通过，证明其断言无法发现ID提示，不证明观察合同通过。

通过条件：另立修订版本，把评估配置ID保留在审查元数据，决策输入使用不含条件、预算或未来发布时间编码的公开身份和不透明request_id；检查任务文本、约束、工具、所有身份字段及旁路。保护合同当前限制simulation字段，不能只随意启用旧blind_future开关而跳过兼容校验。增加反事实输入对照：相同已发布历史／当前局部状态的两臂，在允许公开信息以外不得产生可解码的情境差异。重建8配置全部32条回放，保留现版本，重新核对行为和评分。

## 发现2：作者重计把正确准入与完成混为一项

严重性：作者重计须修正；32条主回放恰好没有暴露此分支，不宣称主回放完成数错误。

代码`homecoord_bench/task_revision/protection_revision.py:61`在发布时保护无效时，把expected固定成completed；:84用最终statuses与expected相等计算correct_disposition。因此正常准入但未完成的请求会被判“处置错误”，而设计中该指标是依据发布状态判断合法准入或终态拒绝，动作完成另计。

审核人另生成的`LIGHT_admitted_no_action`、`BLINDS_admitted_no_action`边界：ConstraintCoordinator；保护6000ms到期；events[7]在6500ms合法request_admitted；events[10]在6800ms脚本返回无动作。生产result正确保留request_status=unresolved、动作完成false、完成时延null；作者audit.correct_disposition却为false。应保持准入正确=true，服务完成=false，未解决请求单列。若作者本意是端到端成功，应另命名指标并补独立准入正确性，不能沿用目前定义。

通过条件：基于发布时状态和实际request_admitted／request_terminal_rejected计算准入处置，独立保留请求终态、真实动作服务及期限。至少补合法准入但无动作、启动前提拒绝、完成迟到三个分支；重计不得把未完成改为服务成功。

## 逐配置实现审查表

原回放：`homecoord_bench/results/protection_v5_offline_20261002.json`。runs与events、agent_requests均为零基数组下标；源码行号为一基。每配置覆盖4策略：IndependentMultiAgent、ConstraintCoordinator、DeadlineAwareCoordinator、GateRetryRule，按此顺序排列。下列事件例示用首个策略，其余三条同样核查。

| 配置 | runs范围／代表策略 | 实现结论 | 对应事件、输入及代码位置 |
|---|---|---|---|
| C1R2-LIGHT-legality-CONFLICT | 0–3／IndependentMultiAgent | 须修正 | runs[0] agent_requests[0]两ID含CONFLICT；events[7]1200ms终拒，[8]6000ms到期后无旧请求动作；v5:954、:981；revision:18 |
| C1R2-LIGHT-legality-SAFE | 4–7／IndependentMultiAgent | 须修正 | runs[4] agent_requests[0]在0ms两ID含SAFE；events[6]6000ms到期，[7]6500ms准入，[12]6900ms启动，[13]7400ms完成；v5:968、:981、:1392 |
| C1R2-LIGHT-equal_response-CONFLICT | 8–11／IndependentMultiAgent | 须修正 | runs[8] agent_requests[0]含equal_response-CONFLICT；events[7]1200ms终拒；截止2700ms，完成false／null；v5:954、:981；revision:18 |
| C1R2-LIGHT-equal_response-SAFE | 12–15／IndependentMultiAgent | 须修正 | runs[12] agent_requests[0]含equal_response-SAFE；events[7]6500ms准入，[12]6900ms启动，[13]7400ms完成；自身时延900ms；v5:968、:981 |
| C1R2-BLINDS-legality-CONFLICT | 16–19／IndependentMultiAgent | 须修正 | runs[16] agent_requests[0]两ID含CONFLICT；events[7]1200ms终拒，[8]6000ms到期仍closed；v5:954、:981；revision:18 |
| C1R2-BLINDS-legality-SAFE | 20–23／IndependentMultiAgent | 须修正 | runs[20] agent_requests[0]在0ms两ID含SAFE；events[7]6500ms准入，[12]6900ms启动，[13]7400ms开帘完成；v5:968、:981 |
| C1R2-BLINDS-equal_response-CONFLICT | 24–27／IndependentMultiAgent | 须修正 | runs[24] agent_requests[0]含equal_response-CONFLICT；events[7]1200ms终拒；截止2700ms，完成false／null；v5:954、:981 |
| C1R2-BLINDS-equal_response-SAFE | 28–31／IndependentMultiAgent | 须修正 | runs[28] agent_requests[0]含equal_response-SAFE；events[7]6500ms准入，[12]6900ms启动，[13]7400ms完成；v5:968、:981 |

表中须修正针对实际输入合同，不能以执行正确抵消。四种场景×用途的设计接受意见维持不变；修正的是实现和作者重计。

## 主回放已符合的执行及评分部分

1. 高请求均0ms发布、400ms启动、900ms匹配完成；初态已安全，不把900ms回执解释为创造真实照度或隐私。开始效果为空，最终效果仅在完成应用。主体、设备、工具、前提和状态版本一致。
2. 所有CONFLICT低请求在1200ms发布处终拒：task_released的request_id=null，随即request_terminal_rejected；无该身份的脚本请求、提案、预约、启动、完成或重试，也没有低请求model_latency字段。6000ms到期后原请求仍终拒。
3. 所有SAFE低请求在6500ms观察到保护false后准入，6800ms提案返回，6900ms启动，7400ms完成；按自身发布时延900ms、等待400ms、迟到0。legality与equal_response的解释分开。
4. 所有CONFLICT低动作完成false，等待／时延／迟到null，动作服务率1/2，low的task_deadline_met=false、all_deadlines_met=false。作者正确处置可以true，但未被改写成动作服务率或按时率100%。
5. 全部32条保护有效区间内设备状态无失效，独立按全过程重算为0。最终状态不是唯一依据。当前输入只有到期外源变更，主回放未直接覆盖“先失效后恢复”的篡改轨迹，不能声称已提交该边界证明。

代码依据：`protection_contract.py:6`校验委托及合同一致性；`event_simulator_v5.py:578`严格工具校验，:1086启动时复查，:1232真实完成，:1365合并真实逐任务指标，:1392登记终态；`runtime/task_response_metrics.py:5`、:15及:23定义匹配开始／完成、自身发布时延、迟到及null。v5当前在无生命周期／DAG时仍保留旧服务投影字段；本32条真实启动均有完整完成，因此与真实计数一致，不将此事实扩展到截断动作。

## 边界证据范围

未把测试存在当作轨迹通过。另用明确确定性脚本、仅ConstraintCoordinator，生成并保存10条补充回放及8项执行前拒绝诊断，共18条边界记录，见[C1_V5_REVIEWER_BOUNDARIES_20261002.json](C1_V5_REVIEWER_BOUNDARIES_20261002.json)。它们是审核人本轮生成，输入变体仅保存在本聊天输出，未改作者冻结输入；不与主32条混算。

| 边界 | 本次证据与判断 |
|---|---|
| 新请求身份 | 两场景旧请求终拒，新task_id在6500ms独立准入完成；旧身份未获得新回执 |
| 到期与发布同刻 | 两场景events[6]6000ms先更新保护false，[7]同刻准入；6400启动、6900完成。队列相位v5:85规定更新先于发布 |
| 慢提案CONFLICT | 7000ms脚本延迟未改变发布处终拒；低请求仍未调用，高请求在到期后启动因前提失效被拒绝 |
| 慢提案SAFE | 低请求13600ms启动、14100ms完成，时延7600、迟到6100ms，按时false；高请求未完成保留null，启动前提仍执行 |
| 准入但无动作 | 两场景生产未完成计分正确；作者correct_disposition出现发现2 |
| 缺委托／重复task_id／非布尔初态／policy不一致 | 两场景均执行前ValueError；保存错误与输入，不伪称有正常执行轨迹 |
| 篡改终态或动作完成 | 实际重跑作者对应负测试通过；仍属于负测试，未冒充正常主回放 |

另外实跑了作者“无到期／未来事件”测试，它通过但漏检发现1。没有重跑全部409项测试、其他任务族或模型；补充边界不覆盖全部4策略、不验证所有可能状态更新。

## 最终处置及通过条件

设计接受；实现整体须修正。修复ID信息通道和作者准入指标后，另立版本重交8输入与32条回放，附不含条件提示的实际完整请求，并补准入未完成的评分负例。不得用现32条正确动作评分宣布完整信息合同通过，也不得把单审登记成独立双审。

本轮未修改源代码、原输入、原结果、作者manifest或默认执行入口；没有API／模型调用。结论只覆盖单保护请求、合成设备状态与上述已提交／另生成证据，不覆盖真实家庭、多用户或其他任务族。
