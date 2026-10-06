import json,csv,hashlib,collections
from pathlib import Path
R=Path('.'); B=R/'docs/f1_aggregation_v1_20261004'; O=Path('outputs')
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
audit=read(O/'F1_AGGREGATION_V1_AUDIT_20261004.json')
for p,h in audit['reviewed_sha256'].items():
    assert hashlib.sha256((R/p).read_bytes()).hexdigest()==h,p
rows=[r for p in sorted(B.glob('D-F1-*.json')) for r in read(p)['runs']]
config=[]
for eid in sorted({r['episode_id'] for r in rows}):
    for policy in sorted({r['policy'] for r in rows}):
        rs=[r for r in rows if r['episode_id']==eid and r['policy']==policy]
        config.append({'config':eid,'policy':policy,'orders':len(rs),'required':sum(r['denominators']['required'] for r in rs),'completed':sum(r['denominators']['completed'] for r in rs),'timely':sum(r['denominators']['timely'] for r in rs),'reject':[r['metrics']['action_rejected_count'] for r in rs],'defer':[r['metrics']['coordination_defer_count'] for r in rs],'retry':[r['metrics']['retry_queued_count'] for r in rs],'wait_ms':[[r['order'],{t:v['task_start_wait_ms'] for t,v in r['tasks'].items()}] for r in rs],'all_finish_ms':[r['metrics']['whole_house_completion_ms'] for r in rs]})
comparisons={};tasks=[]
for kind in ('policy','capacity','deadline','return_order'):
    ps=read(B/f'pairs_{kind}.json')['pairs'];stats={}
    for m in ('service_rate','timely_service_rate','action_rejected_count','coordination_defer_count','whole_house_completion_ms'):
        vs=[p['scalar_deltas'][m]['value'] for p in ps]
        stats[m]={'negative':sum(v is not None and v<0 for v in vs),'zero':sum(v==0 for v in vs),'positive':sum(v is not None and v>0 for v in vs),'null':sum(v is None for v in vs),'min':min((v for v in vs if v is not None),default=None),'max':max((v for v in vs if v is not None),default=None)}
    comparisons[kind]=stats
    for p in ps:
        times=p['conditional_time'];a,b=times['completed_task_ids_by_arm']
        for t in times['common_task_ids']:
            tasks.append({'kind':kind,'left':p['left'],'right':p['right'],'task':t,'E':len(times['required_task_ids']),'common':len(times['common_task_ids']),**{m:times['metrics'][m]['per_task_values'][t][1]-times['metrics'][m]['per_task_values'][t][0] for m in times['metrics']}})
fields=list(tasks[0])
with (O/'F1_FINDINGS_TASK_DELTAS_20261004.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(tasks)
out={'configuration_policy_table':config,'comparison_descriptions':comparisons,'accepted_source_hashes_verified':True,'descriptive_only':True}
out['witnesses']=[{'slot':r['slot_id'],'tasks':r['tasks'],'metrics':r['metrics']} for r in rows if r['episode_id']=='D-F1-02-competition-base' or (r['episode_id']=='D-F1-01-competition-base' and r['order']==0)]
out['source_sha256']={str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in B.glob('*.json') if p.name!='author_verification.json'}
assert all(r['all_completed'] for r in rows)
assert all(r['metrics']['executed_capacity_violation_duration_ms']==0 and r['metrics']['excess_resource_unit_ms']==0 for r in rows)
assert all(d['execution_ms']==0 for d in tasks)
assert all(d['task_start_wait_ms']==0 and d['completion_latency_ms']==0 for d in tasks if d['kind']=='deadline')
out['verified_checks']={'all72complete':True,'executed_capacity_violation_zero_all72':True,'paired_task_execution_duration_unchanged':True,'deadline_pairs_wait_and_completion_unchanged':True}
(O/'F1_FINDINGS_DATA_20261004.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'configuration_policy_table':[{k:v for k,v in r.items() if k!='wait_ms'} for r in config],'comparisons':comparisons},ensure_ascii=False,indent=2))
