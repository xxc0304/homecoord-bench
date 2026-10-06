# F2统计适配器v1：实现审查提交包（2026-10-04）

## 状态与本轮范围

F2统计合同v1已根据用户提供的合同审查意见显式冻结；本次只提交适配器、作者重算结果、专项测试及保护材料核验。**实现验收仍待审，不能沿用F1、F3或F2原执行轨迹的验收代替本次统计实现审查。**

研究问题仍是智慧家庭多Agent异步调度中的冲突、服务与时延权衡。F2研究晚到请求与已启动不可中断服务的资源背景，不是LLM调用时机，不预设协调器或模型优于规则。没有新模型调用、API调用、新仿真、holdout分析、排名或显著性检验，也未上传GitHub。

本轮固定范围：

- 8个配置、32条主运行；E始终为4，early固定3，water固定1。
- 72对比较：policy 24、strong_rule 16、capacity 16、release 16。
- 8组四单元：容量紧／足 × 同时／晚到。
- 48条诊断对应48对发布前前缀，只核对信息与事件，不重计诊断服务成绩。
- 16份结果文件及另存的author_verification.json；原轨迹与历史pending字段不改。

## 冻结依据

合同审查：
docs/review_evidence/2026-10-01_to_2026-10-06/F2_STATISTICAL_CONTRACT_V1_REVIEW_20261004.md

对应机器审计：
docs/review_evidence/2026-10-01_to_2026-10-06/F2_STATISTICAL_CONTRACT_V1_AUDIT_20261004.json

新增冻结记录：docs/f2_statistical_contract_v1_20261004/freeze_20261004.json  
SHA256：78d627277b11978ef7b69faf836a051f4c3b85ba8d8d998dcf4601ddcf3d748f

记录锁定受审文档、静态计划、原F2材料与相关运行时代码。冻结只接受合同，adapter_acceptance仍为null。冻结前核对了审查报告及锁定哈希；历史文档不追溯重写。

## 提交文件与定位

新实现：homecoord_bench/task_revision/f2_aggregation_v1.py

| 入口（当前行号） | 审查重点 |
| --- | --- |
| recount，67 | 实际调用身份、发布、返回、开始、完成；完整输入及状态重建；固定E及分层 |
| arrival_background，243 | S<L<F真实占用，早期历史与未来预约分开，描述性而非不可避免损失 |
| effects，278；time_compare，286 | 两臂差值、四单元交互、共同K、空K及缺失数据 |
| compare，306 | 预定标量白名单、early／water分层、全户完工资格 |
| prefix_check，348 | 严格timestamp<L的完整调用／决策及执行前缀 |
| macro，358 | 每模板4槽1/4、两模板1/2；缺槽报错不重加权 |
| bundle，373 | 冻结及源文件哈希、身份指针、范围、结果序列化 |

新增测试：homecoord_bench/tests/test_f2_aggregation_v1.py

结果目录：docs/f2_aggregation_v1_20261004/

- 每配置JSON：runs中保留slot_id、source_path、source_pointer；tasks记录R/P/S/F及原trace.events的零基下标。
- pairs_policy.json、pairs_strong_rule.json、pairs_capacity.json、pairs_release.json：明确left/right与效果方向。
- four_cells.json：保留静态slots顺序、共同K、逐任务各臂值与交互项。
- information_diagnostics.json：原调用与事件下标、前缀相等标记及首个差异路径；不是性能成绩。
- summary.json：固定权重服务率与按时服务率；不做排名。
- manifest.json：冻结、实现和15份结果文件的SHA256。
- author_verification.json：77项实际测试、182项保护锁和提交文件哈希；不纳入16份成绩材料的manifest以避免自指。

## 要审核什么

### 1. 身份、完整输入与信息边界

逐个核对静态计划32个主身份、原source_pointer与真实策略，确认没有替换、缺失、重复或诊断混入。
完整输入必须与当前重建状态及同刻已发布请求一致；不要只比request_id或局部字段。
适配器调用已受审且被哈希锁定的f2_information.build_agent_request重建预期输入，**这不是独立编写的输入审计器**。复审请独立核对发布规则及原始输入，不只再次调用同一函数。

诊断只比严格早于各自L的完整request+decision和trace事件；不包括L时刻事件，不比较未来成绩。第一差异路径可定位，但相等结果仍需独立取原始数组重核。

### 2. 真实执行与计分

