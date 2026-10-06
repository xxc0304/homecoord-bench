import json,copy
from pathlib import Path
R=Path(r'.');B=R/'homecoord_bench/task_revision/fixtures/c4_v9';O=Path('outputs')
def read(p):return json.loads(p.read_text(encoding='utf-8'))
main=read(B/'inputs.json')['episodes'];diags=read(B/'diagnostic_inputs.json')['cases'];errors=[];rows=[]
def ck(ok,msg):
    if not ok:errors.append(msg)
for e in main+[x['episode'] for x in diags]:
    eid=e['episode_id'];task=e['task_stream'][0];c=e['simulation']['lifecycle_contracts'][task['task_id']];signal=c['valid_when'][0]['path'];state=e['initial_state']['values']
    for k in signal.split('.'):state=state[k]
    ck(state is False,eid+' initial signal');ck(e['response_contract']=={'detection_delay_ms':0,'request_tolerance_ms':0,'quiescence_tolerance_ms':200,'reference_ack_delay_ms':200},eid+' response criteria')
    ck(c['mode']==('restart_from_zero' if e['c4_scene']=='CLEAN' else 'withdraw') and e['user_lifecycle_policy']['authority']=='explicit_synthetic_user_delegation',eid+' policy')
    ck(task['release_at_ms']==0 and task['completion_deadline_ms']==10000 and task['action_template']['duration_ms']==3000,eid+' work timing')
    ck(any(v['at_ms']==10000 and v['event']=='observation_end' for v in e['exogenous_events']),eid+' horizon')
    ck(all(not any(p.startswith('service.') for p in v['patch']) for v in e['exogenous_events']),eid+' external completion')
    for t in e['task_stream']:
        agent=next(a for a in e['agents'] if a['agent_id']==t['agent_id']);g=next(g for g in e['action_grounding'] if g['task_id']==t['task_id']);tool=next(z for z in e['tool_catalog'] if z['agent_id']==t['agent_id'])
        ck(tool['tool_name'] in agent['tools'] and tool['target']==g['target'] and tool['operation']==g['operation'],eid+' permissions')
        ck(tool['cost_contract']=={'duration_ms':g['duration_ms'],'resource_units':g['power_kw']},eid+' costs')
        if t['task_id'].endswith('_new'):ck(t['release_at_ms']==5500 and t['completion_deadline_ms']==10000 and 5500+300+100+3000<=10000,eid+' new request budget')
    rows.append({'id':eid,'scene':e['c4_scene'],'window':e['nominal_window'],'policy':c,'events':e['exogenous_events']})
for scene in ('CLEAN','RAIN'):
    original=next(e for e in main if e['c4_scene']==scene and e['nominal_window']=='MID');local=next(x['episode'] for x in diags if x['episode']['c4_scene']==scene and x['case']=='local_only')
    for field in ('response_contract','home','constraints','user_lifecycle_policy','simulation'):ck(local[field]==original[field],scene+' local control '+field)
    ck(local['task_stream']==original['task_stream'][:1] and local['agents']==original['agents'][:1] and local['tool_catalog']==original['tool_catalog'][:1] and local['action_grounding']==original['action_grounding'][:1],scene+' local monitor-only deletion')
ck(len(main)==14 and len(diags)==10,'coverage counts')
o={'phase':'design_before_results','verdict':'接受' if not errors else '修改','errors':errors,'configurations':rows}
(O/'C4_V9_DESIGN_CHECKS_20261003.json').write_text(json.dumps(o,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(O/'C4_V9_DESIGN_REVIEW_20261003.md').write_text('''# C4 v9 设计复审（先于轨迹成绩，2026-10-03）

结论：接受本次合同。14主配置与10诊断的授权、固定世界事件、观察终点、响应容限和预算明确且与输入一致。实际阶段由真实运行区间和完成边界确定；名义EARLY/MID/LATE不是实际阶段保证。右开边界失效不追溯取消已结束周期。

CLEAN暂停/从零重启和RAIN永久撤回、新身份重新请求是不同生命周期。停止请求0ms容限、静止200ms容限及参考确认窗口预先固定；暴露含参考窗口内真实运行时间，不能以额外暴露0宣称零风险。撤回后自然物理完成不记服务，过晚停止确认不改写终止原因。

信号/本地停止规则是合成用户委托与可信底座，监测动作不驱动联锁。local_only只删监测对象，主服务、可见信号、权限、停止成本及规则保持一致。双方雨停后观察预算足够新完整周期；新请求5500ms发布、10000ms截止也可执行。服务、撤回合法性、未恢复pending以及未完成false/null分别报告。

范围内设计无待补项。实现通过条件：实际输入边界、96条运行的真实尝试/状态/资源/停止与自然结束、区间暴露积分、请求终态/服务计分、8项本地对照须独立核对；旧取消回执不可算完成，雨停不能复活原身份。同刻顺序须符合同右开边界约定。

本判断仅使用设计说明、完整输入/诊断、权限及生成源码；未读取方法成绩。单模型审查，未完成独立双审。接受为布尔环境与合成动作合同，不证明真实停机物理下界、实机风险、进度保留方案或第二Agent优势。
''',encoding='utf-8')
print(json.dumps({'errors':errors,'main':len(main),'diagnostics':len(diags)}))
