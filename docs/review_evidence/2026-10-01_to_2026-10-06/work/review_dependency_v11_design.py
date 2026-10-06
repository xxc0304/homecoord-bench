import json,copy
from pathlib import Path
R=Path(r'.');B=R/'homecoord_bench/task_revision/fixtures/dependency_v11';O=Path('outputs')
def read(p):return json.loads(p.read_text(encoding='utf-8'))
es=read(B/'inputs.json')['episodes'];eps={e['nominal_window']:e for e in es};cert=read(B/'certificates.json');errors=[];schedules=[];pairs=[]
def ck(ok,msg):
    if not ok:errors.append(msg)
def delta(x,y,p=''):
    if isinstance(x,dict) and isinstance(y,dict):return [z for k in sorted(set(x)|set(y)) for z in delta(x.get(k),y.get(k),p+'.'+k)]
    if isinstance(x,list) and isinstance(y,list) and len(x)==len(y):return [z for i,(u,v) in enumerate(zip(x,y)) for z in delta(u,v,p+f'[{i}]')]
    return [] if x==y else [{'path':p,'left':x,'right':y}]
for e in es:
    name=e['nominal_window'];ts={t['task_id']:t for t in e['task_stream']};cs=e['simulation']['lifecycle_contracts']['wash'];gs={g['task_id']:g for g in e['action_grounding']}
    ck(e['batch_binding']=={'wash':'batch_1','dry':'batch_1'} and ts['dry']['depends_on']==['wash'] and not ts['wash'].get('depends_on'),name+' single-batch edge')
    ck(e['simulation']['command_latency_ms']==100 and ts['wash']['release_at_ms']==0 and ts['wash']['completion_deadline_ms']==15000,name+' wash timing')
    ck(ts['dry']['release_at_ms']==(5000 if name=='LATE' else 100) and ts['dry']['completion_deadline_ms']==(8000 if name=='INFEASIBLE_8000' else 8500 if name=='FEASIBLE_8500' else 15000),name+' dry timing')
    ck(e['initial_state']['values']['laundry']=={'washed':False,'dry':False,'wash_authorized':True},name+' initial')
    ck(cs['mode']==('withdraw' if name.startswith('CANCEL') else 'restart_from_zero') and cs['stop_ack_delay_ms']==(1000 if name=='STALE_NATURAL_RACE' else 200),name+' lifecycle')
    ck(e['authority']['principal']=='SyntheticResident' and e['response_contract']=={'detection_delay_ms':0,'request_tolerance_ms':0,'quiescence_tolerance_ms':200,'reference_ack_delay_ms':200},name+' authority/response')
    ck(any(v['at_ms']==16000 and v['event']=='observation_end' for v in e['exogenous_events']),name+' end')
    ck(not any(p.startswith('service.') for v in e['exogenous_events'] for p in v['patch']),name+' fake service receipt')
    for tid,t in ts.items():
        g=gs[tid];tool=next(z for z in e['tool_catalog'] if z['agent_id']==t['agent_id']);agent=next(z for z in e['agents'] if z['agent_id']==t['agent_id'])
        ck(tool['tool_name'] in agent['tools'] and 'devices.'+g['target'] in agent['writable_resources'] and (tool['target'],tool['operation'])==(g['target'],g['operation']),name+tid+' permissions')
        ck(tool['cost_contract']=={'duration_ms':g['duration_ms'],'resource_units':g['power_kw']},name+tid+' costs')
    ck(gs['wash']['duration_ms']==gs['dry']['duration_ms']==4000 and gs['wash']['power_kw']==1.5 and gs['dry']['power_kw']==2,name+' service cost')
    if 'dishes' in ts:ck(not ts['dishes'].get('depends_on') and ts['dishes']['release_at_ms']==0 and gs['dishes']['duration_ms']==8000 and gs['dishes']['power_kw']==1.5,name+' independent load')
    c=cert[name]
    if 'schedule' in c:
        work={x['task_id']:x for x in c['schedule']};check=[]
        for tid,s in work.items():
            check.append(s['end_ms']-s['start_ms']==gs[tid]['duration_ms'] and s['end_ms']<=ts[tid]['completion_deadline_ms'] and s['start_ms']>=ts[tid]['release_at_ms']+300+100)
        check.append(work['dry']['start_ms']>=work['wash']['end_ms']+100)
        peak=max(sum(gs[tid]['power_kw'] for tid,s in work.items() if s['start_ms']<=at<s['end_ms']) for at in {s['start_ms'] for s in work.values()})
        check.append(peak<=e['home']['resources']['max_power_kw'])
        # The certificate's valid wash attempt lies entirely in an authorized interval.
        authorized=True
        for event in e['exogenous_events']:
            if event['at_ms']<=work['wash']['start_ms'] and 'laundry.wash_authorized' in event['patch']:authorized=event['patch']['laundry.wash_authorized']
            if work['wash']['start_ms']<event['at_ms']<work['wash']['end_ms'] and event['patch'].get('laundry.wash_authorized') is False:check.append(False)
        check.append(authorized)
        ck(all(check),name+' constructive certificate');schedules.append({'configuration':name,'valid':all(check),'peak_units':peak})
