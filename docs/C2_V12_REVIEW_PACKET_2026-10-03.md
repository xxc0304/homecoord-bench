# C2 v12 实现审查包

2026-10-03。作者修订与自检，不是验收意见。先审[设计卡](C2_V12_DEMAND_DESIGN_2026-10-03.md)和inputs，保存设计结论；再填[空白审查表](C2_V12_REVIEW_FORM_2026-10-03.md)。

## 材料

fixtures/room_v12内35JSON：inputs（24主＋8诊断）、runs/24文件、diagnostics/8文件、index和manifest。每条包含result、完整实际调用calls、作者audit、可读非环境事件及完整trace的无损编码。trace_encoding=zlib+base64+utf8-json，trace_zlib_base64可由room_revision_v12.unpack解码，原文本sha256另存；不是抽样、区间合并或省略1秒状态事件。可读事件仅供导航，不替代完整轨迹。32条解码后均须独立审计。

例：在Python中读入JSON后，from homecoord_bench.task_revision.room_revision_v12 import unpack；row=unpack(saved)，完整事件为row['trace']['events']，环境分段为row['trace']['environment_intervals']。无需写文件或安装依赖；可打印目标事件下标或时间窗口。生成器python -m homecoord_bench.task_revision.room_revision_v12打印材料列表；附路径参数打印该材料序列化，不自动覆写。

显式event_simulator_v12复制v4，只新增请求边界、需求准入/no-act终态和分层处置指标；物理仍调用冻结room_environment。旧v4、v3、C4 v9/v10和依赖v11源码/冻结结果不改；默认CLI未升级。

## 定位及必审内容

| 文件 | 符号／用途 |
|---|---|
| room_contract_v12.py | AUTHORITY、validate_v12：共同控制底座权限与费用，拒绝费用/延迟不一致与混合配置 |
| room_contract_v12.py | build_agent_request：公共ID、公开需求阈值/工具成本，隐藏模板/私有条件 |
| room_contract_v12.py | disposition_metrics：准入、处置终态与完成时延/按时分开 |
| event_simulator_v12.py | ventilation_not_needed、request_satisfied_without_actuation：低CO₂错误开窗拒绝、合法无动作终态，不伪造动作完成 |
| event_simulator_v12.py | environment_tick、environment_window_closed：1秒观察、3秒实际确认、供暖准入等待 |
| room_revision_v12.py | episode、Provider、bundle、pack/unpack：参数、诊断、真实捕获、24旧物理兼容、无损材料 |
| room_audit_v12.py | audit：真实启动/回执匹配、状态版本与终态重建、skip资格、处置与命令重算 |
| room_audit.py | audit：冻结独立物理审计，不调用evolve；端点、热平衡、CO₂、能量、积分、闭窗与首次联合目标 |
| tests/test_room_v12.py | 12专项：阈值、错误skip/open、分层、共同授权、成本/期限、输入canary、篡改、完整复现、旧冻结 |

## 作者观测，需复审者重算

850ppm时，air300ms合法无动作终态，命令false/null，处置按时true；供暖命令1500ms完成（自100ms发布时延1400ms），默认参数环境162000ms首次联合达标。900同样可skip；901须通风。高CO₂1600时开窗命令2400ms完成，不表示CO₂当刻达标。

主24运行的完整environment报告与对应冻结v4逐字段一致，仅需求处置、公共边界和新增命令期限语义改变；物理积分未改。默认高CO₂参数下立即/等待环境首次目标为340000/572000ms，等待臂超环境期限，但设备命令仍可先完成；低CO₂两臂完整环境报告一致。立即更快但累计供暖能量更高，不能用共同终点前不同完成状态或更低期限能耗单独判优。

8诊断：低CO₂强行开窗拒绝，不能因最终环境达标而反推提案正确；高CO₂跳过不成合法终态，环境首目标null；900/901边界资格明确。所有诊断应用两臂，但只覆盖ConstraintCoordinator与本公开脚本，不是四策略或所有方法实现的验收。

## 验收顺序

1. 核对demand_rule、工具CO₂>900前提及公开请求语义，无动作合法性不是作者私下例外。
2. 对每次实际调用核对captured inputs与trace一致；两准入臂输入相同、私有条件扰动不泄露，无未来事件或动作模板。
3. 按原始trace重放CO₂/窗口，合法skip仅在当前满足且关闭时；无动作不产action_completed或命令时延。高CO₂无动作、低CO₂开窗按合同处理。
4. 准入合法、最终处置、真实命令完成、环境首次达标、按时分别核对；允许合法供暖等待，不能将命令兼容总分当环境需求成功率。
5. 两臂闭窗权限、确认成本、恒温成本、2kW持续能量完全一致；共同360/900秒窗口，开窗供暖为软代价。
6. 核查每个物理区间端点与积分、版本、动作匹配及闭窗请求/确认，保留超期和未完成null；不能只信作者audit。
7. 解码32条完整trace校验sha256及重新审计；35材料与新旧源码锁核查，旧v4冻结复现不变。
8. 限未校准单室环境、首次观察目标和提交轨迹。没有真实家庭、持续满足、LLM/第二Agent必要性结论，也不沿用v11依赖验收。

专项：python -m unittest homecoord_bench.tests.test_room_v12 -q。全套：python -m unittest discover -s homecoord_bench/tests -q。未调用模型、未打开保留集、未上传GitHub。设计与实现待复审，不自动开始跨配置汇总或新模型实验。

实际运行：12项v12专项通过、全套500项通过；包括32条无损trace解码/重计、新材料序列化/源码锁、旧v4冻结与其他任务族回归。作者自检不能代替复审结论。
