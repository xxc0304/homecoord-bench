from pathlib import Path
p=Path('work/audit_f2_aggregation_v1.py').read_text(encoding='utf8')
head=p[:p.index('freeze=read(')]
head=head.replace("B=R/'docs/f2_aggregation_v1_20261004'","B=R/'docs/small_validation_execution_v1_20261005'")
setup='''
plan=read(R/'docs/small_validation_plan_v1_20261005/plan.json');rules=read(R/'docs/small_validation_plan_v1_20261005/execution_statistics_addendum.json')
freeze=read(R/'docs/small_validation_plan_v1_20261005/freeze_20261005.json');prior=read(O/'SMALL_VALIDATION_V1_DESIGN_AUDIT_20261005.json')
ck(freeze['reviewed_sha256']=={p.replace('\\\\','/'):h for p,h in prior['reviewed_sha256'].items()},'frozen exact eleven independently accepted materials')
for section in ('reviewed_sha256','protected_sha256','source_sha256','external_review_sha256'):
    for path,h in freeze[section].items():ck(sha(R/path)==h,'freeze '+path)
author=read(B/'author_verification.json');manifest=read(B/'manifest.json')
for section in ('new_source_sha256','artifact_sha256'):
    for path,h in manifest[section].items():ck(sha(R/path)==h,'submitted '+path)
for path,h in author['protected_sha256'].items():ck(sha(R/path)==h,'protected '+path)
src=Path('work/audit_f2_v7.py').read_text(encoding='utf8').split('details=[]')[0]
src=src.replace("+100,f'e{j} reservation delay'", "+e['simulation']['command_latency_ms'],f'e{j} reservation delay'")
src=src.replace("for k,v in r['audit']['recount'].items():", "for k,v in r.get('audit',{}).get('recount',{}).items():")
ns={};exec(compile(src,'independent_f2_replay_adapted_command_clock','exec'),ns)
ck(not ns['hash_errors'],'unchanged legacy engine inputs and traces')
saved=read(B/'statistics.json')['runs'];expected={};raw={};evidence=[];tm=rules['time_allowlist'];configs=[];baseline_evidence=[]
for ci,config in enumerate(plan['configurations']):
    path=B/f'config_{ci:02d}.json';doc=read(path);ep=copy.deepcopy(ns['eps'][config['source_episode_id']]);w=ep['task_stream'][-1];v=config['value_ms'];f=config['factor'];budget=w['completion_deadline_ms']-w['release_at_ms']
    if f=='water_budget_offset_ms':w['completion_deadline_ms']+=v;w['goal']=w['goal'].replace('within '+str(budget)+' ms','within '+str(budget+v)+' ms')
    if f=='water_release_offset_ms':w['release_at_ms']+=v;w['completion_deadline_ms']+=v;ep['exogenous_events'][0]['at_ms']+=v
    if f=='command_latency_ms':ep['simulation']['command_latency_ms']=v
    public=ep['exogenous_events'][0]['patch']['coordination_context']['requests'][-1];public['release_at_ms']=w['release_at_ms'];public['deadline_ms']=w['completion_deadline_ms']
    digest=lambda obj:hashlib.sha256(json.dumps(obj,sort_keys=True,ensure_ascii=True).encode()).hexdigest()
    ck(digest(ep)==config['derived_episode_sha256'],config['config_id']+' independent derived full input')
    ep['episode_id']=config['config_id'];ck(ep==doc['input'] and digest(ep)==doc['materialized_input_sha256'],config['config_id']+' actual input and hash')
    ck(doc['entry_sha256']==sha(R/'homecoord_bench/task_revision/small_validation_execution_v1.py') and doc['freeze_sha256']==sha(R/'docs/small_validation_plan_v1_20261005/freeze_20261005.json'),config['config_id']+' code freeze binding')
    ck([r['policy'] for r in doc['runs']]==['GateRetryRule','ConstraintCoordinator','DeadlineAwareCoordinator'],config['config_id']+' exact three policies')
    configs.append({'config_id':config['config_id'],'file':str(path.relative_to(R)),'verdict':'符合设计','runs':[]})
    for ri,r in enumerate(doc['runs']):
        sid=config['config_id']+'|'+r['policy'];item={'slot_id':sid,'config_id':config['config_id'],'policy':r['policy'],'source_episode_id':config['source_episode_id'],'factor':config['factor'],'value_ms':config['value_ms']};ev=r['trace']['events'];tasks={t['task_id']:t for t in ep['task_stream']}
        if config['factor']=='baseline':
            old=next(z for z in read(R/('homecoord_bench/task_revision/fixtures/f2_v7/runs/'+config['source_episode_id']+'.json'))['runs'] if z['policy']==r['policy'])
            mask=lambda x:{k:v for k,v in x.items() if k not in ('trace_id','episode_id')}
            ck(r['calls']==old['calls'] and mask(r['trace'])==mask(old['trace']),sid+' exact full baseline excluding two outer fields only')
            baseline_evidence.append({'slot_id':sid,'calls_equal':r['calls']==old['calls'],'trace_equal':mask(r['trace'])==mask(old['trace'])})
'''
block=p[p.index('    d=ns[\'audit\']'):p.index('\ndef effect(')]
block=block.replace("item['source_path'],ri", "str(path.relative_to(R)),ri")
block=block.replace("    evidence.append(","    evidence.append(")
# Indent the old independent event reconstruction one level into config/policy loop.
block='\n'.join('    '+line if line else '' for line in block.splitlines())+'\n'
block=block[:block.index('        ck(eq(out,saved[sid])')]+'''
        clocks=[];C=ep['simulation']['command_latency_ms']
        for i,e in enumerate(ev):
            if e['type'] not in ('action_started','action_rejected'):continue
            pid=e['proposal_id'];tid=e['task_id'];now=e['timestamp_ms'];reservations=[(j,z) for j,z in enumerate(ev[:i]) if z['type']=='action_reserved' and z['proposal_id']==pid and z['task_id']==tid and z['scheduled_start_ms']==now]
            ck(len(reservations)==1,sid+f' e{i} unique matching attempted command');j,z=reservations[0];Q=z['timestamp_ms'];returns=[(k,x) for k,x in enumerate(ev[:j]) if x['type']=='proposal_returned' and x['task_id']==tid];pi,pr=returns[0]
            previous=[(k,x) for k,x in enumerate(ev[:j]) if x['type'] in ('action_started','action_rejected') and x.get('proposal_id')==pid]
            ck(len(returns)==1 and now>=Q+C and Q>=pr['timestamp_ms'],sid+f' e{i} command lower bound {C}')
            g=next(g for g in ep['action_grounding'] if g['task_id']==tid and g['operation']=='prepare');ck(z['duration_ms']==g['duration_ms'] and z['power_kw']==g['power_kw'],sid+f' e{i} reservation costs')
            if previous:
                pk,px=previous[-1];rr=[(k,x) for k,x in enumerate(ev[j+1:i],j+1) if x['type']=='retry_scheduled' and x['task_id']==tid and x['timestamp_ms']==Q and x['start_at_ms']==now];qq=[(k,x) for k,x in enumerate(ev[:j]) if x['type']=='retry_queued' and x['task_id']==tid and pk<k and x['timestamp_ms']<=Q]
                ck(r['policy']=='GateRetryRule' and px['type']=='action_rejected' and len(rr)==1 and len(qq)==1,sid+f' e{i} exact prior rejection queue reservation retry')
            clocks.append({'task_id':tid,'proposal_id':pid,'outcome_event_index':i,'reservation_event_index':j,'return_event_index':pi,'reservation_created_ms':Q,'attempt_ms':now,'command_latency_ms':C,'retry':bool(previous),'outcome':e['type']})
        out['command_clock_evidence']=clocks
        ck(eq(out,saved[sid]),sid+' all independent saved fields');expected[sid]=out;raw[sid]=r
        configs[-1]['runs'].append({'policy':r['policy'],'verdict':'符合设计' if not d['errors'] and eq(out,saved[sid]) else '须修正','events':{tid:val['event_indices'] for tid,val in per.items()},'command_evidence':clocks,'replay_errors':d['errors']})
'''
compare=p[p.index('def effect('):p.index('savedpairs=')]
tail='''
stat=read(B/'statistics.json');ck(len(expected)==84 and set(expected)==set(saved)=={s['slot_id'] for s in plan['run_slots']},'84 fixed unique slots')
ck(len(baseline_evidence)==12 and all(x['calls_equal'] and x['trace_equal'] for x in baseline_evidence),'12 complete baseline reproductions')
ck(len(stat['pairs'])==72,'72 fixed comparisons retained')
for spec,got in zip(plan['pairs'],stat['pairs']):ck(eq(compare(spec),got),'independent full pair '+spec['right'])
findings=[]
for spec in plan['pairs']:
    a,b=[expected[spec[k]] for k in ('left','right')];cap=next(c['capacity_units'] for c in plan['configurations'] if c['config_id']==b['config_id']);same=all(a['tasks'][t][m]==b['tasks'][t][m] for t in a['required_task_ids'] for m in ('start_ms','completion_ms'))
    if spec['factor']=='water_budget_offset_ms':ck(same,spec['right']+' budget no execution change')
    if spec['factor']=='water_release_offset_ms':
        if cap==3:ck(same and b['tasks']['water']['completion_latency_ms']-a['tasks']['water']['completion_latency_ms']==-b['value_ms'],spec['right']+' tight release own clock only')
        else:ck(b['tasks']['water']['completion_ms']-a['tasks']['water']['completion_ms']==b['value_ms'] and b['tasks']['water']['completion_latency_ms']==a['tasks']['water']['completion_latency_ms'],spec['right']+' adequate release execution translated')
    if spec['factor']=='command_latency_ms':ck(b['metrics']['timely_service_rate']==a['metrics']['timely_service_rate'],spec['right']+' command no timely change')
    findings.append({'pair':spec,'capacity':cap,'same_execution':same,'water_by_arm':[x['tasks']['water'] for x in (a,b)]})
inventory={cap:{'runs':0,'all_completed':0,'all_timely':0,'capacity_violations':0} for cap in (3,6)}
for row in expected.values():
    cap=next(c['capacity_units'] for c in plan['configurations'] if c['config_id']==row['config_id']);x=inventory[cap];x['runs']+=1;x['all_completed']+=row['all_completed'];x['all_timely']+=row['all_timely'];x['capacity_violations']+=row['metrics']['executed_capacity_violation_duration_ms']>0
ck(inventory=={3:{'runs':42,'all_completed':42,'all_timely':2,'capacity_violations':0},6:{'runs':42,'all_completed':42,'all_timely':42,'capacity_violations':0}},'independent findings inventory')
sys.path.insert(0,str(R));from homecoord_bench.task_revision import small_validation_execution_v1 as author_adapter
author_adapter.run_event_simulation=lambda *a,**k:(_ for _ in ()).throw(AssertionError('simulation forbidden in review'))
ck(eq(author_adapter.statistics(),stat),'full artifact reproduction simulation disabled after independent recount')
paths=list(manifest['new_source_sha256'])+list(manifest['artifact_sha256'])+['docs/SMALL_VALIDATION_V1_EXECUTION_REVIEW_PACKET_2026-10-05.md','docs/small_validation_execution_v1_20261005/manifest.json','docs/small_validation_execution_v1_20261005/author_verification.json']
result={'errors':[c['check'] for c in checks if not c['passed']],'checks':checks,'configurations':configs,'baseline_evidence':baseline_evidence,'findings_inventory':inventory,'pair_findings':findings,'reviewed_sha256':{p:sha(R/p) for p in paths},'new_simulations':0,'api_calls':0}
(O/'SMALL_VALIDATION_V1_EXECUTION_AUDIT_20261005.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\\n',encoding='utf8')
print(json.dumps({'checks':len(checks),'errors':result['errors'],'inventory':inventory},ensure_ascii=False))
'''
Path('work/audit_small_validation_execution.py').write_text(head+setup+block+compare+tail,encoding='utf8')
