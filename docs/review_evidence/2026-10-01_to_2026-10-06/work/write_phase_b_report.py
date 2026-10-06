import json
from pathlib import Path
ROOT=Path(r'.')
OUT=Path('outputs');data=json.loads((OUT/'PHASE_B_EVENT_AUDIT.json').read_text(encoding='utf-8'))
assert not any(data['summary'][k] for k in ['hash_errors','audit_errors','historical_errors'])
rows=data['summary']['runs_summary'];runs=data['runs']
def group(eid):return [x for x in runs if x['episode_id']==eid]
source_defs=[
('E1','F1容量预约与实际启动安全门','homecoord_bench/runtime/event_simulator.py',122,227),
('E2','F1启动、真实完成、资源释放','homecoord_bench/runtime/event_simulator.py',899,1070),
('E3','F1旧评分投影与真实逐任务指标汇总','homecoord_bench/runtime/event_simulator.py',230,263),
('E4','F1最终评分汇总','homecoord_bench/runtime/event_simulator.py',1089,1151),
('D1','真实完成回执集合与依赖唤醒','homecoord_bench/task_revision/event_simulator_v3.py',412,441),
('D2','提案授权、依赖等待和成本grounding','homecoord_bench/task_revision/event_simulator_v3.py',569,619),
('D3','依赖动作启动前复查与容量安全门','homecoord_bench/task_revision/event_simulator_v3.py',1067,1130),
('D4','依赖真实完成并登记回执','homecoord_bench/task_revision/event_simulator_v3.py',1213,1261),
('D5','依赖服务、完成和期限以真实事件覆写','homecoord_bench/task_revision/event_simulator_v3.py',1345,1372),
('D6','晚发布任务的请求与返回时钟','homecoord_bench/task_revision/event_simulator_v3.py',948,989),
('M1','逐任务等待、完成、迟到和null','homecoord_bench/runtime/task_response_metrics.py',1,38),
('M2','服务动作匹配和合法off排除','homecoord_bench/evaluate.py',86,104),
('M3','通用容量、服务、截止和成功字段','homecoord_bench/evaluate.py',208,280),
('G1','实际持续时间和资源来自冻结grounding','homecoord_bench/runtime/execution.py',43,77),
('G2','主体、工具、写权限和前提校验','homecoord_bench/runtime/tool_contract.py',8,86),
('P1','调用状态与评分提示开关','homecoord_bench/runtime/protocol.py',88,124),
]
code=['# Phase B审查代码摘录','', '2026-10-02读取；源文件与证据包manifest源码哈希一致。下列为原文摘录，行号为原源码一基行号，未修改源代码。','']
for ref,title,path,a,b in source_defs:
    lines=(ROOT/path).read_text(encoding='utf-8').splitlines()
    code.extend([f'## {ref}：{title}','',f'源位置：`{path}:{a}`；摘录至第{min(b,len(lines))}行。','', '```text'])
    code.extend(f'{i}: {lines[i-1]}' for i in range(a,min(b,len(lines))+1))
    code.extend(['```',''])
