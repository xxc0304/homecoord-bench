# 依赖任务 v11 实现审查包

2026-10-03。作者实现与自检，不是验收通过，不是独立双审。先读[设计卡](DEPENDENCY_V11_DESIGN_2026-10-03.md)及输入／证书，保存设计结论后再审运行。见[空白表](DEPENDENCY_V11_REVIEW_FORM_2026-10-03.md)。

## 材料清单

homecoord_bench/task_revision/fixtures/dependency_v11/：17JSON，inputs（13配置）、certificates（可行证书与不可行论证）、runs/（13文件、52条四策略完整trace/result/calls/audit）、index（两种模式内恢复配对、失败规范）和manifest（新旧源码及材料哈希、acceptance=null）。

显式event_simulator_v11入口由v3复制，继承任务依赖并迁入v10确认的“失效立即生效”机制；不修改v3、v9、v10、旧协议/执行器/evaluate/冻结材料。公共builder新增dependency_contract_v11，无私有条件身份或答案。没有默认入口升级，也不沿用其他任务族验收标签。

运行：python -m unittest homecoord_bench.tests.test_dependency_v11 -q；全套python -m unittest discover -s homecoord_bench/tests -q。生成器python -m homecoord_bench.task_revision.dependency_revision_v11打印材料列表，附路径打印JSON序列化，不自行写文件。

## 代码定位

| 文件／符号 | 必审内容 |
|---|---|
| dependency_revision_v11.py / episode、certificates | 参数继承、13配置用途、8000诊断、8500及资源排程证书 |
| dependency_revision_v11.py / Provider、bundle | 单字段非法operation注入、返回/拒绝时刻、恢复单因素配对、实际捕获 |
| dependency_contract_v11.py / build_agent_request、validate_v11 | 公共身份、局部信息、同批次、无未来/答案、拒绝非法service世界写入 |
| event_simulator_v11.py / dependencies_met、wake_dependencies | 可信有效前驱回执才释放；撤回blocked与未决waiting分开 |
| event_simulator_v11.py / invalid_service_attempts、invalid_completion | 失效尝试自然结束只写devices，不能完成请求或写washed |
| dependency_audit_v11.py / onsets、done、dependency_waiting | 从状态+启动身份重建有效性，不相信action_completed名称；对后继启动、等待/阻断与评分独立重算 |
| tests/test_dependency_v11.py | 12专项，覆盖52完整捕获、回执/伪状态/旧尝试、配对、期限、失败、冻结和复现 |

## 作者自检观测，需复审者核查

52回放均完成作者独立重计。四策略烘干从未在有效洗涤回执前启动。基础正常结束8500ms，但DeadlineAwareCoordinator等待dry提议在400ms返回后再派发wash，结束8600ms；因此FEASIBLE_8500仍可行，但它会超期100ms。8000ms配置则各策略超期500/600ms。不把策略迟到写成任务不可行，不隐藏个体迟到。

非法wash提议在300ms返回，三策略当刻拒绝；DeadlineAwareCoordinator在400ms派发时拒绝，均tool_not_authorized，无新模型补调用。dry保留等待且未完成false/null；不是设备执行中失败，更不是已完成服务。CANCEL两配置均撤回原wash、dry blocked；RESTART无恢复时wash等待有效性、dry等待回执，恢复版正常13200ms结束。

STALE_NATURAL_RACE的旧wash自然结束4400ms（DeadlineAware为4500），仅写devices.washer=off；不写washed/service、不生成可信回执。5000ms恢复、新尝试5100→9100，之后dry9200→13200。原取消旧回执在4400/4500ms丢弃。伪造washed=true没有提前释放dry。暴露与尝试物理结束仍保存，不用最终恢复抹去。

容量3存在构造性排程；IndependentMultiAgent可能在门控拒绝后不重试dry，因此可行并不意味着该策略实现全服务。必要排队仍满足期限即算成功。不能将同一DAG的两服务必要串行当第三负载容量冲突证据。

实际验证：新增12项专项通过，全套488项通过，包含旧v3材料重新生成及C4 v9/v10冻结回归；这是作者自检，不代填复审通过。

## 必查项目及通过条件

1. 先确认8000绝对截止小于最早8500结束，8500及容量排程合法；诊断不进入可行全按时分母。区分完成时刻与自发布时延。
2. 同模式恢复配对只改变恢复事件；跨withdraw/restart不是单因素。恢复不复活永久撤回请求。
3. 逐调用核对实际captured inputs/decisions与trace一致，无配置身份/模板答案/未来恢复泄露；注入仅wash.operation变unsupported，四策略同规范。
4. 从真实启动、状态变化、尝试ID、自然/停止终止重建前驱资格；旧取消或失效自然结束、伪washed字段不得释放dry。
5. 所有dry真实启动须有同批次有效wash尝试的真实回执；新回执只由新有效attempt产生，不能用未确认的停止命令代替实停。
6. 非法提议拒绝与真实执行失败分开，返回300ms与校验300/400ms分别确认；waiting、blocked、pending_validity、完成及false/null逐项核对。
7. 独立核对实际状态、资源区间、容量、暴露、等待、完成/迟到/按时；不要只信作者audit或旧兼容汇总字段。
8. 检查新旧源码与材料哈希，旧v3和C4冻结不改；限单批次合成合同和提交轨迹，不外推任意DAG、真实家庭、模型或多Agent必要性。

当前设计/实现均待审，无API、保留集或GitHub上传；C2尚未开始。
