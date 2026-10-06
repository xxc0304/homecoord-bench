# C4 v10 针对性复审结论

日期：2026-10-03。审查者：本会话 Codex。沿用已接受的 v9 设计合同；本轮只审核清洁失效竞态修正及相关回归，不重开任务设计。

**实现：符合设计；v9 的 F1 阻断项在 v10 显式入口和提交轨迹范围内已解决。** 7 个针对性配置 × 4 策略共 28 条保存轨迹通过；另实际执行原 96 个回归并独立重算，未发现不一致。v9 原四条错误回放保持冻结，仍不得用作有效成绩；通过的是 v10 修正轨迹，不是追认旧结果。

四策略为 IndependentMultiAgent、ConstraintCoordinator、DeadlineAwareCoordinator、GateRetryRule，对应各保存文件 runs[0..3]；下文事件下标均为零基。本次另行编写审计重建时间、状态和尝试有效性，不把作者重计或测试通过当验收判据。单模型复审不是独立双审。

## 原问题如何关闭

[执行器失效标记](https://github.com/xxc0304/homecoord-bench/blob/main/homecoord_bench/task_revision/event_simulator_v10.py#L448)在 3000ms 有效性丧失时立即按 proposal_id 记录旧尝试无效；[自然结束处理](https://github.com/xxc0304/homecoord-bench/blob/main/homecoord_bench/task_revision/event_simulator_v10.py#L1177)在 3400ms 剥离 service 效果，记录 `invalidated_action_physically_completed`；[恢复等待](https://github.com/xxc0304/homecoord-bench/blob/main/homecoord_bench/task_revision/event_simulator_v10.py#L1212)保留可恢复请求，不放入完成集合。4000ms 旧停止确认仍是 `stop_ack_too_late`。5000ms 恢复触发新的 proposal_id，5100ms 真实启动，从零执行 3000ms，8100ms 匹配完成回执才计服务成功。该恢复不增加调用。

| late_race 事件 | 时间 ms | 资格与计分 |
|---|---:|---|
| e12 状态更新 / e13 attempt_invalidated | 3000 | 旧尝试丧失服务资格，与最终物理终止分开。 |
| e15 invalidated_action_physically_completed | 3400 | 物理结束并释放资源，无 service 写入，不关闭请求。 |
| e16 stop_ack_too_late | 4000 | 不冒充实际停止确认。此时完成 false、时延 null、按时 false。 |
| e17 恢复 / e18 restart_proposed | 5000 | 同请求、新尝试身份，不复用旧完成资格。 |
| e22 action_started | 5100 | 新尝试开始，有授权及有效启动前提。 |
| e23 action_completed | 8100 | 唯一有效清洁服务回执；最终完成 true、完成时延 8100、迟到 0、按时 true。 |

最终成功不抹去旧尝试暴露：400ms 实际暴露、200ms 参考窗口内暴露、200ms 额外暴露；停止请求及时、实际静止不及时、stop_confirmed=false。首次启动等待仍 400ms。恢复前前缀和永不恢复配置没有假完成。

[新作者重计](https://github.com/xxc0304/homecoord-bench/blob/main/homecoord_bench/task_revision/c4_audit_v10.py#L78)从状态更新和运行区间重建失效时刻，而不是只信新增事件名称。四条原 v9 错误回放均被拒绝。本审核另外构造 8 条伪造正常完成负例（late_race 与提前恢复两组 × 四策略），同时删除 `attempt_invalidated` 证据标签；作者审计仍以“invalid attempt cannot satisfy service”拒绝，独立重算也检出旧尝试无资格。提前恢复因此不会将旧尝试重新变成有效服务。

## 已填写的针对性复审表

每个配置行覆盖四策略。详细逐策略事件、指标和检查结果见[完整独立审计](docs/review_evidence/2026-10-01_to_2026-10-06/C4_V10_EVENT_AUDIT_20261003.json)；相关代码链接：[失效标记](https://github.com/xxc0304/homecoord-bench/blob/main/homecoord_bench/task_revision/event_simulator_v10.py#L448)、[物理完成](https://github.com/xxc0304/homecoord-bench/blob/main/homecoord_bench/task_revision/event_simulator_v10.py#L1177)、[恢复等待](https://github.com/xxc0304/homecoord-bench/blob/main/homecoord_bench/task_revision/event_simulator_v10.py#L1212)、[重计资格](https://github.com/xxc0304/homecoord-bench/blob/main/homecoord_bench/task_revision/c4_audit_v10.py#L78)。

| 对象 | 实现结论 | 理由 | 缺失证据 | 通过条件 | 定位 |
|---|---|---|---|---|---|
| `late_race` | 符合设计 | 3000ms 资格失效；3400ms 仅物理结束；5000ms 恢复后 5100→8100ms 新尝试完成。完成时延 8100ms，首次等待 400ms；旧尝试暴露 400ms、额外暴露 200ms，迟确认仍不算停止确认。 | 本次提交范围内无阻断性缺失。 | 四策略已满足；仅限对应合成轨迹。 | [保存轨迹](https://github.com/xxc0304/homecoord-bench/blob/main/homecoord_bench/task_revision/fixtures/c4_v10/runs/late_race.json)，runs[0..3]；e9 action_started@400；e13 attempt_invalidated@3000；e15 invalidated_action_physically_completed@3400；e16 stop_ack_too_late@4000；e18 restart_proposed@5000；e22 action_started@5100；e23 action_completed@8100；执行器 448 / 1177 / 1212，重计 78 / 105 |
| `before_recovery` | 符合设计 | 4000ms 前缀中没有恢复；完成 false、时延/迟到 null、按时 false，服务状态 false，请求 pending_validity。不能将此前缀加入统一 10000ms 效果比较。 | 本次提交范围内无阻断性缺失。 | 四策略已满足；仅限对应合成轨迹。 | [保存轨迹](https://github.com/xxc0304/homecoord-bench/blob/main/homecoord_bench/task_revision/fixtures/c4_v10/runs/before_recovery.json)，runs[0..3]；e9 action_started@400；e13 attempt_invalidated@3000；e15 invalidated_action_physically_completed@3400；e16 stop_ack_too_late@4000；执行器 448 / 1177 / 1212，重计 78 / 105 |
| `never_restore` | 符合设计 | 10000ms 终点仍无恢复；物理已结束而请求 pending_validity，服务 false/null/false，未伪造新尝试。 | 本次提交范围内无阻断性缺失。 | 四策略已满足；仅限对应合成轨迹。 | [保存轨迹](https://github.com/xxc0304/homecoord-bench/blob/main/homecoord_bench/task_revision/fixtures/c4_v10/runs/never_restore.json)，runs[0..3]；e9 action_started@400；e13 attempt_invalidated@3000；e15 invalidated_action_physically_completed@3400；e16 stop_ack_too_late@4000；执行器 448 / 1177 / 1212，重计 78 / 105 |
| `restore_before_natural_end` | 符合设计 | 3300ms 恢复不修复旧尝试资格；3400ms 仅物理结束，3500ms 新身份开始，6500ms 完成；4000ms 旧确认不停止新尝试。暴露 300ms，额外 100ms，静止时延 400ms，分别保留。 | 本次提交范围内无阻断性缺失。 | 四策略已满足；仅限对应合成轨迹。 | [保存轨迹](https://github.com/xxc0304/homecoord-bench/blob/main/homecoord_bench/task_revision/fixtures/c4_v10/runs/restore_before_natural_end.json)，runs[0..3]；e9 action_started@400；e13 attempt_invalidated@3000；e16 invalidated_action_physically_completed@3400；e17 restart_proposed@3400；e21 action_started@3500；e22 stop_ack_too_late@4000；e23 action_completed@6500；执行器 448 / 1177 / 1212，重计 78 / 105 |
| `just_before_end` | 符合设计 | 3399ms 失效，即使只剩 1ms 也不计旧尝试服务；恢复后 8100ms 真正完成。实际暴露 1ms、额外 0、静止及时，但 stop_confirmed=false。 | 本次提交范围内无阻断性缺失。 | 四策略已满足；仅限对应合成轨迹。 | [保存轨迹](https://github.com/xxc0304/homecoord-bench/blob/main/homecoord_bench/task_revision/fixtures/c4_v10/runs/just_before_end.json)，runs[0..3]；e9 action_started@400；e13 attempt_invalidated@3399；e15 invalidated_action_physically_completed@3400；e16 stop_ack_too_late@4399；e18 restart_proposed@5000；e22 action_started@5100；e23 action_completed@8100；执行器 448 / 1177 / 1212，重计 78 / 105 |
| `exact_boundary` | 符合设计 | 3400ms 同刻适用右开边界例外；正常有效完成，无失效尝试、停止请求或正时长暴露；无需重启。 | 本次提交范围内无阻断性缺失。 | 四策略已满足；仅限对应合成轨迹。 | [保存轨迹](https://github.com/xxc0304/homecoord-bench/blob/main/homecoord_bench/task_revision/fixtures/c4_v10/runs/exact_boundary.json)，runs[0..3]；e9 action_started@400；e13 action_completed@3400；执行器 448 / 1177 / 1212，重计 78 / 105 |
| `just_after_end` | 符合设计 | 3400ms 已有效完成；3401ms 失效不追溯取消，无停止或重启。 | 本次提交范围内无阻断性缺失。 | 四策略已满足；仅限对应合成轨迹。 | [保存轨迹](https://github.com/xxc0304/homecoord-bench/blob/main/homecoord_bench/task_revision/fixtures/c4_v10/runs/just_after_end.json)，runs[0..3]；e9 action_started@400；e12 action_completed@3400；执行器 448 / 1177 / 1212，重计 78 / 105 |
| 原 96 回归：92 结果一致、4 修正 | 符合设计 | 实际重跑并逐字段比较：92 条结果无变化；原竞态四条的新有效完成时间为 8100ms。独立逐事件审计全部通过。RAIN 永久撤回与物理自然结束、迟确认、取消旧回执保持；8 个 local_only 配对一致。 | 无当前回归范围内阻断性缺失。 | 已满足，不能声称所有事件逐字节不变；CLEAN 新增失效证据事件。 | [保存回归](https://github.com/xxc0304/homecoord-bench/blob/main/homecoord_bench/task_revision/fixtures/c4_v10/regression.json)；独立审计 regressions / details / local_controls；[回归生成](https://github.com/xxc0304/homecoord-bench/blob/main/homecoord_bench/task_revision/c4_revision_v10.py#L52)。 |
| 96 实际输入一致 | 符合设计 | 原回归的完整 calls 结构逐条一致，不仅比较配置名或某个时间数字；逐调用另按发布状态、版本与白名单重建。恢复无额外调用。 | 不涵盖任意新增元数据或未提交路径。 | 当前输入保持性已满足；不扩展为模型公平实验。 | 独立审计 regressions.calls_equal / details；28 条目标的 captures。 |
| 原 v9 四条错误与伪造回执拒绝 | 符合设计 | 原错误四条被拒绝；8 条删标签、伪造服务的负例也被两套重算拒绝，包括 3300ms 提前恢复后。 | 未枚举任意轨迹篡改。 | 当前竞态资格检查已满足；不声称通用防篡改证明。 | 独立审计 old_rejections / forgeries；[作者重计服务资格](https://github.com/xxc0304/homecoord-bench/blob/main/homecoord_bench/task_revision/c4_audit_v10.py#L78)。 |
| v9 冻结与新材料哈希 | 符合设计 | 94 项文件/引用哈希检查无差异；v9 manifest 摘要与此前独立审计留存值相同，再核验其来源和材料。v10 的 10 个 JSON 对象重新生成一致。 | 不等于对仓库每个无关文件的冻结承诺。 | 本轮列入 manifest 的代码和材料已满足；不覆写 v9 原错误。 | 独立审计 hash_checks / bundle_reproduction；[v10 manifest](https://github.com/xxc0304/homecoord-bench/blob/main/homecoord_bench/task_revision/fixtures/c4_v10/manifest.json)。 |

## 验证与结论范围

实际运行 v10 专项 `python -m unittest homecoord_bench.tests.test_c4_v10 -v`，10 项全部通过；本轮未重跑作者声明的全套 476 项。28 条保存轨迹及其作者重计通过实际复现；96 条原回归实际执行后，输入、结果差异及作者重计均与提交 regression 对齐。独立审计共 124 条，覆盖授权/启动前提、状态效果时刻与版本、真实开始/结束、尝试身份、资源占用、实际阶段、停止/暴露、等待、时延、迟到、未完成及 false/null。以上执行均为确定性离线脚本，无模型/API 或保留实验。

审核脚本：[独立轨迹重建与探针](docs/review_evidence/2026-10-01_to_2026-10-06/work/audit_c4_v10.py)；本轮未修改研究仓库、冻结材料或上传 GitHub。before_recovery 只验证截至 4000ms 的资格与计分，不参加统一 10000ms 效果比较。

接受范围仅限现有单请求合成合同、v10 显式执行入口及提交轨迹。没有批准真实家庭物理证据、全部事件阶段、多用户仲裁或多 Agent / LLM 必需的主张。作者重计仍有其他字段依赖执行结果，本轮已用独立重建核验这些提交记录；不是对任意将来材料的普遍保证。无需重开设计，v10 本竞态及相关回归可以结束复审。