只能依据匹配的真实action_started/action_completed、完整持续时间及效果计服务；最终状态、旧result/audit、预约、off完成都不能替代服务回执。
重建外源公开请求更新、动作开始状态及完成效果、版本；漏更新或伪造回执应拒绝。

未完成任务保留false/null，主服务分母不缩小。必要排队后按时完成仍成功。零完成时主服务率与按时服务率为0，条件按时率为null。协调/API实际墙钟未测，必须为null；300ms仅为合成逻辑返回偏移。

定点抽查（以下均为原trace.events零基下标，不是跨文件全局编号）：

- F2R1-D-F2-01-competition-late，IndependentMultiAgent，/runs/0：water发布18、返回19，没有开始／完成；完成false，时延null，固定water分母1。
- F2R1-D-F2-02-competition-late，GateRetryRule，/runs/3：water发布19、返回20、开始31、完成32；R=120000、S=180500、F=420500；自身响应时延300500，截止420000，迟到500，不可用绝对F作为响应时延。
- 其余每任务按结果tasks.event_indices回到source_path/source_pointer复核；不要仅检查上面两个示例。

### 3. 晚到背景与非因果限制

early_history列出全部早期服务及开始／完成下标。实际跨越到达时刻的占用仅取prepare且S<L<F；F=L不算继续占用，S=L不算此前承诺。
未来预约独立记录创建时刻、计划开始、计划处置与真实开始下标，不计入L的物理负载。
审查预约处置关联是否唯一、事件下标是否可信、相同proposal的后续尝试是否会混淆；本次合成合同没有取消／重启语义。

不能从晚到、排队或某次预约推出损失不可避免；没有离线最优／regret基线，合同可行性证书也不能替代在线不可避免性证明。

### 4. 配对、共同K、权重

服务率以预定E计算；early和water也固定各自分母。两臂时延用两臂共同完成K；四单元用同一四臂交集，不能用两对交集替代。
每项time_allowlist指标在K上应有真实值；缺值报错，空K效果null并保留覆盖与不合格原因。分层K是固定子集与同一完成交集相交。
全户完工仅在所有臂完成全部E时可比较，注明它是全局排程跨度，不是water自身响应，也不是未来信息价值。
条件按时率、各运行自身完成均值不进入四单元交互或主宏平均。宏平均只含两项主服务率，每模板4配置等权后两模板等权；缺槽报错。

### 5. 原材料保护与复现

独立核验manifest的15份输出哈希，所有16份结果与bundle序列化逐字一致；另检查作者核验记录中的保护锁。
受保护旧文件合并去重后182项核对一致，包括此前164项、合同受审材料、相关原源码和本次冻结。该结论只表示文件一致，不等于独立实现验收。

## 实际验证

最终实际运行77项，全部通过：

```text
python -B -m unittest homecoord_bench.tests.test_f2_aggregation_v1 homecoord_bench.tests.test_f2_statistical_contract_v1 homecoord_bench.tests.test_f1_aggregation_v1 homecoord_bench.tests.test_f1_statistical_contract_v1 homecoord_bench.tests.test_f1_statistical_contract_v2 homecoord_bench.tests.test_f1_findings_20261004 -v
```

26项新适配器测试覆盖：保存内容精确复现、固定范围／权重、忽略旧成绩、未完成water、零完成、预约不算服务、off回执不算服务、必要排队、自身发布时钟与500ms迟到、伪造／缺失回执、伪造终态、漏外源发布、完整输入未来标签、实际占用边界、预约与物理负载分离、空K、四臂交集、K缺值、全户完工资格／白名单、48前缀隔离、完整调用／决策／事件变异、L时刻排除、缺宏槽、冻结哈希失败与读路径范围。其余10项F2合同、41项F1回归通过。

没有重跑全套，没有执行F2仿真测试或生成器。初次试跑曾有缺失TIME_METRICS常量，已修复；保存复现测试也曾因尚未生成结果报缺文件，最终77项已重新运行通过。这些属于作者开发检查，不是独立复审。

## 复审通过条件

独立按原事件重算32条主运行、72对比较和8组四单元；逐条核对48个发布前诊断；复核固定E、各自R、共同K及权重；重复负例并核验源锁与输出哈希。逐配置填写结论、事件下标、代码位置和剩余限制。

在上述复审通过前，结果保持author_result_pending_implementation_review，adapter_acceptance与implementation_acceptance均为null，独立双审未完成。下一步是实现审查，不是补模型试验、重新定义命题或宣称策略优势。

