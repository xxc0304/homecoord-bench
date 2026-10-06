# F2预约机制 v1：新实验限定复审入口

状态：作者实现/运行/统计/另算法交叉核对已完成，独立设计及实现接受均为空。仅审本次新增范围，不将旧v7接受自动转移到新入口，不把作者自检称为独立复审。

## 一、需要阅读的合同及边界

[运行前合同](docs/F2_RESERVATION_ABLATION_V1_PREREG_2026-10-05.md)与[静态计划](docs/f2_reservation_ablation_v1_20261005/plan.json)。固定16条主/敏感性运行、8对，24条信息诊断；不是40条性能样本。参数及代价0/100ms在运行前锁定。更早的v1/v2锁记录审计器预检查失败；当前执行锁是revision3，旧文件不得删除或覆盖。

核查干预是否仅为未启动预约重排，是否固定公开信息、到达/截止、实际执行能力、提议、排程器及命令成本；两臂共同100ms敏感性不能代替实测开销。条件物理界限明确是事后补充解释，不是预登记主指标或在线最优。

## 二、代码位置及必须检查的语义

- [新引擎约束](homecoord_bench/task_revision/event_simulator_reservation_v1.py#L267)：只支持同一DeadlineAwareCoordinator；复用F2公开输入白名单。
- [提交审议/失效未启动预约](homecoord_bench/task_revision/event_simulator_reservation_v1.py#L614)：按实际in_flight裁决；包括计划S等于当前时刻但phase4未实际开始者。运行中的服务不撤销、不改回执、不off。
- [审议延迟完成](homecoord_bench/task_revision/event_simulator_reservation_v1.py#L927)：延迟期间环境继续前进，提交时重新裁决哪些作业已启动。
- [旧回调代次抑制](homecoord_bench/task_revision/event_simulator_reservation_v1.py#L977)：同一proposal可重预约，但旧代次不能启动、修改设备或计完成。
- [完整事件审计](homecoord_bench/task_revision/f2_reservation_ablation_v1.py#L136)：匹配原始公开输入、状态更新、预约/代次/真实回执。前置条件只允许忽略协议null范围字段，不能忽略有效语义条件。
- [两臂前缀及固定E/K统计](homecoord_bench/task_revision/f2_reservation_ablation_v1.py#L313)：比较完整调用和提交快照前缀；逐任务未完成保持null；全户有全E完成资格。
- [4条历史基线完整复现](homecoord_bench/task_revision/f2_reservation_ablation_v1.py#L351)：投影仅去新观察事件/代次字段及两项私有外层身份，不能递归删除差异字段。
- [原始事件另算法](homecoord_bench/task_revision/f2_reservation_crosscheck_v1.py#L25)：同作者重算，不是另一审阅者接受。

## 三、逐配置必审索引

事件下标均为原始完整trace.events的0基下标。每个config文件内runs[0]=retain，runs[1]=replan；pair/audits还列出每任务R/P/S/F及回执下标。下表不得依据策略成绩删除配置。

|配置|模板/容量/审议延迟|完整轨迹|提交快照下标 retain/replan|重排失效对象|water开始/完成下标 retain → replan|
|---|---|---|---|---|---|
|RA1-00|D-F2-01/competition/0ms|[config_00.json](docs/f2_reservation_ablation_v1_20261005/config_00.json)|20/20 |laundry|29/30 → 29/31|
|RA1-01|D-F2-01/competition/100ms|[config_01.json](docs/f2_reservation_ablation_v1_20261005/config_01.json)|20/20 |laundry|29/30 → 29/31|
|RA1-02|D-F2-01/no_competition/0ms|[config_02.json](docs/f2_reservation_ablation_v1_20261005/config_02.json)|22/22 |无|26/27 → 26/27|
|RA1-03|D-F2-01/no_competition/100ms|[config_03.json](docs/f2_reservation_ablation_v1_20261005/config_03.json)|22/22 |无|26/27 → 26/27|
|RA1-04|D-F2-02/competition/0ms|[config_04.json](docs/f2_reservation_ablation_v1_20261005/config_04.json)|20/20 |cleaning|28/30 → 29/30|
|RA1-05|D-F2-02/competition/100ms|[config_05.json](docs/f2_reservation_ablation_v1_20261005/config_05.json)|20/20 |cleaning|28/30 → 29/30|
|RA1-06|D-F2-02/no_competition/0ms|[config_06.json](docs/f2_reservation_ablation_v1_20261005/config_06.json)|22/22 |无|26/29 → 26/29|
|RA1-07|D-F2-02/no_competition/100ms|[config_07.json](docs/f2_reservation_ablation_v1_20261005/config_07.json)|22/22 |无|26/29 → 26/29|

逐条核查：晚到需求没有提前参与；原预约确实尚未启动；被撤销的是预约代次而非执行尝试；同刻旧回调被抑制；新代次只有一次真实开始和完成；被延后early仍按固定身份保留；迟到仍false、不能以平均响应改善替代按时率改善。

主紧容量01：replan失效laundry事件21、旧回调抑制27，新water开始29/完成31，新laundry开始33/完成34。
主紧容量02：replan失效cleaning事件21、旧回调抑制27，新water开始29/完成30，新cleaning开始32/完成34。
足容量两模板无未启动预约，本批两臂在所有真实执行指标上相同；保留负结果，不要求制造失效对象。

## 四、诊断、边界与计分检查

[statistics.json](docs/f2_reservation_ablation_v1_20261005/statistics.json)列出24条信息诊断身份；diagnostic_00至03.json各6条，覆盖两臂×3类未来变更，按原始water发布时刻严格“<截止”比较完整输入及事件。诊断不进入E服务分母，也不当作24个独立家庭。

[新测试](homecoord_bench/tests/test_f2_reservation_ablation_v1.py)与[补充正确性探针](homecoord_bench/tests/test_f2_reservation_supplemental_v1.py)。补充探针是合成正确性测试，不是新性能配置：旧回调晚于新完成应仍不改变终态；干预同刻开始按phase3/4处理；审议期间已开始者不能撤回。无动作应0完成/0按时、条件按时率null；伪回执、非null范围条件/语义前置条件变化须被拒绝。

核查固定E=4、early=3、water=1，各臂真实完成K及覆盖；失败不删分母、不因成绩调整参数。均值响应、逐任务响应、全户完工、按时率分别解释。实际资源占用从开始/完成积分，预约不能算当前负载。

## 五、通过条件及禁止扩展

1. 合同与静态范围接受；完整输入/前缀与物理能力固定，无未来泄露。
2. 全16条新轨迹的代次、回执及计分符合新合同；24条诊断身份/前缀核对完整。
3. 当前revision3锁、所有源保护哈希与新产物绑定一致；4条retain复现门没有掩盖差异；两份前检查失败及旧锁保留。
4. 成对差值、完整K、未完成/迟到、0/100ms和容量负对照不被选择性解释。
5. 结论限于同一调度器、两个开发模板、合成时钟。不能接受“已证明重排全面更优”“损失全局不可避免”“创新已成立”“真实家庭/LLM性能提升”。

审阅者请逐配置写结论、理由、缺失证据、通过条件，并定位事件及代码；现有作者自检不能代填独立接受。未提交真实部署成本、新任务结构或模型重复实验，本批不验收这些内容。
