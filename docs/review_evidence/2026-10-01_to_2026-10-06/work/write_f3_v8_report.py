import json,csv
from pathlib import Path
O=Path('outputs');R=Path(r'.');a=json.loads((O/'F3_V8_EVENT_AUDIT_20261002.json').read_text(encoding='utf-8'));B='homecoord_bench/task_revision/fixtures/f3_v8';eps={e['episode_id']:e for e in json.loads((R/B/'inputs.json').read_text(encoding='utf-8'))['episodes']}
def link(label,path,line=None):return f'[{label}]('+str(R/path).replace('\\','/')+(f':{line}' if line else '')+')'
def local(label,name):return f'[{label}]('+str((O/name).resolve()).replace('\\','/')+')'
rows=[]
for d in a['details']:
    events=d['events'];triples={tid:{'commit_event':c['event_index'],'start_event':next((x['index'] for x in events if x['type']=='action_started' and x['task_id']==tid),None),'finish_event':next((x['index'] for x in events if x['type']=='action_completed' and x['task_id']==tid),None)} for tid,c in d['commits'].items()}
    rows.append({'section':d['section'],'file':d['file'],'run_index':d['run_index'],'world':d['world'],'configuration':d['episode_id'],'policy':d['policy'],'selector':d['selector'],'case':d['case'],'verdict':'符合设计','peak_units':d['peak_units'],'capacity':d['capacity'],'events':json.dumps(triples,ensure_ascii=False),'wait_ms':json.dumps(d['computed']['task_start_wait_ms']),'latency_ms':json.dumps(d['computed']['task_completion_latency_ms']),'tardiness_ms':json.dumps(d['computed']['task_completion_tardiness_ms']),'deadline_met':json.dumps(d['computed']['task_deadline_met']),**{k:json.dumps(v,ensure_ascii=False) if isinstance(v,dict) else v for k,v in d['extended_metrics'].items()}})
