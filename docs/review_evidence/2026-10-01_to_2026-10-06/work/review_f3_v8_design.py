import json,itertools
from pathlib import Path
R=Path(r'.');B=R/'homecoord_bench/task_revision/fixtures/f3_v8';O=Path('outputs')
def read(p):return json.loads(p.read_text(encoding='utf-8'))
eps=read(B/'inputs.json')['episodes'];cert=read(B/'feasibility.json')['certificates'];errors=[];rows=[];witnesses=[]
def check(ok,s):
    if not ok:errors.append(s)
for e in eps:
    cap=e['mode_capability'];ds={d['agent_id']:d for d in e['public_devices']};tidmap={t['task_id']:t for t in e['task_stream']}
    check(e['service_delegation']['principal']=='SyntheticResident' and cap['selection_boundary']=='one_proposal_before_start_no_switch',e['episode_id']+' delegation')
    for t in e['task_stream']:
        d=ds[t['agent_id']];allowed=cap['authorized_modes_by_task'][t['task_id']];owner=next(a for a in e['agents'] if a['agent_id']==t['agent_id'])
        check(t['release_at_ms']==0 and t['completion_deadline_ms']>0,e['episode_id']+' release/deadline')
        check(set(owner['tools'])=={d['role']+'_'+m for m in allowed+['off']},e['episode_id']+' tools')
        check(len(allowed)==1 if cap['kind']=='fixed' else set(allowed)=={m['operation'] for m in d['modes']},e['episode_id']+' capability')
        check(t['acceptable_actions']==[{'target':d['target'],'operation':m['operation']} for m in d['modes']],e['episode_id']+' physical service')
        for m in d['modes']:
            g=next(g for g in e['action_grounding'] if g['task_id']==t['task_id'] and g['operation']==m['operation'])
            check(g['duration_ms']==m['duration_ms'] and g['power_kw']==m['resource_units'] and g['completion_effects']=={'devices.'+d['target']:'complete'},e['episode_id']+' physical costs/equivalence')
            if m['operation'] in allowed:
                tool=next(z for z in e['tool_catalog'] if z['agent_id']==t['agent_id'] and z['operation']==m['operation'])
                check(tool['provides_service']==d['service'] and tool['cost_contract']=={'duration_ms':m['duration_ms'],'resource_units':m['resource_units']},e['episode_id']+' public cost')
        off=next(z for z in e['tool_catalog'] if z['agent_id']==t['agent_id'] and z['operation']=='off')
        check(off['provides_service']=='none' and off['preconditions']==[{'path':'devices.'+d['target'],'op':'eq','value':'idle'}],e['episode_id']+' off boundary')
    rows.append({'episode_id':e['episode_id'],'world':e['evaluation_world_id'],'kind':cap['kind'],'authorized_modes_by_task':cap['authorized_modes_by_task']})
for c in cert:
    group=[e for e in eps if e['evaluation_world_id']==c['evaluation_world_id']];base=group[0];tasks={t['task_id']:t for t in base['task_stream']}
    check(len([e for e in group if e['mode_capability']['kind']=='selectable'])==1,c['evaluation_world_id']+' selectable coverage')
    for e in group:check(e['task_stream']==base['task_stream'] and e['public_devices']==base['public_devices'] and e['action_grounding']==base['action_grounding'],c['evaluation_world_id']+' permission changes service')
    fixed=[e for e in group if e['mode_capability']['kind']=='fixed'];check(len(fixed)==len(c['mode_witnesses']),c['evaluation_world_id']+' vectors')
    for w in c['mode_witnesses']:
        schedule=w['schedule'];check(w['status']=='witness_found' and {s['task_id'] for s in schedule}==set(tasks),c['evaluation_world_id']+' witness coverage')
        for s in schedule:
            t=tasks[s['task_id']];g=next(g for g in base['action_grounding'] if g['task_id']==t['task_id'] and g['operation']==s['operation'])
            check(s['operation']==w['modes'][s['task_id']] and s['start_ms']>=t['release_at_ms']+2100 and s['end_ms']==s['start_ms']+g['duration_ms'] and s['units']==g['power_kw'] and s['end_ms']<=t['completion_deadline_ms'],c['evaluation_world_id']+' witness clock/cost')
        peak=max(sum(s['units'] for s in schedule if s['start_ms']<=at<s['end_ms']) for at in {s['start_ms'] for s in schedule});check(peak<=base['home']['resources']['max_power_kw'],c['evaluation_world_id']+' witness capacity')
        witnesses.append({'world':c['evaluation_world_id'],'modes':w['modes'],'peak_units':peak,'schedule':schedule})
out={'phase':'design_before_results','errors':errors,'verdict':'接受' if not errors else '修改','configurations':rows,'offline_witnesses':witnesses}
(O/'F3_V8_DESIGN_CHECKS_20261002.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
report='''# F3 v8 设计复审（先于读取成绩，2026-10-02）

结论：接受本次能力合同。32权限配置（24固定+8可选）的授权与物理合格明确分开，同合同内四策略共享权限；固定向量含全组合，可选组三规则只读相同公开成本/请求/容量。模式启动前选择、预约前承诺、运行期间不可改/取消的合成委托清楚。

服务等价接受为作者设备complete效果合同，不等于真实质量。eco/fast只表示瞬时预约量/周期，不赋予节能含义。实际资源时间积、任务等待/时延/迟到、全服务完成/部分latest_observed分别报告，避免默认模板或标签替代实际成本和真实完成。

固定向量内排程比较、同策略全eco/全fast控制、相同实际模式向量控制分别限定比较对象；未完成差值为null且保留双方完成标记。该设计足以区分脚本中的排程和模式变化，不支持LLM优势、普遍因果关系、实机能源收益或损失不可避免性。

8基础世界/24离线模式组合逐项检查完整周期、release+2100ms、容量半开区间及截止，全部成立，仅证明离线可行。模式权限变化保持任务物理合格集合、成本、grounding和需求不变。全体任务0ms公开，不扩展F2未来到达合同。

设计范围无待补项。实现通过条件：真实目录与权限、预约前拒绝/承诺、192主+32诊断的状态/版本/资源/回执/评分与成本，以及72/192/96对照须从原事件独立重算；不得以测试数量代替。后续须明确诊断只有Constraint覆盖。单模型审查，未完成独立双审。

本记录只用设计卡、inputs、feasibility及能力/生成源码，未读取策略成绩或对照数值。设计接受后才进入实现审查。
'''
(O/'F3_V8_DESIGN_REVIEW_20261002.md').write_text(report,encoding='utf-8')
print(json.dumps({'errors':errors,'configs':len(rows),'witnesses':len(witnesses)}))
