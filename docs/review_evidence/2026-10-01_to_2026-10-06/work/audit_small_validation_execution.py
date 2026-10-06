import json,hashlib,copy,sys,collections,math
from pathlib import Path
sys.dont_write_bytecode=True
R=Path('.');O=Path('outputs');B=R/'docs/small_validation_execution_v1_20261005'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
checks=[]
def ck(v,s):checks.append({'check':s,'passed':bool(v)})
def eq(a,b):
    if isinstance(a,dict):return isinstance(b,dict) and a.keys()==b.keys() and all(eq(v,b[k]) for k,v in a.items())
    if isinstance(a,list):return isinstance(b,list) and len(a)==len(b) and all(eq(v,w) for v,w in zip(a,b))
    if type(a) in (int,float) and type(b) in (int,float):return math.isclose(a,b,abs_tol=1e-9,rel_tol=1e-12)
    return a==b

plan=read(R/'docs/small_validation_plan_v1_20261005/plan.json');rules=read(R/'docs/small_validation_plan_v1_20261005/execution_statistics_addendum.json')
freeze=read(R/'docs/small_validation_plan_v1_20261005/freeze_20261005.json');prior=read(O/'SMALL_VALIDATION_V1_DESIGN_AUDIT_20261005.json')
ck(freeze['reviewed_sha256']=={p.replace('\\','/'):h for p,h in prior['reviewed_sha256'].items()},'frozen exact eleven independently accepted materials')
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
        d=ns['audit'](ep,r,str(path.relative_to(R)),ri,'main');ck(not d['errors'],sid+' independently replayed complete input state permissions receipts')
        for cj,call in enumerate(r['calls']):
            q=call['request'];tool=next(x for x in q['available_actions'] if x['operation']=='prepare')
            req=[{**x,'range_min':None,'range_max':None} for x in tool['preconditions']]
            decision={'response_type':'action_proposal','actions':[{'proposal_id':q['request_id']+':0','target':tool['target'],'operation':'prepare','parameters':[],'based_on_state_version':q['state_version'],'requires':req,'estimated_duration_ms':tool['cost_contract']['duration_ms'],'estimated_power_kw':tool['cost_contract']['resource_units']}],'accepted_proposal_ids':[],'rejected_proposal_ids':[],'defer_until_ms':None,'reason_code':'goal_progress'}
            ck(call['decision']==decision,sid+f' call{cj} full decision uses public capability only')
        for ei,e in enumerate(ev):
            if e['type']=='action_rejected':
                load=sum(x['units'] for x in d['intervals'] if x['start_event']<ei<x['end_event']);g=next(g for g in ep['action_grounding'] if g['task_id']==e['task_id'] and g['operation']=='prepare')
                version=ep['initial_state']['version']+sum(x['type'] in ('state_update','action_completed') for x in ev[:ei])
                ck(e['reason']=='shared_gate_capacity' and load+g['power_kw']>ep['home']['resources']['max_power_kw'] and e['state_version']==version,sid+f' e{ei} safe rejection actual load/version')
        ck((r['evaluation_episode_id'],r['policy'])==(item['config_id'],item['policy']),sid+' actual row identity')
        count=collections.Counter();affected=collections.defaultdict(set);reasons=collections.defaultdict(collections.Counter)
        rel={};ret={};starts={};done={}
        for i,e in enumerate(ev):
            k=e['type'];tid=e.get('task_id');count[k]+=1
            if tid is not None:affected[k].add(tid)
            if 'reason' in e:reasons[k][str(e['reason'])]+=1
            if k=='coordination_decision':count['coordination_'+e['decision']]+=1;affected['coordination_'+e['decision']].add(tid)
            if k=='task_released':rel[tid]=(i,e['timestamp_ms'])
            if k=='proposal_returned':ret[tid]=(i,e['timestamp_ms'])
            if k=='action_started' and e['operation']=='prepare':starts[tid]=(i,e['timestamp_ms'])
            if k=='action_completed' and e['operation']=='prepare':done[tid]=(i,e['timestamp_ms'])
        per={}
        for tid,t in tasks.items():
            ri0,R0=rel[tid];pi,P=ret[tid];si,S=starts.get(tid,(None,None));fi,F=done.get(tid,(None,None))
            per[tid]={'release_ms':R0,'deadline_ms':t['completion_deadline_ms'],'proposal_return_ms':P,'start_ms':S,'completion_ms':F,'started':S is not None,'completed':F is not None,'timely':F is not None and F<=t['completion_deadline_ms'],'logical_proposal_return_ms':P-R0,'proposal_to_start_ms':S-P if S is not None else None,'task_start_wait_ms':S-R0 if S is not None else None,'execution_ms':F-S if F is not None else None,'completion_latency_ms':F-R0 if F is not None else None,'tardiness_ms':max(0,F-t['completion_deadline_ms']) if F is not None else None,'event_indices':{'release':ri0,'return':pi,'start':si,'completion':fi},'null_reasons':{'start':None if S is not None else 'not_started','completion':None if F is not None else 'not_completed'},'coordination_compute_ms':None,'API_wallclock_ms':None,'unobserved_reason':'not_instrumented'}
        intervals=[{'task_id':it['task_id'],'proposal_id':ev[it['start_event']]['proposal_id'],'start_event_index':it['start_event'],'completion_event_index':it['end_event'],'start_ms':it['start_ms'],'end_ms':it['end_ms'],'units':it['units'],'operation':ev[it['start_event']]['operation']} for it in d['intervals']]
        cap=ep['home']['resources']['max_power_kw'];safety=[];last=0
        for i,e in enumerate(ev):
            now=e['timestamp_ms'];load=sum(it['units'] for it in intervals if it['start_ms']<=last<it['end_ms'])
            if now>last and load>cap:safety.append({'start_ms':last,'end_ms':now,'load_units':load,'capacity_units':cap,'next_event_index':i})
            last=now
        validity=[];state=copy.deepcopy(ep['initial_state']['values']);before={}
        for i,e in enumerate(ev):
            tid=e.get('task_id')
            if e['type']=='state_update':
                if e.get('source')=='action_started':before[tid]=copy.deepcopy(state)
                for p,v in e['patch'].items():ns['put'](state,p,v)
            elif e['type']=='action_started':
                prestate=before.pop(tid,state)
                validity.append({'task_id':tid,'event_index':i,'valid':all(ns['holds'](prestate,q) for q in e['requires'])})
            elif e['type']=='action_completed':
                for p,v in e['effects'].items():ns['put'](state,p,v)
        n=len(tasks);c=len(done);t=sum(p['timely'] for p in per.values());E=list(tasks);early=[t for t in E if t!='water'];L=per['water']['release_ms']
        metrics={'service_rate':c/n,'timely_service_rate':t/n,'executed_capacity_violation_duration_ms':sum(it['end_ms']-it['start_ms'] for it in safety),'excess_resource_unit_ms':sum((it['end_ms']-it['start_ms'])*(it['load_units']-cap) for it in safety),'whole_house_completion_ms':max(p['completion_ms'] for p in per.values())-ep['episode_release_at_ms'] if c==n else None,**{k:count[k.removesuffix('_count')] for k in ('coordination_defer_count','action_rejected_count','retry_queued_count','retry_scheduled_count')}}
        subsets={name:{'required_task_ids':ids,'denominators':{'required':len(ids),'completed':sum(per[t]['completed'] for t in ids),'timely':sum(per[t]['timely'] for t in ids)},'service_rate':sum(per[t]['completed'] for t in ids)/len(ids),'timely_service_rate':sum(per[t]['timely'] for t in ids)/len(ids)} for name,ids in [('early',early),('water',['water'])]}
        bg=None
        if L:
            crossing=[{**it,'remaining_ms':it['end_ms']-L} for it in intervals if it['task_id'] in early and it['operation']=='prepare' and it['start_ms']<L<it['end_ms']];reservations=[]
            for i,x in enumerate(ev):
                if x['type']!='action_reserved' or not x['timestamp_ms']<L<x['scheduled_start_ms']:continue
                outcomes=[(j,e) for j,e in enumerate(ev) if j>i and e['type'] in ('action_started','action_rejected') and e.get('proposal_id')==x['proposal_id'] and e['timestamp_ms']==x['scheduled_start_ms']]
                later=[(j,e) for j,e in enumerate(ev) if j>i and e['type']=='action_started' and e.get('proposal_id')==x['proposal_id']]
                ck(len(outcomes)==1 and len(later)<=1,sid+f' reservation e{i} unique scheduled outcome/start');j,e=outcomes[0]
                reservations.append({'task_id':x['task_id'],'proposal_id':x['proposal_id'],'reservation_event_index':i,'reserved_ms':x['timestamp_ms'],'planned_start_ms':x['scheduled_start_ms'],'scheduled_disposition_event_index':j,'scheduled_disposition':e['type'],'actual_start_ms':later[0][1]['timestamp_ms'] if later else None,'actual_start_event_index':later[0][0] if later else None,'counts_as_physical_load_at_L':False})
            water_events={k:next(({'event_index':i,'timestamp_ms':e['timestamp_ms']} for i,e in enumerate(ev) if e.get('task_id')=='water' and e['type']==k and e['timestamp_ms']>=L),None) for k in ('task_released','proposal_returned','action_started','action_completed','action_rejected','retry_queued','retry_scheduled')}
            bg={'release_ms':L,'interpretation':'descriptive_resource_background_not_causal_or_unavoidable','early_history':[{'task_id':tid,'start_ms':per[tid]['start_ms'],'end_ms':per[tid]['completion_ms'],'started_before_L':per[tid]['start_ms'] is not None and per[tid]['start_ms']<L,'event_indices':per[tid]['event_indices']} for tid in early],'crossing_actual_intervals':crossing,'physical_units_crossing_L':sum(it['units'] for it in crossing),'capacity_units':cap,'water_required_units':next(g['power_kw'] for g in ep['action_grounding'] if g['task_id']=='water' and g['operation']=='prepare'),'future_reservations_created_before_L':reservations,'first_water_events':water_events}
        out={**item,'subsets':subsets,'arrival_background':bg,'required_task_ids':E,'completed_task_ids':[tid for tid in E if tid in done],'denominators':{'required':n,'completed':c,'timely':t},'metrics':metrics,'auxiliary':{'conditional_timely_rate':t/c if c else None,'conditional_timely_null_reason':None if c else 'no_completed_requests','own_completed_means':{m:sum(per[tid][m] for tid in done)/c if c else None for m in tm}},'all_completed':c==n,'all_timely':t==n,'tasks':per,'event_counts':dict(count),'affected_task_ids':{k:sorted(v) for k,v in affected.items()},'event_reason_counts':{k:dict(v) for k,v in reasons.items()},'physical_intervals':intervals,'capacity_violation_intervals':safety,'preconditions_at_start':validity,'invalid_precondition_start_count':sum(not p['valid'] for p in validity),'coordination_compute_ms':None,'API_wallclock_ms':None,'unobserved_reason':'not_instrumented'}

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
def effect(y):
    if len(y)==2:return {'right_minus_left':y[1]-y[0]}
    return {'capacity_effect_simultaneous':y[2]-y[0],'capacity_effect_late':y[3]-y[1],'release_effect_tight':y[1]-y[0],'release_effect_adequate':y[3]-y[2],'interaction':(y[3]-y[1])-(y[2]-y[0])}
