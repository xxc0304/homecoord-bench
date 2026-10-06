import json, hashlib, re
from pathlib import Path
BASE=Path(r'docs\design_review_20261001')
c=json.loads((BASE/'contracts.json').read_text(encoding='utf-8'))
p=json.loads((BASE/'pair_changes.json').read_text(encoding='utf-8'))
f=json.loads((BASE/'feasibility.json').read_text(encoding='utf-8'))
m=json.loads((BASE/'manifest.json').read_text(encoding='utf-8'))
rows={r['contract']['episode_id']:r['contract'] for r in c['rows']}
bad_hash=[name for name,h in m['artifact_sha256'].items() if hashlib.sha256((BASE/Path(name).name).read_bytes()).hexdigest()!=h]
def diff(a,b,path=''):
    if isinstance(a,dict) and isinstance(b,dict):
        out=[]
        for k in sorted(a.keys()|b.keys()):
            if k in ['episode_id','base_episode_id','pairing']:continue
            q=f'{path}.{k}' if path else k
            if k not in a or k not in b:out.append(q)
            else:out+=diff(a[k],b[k],q)
        return out
    if isinstance(a,list) and isinstance(b,list):
        if len(a)!=len(b):return [path]
        return [v for i,(x,y) in enumerate(zip(a,b)) for v in diff(x,y,f'{path}[{i}]')]
    return [] if a==b else [path]
pair_errors=[]
def resolve(obj,path):
    for part in re.findall(r'[^.\[\]]+',path):
        obj=obj[int(part)] if isinstance(obj,list) else obj[part]
    return obj
for pair in p['pairs']:
    actual=set(diff(rows[pair['before_id']],rows[pair['after_id']]))
    reported={d['path'] for d in pair['contract_differences']}
    if actual!=reported:pair_errors.append({'pair':[pair['before_id'],pair['after_id']],'only_actual':sorted(actual-reported),'only_reported':sorted(reported-actual)})
    for d in pair['contract_differences']:
        if resolve(rows[pair['before_id']],d['path'])!=d['before'] or resolve(rows[pair['after_id']],d['path'])!=d['after']:
            pair_errors.append({'pair':[pair['before_id'],pair['after_id']],'value_mismatch':d['path']})
errors=[]; witnesses=0; min_slack={}
for entry in f['entries']:
    ep=rows[entry['episode_id']]; tasks={t['task_id']:t for t in ep['task_stream']}
    grounds={(g['task_id'],g['operation']):g for g in ep['action_grounding']}
    cap=ep['home']['resources']['max_power_kw']
    for w in entry['certificate']['mode_witnesses']:
        witnesses+=1
        if w['status']!='witness_found':errors.append([ep['episode_id'],'no witness']);continue
        sched=w['schedule']
        if len(sched)!=len(tasks) or {s['task_id'] for s in sched}!=set(tasks):errors.append([ep['episode_id'],'task coverage'])
        for s in sched:
            t=tasks[s['task_id']];g=grounds[(s['task_id'],s['operation'])]
            if s['operation']!=w['modes'][s['task_id']]:errors.append([ep['episode_id'],'mode mismatch'])
            if not any(a['operation']==s['operation'] for a in t['acceptable_actions']):errors.append([ep['episode_id'],'illegal mode'])
            if s['start_ms']<t['release_at_ms']+2100 or s['end_ms']-s['start_ms']!=g['duration_ms'] or s['units']!=g['power_kw'] or s['end_ms']>t['completion_deadline_ms']:errors.append([ep['episode_id'],'timing/resources'])
            slack=t['completion_deadline_ms']-s['end_ms'];min_slack[ep['episode_id']]=min(min_slack.get(ep['episode_id'],float('inf')),slack)
        for at in sorted({s['start_ms'] for s in sched}|{s['end_ms'] for s in sched}):
            if sum(s['units'] for s in sched if s['start_ms']<=at<s['end_ms'])>cap:errors.append([ep['episode_id'],'capacity'])
verification={'manifest_sha256':hashlib.sha256((BASE/'manifest.json').read_bytes()).hexdigest(),'artifact_hash_count':len(m['artifact_sha256']),'counts':{g:sum(r['group']==g for r in c['rows']) for g in sorted({r['group'] for r in c['rows']})},'hash_mismatches':bad_hash,'pair_count':len(p['pairs']),'pair_errors':pair_errors,'certificate_entries':len(f['entries']),'witness_count':witnesses,'witness_errors':errors,'min_slack_ms':min_slack,'scope':'Read-only Phase A check; ignored episode_id, base_episode_id and pairing metadata. No executor, policy result, heldout input or scoring code read.'}
Path('outputs').mkdir(exist_ok=True)
Path('outputs/phase_a_verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(verification,ensure_ascii=False,indent=2))
if __name__=='__main__':
    raise SystemExit(0)
for group in ['C1-LIGHT','C1-BLINDS','C3-F1','C3-F2','C3-F3','C4-CLEAN','C4-RAIN','DEPENDENCY','C2-ROOM']:
    rs=[r['contract'] for r in c['rows'] if r['group']==group]
    print('\nGROUP',group)
    if group in ['C4-CLEAN','C4-RAIN','DEPENDENCY']:
        for ep in rs:
            print(json.dumps({'id':ep['episode_id'],'initial':ep['initial_state'],'events':ep['exogenous_events'],'simulation':ep['simulation'],'rules':ep['conflict_rules']},ensure_ascii=False))
    else:
        ep=rs[0]
        print(json.dumps({'id':ep['episode_id'],'grounding':ep['action_grounding'],'rules':ep['conflict_rules'],'simulation':ep['simulation']},ensure_ascii=False))
    print('PAIR PATHS',json.dumps([{'ids':[v['before_id'],v['after_id']],'paths':[d['path'] for d in v['contract_differences']]} for v in p['pairs'] if v['group']==group],ensure_ascii=False))
