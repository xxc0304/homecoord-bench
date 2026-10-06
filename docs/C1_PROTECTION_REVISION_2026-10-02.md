# C1首批设计修订：保护授权与请求终态

2026-10-02。作者修订草稿，待修改项Phase A复审；原任务、旧Phase A/B包及成绩未改。本页先给设计合同，不以运行成绩决定接受与否。

## 本次明确的选择

选择“发布时决定准入、保护有效则终态拒绝”，不采用等待保护到期再执行的合同。这个选择是版本化的合成用户政策，不声称是所有真实用户的偏好。

合成居民SyntheticResident明确委托可信执行器：阅读／隐私保护布尔值有效时，维护当前受保护设备状态；相反的本次请求若在发布时遭保护阻止，即被关闭。用户若稍后仍需要关灯／开帘，必须发出一个新的task_id。保护到期只解除保护，不复活已关闭请求，也不自动产生新动作。

数值priority不再被当作委托依据；新增`user_delegations`载明principal、目标、保护状态、限域和终态语义。`simulation.request_disposition_contracts`和低请求的`request_contract`使用同一policy_id和admit_when。缺委托、不一致合同、隐藏保护状态或非布尔初态被拒绝。

## 状态机与计分合同

| 发布时状态 | 请求状态演变 | 动作服务与时间 |
|---|---|---|
| protection=true | 发布→rejected_terminal，不调用该低请求的脚本、不排队 | 动作完成false，完成时延null；合理拒绝另计正确处置。 |
| protection=false | 发布→准入→真实动作完成；未完成则unresolved | 只有匹配真实完成才算服务，按自身发布时间计算时延。 |
| 原请求已rejected_terminal，后来保护到期 | 保持rejected_terminal | 不重试，不补回执，不产生原请求完成。 |
| 到期后另有新请求身份 | 对新请求独立准入 | 可以正常完成，不把它记在旧请求名下。 |

准入由共同可信底座完成，是用户授权政策，不是Agent推理收益。终态拒绝事件为`request_terminal_rejected`，不是把没有提出的动作伪造为`action_rejected`。被拒绝请求没有模型耗时字段条目，不能当零耗时LLM调用；全组均无真实API。

保留旧动作完成、按时和服务指标，新增request_status区分请求处置。保护阶段全区间状态检查仍保留；最终设备安全不抹掉过程失效。合理拒绝不算动作完成，也不把全部动作按时率改写成100%。

## 场景与权限

| 场景 | 高请求／低请求主体 | 共享关键状态 | 可写设备与低请求操作 |
|---|---|---|---|
| 阅读照明 | ReadingAgent／EnergyAgent | study.reading_active、devices.study_light | devices.study_light；off |
| 隐私窗帘 | PrivacyAgent／DaylightAgent | bedroom.privacy_required、devices.bedroom_blinds | devices.bedroom_blinds；open |

两主体都可见保护布尔值和目标设备；其他角色状态保持源合同（如occupied、daylight_requested），不声称所有观察字段完全相同。工具严格限定本人签名、目标和操作；完整参数、权限及局部policy_constraints见新输入。

观察合同只公开当前有效性，不公开expires_at、未来事件或完整task_stream。目标和约束按local视图给出，不给评分全局目标作为模型信息。委托表为审查者/可信底座授权合同，低任务文本及request_contract明确终态政策。工具参数中的lux是旧合成设备操作参数，不能据此声称实测500lx。

两设备仍共享一种“持续保护”机制，不能把本次8配置计成8结构或新增两个机制。仅单保护请求，没有多个使用者／撤销仲裁，不能据此认为现实到期后总应关灯／开帘。

## 参数及配对

初态已为reading／closed；高请求0ms发布、1100ms截止。保护在世界时钟6000ms到期，决策者只观察当前有效性。服务周期500ms、命令延迟100ms、脚本提案300ms，全部作者合同，不是实机测量。容量非约束，不测C3。

每场景两个配对组，共8输入：

| 用途 | 有效期内请求：发布／截止ms | 到期后请求：发布／截止ms | 可比较什么 |
|---|---|---|---|
| legality | 1200／8000 | 6500／8000 | 保留原有效/到期合法性因素；剩余时限6800/1500不同，不用于等预算时延比较。 |
| equal_response | 1200／2700 | 6500／8000 | 两个低请求都给自身发布后1500ms动作预算；发布时间和绝对截止联动。 |

equal_response不意味着两臂都必须执行，也不能把拒绝的null完成时间当作更快完成。它消除服务预算混杂，仍需按完成／拒绝分别报告，不对两个不同处置强行做完成时延平均。

与旧源相比：新增委托与request_contract、发布时终态准入、任务/工具文字澄清、local目标/约束视图、版本/预算用途元数据；equal_response另改变冲突臂截止。旧保护世界时刻、设备状态和动作周期不改。完整旧输入仍在原目录，不能把新版本结果回填旧记录。

## 新文件与入口

- [8个新输入](../homecoord_bench/task_revision/fixtures/protection_v5_inputs.json)：C1R2-LIGHT/BLINDS × legality/equal_response × CONFLICT/SAFE。
- [源码和产物哈希](../homecoord_bench/task_revision/fixtures/protection_v5_manifest.json)。
- `task_revision.event_simulator_v5`从冻结v3派生，只在显式终态合同开启时增加准入。不是v4环境接口的升级，不替换默认CLI，不修改v1-v4。
- 支持四个普通执行策略和共享安全门；本合同不与环境、生命周期、DAG或compute/批计划同时启用。

## 交给审查者确认的修改项

1. 是否接受显式合成用户委托与“一次性发布时终态拒绝”的限域选择？
2. 是否认可低请求不调用脚本是共同可信准入而非模型能力，不把它拿来声称模型低时延？
3. 是否认可legality与equal_response用途、联动字段以及拒绝/服务分开计分？
4. 是否明确当前有效性可见、到期时刻不可见，以及单保护请求/设备状态的限制？

修改项尚未获得复审接受，不沿用旧13配置Phase B结论。本次作者离线验证另见[验证记录](C1_PROTECTION_VERIFICATION_2026-10-02.md)；做Phase A时可以先不打开。
