import json
from pathlib import Path
O=Path('outputs');R=Path(r'.')
a=json.loads((O/'DEPENDENCY_V11_EVENT_AUDIT_20261003.json').read_text(encoding='utf-8'))
def link(label,p,line=None):return f'[{label}]({(R/p).as_posix()+(f":{line}" if line else "")})'
def out(label,p):return f'[{label}]({(O/p).resolve().as_posix()})'
E='homecoord_bench/task_revision/event_simulator_v11.py';C='homecoord_bench/task_revision/dependency_contract_v11.py';Q='homecoord_bench/task_revision/dependency_audit_v11.py';M='homecoord_bench/runtime/task_response_metrics.py'
groups={}
for d in a['details']:groups.setdefault(d['episode_id'],[]).append(d)
assert len(groups)==13 and len(a['details'])==52
assert not any(x['errors'] or x['contract_errors'] for x in a['details'])
why={
 'EARLY':'有效 wash 4400ms 完成后才释放 dry，4500→8500ms 完成；DeadlineAware 的对应时间为 4500、4600→8600ms。dry 自发布时延 8400/8500ms，必要依赖等待不算失败。',
 'LATE':'dry 5000ms 才发布/调用，5400→9400ms 执行；未偷跑。四策略等待 400ms、完成时延 4400ms。仅发布时间变化。',
 'INFEASIBLE_8000':'完成而超期，dry 迟到 500ms，DeadlineAware 600ms；完成 true、按时 false。8000ms 小于最早8500ms，作为不可行诊断单列。',
 'FEASIBLE_8500':'三个策略8500ms恰好完成；DeadlineAware8600ms完成、迟到100ms、按时false。任务存在可行排程，不把单策略迟到隐去或改称任务不可行。',
 'CANCEL_NO_RESTORE':'1000ms撤权，wash终态withdrawn，1200ms实停、旧完成丢弃；dry blocked。两任务均完成false、时延/迟到null、按时false；合法撤回单列而不伪装服务。',
 'CANCEL_RESTORE':'与无恢复版固定同一withdraw政策；5000ms恢复不复活wash，dry仍blocked；服务false/null/false，无restart。',
 'RESTART_NO_RESTORE':'1000ms旧wash尝试失效并停止；无恢复时wash pending_validity，dry dependency_waiting；服务false/null/false，旧回执不放行。',
 'RESTART_RESTORE':'同一restart政策只增5000ms恢复；新wash5100→9100ms有效完成，dry9200→13200ms完成；dry等待9100ms、完成时延13100ms，仍按15000ms期限算成功。旧4400/4500ms回执丢弃。',
 'INVALID_PROPOSAL':'仅wash.operation注入unsupported，300ms返回；三策略300ms拒绝，DeadlineAware400ms校验拒绝，均tool_not_authorized。无执行/可信回执；dry等待而非终态blocked；完成false/null，无补模型调用。',
 'FORGED_STATE':'450ms untrusted washed=true不能释放依赖；仍须4400ms有效wash回执才启动dry，DeadlineAware为4500ms回执。未把普通状态等同可信完成。',
 'STALE_NATURAL_RACE':'4000ms洗涤尝试失效；4400ms仅物理结束（DeadlineAware4500ms），效果仅devices.washer=off。5000ms恢复后新wash9100ms完成，dry9200ms才启动；旧暴露400/500ms和额外200/300ms保留，旧停止确认过晚。',
 'CAPACITY_TIGHT':'实际峰值3，未超容量。Independent的dry门控拒绝后未重试，故未完成/null/按时false；其他三策略必要排队后12400/12500ms完成且按时，正确记成功。不能将可行世界中的策略未完成当执行错误。',
 'CAPACITY_SAFE':'实际峰值3.5≤6，独立dishes与wash/dry合法并行；四策略三项服务真实完成。wash→dry串行仍由依赖回执决定。'
}
rows=[]
for eid,ds in groups.items():
    name=eid.removeprefix('DEP11-');refs=[]
    for d in ds:
        ev=[x for x in d['events'] if x['type'] in ('action_started','action_completed','action_rejected','dependency_waiting','dependency_blocked','dependency_ready','completion_discarded','invalidated_action_physically_completed','task_withdrawn','attempt_invalidated','action_stopped') or x['type']=='state_update' and x['source'] not in ('action_started','stop_ack') and x['time_ms']!=16000]
        key='；'.join(f"e{x['index']} {x['type']}({x['task_id']})@{x['time_ms']}" for x in ev)
        refs.append(f"runs[{d['run_index']}]：{key}")
    rows.append(f"| `{name}` | 接受／符合设计 | {why[name]} | 当前提交范围内无阻断性缺失。 | 已满足本配置四策略合同；不等于四策略全服务成功。 | {link('原轨迹',d['file'])}；{'<br>'.join(refs)}；统一代码定位见下。 |")