def times(rs,subset=None):
    E=rs[0]['required_task_ids'];E=[t for t in E if subset is None or t in subset];K=[t for t in E if all(t in r['completed_task_ids'] for r in rs)]
    out={'required_task_ids':E,'completed_task_ids_by_arm':[[t for t in E if t in r['completed_task_ids']] for r in rs],'common_task_ids':K,'common_count':len(K),'required_count':len(E),'coverage':len(K)/len(E),'excluded_tasks':[{'task_id':t,'not_completed_arm_indices':[i for i,r in enumerate(rs) if t not in r['completed_task_ids']]} for t in E if t not in K],'eligible':bool(K),'null_reason':None if K else 'no_common_completed_requests','metrics':{}}
    for m in tm:
        y=[sum(r['tasks'][t][m] for t in K)/len(K) if K else None for r in rs]
        out['metrics'][m]={'arm_means':y,'effects':effect(y) if K else dict.fromkeys(effect([0]*len(rs)),None),'null_reason':None if K else 'no_common_completed_requests','per_task_values':{t:[r['tasks'][t][m] for r in rs] for t in K}}
    return out
def compare(s,four=False):
    rs=[expected[x] for x in s['slots']] if four else [expected[s['left']],expected[s['right']]];scalar={}
    for m in rules['primary_rates']+rules['process_allowlist']+['whole_house_completion_ms']:
        y=[r['metrics'][m] for r in rs];ok=m!='whole_house_completion_ms' or all(r['all_completed'] for r in rs)
        scalar[m]={'arm_values':y,'effects':effect(y) if ok else dict.fromkeys(effect([0]*len(rs)),None),'null_reason':None if ok else ('not_all_required_completed_in_four_cells' if four else 'not_all_required_completed_in_both_arms')}
    layers={name:{'required_task_ids':rs[0]['subsets'][name]['required_task_ids'],'denominators_by_arm':[r['subsets'][name]['denominators'] for r in rs],'rates':{m:{'arm_values':[r['subsets'][name][m] for r in rs],'effects':effect([r['subsets'][name][m] for r in rs])} for m in rules['primary_rates']}} for name in ('early','water')}
    return {**s,'scalar_comparison':scalar,'fixed_subset_service':layers,'conditional_time':times(rs),'conditional_subset_time':{name:times(rs,rs[0]['subsets'][name]['required_task_ids']) for name in layers},'whole_house_clock_note':'global_schedule_span_not_own_release_response_or_future_information_value'}

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
submitted_findings=read(B/'findings_evidence.json')
for finding,got in zip(findings,submitted_findings['pairs']):
    spec=finding['pair'];a,b=[expected[spec[k]] for k in ('left','right')]
    want={'left':spec['left'],'right':spec['right'],'factor':spec['factor'],'value_ms':b['value_ms'],'capacity_units':finding['capacity'],'absolute_start_and_finish_unchanged_for_all_tasks':finding['same_execution'],'water':{'left':a['tasks']['water'],'right':b['tasks']['water']},'whole_house':{'left':a['metrics']['whole_house_completion_ms'],'right':b['metrics']['whole_house_completion_ms']},'timely_service_rate_delta':b['metrics']['timely_service_rate']-a['metrics']['timely_service_rate']}
    ck(got==want,'findings full pair '+spec['right'])
sys.path.insert(0,str(R));from homecoord_bench.task_revision import small_validation_execution_v1 as author_adapter
author_adapter.run_event_simulation=lambda *a,**k:(_ for _ in ()).throw(AssertionError('simulation forbidden in review'))
ck(eq(author_adapter.statistics(),stat),'full artifact reproduction simulation disabled after independent recount')
paths=list(manifest['new_source_sha256'])+list(manifest['artifact_sha256'])+['docs/SMALL_VALIDATION_V1_EXECUTION_REVIEW_PACKET_2026-10-05.md','docs/small_validation_execution_v1_20261005/manifest.json','docs/small_validation_execution_v1_20261005/author_verification.json']
result={'errors':[c['check'] for c in checks if not c['passed']],'checks':checks,'configurations':configs,'baseline_evidence':baseline_evidence,'findings_inventory':inventory,'pair_findings':findings,'reviewed_sha256':{p:sha(R/p) for p in paths},'new_simulations':0,'api_calls':0}
(O/'SMALL_VALIDATION_V1_EXECUTION_AUDIT_20261005.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
print(json.dumps({'checks':len(checks),'errors':result['errors'],'inventory':inventory},ensure_ascii=False))
