"""Phase-A development-only design evidence. No model, runtime or result reads."""
import hashlib
import itertools
import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
DATA=ROOT/'homecoord_bench'
OUT='docs/design_review_20261001'
FIELDS=('episode_id','base_episode_id','episode_release_at_ms','home','initial_state','agents',
        'task_stream','tool_catalog','tool_contract_version','action_grounding','conflict_rules',
        'constraints','exogenous_events','goals','simulation','resource_unit','scenario_assumptions','calibration','pairing')
GROUPS=('C1-LIGHT','C1-BLINDS','C3-F1','C3-F2','C3-F3','C4-CLEAN','C4-RAIN','DEPENDENCY','C2-ROOM')
RULES={
 'C1-LIGHT':('一个阅读保护请求有效至6000ms；相反请求有效期内应拒绝，到期后可执行。这里只判设备状态保护，不判真实照度。',
             '仅有单一保护请求，其他同时使用需求与撤销仲裁未建模；有效期和优先级均为作者假设。不得声称真实照明或多请求仲裁验收。'),
 'C1-BLINDS':('一个隐私保护请求有效至6000ms；有效期内不得开帘，到期后解除本请求保护。',
              '与照明共享持续保护控制图，合并机制计数；隐私授权主体、优先级来源和其他请求未建模。'),
 'C3-F1':('任务互相独立、常负载、不可中断；同时运行总预约单位不能超过容量，完成匹配服务且不晚于各自截止。',
          '功率字段为抽象资源，不是实机功率；时长和期限为作者合同。排队但按时是服务成功，等待另计。可行证书仅排除合同根本不可行。'),
 'C3-F2':('早期任务不可中断；新请求独立于方法动作按预设时刻发布。只可使用当时已发布请求；自身时限=截止-发布。',
          '不可中断尚无设备来源；预设到达不是实测到达分布。离线存在可行排程不证明在线可避免全部损失，不用事后最优裁定推理错误。'),
 'C3-F3':('声明的多种模式均提供同一抽象服务，fast的持续时间较短但资源占用较高；off不提供服务。',
          '模式合格性为作者定义，无质量/能耗实测。不支持在途改模式；应分开固定模式排程与允许选模式的能力合同，资源时间积不自动当电能。'),
 'C4-CLEAN':('空置时才能执行清洁；占用变真请求停止，确认后才停止并释放资源；空置恢复后从零执行完整新尝试。',
             '200ms确认、从零恢复均为合成合同；第二主体只提供独立服务，不证明协调必要。未模拟检测滞后；事件时刻即执行器获知时刻。'),
 'C4-RAIN':('降雨变真永久撤回本次灌溉请求；运行中须停止确认，雨停不复活；完成后事件不追溯撤回。',
            '雨量阈值、用户偏好和实际供水量未建模；这里只用布尔事件和违规持续时间，不称雨已满足灌溉需求。'),
 'DEPENDENCY':('dry必须同时满足washed状态与有效wash完成回执。撤回的wash及旧取消尝试不放行；独立第三负载才引入容量因素。',
               '仅单次任务级工作流，尚无实体衣物batch_id；请求/提案ID不等于批次身份。FAILED_WASH需Phase B非法提案注入，源episode除ID等元数据外不是独立结构。'),
 'C2-ROOM':('命令只改窗口/供暖执行器；环境按统一时钟演化。联合目标=温度>=21、CO2<=900且关窗，期限360000ms，共同终点900000ms。',
            '未校准合成模型；只有首次观察达标，没有持续保持时长合同。冷热/CO2方程及积分定义见本包README，不验收真实舒适或持续舒适。')}


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def inputs():
    rows=[]
    def add(path,e,group):
        rows.append({'group':group,'source_path':str(path.relative_to(ROOT)).replace('\\','/'),
                     'source_episode_sha256':digest(e),
                     'contract':{k:deepcopy(e[k]) for k in FIELDS if k in e}})
    directory=DATA/'revision_drafts/20261001_task_semantics'
    for kind in ('LIGHT','BLINDS'):
        for condition in ('CONFLICT','SAFE'):
            p=directory/f'REV-C1-{kind}-{condition}.json'
            add(p,json.loads(p.read_text(encoding='utf-8')),'C1-'+kind)
    directory=DATA/'revision_drafts/20260930_task_family_split/development'
    for p in sorted(directory.glob('D-*.json')):
        e=json.loads(p.read_text(encoding='utf-8'))
        assert e['split']=='development'
        add(p,e,'C3-'+e['family_block'])
    for name,group in (('lifecycle_v2_inputs.json','C4'),('dependency_v3_inputs.json','DEPENDENCY'),('room_v4_inputs.json','C2-ROOM')):
        p=DATA/'task_revision/fixtures'/name
        for e in json.loads(p.read_text(encoding='utf-8'))['episodes']:
            selected=('C4-CLEAN' if 'CLEAN' in e['episode_id'] else 'C4-RAIN') if group=='C4' else group
            add(p,e,selected)
    assert len(rows)==71
    return rows


