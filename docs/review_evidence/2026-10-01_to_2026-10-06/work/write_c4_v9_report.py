import json,csv
from pathlib import Path
O=Path('outputs'); A=json.loads((O/'C4_V9_EVENT_AUDIT_20261003.json').read_text(encoding='utf-8'))
R=Path(r'.')
def link(label,path,line=None):
    target=(R/path).as_posix()+(f':{line}' if line else '')
    return f'[{label}]({target})'
E='homecoord_bench/task_revision/event_simulator_v9.py'; Q='homecoord_bench/task_revision/c4_audit_v9.py'; C='homecoord_bench/task_revision/c4_contract_v9.py'
policies=['IndependentMultiAgent','ConstraintCoordinator','DeadlineAwareCoordinator','GateRetryRule']
groups={}
for d in A['details']:groups.setdefault(d['episode_id'],[]).append(d)
assert len(groups)==24 and len(A['details'])==96
assert sum(bool(d['errors'] or d['contract_errors']) for d in A['details'])==4
with (O/'C4_V9_RUN_CHECKS_20261003.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.writer(f);w.writerow(['configuration_id','section','policy','run_index','verdict','actual_stages','task_metrics','request_disposition','stop_response','harm_ms','event_refs','errors','source_file'])
    for d in A['details']:
        c=d['computed']; w.writerow([d['episode_id'],d['section'],d['policy'],d['run_index'],'须修正' if d['errors'] or d['contract_errors'] else '符合设计',json.dumps(c['actual_event_stages'],ensure_ascii=False),json.dumps(c['service_recount'],ensure_ascii=False),json.dumps(c['request_disposition'],ensure_ascii=False),json.dumps(c['response_records'],ensure_ascii=False),c['harm_duration_ms'],json.dumps(d['events'],ensure_ascii=False),json.dumps(d['errors']+d['contract_errors'],ensure_ascii=False),(R/d['file']).as_posix()])
reason={
 'NOEVENT':'有效尝试 400→3400ms 完成；无停止及暴露。',
 'EARLY':'100ms 时尚未启动；清洁等待恢复后新尝试，灌溉永久撤回；暴露 0。',
 'MID':'1800ms 为实际执行中段；停止请求当刻发出、2000ms 实停；暴露 200ms。',
 'LATE':'3000ms 为实际执行后段；3200ms 实停，旧 3400ms 回执丢弃；暴露 200ms。',
 'BOUNDARY':'3400ms 与自然结束同刻；按右开运行区间结算有效完成，无正时长暴露。',
 'POST':'3400ms 已完成，4000ms 更新不追溯取消。',
 'UNRELATED':'1800ms 心跳不触发有效性失效或停止。',
 'slow_proposal':'1800ms 实际阶段为 released_not_started；旧提案不能执行。监测任务 2700ms 完成、迟到 700ms 被如实计入。',
 'slow_ack':'1800ms 请求停止、2500ms 实停；暴露 700ms，超容忍 500ms；未把及时请求当及时停止。',
 'late_natural_race':'3000ms 失效；3400ms 自然物理结束，4000ms 停止确认过晚。',
 'local_only':'移除监测 Agent 后主服务、停止及暴露与对应 MID 四策略逐一一致；本地联锁足够。',
 'never_restore':'停止后无有效性恢复；旧回执丢弃，待恢复请求服务 false、完成时延 null、按时 false。',
 'new_request':'旧请求永久撤回；5500ms 新身份发布，5900→8900ms 执行，新请求时延 3400ms；旧请求仍 false/null。'
}
rows=[]
for eid,ds in groups.items():
    d=ds[0]; scene='CLEAN' if '-CLEAN-' in eid else 'RAIN'; suffix=eid.split('-')[-1]; key=suffix
    if suffix not in reason:key=eid.split('-')[-1]
    bad=any(x['errors'] or x['contract_errors'] for x in ds)
    explanation=reason[key]
    if key in ('EARLY','MID','LATE','slow_proposal','slow_ack'):
        explanation+=(' 清洁恢复后从零重做并在 8100ms 完成。' if scene=='CLEAN' else ' 雨停不复活，原请求保持撤回、服务 false/null。')
    if key=='late_natural_race':
        explanation+=(' **失效旧尝试误记成功，恢复后不重启。**' if scene=='CLEAN' else ' 仅记 withdrawn_action_physically_completed，无服务效果；雨停不复活。')
    refs='；'.join(f"e{v['index']} {v['type']}@{v['time_ms']}" for v in d['events'] if v['type'] in ['state_update','action_started','action_completed','action_stopped','stop_requested','stop_ack_too_late','completion_discarded','task_withdrawn','restart_proposed','withdrawn_action_physically_completed'] and not (v['type']=='state_update' and v['time_ms'] in (400,10000)))
    positions=(link('执行器',E,1170)+'、'+link('重计',Q,70) if bad else link('生命周期',E,429)+'、'+link('开始/完成',E,1028)+'、'+link('重计',Q,98))
    missing='四策略修正后轨迹、独立重计与边界回归。' if bad else '当前保存轨迹范围内无阻断性缺失；不代表未提交边界已覆盖。'
    condition='满足上述 F1 修正条件；当前不得使用这些成功指标。' if bad else '限本版合同和已提交四策略轨迹通过；保持有效回执与生命周期分离。'
    rows.append(f"| `{eid}` | 保留（接受）／{'须修正' if bad else '符合设计'} | {explanation} | {missing} | {condition} | {link('原轨迹',d['file'])}，runs[0..3]；{refs}；{positions} |")
report=f'''# C4 v9 设计与实现复审

日期：2026-10-03。审查者：本会话 Codex；采用另行编写的轨迹重算及运行输入捕获，不依赖作者重计作为判据。本结论不是独立双审。

**设计接受；实现不能整体通过。** 14 个主配置（56 条）和 9 个诊断配置（36 条）在已提交轨迹范围内符合设计。`C4R1-CLEAN-LATE-late_natural_race` 的四策略均须修正：执行器把失效清洁尝试的自然物理结束计为服务成功，作者重计重复了同一错误，并因此漏掉恢复后的新尝试。其余 92 条逐事件检查一致。此处“符合设计”不表示零暴露、第二 Agent 有增益或任务成绩优越。

先读取并审核设计、输入和权限参数，保存[设计结论](C4_V9_DESIGN_REVIEW_20261003.md)后，才读取结果与实施运行核查。此次仅审 C4，不沿用其他任务族验收。

## 设计结论

清洁采用“有人使当前尝试失效、无人恢复后同请求从零重做”；灌溉采用“降雨永久撤回本次请求、雨停不复活、另用新 task_id 请求”。两者依据明确的合成用户委托，技术能力与政策许可分开。有效性、监测动作完成、本地联锁、实际服务回执分别记录，允许物理结束而服务失败。接受这些限定的合成生命周期合同。

接受以真实启动/终止时间重建事件阶段，并采用右开运行区间：在自然结束前失效必须使该尝试失效；与自然结束同刻的边界不产生正时长无效运行。接受停止请求容忍 0ms、实际静止容忍 200ms、参考确认窗口 200ms；该容忍并不抹去 200ms 暴露。统一观察终点 10000ms。

模型输入不包含未来事件、名义阶段或模板动作；实际 96 次运行逐调用捕获与白名单重建一致。24 个私有字段扰动探针通过，8 个 NOEVENT/MID 发布前完整输入配对通过。合同校验位置：{link('validate_v9',C,8)}；输入构造：{link('build_public_request_v9',C,31)}。这些探针覆盖提交材料及所扰动字段，不能推广为任意新增元数据的无泄露证明。

本地联锁是共同可信执行底座。8 个 local_only 四策略配对表明，此处监测 Agent 不改变主服务和停止轨迹，不能把停止安全性或恢复能力归功于多 Agent 推理。实际提交阶段没有 before_release 和 running_early；名为 EARLY 的主配置是 released_not_started，不能声称已覆盖所有执行阶段。

## F1：失效清洁尝试误算服务成功（高优先级）

配置：`C4R1-CLEAN-LATE-late_natural_race`。四策略依次为 {', '.join(policies)}，保存文件 runs[0] 至 runs[3]，事件下标均为 **零基**：

| 事件下标 | 时间 ms | 实际含义与错误 |
|---|---:|---|
| e9 | 400 | 清洁开始，计划自然结束 3400ms。 |
| e12 | 3000 | occupancy=true；自然结束之前当前尝试已失效，实际阶段 running_late。 |
| e13 | 3000 | 请求停止，确认延迟 1000ms，计划 4000ms。 |
| e14 | 3400 | 自然物理结束，却写入 `service.work_completed=true` 并发出 `action_completed`。 |
| e15 | 4000 | `stop_ack_too_late`；不能认作命令确认的停止。 |
| e16 | 5000 | occupancy=false 恢复；请求已被错误标记完成，未产生新清洁尝试。 |

这不是 BOUNDARY 配置的同刻例外：失效发生在 3000ms，严格早于自然结束 3400ms。

根因：{link('失效与停止请求',E,429)}只在实际停止确认时将提案加入 cancelled（{link('cancelled_proposals',E,858)}）；{link('完成处理',E,1164)}仅剥离 withdrawn 请求的服务效果（{link('服务效果过滤',E,1170)}），未检查清洁尝试是否已失效。因此自然结束先于停止确认时仍发出 action_completed，并在{link('completed_task_ids',E,1204)}关闭请求，阻止恢复后重做。{link('作者重计',Q,70)}仅排除 withdrawn 状态，把同一错误回执写入 done，再在{link('指标计算',Q,98)}认可其服务成功。

| 主清洁指标 | 保存结果／作者重计 | 按合同重计 |
|---|---|---|
| task_correct_action_completed | true | false |
| task_completion_latency_ms | 3400 | null |
| task_completion_tardiness_ms | 0 | null |
| task_deadline_met | true | false |
| request_disposition | completed | unresolved（观察结束时恢复有效，但没有新有效尝试完成） |
| task_start_wait_ms | 400 | 400（真实首次启动等待仍保留） |

暴露和停止指标本身在这四条中正确：停止请求时延 0、实际静止时延 400、实际暴露 400、参考窗口暴露 200、超过容忍暴露 200ms；stop_confirmed=false、quiescence_timely=false。修正服务错误不能抹去这些物理记录。错误回执及完成集合也会影响衍生服务/目标/按时汇总；不得只改报告字段而保留错误的执行终态。

通过条件：在 3000ms 失效时记录尝试有效性已丧失。3400ms 自然结束只能释放资源并记录物理结束，不得写服务成功或将可恢复请求标记完成；5000ms 恢复后必须产生新尝试，从零执行，只有该有效尝试的匹配真实回执可计成功。作者重计须从有效性事件与尝试身份重建资格，不能只相信 action_completed 的名称。提交四策略修正轨迹、正确逐任务指标及独立重计；成对回归 CLEAN 提前失效自然结束与恰好同刻边界，并保持 RAIN 永久撤回、迟确认、旧回执丢弃及 local_only 对照。现有错误四条不能作为有效成绩使用。

## 逐配置复审表

每行覆盖四策略，顺序同上；详细逐策略、逐事件值见[96 行核查表](C4_V9_RUN_CHECKS_20261003.csv)及[完整独立事件审计](C4_V9_EVENT_AUDIT_20261003.json)。表中下标直接指向保存轨迹事件；通过是合同一致性判断，不是服务率判断。设计均保留，明确限制已经写在本报告设计结论中。

| 配置 | 设计／实现 | 理由 | 缺失证据 | 通过条件 | 事件／代码／策略 |
|---|---|---|---|---|---|
{chr(10).join(rows)}

## 核验范围与证据

独立逐事件重算覆盖 56 条主回放与 40 条诊断：请求发布时间、工具/状态前提、预约/真实开始、效果时刻和版本、尝试身份、实际阶段、撤回与恢复、停止请求/实停、暴露、容量、逐任务等待/完成/迟到/未完成以及监测任务独立完成。没有比较方法排名，也没有调用模型或保留实验。

96 条实际确定性运行输入/轨迹/结果与保存件全部复现一致；包括错误四条，这证明错误可复现而不是正确。28 个 JSON 包对象再生成一致；C4 文件哈希校验无差异。10 个负向合同探针在调用前拒绝非法条件。148 个旧冻结材料核查项均未变化。详细结果见[运行探针](C4_V9_RUNTIME_PROBES_20261003.json)及[设计参数检查](C4_V9_DESIGN_CHECKS_20261003.json)。没有写入研究仓库、上传 GitHub 或修改冻结材料。

实际运行 `homecoord_bench.tests.test_c4_v9` 的 17 项专项测试，均通过；没有重跑作者声称的全套 466 项。专项测试没有断言 CLEAN 提前失效后自然完成不得计服务的语义，所以不能替代本次失败判定。

结论仅覆盖单请求的合成设备状态、明确用户委托、当前合同与已提交轨迹。未覆盖真实家庭物理证据、多用户仲裁、任意新增执行路径或全部事件阶段；也不支持 LLM 必需或第二 Agent 必需的主张。须修正 F1 后针对该竞态及相关回归复审，不需要重开整个设计。
'''
for name in ['C4_V9_DESIGN_REVIEW_20261003.md','C4_V9_RUN_CHECKS_20261003.csv','C4_V9_EVENT_AUDIT_20261003.json','C4_V9_RUNTIME_PROBES_20261003.json','C4_V9_DESIGN_CHECKS_20261003.json']:
    report=report.replace(']('+name+')',']('+(O/name).resolve().as_posix()+')')
(O/'C4_V9_REVIEW_20261003.md').write_text(report,encoding='utf-8')
print(json.dumps({'report':str((O/'C4_V9_REVIEW_20261003.md').resolve()),'configurations':len(groups),'runs':len(A['details']),'failing_runs':4},ensure_ascii=False))
