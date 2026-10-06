import json,copy,hashlib
from pathlib import Path
ROOT=Path(r'.');BASE=ROOT/'homecoord_bench/task_revision/fixtures/f2_v7';OUT=Path('outputs')
def read(p):return json.loads(p.read_text(encoding='utf-8'))
eps=read(BASE/'inputs.json')['episodes'];certs=read(BASE/'feasibility.json')['certificates'];errors=[];details=[]
def check(ok,msg):
    if not ok:errors.append(msg)
for e in eps:
    eid=e['episode_id'];ts={t['task_id']:t for t in e['task_stream']};cap=e['home']['resources']['max_power_kw'];ds={d['agent_id']:d for d in e['public_devices']}
    check(e['nonpreemptive_delegation']['authority']=='explicit_synthetic_service_contract',eid+' delegation')
    check(len(ds)==4 and len(ts)==4,eid+' independent four services')
    for t in ts.values():
        d=ds[t['agent_id']];g=next(g for g in e['action_grounding'] if g['task_id']==t['task_id'] and g['operation']=='prepare');tool=next(z for z in e['tool_catalog'] if z['agent_id']==t['agent_id'] and z['operation']=='prepare')
        check(d['duration_ms']==t['action_template']['duration_ms']==g['duration_ms']==tool['cost_contract']['duration_ms'],eid+' duration '+t['task_id'])
        check(d['resource_units']==t['action_template']['power_kw']==g['power_kw']==tool['cost_contract']['resource_units'],eid+' units '+t['task_id'])
        check(not t.get('depends_on') and g['start_effects']=={'devices.'+d['target']:'running'} and g['completion_effects']=={'devices.'+d['target']:'complete'},eid+' lifecycle '+t['task_id'])
        off=next(z for z in e['tool_catalog'] if z['agent_id']==t['agent_id'] and z['operation']=='off')
        check(off['preconditions']==[{'path':'devices.'+d['target'],'op':'eq','value':'idle'}] and off['provides_service']=='none',eid+' nonpreemptive off')
    cert=next(c for c in certs if c['evaluation_episode_id']==eid);w=cert['mode_witnesses'][0];schedule=w['schedule']
    check(w['status']=='witness_found' and {s['task_id'] for s in schedule}==set(ts),eid+' witness coverage')
    for s in schedule:
        t=ts[s['task_id']];d=ds[t['agent_id']]
        check(s['start_ms']>=t['release_at_ms']+2100 and s['end_ms']==s['start_ms']+d['duration_ms'] and s['end_ms']<=t['completion_deadline_ms'] and s['units']==d['resource_units'],eid+' witness timing '+s['task_id'])
    peak=max(sum(s['units'] for s in schedule if s['start_ms']<=at<s['end_ms']) for at in {s['start_ms'] for s in schedule})
    check(peak<=cap,eid+' witness capacity')
    details.append({'episode_id':eid,'capacity':cap,'tasks':[{k:t[k] for k in ('task_id','release_at_ms','completion_deadline_ms','priority')} for t in ts.values()],'witness_peak_units':peak,'witness_schedule':schedule})
for base in ('D-F2-01','D-F2-02'):
    group=[e for e in eps if e['base_episode_id']==base]
    check(all(e['public_devices']==group[0]['public_devices'] for e in group),base+' static devices differ by arm')
    for arm in ('competition','no_competition'):
        late=next(e for e in group if e['pairing']=={'resource_arm':arm,'temporal_arm':'late'});sim=next(e for e in group if e['pairing']=={'resource_arm':arm,'temporal_arm':'simultaneous'})
        for a,b in zip(late['task_stream'],sim['task_stream']):
            aa=copy.deepcopy(a);bb=copy.deepcopy(b)
            check(a['completion_deadline_ms']-a['release_at_ms']==b['completion_deadline_ms']-b['release_at_ms'],base+' own release budget')
            for key in ('release_at_ms','completion_deadline_ms'):aa.pop(key);bb.pop(key)
            check(aa==bb,base+' temporal pair other task changes')
    for arm in ('late','simultaneous'):
        x=next(e for e in group if e['pairing']=={'resource_arm':'competition','temporal_arm':arm});y=next(e for e in group if e['pairing']=={'resource_arm':'no_competition','temporal_arm':arm})
        check(x['task_stream']==y['task_stream'] and x['public_devices']==y['public_devices'] and x['action_grounding']==y['action_grounding'] and x['tool_catalog']==y['tool_catalog'],base+' capacity pair contracts')
out={'phase':'design_before_results','errors':errors,'configurations':details,'verdict':'接受' if not errors else '修改','scope':'explicit white-list, single synthetic nonpreemptive service contract; offline feasibility only'}
(OUT/'F2_V7_DESIGN_CHECKS_20261002.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
report='''# F2 v7 设计复审（先于读取策略轨迹，2026-10-02）

结论：**接受本次设计修订**。8配置的静态能力、非抢占合成委托、同刻原子发布、容量配对和自身发布时限配对清楚且一致；8份离线排程证书经独立检查资源半开区间、完整时长、release+2100ms假设和截止，均成立。

白名单接受理由：设备存在、服务能力及成本不等于某次请求存在；仅公开 release<=当前时刻 的任务需求，同刻批次全部可见。四方法获得相同类别信息；只观察自身设备、公共容量、静态能力及已发布任务。规范化文本仍表达原prepare服务、截止和不可中断周期。原自由文本、评分模板、未来任务流及任意上下文应由可信执行器隔离。

非抢占接受理由：SyntheticResident 委托明示，off仅在idle有效且不提供服务，没有运行中取消接口。这是合成服务合同，不能证明真实设备无法中断或真实用户偏好如此。晚到由外源预设时间发布，早期请求没有额外未来分布信息。离线可行只排除合同不可行，不是公平在线基线，不推出在线迟到必然可避免。

缺失证据：设计声明尚未证明实际输入和调度执行遵守白名单，留待实现审查；真实家庭外推、未来到达概率、损失不可避免性及反事实因果归因未建立，不属于此次接受范围。

实现通过条件：逐字段确认实际provider与保存请求一致、32主轨迹无提前调用/超容量/中断或伪完成，48反事实在首次分歧前完整calls及事件相同；排队完成、未完成和迟到正确计分；拒绝离线oracle/全局hook/外部instructions等旁路。

本轮设计判断仅使用设计说明、8输入、离线证书和白名单源码；未读取主回放或策略成绩。单模型审查，未完成独立双审。结果详见同目录 F2_V7_DESIGN_CHECKS_20261002.json。
'''
(OUT/'F2_V7_DESIGN_REVIEW_20261002.md').write_text(report,encoding='utf-8')
print(json.dumps({'errors':errors,'configurations':len(eps),'verdict':out['verdict']},ensure_ascii=False))