text=f'''# 依赖任务 v11 设计与实现复审

2026-10-03。审查者：本会话 Codex。先审核设计卡、完整输入及可行证书并保存{out('设计结论','DEPENDENCY_V11_DESIGN_REVIEW_20261003.md')}，然后读取实现包、成绩和代码。本轮不沿用其他任务族的验收。

**设计：接受。实现：13 个配置、52 条四策略回放均在提交范围内符合设计；未发现执行或计分的阻断性错误。** 这是另写脚本重建事件的单模型复审，不是独立双审，不是方法排名，也不表示所有回放都成功或按时。

## 设计核查

接受 SyntheticResident 的显式合成政策，固定同一逻辑批次 batch_1、wash→dry 唯一依赖。工具授权、合成洗涤有效性和可信完成回执分开：washed=true 不足以放行；撤回、非法提议、取消旧回执、失效尝试自然物理结束不能产生前驱成功。恢复新尝试从零重做，已撤回请求不恢复。局限为单批次固定映射，未批准任意DAG或多批并发。

独立参数检查和8个构造性排程证书通过。300ms提议+100ms命令确认使wash最早400→4400ms；真实回执后dry至少再确认100ms，最早4500→8500ms。因此8000ms诊断不可行，8500ms紧期限可行；证书是离线存在性证明，不是在线保证。LATE只有dry发布改5000ms；容量3/6只改变共同上限及派生capacity字段。两组恢复配对在各自固定模式内，仅增删恢复事件；跨withdraw/restart比较不是单因素。

EARLY/INVALID_PROPOSAL只有私有诊断分类及注入输出差异，实际完整调用输入相同；8000/8500的evaluation_class属于派生诊断标记，实际输入中不公开它。设计检查见{out('参数、配对与证书核验','DEPENDENCY_V11_DESIGN_CHECKS_20261003.json')}。

## 执行与计分核查

可信依赖由共同执行底座承担：{link('dependencies_met',E,421)}读取真实成功回执集合，{link('wake_dependencies',E,425)}区分前驱撤回blocked与未决waiting；{link('提案依赖门控',E,606)}及{link('启动前再次校验',E,1077)}共同阻止提前执行。

{link('尝试立即失效',E,475)}将撤权历史按proposal_id锁定；{link('失效自然结束',E,1227)}仅应用devices效果，剥离washed及service；{link('有效成功才产生可信回执',E,1265)}阻止旧尝试释放后继。停止确认、自然结束、取消回执及新恢复身份在52条中逐一匹配真实开始。

独立重算逐任务首次启动等待、真实有效完成、自发布时延、迟到、按时、未开始/未完成计数及服务率；对照{link('逐任务指标代码',M,5)}和{link('执行器重计',E,1361)}，结果一致。撤回或未完成保持完成false、完成时延/迟到null、按时false；没有把安全拒绝改成服务成功。作者重计见{link('独立资格核对',Q,89)}，本审核另用自己的状态/尝试重建，不只信其输出。

几个必须保留的失败和口径差异：

- 8000ms诊断各策略确实迟到500/600ms；8500ms可行配置中的DeadlineAware仍迟到100ms，按时false。两者不能混称“共同不可行”。
- 容量3下Independent的dry因门控拒绝后未重试而未完成，这是已执行策略行为；其他策略排队仍按时，就计服务成功。实际资源峰值从未超过上限。
- CANCEL两臂wash终态撤回、dry blocked；RESTART无恢复和非法提议的dry是dependency_waiting。作者request_disposition对未完成dry使用宽泛unresolved，但专门的dependency_blocked/waiting字段和事件清楚区分，不能仅凭那个宽泛字段合并统计。
- STALE_NATURAL_RACE旧尝试暴露400ms（DeadlineAware500ms），额外暴露200/300ms，停止请求及时但静止不及时、stop_confirmed=false；最终恢复成功不抹去暴露。

不可行排除标记在certificates中明确存在；本包提供的是逐配置结果，未提供跨配置“可行全按时率”汇总代码或成绩。因此本轮确认其任务划分和逐任务超期计分，不批准任何尚未提交的混合分母汇总。合法撤回、非法输出等诊断同样应单列解释，不能把这些行混成可行全服务结果。

## 已填写逐配置表

四策略顺序：runs[0] IndependentMultiAgent，runs[1] ConstraintCoordinator，runs[2] DeadlineAwareCoordinator，runs[3] GateRetryRule。下标零基；时间单位ms。每行列出四策略关键事件，其完整状态、区间、指标和检查结果见{out('52条独立审计','DEPENDENCY_V11_EVENT_AUDIT_20261003.json')}。统一代码位置为上述421/425/606/1077（依赖）、475/1227/1265（尝试与回执）、1361及task_response_metrics（计分）。

| 配置 | 设计／实现 | 理由 | 缺失证据 | 通过条件 | 事件／代码／策略 |
|---|---|---|---|---|---|
{chr(10).join(rows)}

## 额外探针、冻结与测试

52条实际确定性回放的trace/result/calls/audit与保存件完全复现一致。逐调用从发布时状态和版本、角色权限、白名单工具和公共task字段重建完整请求，未发现配置ID、评估分类、模板答案或未来恢复条件泄露。13组私有字段扰动后完整请求保持一致；8组模式内恢复配对调用也一致。四策略非法输出均只改wash.operation，返回300ms与拒绝300/400ms分开记录；拒绝原因为tool_not_authorized，无额外调用。

4个负例把旧失效物理结束伪造为正常服务，同时删除attempt_invalidated标签；作者与审核者两套重建仍按失效历史拒绝。6个入口负例在任何调用前拒绝错误batch、世界service写入、批量未来hook、非空instructions、未支持策略和关闭共享门。此处不是任意元数据或轨迹篡改的普遍保证。

新v11的17个JSON对象重新生成一致；旧v3的3个包对象重新生成一致。共{len(a['hash_checks'])}项哈希检查无差异，包括此前独立审计留存的Phase B、C4 v9/v10 manifest摘要及其声明源码/材料，支持这些指定冻结文件未变。本审核未写入研究仓库或上传GitHub。

实际运行v11专项 `python -m unittest homecoord_bench.tests.test_dependency_v11 -v`，12项全部通过；未重跑作者声称全套488项。没有模型/API、保留实验或C2任务执行。审核脚本：{out('独立事件审计与运行探针','../work/audit_dependency_v11.py')}。

结论仅限已提交合成单批次合同、v11显式入口和52条轨迹。未涵盖真实衣物物理、任意DAG、多用户授权、所有事件阶段，也不证明LLM或额外Agent必需。依赖v11在本轮范围内可结束复审，C2尚未审查。
'''
(O/'DEPENDENCY_V11_REVIEW_20261003.md').write_text(text,encoding='utf-8')
print(json.dumps({'configurations':13,'runs':52,'verdict':'符合设计','blocking_findings':0,'report':str((O/'DEPENDENCY_V11_REVIEW_20261003.md').resolve())},ensure_ascii=False))
