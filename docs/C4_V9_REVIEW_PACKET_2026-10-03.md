# C4 v9 实现审查包

2026-10-03。作者实现与自检记录，不是验收意见，不是独立双审。请先提交[设计卡](C4_STAGE_RESPONSE_V9_2026-10-03.md)审查结论，再阅读轨迹。空白[逐配置审查表](C4_V9_REVIEW_FORM_2026-10-03.md)需填写结论、理由、缺失证据、通过条件和可定位证据。

## 材料与入口

- 新数据目录：homecoord_bench/task_revision/fixtures/c4_v9/
- inputs.json：14主配置；diagnostic_inputs.json：10诊断。
- runs/：每配置四策略，56条；diagnostics/：每配置四策略，40条。
- 各条保存policy、trace（含完整agent_requests与事件）、result、实际provider捕获calls、独立audit。
- index.json：文件列表、8项local-only匹配控制；manifest.json：全部材料哈希及新旧源码锁。acceptance=null。
- 生成：python -m homecoord_bench.task_revision.c4_revision_v9，打印材料列表；加路径参数打印该材料的JSON序列化文本，不自动写文件。
- 专项：python -m unittest homecoord_bench.tests.test_c4_v9 -q。
- 全套：python -m unittest discover -s homecoord_bench/tests -q。

## 定位代码与核查内容

| 文件 | 搜索符号／关键字 | 审查内容 |
|---|---|---|
| task_revision/c4_contract_v9.py | validate_v9 / build_agent_request | 版本、权限、响应规则、无答案和条件身份、实际输入 |
| task_revision/c4_revision_v9.py | episode / PublicC4 / diagnostic_inputs / bundle | 参数、固定世界时刻、公开脚本、配对公平性、采样范围 |
| task_revision/event_simulator_v9.py | stop_requested / completion_discarded / withdrawn_completion | 真实动作、停止确认、旧尝试取消、撤回物理结束不写服务 |
| task_revision/c4_lifecycle_contract_v9.py | validate_contracts | 原严格生命周期字段；显式单主体对照例外，不放宽其他错误 |
| task_revision/c4_evaluate_v9.py | shape_errors | 显式local-only形状例外；不改变旧evaluate |
| task_revision/c4_audit_v9.py | phases / onsets / service_recount / response_records | 独立逐事件阶段、实际状态、资源区间、暴露和终态重算 |
| tests/test_c4_v9.py | C4V9Tests | 17项回归、篡改拒绝、旧v2冻结与新材料复现 |

v9复制旧引擎另立入口，仅新builder/校验、单主体对照和撤回竞态语义生效；冻结v2及旧运行器不修改。复制的校验/evaluate只针对显式单主体例外，不意味着全项目允许单主体benchmark。源码行号可随未冻结文档变动，请用符号+回放事件下标记录结论。

## 作者自检观测（需审查者重算）

默认MID在400ms启动，1800ms失效、2000ms停止，暴露200ms；请求及时、静止及时，但非零危害。700ms确认诊断，暴露700ms、额外500ms；请求及时而静止超容限。RAIN晚期1000ms确认诊断在3000ms撤回、3400ms自然结束，实际暴露400ms、额外200ms；主请求仍未完成，工作回执false，停止确认过晚。

CLEAN恢复的新尝试于5100ms开始、8100ms完成；3400ms旧完成回执丢弃。未恢复诊断保持pending_validity。RAIN于5000ms雨停后原请求不复活；5500ms新请求可于8900ms完成，旧请求仍false/null。自然完成边界仅默认时延场景；实际阶段不可套到慢提议。

8项同策略local-only对照的主任务服务指标、响应与危害一致：本材料不建立第二Agent增益。诊断覆盖四策略，区别于旧F3负诊断仅ConstraintCoordinator的范围。56主+40诊断仅是开发回放，不是独立样本数或方法成绩排名；并不支持LLM优势。

## 必查项目

1. 对每条完整调用，核对实际捕获与trace一致、任务已发布、无名义窗口/未来事件/私有答案。NOEVENT与MID发布前输入匹配，慢提议变化来自预设延迟。
2. 逐事件核对实际阶段，不把未启动统计为运行停止；核查BOUNDARY右开边界与POST不追溯撤回。
3. 根据action_started、状态更新、action_stopped／物理完成构造运行区间，积分实际暴露；核对请求容限和静止容限、参考窗口与额外暴露。
4. 撤回、工作完成和监测完成分离；旧取消回执不放行新尝试；RAIN物理自然结束不能恢复service回执。
5. 雨停后预算足够、原身份不复活、新身份单独计分；完成后事件不追溯改变服务。
6. local-only只有监测对象删减，主设备信息、权限、确认成本一致；无第二Agent因果收益宣称。
7. false/null、等待、迟到、撤回合法性和未恢复状态逐任务重算；不要使用旧兼容总分替代上述指标。
8. 新旧源码锁与材料哈希、完整17专项和旧回归，冻结v1-v8、Phase A/B与结果不得改写。

没有API/新模型/保留集实验，未上传GitHub。C4尚待设计与实现复审；通过之后才进入依赖不可行压力与取消/恢复修订，再到C2需求语义。
