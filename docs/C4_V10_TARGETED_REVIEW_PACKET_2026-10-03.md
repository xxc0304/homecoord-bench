# C4 v10 清洁失效竞态：针对性复审包

2026-10-03。依据用户提交的 C4_V9_REVIEW_20261003.md，沿用已接受的v9设计，不重开设计、不代填实现通过。v9的56主及36诊断获限定单模型复审符合设计；CLEAN-LATE-late_natural_race四策略原结果错误、不得作有效成绩。原源码、28JSON与哈希保持原样，修正另立v10；未完成独立双审。

## 修正与证据

- event_simulator_v10.py:448：失效事件立即写attempt_invalidated，按proposal_id保存尝试失效时刻，而不是等停止确认。自然结束同刻的右开边界例外不变。
- event_simulator_v10.py:1177：失效尝试自然结束剥离service效果，发invalidated_action_physically_completed；物理状态、结束时间、资源释放照实保留。
- event_simulator_v10.py:1212：可恢复请求不加入completed集合，而加入恢复等待；恢复后新proposal_id从零执行，旧停止确认不能停止新尝试。
- c4_audit_v10.py:78：从状态事件、运行区间与proposal_id独立重建失效onsets；曾失效尝试不能计action_completed，即使环境已恢复也不能恢复旧尝试资格。不是只依赖新增事件名称。新审计可拒绝原v9四条错误回放和伪造正常完成。
- 新模块沿用已冻结v9信息、权限和合成参数合同；显式v10运行入口，不替换默认或旧入口，不改变通用evaluate/协议。

| 时间 | 修正轨迹的含义 |
|---|---|
| 3000ms | occupancy=true，旧尝试即时失效，停止请求仍及时 |
| 3400ms | 旧尝试自然物理结束，service仍false，不计请求完成 |
| 4000ms | 旧尝试stop_ack_too_late，不冒充停止确认；截至恢复前false/null/false |
| 5000ms | 恢复有效，产生新尝试 |
| 5100ms | 新尝试开始，从零执行 |
| 8100ms | 新有效尝试真实完成；此时才能完成请求，时延8100ms |

原轨迹未重新执行，因此按合同应false/null/false；修正后的整条轨迹新增了有效恢复尝试，所以最终可以true/8100/true。这不是把错误四条仅改分数，而是修正执行过程。

物理事实仍为旧尝试失效后暴露400ms、参考窗口200ms、额外200ms，stop_confirmed=false、quiescence_timely=false、request_timely=true；不能用恢复成功抹去这些记录。首次启动等待仍400ms。新恢复不增加模型调用。

## 提交材料

homecoord_bench/task_revision/fixtures/c4_v10/：10JSON，inputs、7个runs文件、regression、manifest。每个目标配置保存四策略完整调用、事件、result及audit，共28条；另外重新执行全部原96回放，regression保存逐条完整作者重计及结果差异字段。

7个配置：late_race（四条修正轨迹）、before_recovery（截至4000ms的前缀，未恢复且未完成）、never_restore（统一10000ms无恢复）、restore_before_natural_end（3300ms恢复，旧尝试仍不能重新有效）、just_before_end（3399ms失效）、exact_boundary（3400ms同刻）、just_after_end（3401ms失效）。前缀诊断不改变服务期限，不加入统一10000ms效果比较分母。

恢复早于自然结束的诊断：旧失效尝试3400ms物理结束，3500ms新尝试启动、6500ms完成；4000ms旧停止确认不得影响新尝试。仍明确从零重做，无进度保留结论。

原96回放的实际捕获输入完全一致；未受影响的92条结果逐字段一致，包括RAIN永久撤回与自然结束竞态、迟确认、旧回执、local_only。CLEAN正常停止轨迹会新增attempt_invalidated证据事件，不能宣称所有旧轨迹逐字节相等。四条修正结果变化及衍生汇总全保存在regression。v9冻结源码与28材料哈希逐项锁定，旧错误不覆写。

## 测试与运行

新增10测试，重点覆盖四策略失效自然结束、恢复前false/null/false、无恢复、提前恢复不修复旧资格、边界前/同刻/后、暴露不被抹去、旧确认不影响新尝试、审计拒绝旧v9错误和伪造事件、92结果/96输入一致与材料复现。

专项：python -m unittest homecoord_bench.tests.test_c4_v10 -q。
全套：python -m unittest discover -s homecoord_bench/tests -q。
生成材料列表：python -m homecoord_bench.task_revision.c4_revision_v10；附路径参数打印序列化文本，不自行写文件。

作者自检不代替复审。无模型/API/保留集实验，无上传。下一步仅针对本竞态与相关回归复审，填写[空白复审表](C4_V10_TARGETED_REVIEW_FORM_2026-10-03.md)，通过前不推进依赖/C2。

实际运行结果：10项v10专项全部通过，全套476项通过；旧v9的17项及冻结复现仍通过，但旧四条语义错误仅作为负例保留。差异字段排序已固定，跨进程序列化复现通过。

## 通过条件

逐策略核对旧失效attempt ID、3000ms资格丧失、3400ms实际结束无service写入、恢复前未完成、新attempt的真实完成及资源释放；独立重算不能相信错误回执名称。确认同刻边界与提前失效区别、提前恢复不复活旧资格、晚确认不影响新尝试，且RAIN、local_only、其他92结果及冻结哈希保持。结论仅限提交合成合同、显式入口与轨迹；不证明实际硬件、所有事件阶段或多Agent/LLM必需。