def feasible(e):
    """A constructive offline witness, NOT an online baseline or optimum claim."""
    tasks=e['task_stream'];cap=e['home']['resources']['max_power_kw']
    options=[[g for g in e['action_grounding'] if g['task_id']==t['task_id'] and g['operation']!='off'] for t in tasks]
    witnesses=[]
    for choices in itertools.product(*options):
        found=None
        for order in itertools.permutations(range(len(tasks))):
            slots=[]
            for i in order:
                t,g=tasks[i],choices[i];ready=t['release_at_ms']+2100
                candidates=sorted({ready,*[x['end_ms'] for x in slots if x['end_ms']>=ready]})
                chosen=None
                for start in candidates:
                    end=start+g['duration_ms']
                    if end>t['completion_deadline_ms']:continue
                    edges=sorted({start,end,*[v for x in slots for v in (x['start_ms'],x['end_ms']) if start<v<end]})
                    if all(g['power_kw']+sum(x['units'] for x in slots if x['start_ms']<=a<x['end_ms'])<=cap
                           for a in edges[:-1]):
                        chosen={'task_id':t['task_id'],'operation':g['operation'],'start_ms':start,'end_ms':end,'units':g['power_kw']};break
                if chosen is None:break
                slots.append(chosen)
            if len(slots)==len(tasks):found=sorted(slots,key=lambda x:x['start_ms']);break
        witnesses.append({'modes':{t['task_id']:g['operation'] for t,g in zip(tasks,choices)},
                          'status':'witness_found' if found else 'not_established_by_this_search','schedule':found})
    return {'scope':'offline feasibility only; knows all requests; assumes each command can start >= release+2100ms; not measured latency or online guarantee',
            'capacity_units':cap,'mode_witnesses':witnesses}


def verify_witness(e,cert):
    tasks={t['task_id']:t for t in e['task_stream']}
    for item in cert['mode_witnesses']:
        if item['schedule'] is None:continue
        slots=item['schedule'];assert set(x['task_id'] for x in slots)==set(tasks)
        for x in slots:
            t=tasks[x['task_id']]
            g=next(g for g in e['action_grounding'] if g['task_id']==x['task_id'] and g['operation']==x['operation'])
            assert x['end_ms']-x['start_ms']==g['duration_ms'] and x['units']==g['power_kw']
            assert x['start_ms']>=t['release_at_ms']+2100 and x['end_ms']<=t['completion_deadline_ms']
        for at in {v for x in slots for v in (x['start_ms'],x['end_ms'])}:
            assert sum(x['units'] for x in slots if x['start_ms']<=at<x['end_ms'])<=cert['capacity_units']


def card(group,rows):
    lines=[f'# {group}：设计证据卡','',
           '状态：待审。仅任务定义，不含运行成绩。完整状态、工具签名、动作效果与约束见 contracts.json 中本组。',
           '任务模板、grounding 和 service 字段为审查者可见的执行/评分合同，不能据此认为全部进入决策者输入。',
           '权限表的 observable_state 才是局部状态视图；公共信息与未来事件另按发布规则限制。','',
           '## 请求语义与验收边界','',RULES[group][0],'',RULES[group][1],'',
           '审查者需判断以上合同能否接受或应修改；它们是当前声明，不是已获批准的事实。','',
           '## 输入与配对参数','',
           '| 输入 ID | 任务 | 发布 ms | 截止 ms | 合格操作：持续 ms / 资源 |',
           '|---|---|---:|---:|---|']
    for row in rows:
        e=row['contract']
        for t in e['task_stream']:
            options=[g for g in e['action_grounding'] if g['task_id']==t['task_id']]
            lines.append('| '+e['episode_id']+' | '+t['task_id']+' | '+str(t['release_at_ms'])+' | '+str(t.get('completion_deadline_ms','未声明'))+' | '+ '; '.join(f"{g['operation']}: {g['duration_ms']} / {g['power_kw']}" for g in options)+' |')
    lines+=['','资源：C3-F* 的旧 power_kw 字段是抽象预约单位，不是实测 kW；其他组按作者定义参数解释，均未设备校准。',
            '完整合法操作以工具签名、前提和服务匹配为准；off 即使合法也不提供请求服务。','',
            '## 权限与可见信息','',
            '| 输入 | 主体 | 可见状态 | 可写资源 | 工具 |','|---|---|---|---|---|']
    seen=set()
    for row in rows:
        for a in row['contract']['agents']:
            signature=digest(a)
            if signature in seen:continue
            seen.add(signature)
            lines.append('| '+row['contract']['episode_id']+' | '+a['agent_id']+' | '+', '.join(a['observable_state'])+' | '+', '.join(a['writable_resources'])+' | '+', '.join(a['tools'])+' |')
    lines+=['','上表对字段相同的主体去重；逐输入权限仍以 contracts.json 为准。服务回执由可信执行器写入，不授权主体直接写评分字段。',
            '','## 初态、容量与外源事件','']
    for row in rows:
        e=row['contract']
        lines += [f"### {e['episode_id']}",'',f"容量字段：{e['home']['resources']['max_power_kw']}；命令延迟：{e['simulation'].get('command_latency_ms','未声明')} ms。",
                  '', '```json',json.dumps({'initial_state':e['initial_state'],'events':e.get('exogenous_events',[]),
                                           'simulation':e['simulation'],'constraints':e.get('constraints',[]),'goals':e.get('goals',[])},ensure_ascii=False,indent=2),'```','']
    return '\n'.join(lines).rstrip()+'\n'