ck(400+4000+100+4000==8500>8000 and cert['INFEASIBLE_8000']['excluded_from_feasible_success_denominator'] is True,'infeasible lower bound')
for left,right in [('CANCEL_NO_RESTORE','CANCEL_RESTORE'),('RESTART_NO_RESTORE','RESTART_RESTORE'),('EARLY','LATE'),('EARLY','INVALID_PROPOSAL'),('INFEASIBLE_8000','FEASIBLE_8500'),('CAPACITY_TIGHT','CAPACITY_SAFE')]:
    x=copy.deepcopy(eps[left]);y=copy.deepcopy(eps[right])
    for e in (x,y):
        for k in ('episode_id','nominal_window'):e.pop(k)
    if 'NO_RESTORE' in left:y['exogenous_events']=[v for v in y['exogenous_events'] if v['event']!='wash_authorization_restored']
    differences=delta(x,y);pairs.append({'left':left,'right':right,'differences':differences})
    allowed=[] if 'NO_RESTORE' in left or right=='INVALID_PROPOSAL' else ['.task_stream[1].release_at_ms'] if right=='LATE' else ['.task_stream[1].completion_deadline_ms'] if right=='FEASIBLE_8500' else ['.home.resources.max_power_kw','.conflict_rules[0].capacity']
    # evaluation_class is derived private diagnostic classification, not a
    # second world/permission factor. Later verify absent in actual requests.
    ck(all(d['path'] in allowed or d['path']=='.evaluation_class' for d in differences),left+'/'+right+' paired factors')
out={'configurations':len(es),'errors':errors,'certificate_checks':schedules,'paired_differences':pairs,'design_verdict':'接受' if not errors else '修改'}
(O/'DEPENDENCY_V11_DESIGN_CHECKS_20261003.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
if not errors:
    text='''# 依赖 v11 设计复审（先于成绩）

2026-10-03。仅先读取设计卡、13 个完整输入与离线可行证书，尚未读取保存成绩或实现包。

设计：接受，限于合成单批次洗→烘和已声明诊断。烘干须等待同批次、未失效洗涤尝试的真实成功回执；washed 布尔状态不是可信回执。withdraw 与 restart_from_zero 是不同合成政策；恢复事件只在同模式内作单因素对照。非法提议仅为工具拒绝诊断，不当成物理失败或终态撤回。

8500ms 最早物理完成下界可由公开 300ms 提议、100ms 命令及两段 4000ms 服务推得；8000ms 不可行诊断必须排除可行全按时分母。8500ms 有构造性可行证书，但不是在线方法成功保证。完成时延按各自发布时间计算，基础 dry 为8400ms。独立第三负载没有依赖边，容量3/6对照才审查竞争；必要 wash→dry 串行不能计资源冲突。

输入参数、权限、授权和观察终点检查通过；证书工作时长、发布、期限、依赖间100ms确认和峰值容量独立核验通过。两组取消/恢复配对仅增删恢复事件；容量字段两处联动属于同一派生上限。保护失效时尝试立即无效，旧自然结束不得产生 washed 或 service；右开区间同刻完成例外可接受。

实现尚未验收。须逐策略检查真实回执来源、启动/完成匹配、撤回/恢复/旧回执、第三负载容量、输入白名单及false/null/迟到口径。能力来自共同底座，不支持LLM必需或真实洗涤物理证据。缺失证据为尚未审的实现轨迹；通过条件是后续检查符合上述合同。
'''
    (O/'DEPENDENCY_V11_DESIGN_REVIEW_20261003.md').write_text(text,encoding='utf-8')
print(json.dumps(out,ensure_ascii=False,indent=2))