(OUT/'PHASE_B_CODE_EXCERPTS.md').write_text('\n'.join(code),encoding='utf-8')
report='''# Phase B：执行与评分实现审查

审核人：Codex，本聊天单一模型审查者。日期：2026-10-02（Asia/Shanghai）。本轮只审第一轮接受范围的13配置，不重新评判其他任务设计，不比较方法优劣，不运行模型。

**结论：13个配置在已提交的92条确定性回放中，核心执行与计分均符合第一轮认可的限域设计。未发现本轮已核查指标受到提前完成、超容量、伪造状态放行、提前发布执行或安全拒绝冒充服务完成的污染。**

这是单审实现结论；不等于独立双审完成，也不证明未提交的模型轨迹或其他执行入口符合设计。

## 证据及验证范围

源包：`docs/implementation_review_20261001`。

manifest SHA-256：`MANIFEST_HASH`。

读取任务合同、实际调用输入、92条完整有序事件及其reported_result；静态审查使用中的F1旧event_simulator与依赖event_simulator_v3、评分、工具授权、请求序列化及grounding代码。用本地独立脚本从原事件重算，没有调用作者的recount或生产评分函数来生成预期值，也未重跑模拟器、模型或网络请求。

核查所有manifest所列源码、产物及历史结果的哈希，未发现不一致；13份episode的规范化哈希与Phase A source_episode_sha256一致。历史JSON容器仅对本轮13配置进行比较：F1核对原来保存的服务、按时、逐任务等待／完成时延及过程暴露；依赖核对原metrics和保存的trace字段，均一致。F1新增完整轨迹仍是确定性回放证据，不能冒称旧模型原始日志。

92条回放组成：F1每配置9条（3种返回顺序×3种既有执行策略），共72；依赖每配置4条，共20。策略名仅用于定位证据，不构成排名。

实际事件数组保持原顺序，以下`runs[i]`与`events[j]`均是**零基JSON数组下标**；代码行号是一基行号。峰值占用按真实action_started至对应action_completed的半开区间统计，不把action_reserved当已运行。

## 逐配置审查表

下列代表事件便于人工复核；结论已覆盖每配置全部回放，完整区间、事件序号与重计值保存在PHASE_B_EVENT_AUDIT.json。

| 配置 | 结论 | 覆盖回放／实际峰值÷容量 | 代表事件证据 | 代码位置索引 |
|---|---|---|---|---|
'''.replace('MANIFEST_HASH',data['summary']['manifest_sha256'])
configs=list(dict.fromkeys(x['episode_id'] for x in rows))
for eid in configs:
    g=group(eid);r=g[0];parts=[]
    for iv in r['intervals']:
        parts.append(f"{iv['task_id']}：events[{iv['start_event']}] {iv['start_ms']}启动→[{iv['finish_event']}] {iv['finish_ms']}完成")
    if eid=='DEP-LAUNDRY-FORGED_STATE':parts.insert(0,'events[9] 450ms伪造washed=true；[10] 4400ms才有wash回执')
    if eid=='DEP-LAUNDRY-CAPACITY_TIGHT':parts.append('events[19] 4500ms安全拒绝dry；dry完成=false，时延/迟到=null；runs[1] dry [21]8400→[22]12400')
    if eid=='DEP-LAUNDRY-LATE_REQUEST':parts.insert(0,'events[7] 5000ms发布dry；calls[1].request.current_time_ms=5000')
    if eid=='D-F1-02-competition-base':parts.append('迟到另见runs[3]/events[41]、runs[4]/[33]、runs[6]/[38]、runs[7]/[34]，均按时=false')
    peak=max(x['peak_actual_units'] for x in g)
    refs='E1/E2/E3/E4、M1/M2/M3、G1/G2' if eid.startswith('D-F1') else 'D1/D2/D3/D4/D5、M1、G1/G2'
    if eid=='DEP-LAUNDRY-LATE_REQUEST':refs+='、D6'
    report+=f"| {eid} | 符合设计（本包回放范围） | {len(g)}／{peak:g}÷{r['capacity']:g} | runs[0]；"+'；'.join(parts)+f"；时间单位ms | {refs} |\n"
