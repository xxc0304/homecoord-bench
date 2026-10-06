# C1 v6 实现修正与针对性复审包

状态：作者修正及回归完成，**实现复审待填写，acceptance=null**。用户提交的 v5 单审结论为设计接受、实现须修正；不是独立双审。v5 原代码、输入、结果、manifest 及 Phase A/B 冻结材料不改。

## 本次修正范围

1. v6 显式运行入口将私有实验身份与公开场景身份分开。外层 `evaluation_episode_id` 保留配置索引；执行器及实际 provider 请求仅使用依据设备场景确定的 HC-M02 / HC-M03，不含 condition/budget，也不使用私有 ID 的哈希。请求身份为公开场景、策略及 task_id，在单次隔离回放内唯一；不声称是跨运行共享会话的全局唯一身份。变体/审查状态/任务卡从执行输入副本移除，原配置不变。
2. provider 仅接收实际请求与空 instructions。拒绝具有 `prepare_release_batch` 的 provider，以关闭完整 episode、未来发布时间的旁路。这里不增加新的 provider 能力或自动适配 API。完整 trace 保存的是实际调用输入，不是事后清洗的展示副本。
3. 不再提供混合 `correct_disposition`。由发布时状态计算 `expected_admission`，从实际 `request_admitted` / `request_terminal_rejected` 事件计算 `observed_admission`、`admission_correct`。分别保留 request_status、task_correct_action_completed、task_completion_latency_ms、task_deadline_met。合法准入但无动作：准入正确、unresolved、动作 false、时延 null。迟到完成：准入正确、动作 true、按时 false。

v6 组合冻结 v5 的执行引擎与新的公开身份边界，不复制或修改 v5 评分和执行代码。新 audit 复用 v5 的真实回执、保护积分和终态断言，但丢弃已知混用的旧处置指标。无 C1 功能时 v5/v6 完整返回值保持一致；默认 CLI 未换入口。

## 提交材料

路径均相对仓库根目录：

| 材料 | 路径 | 审查内容 |
| --- | --- | --- |
| 8 个配置及合同 | homecoord_bench/task_revision/fixtures/protection_v6_inputs.json | 两设备 × 两预算 × 两条件；与 v5 的合同和行为不变 |
| 主回放及诊断 | homecoord_bench/results/protection_v6_offline_20261002.json | runs 共32条；diagnostics 共16条；每条包含实际请求、完整事件、结果和作者audit |
| 哈希清单 | homecoord_bench/task_revision/fixtures/protection_v6_manifest.json | 新模块、所复用的冻结模块和两份新数据的哈希；不是对所有传递依赖的完整软件供应链认证 |
| v6 边界实现 | homecoord_bench/task_revision/event_simulator_v6.py | 公开身份构造、元数据移除、hook 拒绝、无功能兼容 |
| 新指标及生成器 | homecoord_bench/task_revision/protection_revision_v6.py | expected/observed admission 独立来源、状态与服务分离、配对输入检查 |
| 冻结执行引擎 | homecoord_bench/task_revision/event_simulator_v5.py | task_release 准入、真实动作开始/完成、结果生成；不得沿用旧正确处置指标 |
| 测试 | homecoord_bench/tests/test_protection_v6.py | 11项新增测试；输入、指标、篡改、兼容、冻结与复现 |
| 空白复审表 | docs/C1_V6_REVIEW_FORM_2026-10-02.md | 逐配置判断与证据位置，记录审查者、独立性及范围 |

定位关键实现可执行 `rg -n 'def run_event_simulation|prepare_release_batch|episode_id' homecoord_bench/task_revision/event_simulator_v6.py` 和 `rg -n 'def audit|expected_admission|observed_admission|def bundle' homecoord_bench/task_revision/protection_revision_v6.py`。冻结 v5 的 task_release / build_agent_request / action_started / action_completed / request_status 仍需核查。

## 必须复审的问题

### A. 信息边界

- 比较每设备、每策略的4种条件：0ms相同可见历史下，**完整实际输入**应相同，不只是 ID 不带关键词。结果中的 full_input_counterfactual_checks 共8组，并带请求摘要哈希；审查者应从原请求重做比较。
- 独立检查所有请求字段，包括 agent、task、constraints、catalog、pending_proposals、模板答案提示。未来事件、低任务到达和预算条件不应提前出现。低请求发布后其自身已知截止时间允许不同，不应强求此时输入相等。
- 检查私有 episode/base ID 被任意更改，以及未来到期/低请求时刻变化但保持初始可见状态时，首个输入仍相同。验证实际 provider 捕获输入与 trace 一致，以及 episode-level hook 确实在调用前拒绝。
- 私有评估标签允许出现在外层记录，但禁止作为决策输入或 provider 旁路。当前测试范围仅这两个 C1 场景，不推及 F2 或其他模块。

### B. 准入与服务分离

- 发布时有效保护应终态拒绝，原请求到期后不复活、不调用 provider、不产生动作完成；动作 false、时延 null 保持。
- 到期后准入应按 request_admitted 事件判定正确，不能要求必须完成动作才能算准入正确。
- 16条诊断：每设备×四策略各提供 admitted_no_action 和 start_precondition_rejected_and_late_completion 两类回放。后者在同一条回放覆盖高请求启动前条件失效与低请求迟到完成，合计覆盖三项边界，不是16个独立任务结构。
- 对 NoAction：低请求 admission_correct=true、unresolved、动作false、时延null、按时false。对 Slow：高请求未完成且时延null；低请求完成但超期，准入仍正确。不同策略可以产生不同等待时间，不能把某策略的7600ms写死为统一期望。
- 删除/重复准入事件应不能通过 audit；重计仍必须以真实事件为证据，而不是只接受作者audit。

### C. 冻结与范围

- 主回放32条的 request_status、动作完成、完成时延、按时、保护失效积分与 v5 一致。数字一致不抹除 v5 输入合同错误，v5 不因此重新获批。
- 复查 v5 三份冻结数据与源码哈希不变。保留旧指标只作为历史缺陷证据，不用于 v6 新结论。
- 本次全部为给答案模板的 FixedProposals/诊断脚本，不是 LLM 试验、模型作弊证据、真实设备实验或新独立双审。先验收本次实现修正，再修订 F2/F3；不自动扩大预算或运行保留测试。

## 作者验证记录（不是验收）

2026-10-02：8配置、32主回放、16诊断回放生成完成；8组完整首请求配对一致；11项新增测试通过，全套420测试通过。主回放核心五类指标与 v5 一致，旧语义14配置×四策略56对无功能 v5/v6 完整返回值一致；v5 bundle 与冻结文件复现一致。新 v6 数据及manifest可复现。未调用 API、未运行保留测试、未上传 GitHub。

复现：在仓库根目录使用可用 Python 运行 `-m unittest homecoord_bench.tests.test_protection_v6 -v`；全套为 `-m unittest discover -s homecoord_bench/tests`。`-m homecoord_bench.task_revision.protection_revision_v6` 只向 stdout 输出确定性数据包，不覆写文件。
