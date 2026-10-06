# F1统计合同v2：四单元任务集合与指标资格修正

2026-10-04。**已修订，待针对性复审，不冻结，不代表适配器验收。** 本文与 `F1_STATISTICAL_CONTRACT_V1_2026-10-04.md` 合读；仅以下规则替代v1第2节四单元的泛化标量授权及第4节族内率的未限定表述。v1原文、计划、审查及哈希保留。其余固定E、服务/回执、冲突分层、时间定义、来源和证据限制不变。

## 1. 固定研究与配对范围

仍为异步多Agent调度中的冲突、过程安全、必要服务与时延，不研究LLM调用时机。8配置、72确定性运行、168对、18四单元及源指针/允许变化不变。没有新模型试验、策略成绩或统计适配器。

v2机器计划 `f1_statistical_contract_v2_20261004/plan.json` 增加 `/metric_rules`，18组四单元均引用该规则，不根据成绩动态选择指标。生成器 `../homecoord_bench/task_revision/f1_statistical_contract_v2.py` 锁定受审v1合同与计划，沿用旧身份生成，新增静态指标资格。

## 2. 四单元的同一任务集合

单元顺序保持 tight_base、tight_loose、adequate_base、adequate_loose。E仍是对应基础模板的全部预定请求；每单元C来自其合格的真实完成回执。不得因拒绝、未启动、未完成、分析资格不足而缩小E。

时延分析集合为 **K=C_tight_base∩C_tight_loose∩C_adequate_base∩C_adequate_loose**。四个单元都使用同一K，按任务等权求时延均值，或逐同一task计算交互。不得用各自C上的均值，也不得用两个不同的两臂交集拼接交互。

对每一时延指标，在K上分别得到四个y后，交互仍为 `(y_adequate_loose-y_tight_loose)-(y_adequate_base-y_tight_base)`。逐任务时延定义不变；task_start_wait是首个合格实际启动等待，execution是匹配完成尝试的执行时间，本范围不扩展多尝试生命周期。

必须输出E身份、每单元C身份、K身份、|K|、|E|、覆盖率|K|/|E|和各未覆盖任务在何单元没有完成（not_completed_in_all_four_cells）。不把“没有完成”自动解释成特定策略失误或不可避免损失。

K为空：时延均值和交互null，原因 `no_common_completed_requests`；保留四单元、E及各臂的主服务比较。K非空但某任务的所需指标缺失：数据错误，不能删除该任务、补0或重新缩小K。缺源/缺单元也属于数据错误，保留预定槽但不将其当普通未完成进入正式成绩。

K只是有条件的机制分析集合，不替代服务评价对象。主服务率仍为|C|/|E|，按时服务率仍为|T|/|E|。即使K很小，主服务差异及覆盖率都必须同时展示，不能宣称同等完整服务下更快。

## 3. 指标资格白名单

此版不再允许任意“非null标量”进入四单元交互。只授权以下指标类别，命名由机器 `/metric_rules/four_cell_allowlist` 固定：

| 类别 | 授权指标 | 分析对象/资格 |
| --- | --- | --- |
| 固定E主率 | service_rate、timely_service_rate | 四单元均使用同一预定E，未完成保留 |
| 运行级过程 | executed_capacity_violation_duration_ms、excess_resource_unit_ms | 本次运行实际执行区间，非完成条件均值 |
| 运行级介入 | coordination_accept/defer/reject_count、action_rejected_count、retry_queued/scheduled_count、reservation_count、actual_start_count | 按事件定义计数，各种事件不能混称执行冲突 |
| 同任务时延 | task_start_wait_ms、execution_ms、completion_latency_ms、tardiness_ms | 四臂相同K上的等任务权重均值，或逐task；空K为null |
| 全户完工 | whole_house_completion_ms | 四臂各自全部E完成才能计算交互；任一臂不满足则null |

全户完工资格不足原因为 `not_all_required_completed_in_four_cells`，不能把K的最后完成时间称作全户完工。各臂运行表仍分别遵循原v1定义，已全部完成的某一臂可保留其单臂完工时间，不因此让四臂交互自动有资格。

未列指标不参与此版交互。条件按时率|T|/|C|和各臂自身completed-only时延均值仅作逐运行辅助量，列身份、分母和覆盖率；它们不能自动用于同任务机制交互。真实API/协调计算耗时仍不可观测，不授权补值或交互。

## 4. 族内主率权重

每策略、每基础模板的12个配置/顺序槽等权，再对2模板等权的规则，**仅用于固定E的service_rate与timely_service_rate**。这两个主率在合法零完成运行中为0，不能改成null；同时保留分层表及分子/分母。缺少输入槽应阻断正式汇总，不能跳过并重归一化权重。

条件按时率仍在C为空时null（no_completed_requests），只逐运行列示，不做12槽宏平均、不默认跳过null，也不参与四单元交互。时延仍不做跨模板总排名。

## 5. 对应审查反例与边界检查

纯合成反例E={a,b}，a时延100ms、b时延1000ms，每个单元中同一任务的时延不变。tight_base只完成a，其余三臂完成a,b：各自C均值100/550/550/550ms相减得到-450ms，不能作为此版合格交互。修正后K={a}，四臂均值均100ms，交互0；各臂服务率仍为1/2、1、1、1，未覆盖b和覆盖率1/2保留。

新增测试同时覆盖：四臂交集为空、两个非空两臂交集互不相同、完成集合不同、全部完成、全部未完成、缺单元、重复/陌生任务、条件率和各自C均值的资格禁止、全户完工资格不得以K替E、v1身份及配对未变。

新增 `analysis_population` 仅对假设输入选择集合与资格，不读取轨迹或计时，不提取实际完成集合，不是服务计分或统计适配器。反例的均值/交互仅在测试中计算，不能解释为已计算策略成绩。

## 6. 本轮交付与下一步

本轮新增合同修正、静态指标元数据、集合资格辅助函数及边界测试，保留全部v1受审材料与既有冻结任务。作者自测不能充当针对性复审或独立双审。

下一步审查本修正及边界证据，重点确认四臂共同K、主服务E、指标资格、null/数据错误边界与主率权重。通过后显式冻结v1基础合同加v2修正和v2机器计划，再实现F1适配器及逐事件重计；不提前开始实现或模型实验。