report+='''
上述每行的原证据路径是`docs/implementation_review_20261001/traces/<配置ID>.json`。F1代表runs[0]为GateRetryRule、arrival_order_index=0；依赖代表runs[0]为IndependentMultiAgent、arrival_order_index=null。依赖CAPACITY_TIGHT的runs[1]为ConstraintCoordinator。

没有配置被判为“须修正”或“证据不足”；这只指本轮13配置已提交轨迹的核心执行／计分。任务运行未按时或未完成可以是正确记录的结果，不应因此判实现不符合设计。

## 关键核查结果

### 实际容量、授权和动作完成

逐事件核对request/task/agent/proposal身份、公开工具及可写设备、请求状态版本、启动前提、冻结grounding时长与效果。完整动作均有对应捕获提案、真实启动和匹配完成，完成时刻=实际启动+合同持续时间。开始效果只改变running，完成效果到action_completed才应用。

F1八配置实际峰值依次为3、3、4、4、4、4、8、8，均不超过对应容量。依赖容量紧峰值3/容量3，容量足峰值3.5/容量6。无越权动作、发布前启动、容量超限或无法匹配的完成回执。

容量预约在E1按区间边界核验；共享安全门在`runtime/event_simulator.py:207`及v3相应函数只使用已在途动作进行最终否决。F1真实开始与完成在E2；实际成本由G1读取合同，不采用提案自报估计作为真实执行成本。

### 排队按时、迟到和未完成分开

F1-01容量紧，runs[0]的dishes在1300ms安全拒绝，meal于181100ms完成后，dishes于181200ms真实启动、481200ms完成，早于截止900000ms。等待181200ms仍算服务完成且按时，不因排队或曾被门控拒绝算任务失败；重试产生同一proposal_id，但只有真实成功启动／完成计入服务。

F1-02容量紧基准有4个water迟到记录，完整明细如下。water均真实完成，task_service=true；task_deadline_met.water=false、all_deadlines_met=false、timely_process_valid_success=false。不能用final_goal_success或process_valid_success替代期限成功。

| runs下标 | 定位策略／返回顺序 | 启动→完成事件 | 完成ms／截止ms | 正确迟到ms |
|---|---|---|---|---|
| 3 | GateRetryRule／1 | events[37]→[41] | 661300／360000 | 301300 |
| 4 | ConstraintCoordinator／1 | events[32]→[33] | 720900／360000 | 360900 |
| 6 | GateRetryRule／2 | events[37]→[38] | 661100／360000 | 301100 |
| 7 | ConstraintCoordinator／2 | events[32]→[34] | 901300／360000 | 541300 |

依赖CAPACITY_TIGHT的runs[0]：wash于4400ms完成后dry满足依赖，但4500ms启动时与尚未完成的dishes合计3.5>容量3，events[19]安全拒绝。没有dry的action_started/action_completed；task_service.dry=false，task_correct_action_completed.dry=false，等待／完成时延／迟到均null，未开始与未完成计数均1。serviceable_task_count仍3、served_task_count为2、服务率2/3，task_deadline_met.dry与all_deadlines_met均false。该安全拒绝未伪装成服务完成。

同配置runs[1]，dishes的events[19]在8400ms完成，dry的events[21]同刻之后启动，events[22]12400ms完成；按自身100ms发布时间算等待8300、完成时延12300ms，仍在15000ms截止内。事件顺序及半开区间允许同刻释放和启动，不误报容量重叠。

### 真实wash回执及伪造状态

EARLY_REQUEST的dry提案在400ms进入dependency_waiting；4400ms wash真实完成后生成回执，同刻才dependency_ready，4500ms dry开始。等待依赖不算容量违规。

FORGED_STATE的runs[0]，events[9]450ms把washed置true，但events[10]4400ms才是wash完成；events[11]4400ms释放dry，events[15]4500ms才启动。其余3条回放同样无提前放行。仅状态布尔值不产生回执。

代码D1的dependencies_met检查可信完成集合；D2在提案处理阶段等待；D3启动前再次检查集合及washed前提；D4只在实际action_completed、服务动作匹配且未撤回时加入回执。回执粒度为task_id，符合已接受的单次工作流范围，本轮不验收实体衣物batch_id或跨批次。

### 晚发布及计时基准

LATE_REQUEST的全部4条回放，dry均在5000ms请求，5400ms启动、9400ms完成。不存在5000ms之前的dry请求、预约或执行。等待400ms、完成时延4400ms；兼容字段task_action_finish_time_ms.dry=9400表示相对episode发布的完成时刻，两者不可混用。

生产计时M1以各任务release_at_ms计算等待和时延，迟到为max(0,真实完成-绝对截止)。缺启动／完成为null，有限等待汇总明确命名max_observed，不据此排除未完成任务的失败计数。D5用真实事件覆写依赖服务及期限字段，null==0为false，未完成不会被判按时。

## 代码位置索引

完整原文摘录见[PHASE_B_CODE_EXCERPTS.md](PHASE_B_CODE_EXCERPTS.md)。源文件均在`homecoord_bench`下。

| 索引 | 实际代码位置 | 核查语义 |
|---|---|---|
| E1 | runtime/event_simulator.py:122；:207 | 预约区间排程、实际在途安全门 |
| E2 | runtime/event_simulator.py:899；:983；:1029 | 启动前提、开始效果、真实完成与释放 |
| E3/E4 | runtime/event_simulator.py:230；:1089；:1150 | 旧评分投影、生产汇总与真实逐任务指标 |
| D1 | task_revision/event_simulator_v3.py:417；:421 | 完成集合门槛及依赖唤醒 |
| D2 | task_revision/event_simulator_v3.py:575；:597；:610 | 授权、前驱等待、动作实体化 |
| D3 | task_revision/event_simulator_v3.py:1067；:1085；:1109 | 启动再次验证依赖、状态前提和容量 |
| D4 | task_revision/event_simulator_v3.py:1213；:1250 | 实际完成效果与服务匹配回执 |
| D5 | task_revision/event_simulator_v3.py:1346；:1349；:1355 | 真实服务、完成时刻及未完成的期限false |
| D6 | task_revision/event_simulator_v3.py:948；:979 | 到自身发布时才请求并安排提案返回 |
| M1 | runtime/task_response_metrics.py:5；:15；:23 | 真开始／真完成、自身发布基准、迟到／null |
| M2/M3 | evaluate.py:90；:103；:208；:225；:251 | 服务动作匹配、容量与通用期限字段 |
| G1/G2 | runtime/execution.py:43；:72；runtime/tool_contract.py:8 | grounding与工具权限校验 |
| P1 | runtime/protocol.py:88；:114 | 局部可见状态及评分提示开关 |

## 接受范围与口径限制

1. 只接受本包13配置、指定两个执行器版本及共享安全门开启条件。依赖v3不是默认CLI入口，不能把这里的结论推广到旧closed-loop或默认入口。
2. F1保留旧投影：action_started被映射为action_effective，旧task_service和task_action_finish_time_ms据启动及合同持续时间推算；本包所有F1真实启动均有完整匹配完成，且推算和真实完成逐项一致，因此本包没有提前完成污染。此结论不适用于截断、取消或未结束长动作；不能只取旧task_service作为那些场景的完成证据。M1真实完成字段才是本轮核查依据。
3. 旧兼容字段不全部纳入本次接受：例如coordination_decision_latency_ms在这些结果中为null，投影E3不保留coordination_decision；它不能用作协调耗时证据。first_effective_action_latency_ms按源码定义为目标首次进展，不能当设备启动时间。两项不影响本轮核查的服务、容量、等待、迟到或未完成结果。
4. 数据来自确定性脚本。F1输入未带评分模板提示；依赖脚本带模板提示已明确披露，限于执行诊断，不视为公平模型输入或模型推理证据。源码、快照及轨迹一致性不等于对真实设备或全部软件状态的证明。
5. 没有重新评价其他组，也没有把取消／恢复、失败注入或紧期限依赖配置纳入验收；没有因某方法安全但未完成就判执行器错误。

## 最终登记

13配置：均符合设计（已提交确定性回放及核心计分范围）。生产执行／核心评分污染：未发现。本轮无需因这些证据改动任务输入或生产代码。兼容字段未验收部分按上文限制使用。

历史比较、独立重计及源码阅读的证据齐备，但F1的旧完整轨迹未保存，故不能追溯认证不存在的历史模型日志。对本包新生成确定性回放的结论与历史摘要字段一致性结论分别成立。

第二位审核人：未提供；独立双审与分歧处理尚未完成。源审查表、任务、生产代码与冻结结果均未改动。本文为本聊天独立保存的审查记录。
'''
(OUT/'PHASE_B_REVIEW_20261002.md').write_text(report,encoding='utf-8')
print('Wrote report and code excerpts; 13 configuration verdicts.')
