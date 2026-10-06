# 延迟窗口试点 v2：限定审查材料

2026-10-06。作者提交，未独立验收。不要求审核者接受创新性或某策略胜利；隐藏策略成绩的设计复审现在只能做事后接受，不能冒称运行前独立设计审查。

## 1. 本批文件与有效入口

- 原设计：`LATENCY_WINDOW_PILOT_V1_PREREG_2026-10-06.md`，运行前原计划/预测 `latency_window_pilot_v1_20261006/plan.json` 与 `author_pre_execution_lock.json`。
- 数量修正：`LATENCY_WINDOW_PILOT_V2_METADATA_CORRECTION_2026-10-06.md`、`plan_v2_metadata.json`、`metadata_correction_lock_v2.json`；后者锁定于轨迹之后，仅审计修正范围，不是新预登记。
- 原失败：`statistics_preflight_failure_v1.json`；原v1入口/测试保留。未改网格、预测、模拟器或44配置。
- 模拟：`homecoord_bench/task_revision/event_simulator_reservation_v1.py`（旧文件未动），新试点执行 `latency_window_pilot_v1.py`，**只使用plan/lock/gate/run/diagnostics入口，v1 statistics已被替代**。
- 汇总：`latency_window_statistics_v2.py`；另路算术 `latency_window_crosscheck_v2.py`。
- 研究判断与结果：`LATENCY_CORE_FEASIBILITY_2026-10-06.md`、`LATENCY_WINDOW_PILOT_V2_RESULT_2026-10-06.md`。
- 数据目录：`docs/latency_window_pilot_v1_20261006/`，4条新基线gate、`config_00.json`–`config_43.json`、`diagnostic_world_01/03/05/07.json`、`statistics.json`、`separate_crosscheck_v2.json`、`verification_record.json`。

## 2. 审查对象及必须核查的内容

| 对象 | 需核查内容 |
| --- | --- |
| 原8世界与44配置 | 2模板×容量×发布时间分层；original={0,100,2001}，near={0,100,1899,1900,1999,2000,2001,3000}；全部slot保留，88正式与24诊断隔离。 |
| near构造 | 只以旧early区间确定R=B-300-2000；预算不变、D随R平移，5处字段同步；不能把跨世界按时变化当纯延迟效应。8世界可行证书仅离线，不泄露给执行者。 |
| 运行前预测 | 旧early前缀、C=R+300+d、100ms命令、全服务区间容量核验；预定剩余EDF中water排第一；未读取新water S/F拟合边界。条件预测不是未知世界泛化/在线最优。 |
| 事件边界 | C=B时phase3审议先于phase4启动，预约可撤销；C>B实际运行不能撤销；d=1900与2000是不同边界；3000延迟点同样保留。 |
| 完整信息与前缀 | 两臂完整调用与提交前快照一致；同世界不同d在审议前相同；water发布前无未来情境标签，24条诊断完整核对。 |
| 执行与回执 | 无off/抢占/模式切换；提交时实际运行区间不变；失效代次旧回调仅suppressed，真实开始/完成匹配；不把计划预约算实际负载。 |
| 服务与时间 | 固定E=4，未完成false/null；逐任务自身R/P/S/F，迟到不变成功；成对K及全部预定槽K；全户需全部E完成。 |
| 两类干预与解释 | replan−retain不同于高d−低d；water延迟、其他任务提前、全户略早须一起保留；容量足/原发布负对照不得删除。 |
| 数量修正 | 正式槽和预测逐项不变，仅40→36组及80→72臂；失败记录原样保留；v2锁不是运行前锁。 |
| 边界与创新 | 44点不是44独立结构，88确定性运行不估P99/显著性；2秒额外审议为合成；没有证明现实自然频率、新理论、LLM胜利或顶会创新。 |

每配置的输入、完整调用、轨迹、真实回执和作者重计在对应config中。`pair.audits[*].tasks[*].event_indices` 定位发布、返回、实际开始和完成；`pair.commit_event_indices`、`running_task_ids`、`unstarted_task_ids` 与 `invalidated_reservations` 定位阶段和代次。独立审核应直接从完整事件重计，而不把prediction当答案。

## 3. 重点索引

| 世界 | config下标 | 审查角色 |
| --- | --- | --- |
| W00：01紧原发布 | 00–02 | 延迟吸收；旧基线完整复现 |
| W01：01紧近启动 | 03–10 | 1.9/2秒边界、laundry代价、479.9秒局部变化 |
| W02：01足原发布 | 11–13 | 两臂一致、直接延迟传递 |
| W03：01足近启动 | 14–21 | 没有预约跳变的匹配负对照 |
| W04：02紧原发布 | 22–24 | 延迟吸收；旧基线完整复现 |
| W05：02紧近启动 | 25–32 | 1.9/2秒边界、cleaning代价、359.9秒局部变化 |
| W06：02足原发布 | 33–35 | 两臂一致、直接延迟传递 |
| W07：02足近启动 | 36–43 | 没有预约跳变的匹配负对照 |

特别看config_08/09（W01，d=2000/2001）与config_30/31（W05，d=2000/2001）。不只看water：高d时另一服务提前、全户早100ms、water从按时变迟到。config_10/32的d=3000帮助确认不是只依赖恰好相邻的1ms点；仍不代表连续实机时钟的测量。

## 4. 可复核检查命令与状态

Python模块路径：在仓库根目录运行。只读汇总/另路重计不产生新模拟；gate/run/diagnostics是新模拟入口，审核无需重跑。

```text
python -m homecoord_bench.task_revision.latency_window_statistics_v2 statistics
python -m homecoord_bench.task_revision.latency_window_crosscheck_v2
python -m unittest homecoord_bench.tests.test_latency_window_pilot_v1.StaticLatencyWindowTests homecoord_bench.tests.test_latency_window_statistics_v2 homecoord_bench.tests.test_f2_reservation_ablation_v1 homecoord_bench.tests.test_f2_reservation_supplemental_v1 homecoord_bench.tests.test_f2_aggregation_v1 homecoord_bench.tests.test_small_validation_execution_v1 -v
```

作者实际执行上述有效99项测试通过；未执行全仓库自动discover，不能说全套通过。原v1 Saved组两项聚合测试绑定已失败/被替代入口，**不在本批有效测试入口中**；文件保留，不能把选择有效版本说成所有版本都通过。旧回归包含额外单元模拟，不计正式研究样本。868旧文件保护哈希一致；同作者另路6301个顶层断言通过，不是独立评审。

当前独立设计接受、实现接受均为null。审查允许否定机制推广或提出新修订，不要求作者解释正结果为创新。独立复审后才决定F1合同和进一步实际相关性验证，不自动扩模型预算/打开保留集。