with (O/'F3_V8_RUN_CHECKS_20261002.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
with (O/'F3_V8_CONTRAST_CHECKS_20261002.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=['section','index','equal','left','right','computed']);w.writeheader();w.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,dict) else v for k,v in c.items()} for c in a['contrast_checks'])
info='homecoord_bench/task_revision/f3_capability.py';eng='homecoord_bench/task_revision/event_simulator_v8.py'
text='''# F3 v8 能力与实现复审（2026-10-02）

总体结论：**设计接受；32权限配置实现均“符合设计”**。192主回放及32诊断未发现提交范围内的越权执行、估计成本替代真实成本、超容量、伪完成或相关计分污染。72固定模式排程对照、192同策略模式选择对照及96相同模式控制独立重算一致。

审查者：本聊天Codex单模型，与作者audit分开进行事件重算；不是人类审查，未完成独立双审。第一阶段仅使用设计说明、32输入、离线证书与能力源码，保存设计结论后才读取策略成绩。第二阶段成绩仅用于实现/评分核验，不判方法优劣。

8基础世界、24fixed+8selectable权限配置不是32种独立任务结构。仅审本次显式v8入口、四普通策略、三公开简单选择规则、合成同服务效果与不可中断周期。未运行API、模型、保留实验或全套449测试；16项F3专项测试实际重跑通过。原仓库文件及作者reviewer_acceptance未改，产物仅在独立审查工作区。

下标从0开始。主文件fixed runs[0..3]依次P0 IndependentMultiAgent、P1 ConstraintCoordinator、P2 DeadlineAwareCoordinator、P3 GateRetryRule；selectable runs[0..3]/[4..7]/[8..11]分别low_resource/short_duration/capacity_pressure，各组同四策略顺序。诊断runs[0..3]分别forbidden_fast/cost_lie/off/noop，仅P1。eN为trace.events[N]；qN同时核对calls[N].request和trace.agent_requests[N]。

## 先行设计结论及代码定位

'''
text+=f'''{local('先于成绩保存的设计结论','F3_V8_DESIGN_REVIEW_20261002.md')}；{local('32配置及24离线模式证书检查','F3_V8_DESIGN_CHECKS_20261002.json')}。

固定组只授权指定模式及off；可选组授权全部合格模式及off。物理服务等价集合/grounding不随权限变化，同合同内方法获得相同权限。固定组的“只排程”不额外授予任意起始时刻API。单提案、预约前承诺、完整周期、无运行中切换/取消的委托明确。低预约量、短周期、容量压力规则都有相同可选权限，不读私有模板或离线计划。

模式名称不推导能源/质量：01 laundry资源时间积eco=540000、fast=480000；02 drying=720000/900000，dishes=600000/720000单位·ms。服务等价仅为合成complete效果；这些数值不是实测家庭功率、节能或实机服务质量。

- A：{link('能力与支持范围校验',info,8)}；第48–72行校验授权覆盖、实际工具、物理效果与成本一致；{link('模式调用守卫',info,75)} 独立于物理合格集合拒绝越权和虚报成本。
- B：{link('公开任务与完整白名单',info,87)}，第94–124行重建公开请求、能力、规范化角色/工具和已发布目标，隔离私有ID、selector标签、自由文本及模板。{link('单任务最多一个动作','homecoord_bench/runtime/protocol.py',287)}。
- C：{link('执行前边界',eng,321)}；{link('预约前守卫与承诺',eng,493)} 第506行写mode_selection_committed，随后才materialize/预约；{link('实际发布与调用',eng,797)} 第805行builder，保存请求后调用provider。
- D：{link('启动前提与安全门',eng,915)}；第1013行真实启动，{link('真实完成回执',eng,1045)}，第1159行生产任务响应指标；{link('自身发布时间及匹配完成计分','homecoord_bench/runtime/task_response_metrics.py',10)}。GateRetry沿用原候选动作及proposal身份。
- E：{link('简单规则','homecoord_bench/task_revision/f3_revision.py',67)}；第105行作者audit；{link('对照差值','homecoord_bench/task_revision/f3_revision.py',175)}。本次从原回放独立重算，不以作者通过标记或摘要布尔值代替证据。

## 32权限配置复审表

每行覆盖全部指定run范围，不只审示例。表内示例为P1/low_resource的多模式任务“commit→start→complete”事件下标；全部192策略/选择规则的准确下标、实际模式、等待/迟到及成本见后附逐回放表和完整事件JSON。

| 基础世界 | 能力／固定向量 | 设计：结论／理由／缺失证据／通过条件 | 实现：结论／理由／缺失证据／通过条件 | JSON调用／事件位置及代码 |
| --- | --- | --- | --- | --- |
'''
for file in dict.fromkeys(d['file'] for d in a['details'][:192]):
    group=[d for d in a['details'][:192] if d['file']==file];d=group[1];e=eps[d['episode_id']];mult=[t['task_id'] for t in e['task_stream'] if len(t['acceptable_actions'])>1];kind=d['kind'];cap='selectable' if kind=='selectable' else 'fixed '+ '/'.join(e['mode_capability']['authorized_modes_by_task'][tid][0] for tid in mult)
    loc=[]
    for tid in mult:
        commit=d['commits'][tid]['event_index'];st=next((x['index'] for x in d['events'] if x['type']=='action_started' and x['task_id']==tid),None);fin=next((x['index'] for x in d['events'] if x['type']=='action_completed' and x['task_id']==tid),None)
        loc.append(f'{tid}:e{commit}→'+(f'e{st}→e{fin}' if st is not None else '未启动'))
    range_text='runs[0..3]' if kind=='fixed' else 'runs[0..11]'
    text+=f'| {d["world"]} | {cap} | 接受；同需求、明示委托及能力合同成立。范围内无缺项；设计条件满足。 | 符合设计；全部{len(group)}回放权限、真实模式/成本及评分一致。范围内无缺项；实现条件满足。 | {link("主文件",file)} {range_text}；q0–q{len(e["task_stream"])-1}；run[1] '+ '; '.join(loc)+'（A–E）。 |\n'
text+='''
## 实际输入、执行和计分

32配置内的完整请求除策略architecture/request_id身份外逐字段相同，selectable的三规则也相同；公开mode_capability.kind和授权向量属于合法权限信息，不当作泄露。192主回放共800次请求、含诊断共928次请求均按合同白名单和发布快照重建相符。实际agent工具/目录恰好是授权模式+off；fixed-fast不被默认eco模板覆盖，selectable未被默认模板限制。独立按公开成本重算三规则的期望选择，实际commit向量均匹配。

逐事件核对主体、目标、操作、提案身份、授权工具、idle前提、状态版本、预约和命令确认、完整周期及完成effects。主回放均为0ms发布，没有提前调用/启动；所有半开资源区间峰值不超容量，运行周期无取消、缩短或切换。每个合法服务commit在预约前、且时间严格早于启动；GateRetry重试不新增选择、不换操作或真实grounding成本。

资源成本从所有实际运行区间积分；task成本仅对真完成的服务记实际模式的预约量×完整时长，未服务为null，total包括实际off区间（预约量0）。同时核对按时间分段的总负载积分与逐区间求和；不使用提案估计、默认eco或名称计成本。

完成、等待、时延、迟到和按时均从真服务启动/完成与自身release计算。主回放有24条部分服务未完成、12条含真实迟到完成，均保留原标记：未完成false/null，迟到完成true且按时false。all_service_completion_ms仅全部服务完成时有值；部分完成latest_observed单列，不能当全计划完成时间。

例：01-competition-base fixed-eco/P0的meal未启动，all_service_completion_ms=null，latest_observed=540400ms；同配置P1的meal等待240400ms并在600400ms真完成，仍按时。这是计分核验，不是策略排名。laundry fast真实资源时间积480000而eco为540000，证实成本未按默认模板或“eco节能”标签填写。所有个体等待/迟到保留在逐回放表，没有用整体完工更早抹去个体损失。

生产legacy投影字段不作为本次真实完成或成本的证据；本次验收主字段为task_correct_action_completed、响应/迟到/按时及独立实际资源与全服务完成指标。没有把命令或脚本返回时间折算成实测能源成本。

## 对照归因复核

| 类型 | 数量与索引 | 独立核对 | 结论 |
| --- | --- | --- | --- |
| 固定向量排程 | contrasts.fixed_mode_scheduling[0..71] | 同世界/模式向量；政策对照P1；从两原始run重算完工、资源积分、双方完成、逐任务等待/迟到差 | 全72一致 |
| 同策略模式选择 | contrasts.same_policy_mode_selection[0..191] | 同世界/策略；selectable分别对全eco/全fast fixed，保留权限差异含义，不作跨权限排名 | 全192一致 |
| 相同模式控制 | contrasts.mode_matched_controls[0..95] | 实际commit向量匹配fixed，同世界/策略；等待、时延、迟到、按时、实际模式/逐任务与总成本及完成标记均重算相等 | 全96一致 |

360项对照均保存左右主文件路径与run下标。双方有一方全服务未完成时全服务完成差值为null；任务一方未启动/未完成时等待/迟到差值为null，未用0代替。双方完成布尔值与成本差同时保留；成本差即使为负，也不将少服务解释为优越。选择和排程的脚本控制差异可复核，不建立普遍因果、LLM能力或线上损失不可避免性。

## 32诊断逐条核查

诊断只覆盖ConstraintCoordinator。不是全部策略负例覆盖，也不是新的权限配置。每世界固定低预约向量越权fast、selectable虚报时长/off/noop，均审完整calls、events及结果。

| 世界／诊断文件 | runs下标／case | 拒绝或动作事件位置 | 服务与成本结论 |
| --- | --- | --- | --- |
'''
for d in a['details'][192:]:
    case=d['case'];ev=d['events'];caseevents=[x for x in ev if x['type'] in ('action_rejected','action_started','action_completed','agent_no_action')]
    loc='；'.join(f'{x["task_id"]}:e{x["index"]}/{x["time_ms"]} {x["type"]}'+(f'({x["reason"]})' if x['reason'] else '') for x in caseevents)
    if case=='forbidden_fast':verdict='物理合格但越权的fast在300ms守卫拒绝，无相应commit/预约/启动/完成；其服务false/null。其他合法prepare可执行。'
    elif case=='cost_lie':verdict='declared_mode_cost_mismatch；所有服务无commit/预约/启动，完成false、时延null、总成本0。'
    elif case=='off':verdict='off完整100ms可真完成，但服务全部false/null、按时false、整体完成null、总成本0。'
    else:verdict='noop无服务动作；完成全部false、时延null、整体完成null、总成本0。'
    text+=f'| {link(d["world"],d["file"])} | {d["run_index"]} / {case} | {loc} | 符合设计；{verdict} |\n'
text+='''
## 运行探针、冻结与限域

另捕获全部192主回放的真实provider输入：trace/result/calls与保存材料全部相同，instructions为空；将v8模块ideal_schedule改为直接抛异常的探针，全部192在线路径仍执行成功。32配置分别插入私有配置/selector标记、原goal/context/description、agent字段和模板canary，真实请求保持不变。

15项范围负探针均在调用前拒绝：hook/instructions、中央/未来保留/事后可行性策略、世界事件、离线批次/compute计划、缺失授权、物理成本不一致、fixed仍授全模式、实际工具权限不一致、额外约束、按私有ID合成时延和外部协调延迟。单提案协议代码及专项测试进一步约束返回结构；不把此有限入口宣称为任意第三方provider的通用安全边界。

F3专项16项实际测试通过，含模式/时长/commit/计分篡改、实际成本、权限拒绝、门控重试、oracle禁止、基础同模式数值回归与冻结复现。主要证据仍是独立224条事件重算及360项原始对照重算；全套449未重跑。

新manifest源码、原开发输入和44份JSON哈希全部相符；45份确定性对象复现相等。旧Phase B/C1已记录哈希和F2冻结manifest所列文件共82项一致。此冻结检查区分先前审查已保存哈希与F2声明manifest参考，不声称本轮重新执行了所有旧任务族。旧版本没有因新合同通过而被追认。

设计/实现范围内没有待补验收项，无需为本次验收改代码。未完成独立双审；真实家庭服务质量/物理成本/用户偏好、运行中动态换模式、F2未来发布混合、多用户、跨运行共享会话、LLM优势与全部损失因果归因均不在本次通过范围。离线可行证书不作在线成绩或不可避免性结论。若增加新provider或动态能力须另立合同。

'''
text+=f'逐回放下标与所有个体指标：{local("F3_V8_RUN_CHECKS_20261002.csv","F3_V8_RUN_CHECKS_20261002.csv")}；360项对照原文件定位/差值：{local("F3_V8_CONTRAST_CHECKS_20261002.csv","F3_V8_CONTRAST_CHECKS_20261002.csv")}；完整事件重算：{local("F3_V8_EVENT_AUDIT_20261002.json","F3_V8_EVENT_AUDIT_20261002.json")}；运行探针：{local("F3_V8_RUNTIME_PROBES_20261002.json","F3_V8_RUNTIME_PROBES_20261002.json")}。\n'
(O/'F3_V8_REVIEW_20261002.md').write_text(text,encoding='utf-8')
print('report',len(text.encode('utf-8')),'bytes; rows',len(rows))