def differences(a,b,path=''):
    if isinstance(a,dict) and isinstance(b,dict):
        out=[]
        for k in sorted(set(a)|set(b)):
            if k in ('episode_id','base_episode_id','pairing'):continue
            out+=differences(a.get(k),b.get(k),path+'.'+k if path else k)
        return out
    if isinstance(a,list) and isinstance(b,list) and len(a)==len(b):
        return [d for i,(x,y) in enumerate(zip(a,b)) for d in differences(x,y,f'{path}[{i}]')]
    return [] if a==b else [{'path':path,'before':a,'after':b}]


def bundle():
    rows=inputs()
    certs=[]
    for r in rows:
        if r['group'].startswith('C3-'):
            cert=feasible(r['contract']);verify_witness(r['contract'],cert)
            certs.append({'episode_id':r['contract']['episode_id'],'certificate':cert})
    contracts={'phase':'A_design_only','independent_acceptance':None,
               'scope':'71 development configurations, 9 review groups; not independent structure count; no heldout/result reads',
               'rows':rows}
    pairs=[]
    by_id={r['contract']['episode_id']:r for r in rows}
    for r in rows:
        eid=r['contract']['episode_id']
        targets=[]
        if r['group'].startswith('C1-') and '-CONFLICT' in eid:targets.append(eid.replace('-CONFLICT','-SAFE'))
        if r['group'].startswith('C3-'):
            if '-competition-' in eid:targets.append(eid.replace('-competition-','-no_competition-'))
            if eid.endswith('-base'):targets.append(eid[:-4]+'loose')
            if eid.endswith('-simultaneous'):targets.append(eid[:-12]+'late')
        if r['group']=='C2-ROOM' and eid.endswith('-immediate'):targets.append(eid[:-9]+'after_ventilation')
        if r['group']=='C2-ROOM' and eid.startswith('ROOM-1600-'):targets.append(eid.replace('ROOM-1600-','ROOM-850-'))
        if eid=='DEP-LAUNDRY-EARLY_REQUEST':targets+=['DEP-LAUNDRY-LATE_REQUEST','DEP-LAUNDRY-TIGHT_DEADLINE','DEP-LAUNDRY-FAILED_WASH']
        if eid=='DEP-LAUNDRY-CAPACITY_TIGHT':targets.append('DEP-LAUNDRY-CAPACITY_SAFE')
        if eid=='DEP-LAUNDRY-CANCEL_WASH':targets.append('DEP-LAUNDRY-RESTART_WASH')
        if r['group'].startswith('C4-') and '-NOEVENT-' in eid:
            targets += [eid.replace('-NOEVENT-',f'-{c}-') for c in ('PRESTART','INFLIGHT','POSTCOMPLETE','UNRELATED')]
        for target in targets:
            assert target in by_id,target
            pairs.append({'group':r['group'],'before_id':eid,'after_id':target,
                          'contract_differences':differences(r['contract'],by_id[target]['contract'])})
    data={f'{OUT}/contracts.json':contracts,f'{OUT}/feasibility.json':{'phase':'A_offline_witnesses_not_method_results','entries':certs},
          f'{OUT}/pair_changes.json':{'note':'actual field differences, metadata excluded; not all variants are single-factor or independent structures','pairs':pairs}}
    for g in GROUPS:data[f'{OUT}/{g}.md']=card(g,[r for r in rows if r['group']==g])
    data[f'{OUT}/manifest.json']={'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'artifact_sha256':{p:hashlib.sha256(serialize(v).encode()).hexdigest() for p,v in data.items()},
        'results_read':0,'heldout_episode_content_read':0,'api_calls':0,'acceptance':None}
    return data


def serialize(value):
    return value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2)+'\n'


if __name__=='__main__':
    data=bundle()
    if len(sys.argv)==1:
        certs=data[f'{OUT}/feasibility.json']['entries']
        print(json.dumps({'paths':list(data),'configurations':71,'C3_certificates':len(certs),
                          'unestablished_modes':sum(x['status']!='witness_found' for c in certs for x in c['certificate']['mode_witnesses'])}))
    else:
        content=serialize(data[sys.argv[1]]);offset=int(sys.argv[2]);limit=22000
        print(json.dumps({'text':content[offset:offset+limit],'next':offset+limit if offset+limit<len(content) else None},ensure_ascii=True))
