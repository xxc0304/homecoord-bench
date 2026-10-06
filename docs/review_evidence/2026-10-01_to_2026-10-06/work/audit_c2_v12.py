import json,copy,math,base64,zlib,hashlib,sys
from pathlib import Path
sys.dont_write_bytecode=True
R=Path(r'.');O=Path('outputs');B=R/'homecoord_bench/task_revision/fixtures/room_v12';sys.path.insert(0,str(R))
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def get(s,p):
    for k in p.split('.'):s=s[k]
    return s
def put(s,p,v):
    ks=p.split('.')
    for k in ks[:-1]:s=s.setdefault(k,{})
    s[ks[-1]]=copy.deepcopy(v)
def close(x,y):return math.isclose(x,y,rel_tol=1e-8,abs_tol=1e-7)
def physical(t,c,opened,enabled,dt,p):
    # Independently integrate the declared ODE: temperature is evaluated from
    # its analytic solution; Simpson quadrature split at the thermostat hit.
    k=p['exchange_per_s'] if opened else 0;g=p['heat_rate_c_per_s'] if enabled else 0;out=p['outdoor_temp_c'];target=p['target_temp_c']
    def temp(u):return min(target,out+(t-out)*math.exp(-k*u)+g*(-math.expm1(-k*u))/k) if k else min(target,t+g*u)
    cuts=[0,dt]
    if g and temp(dt)>=target and t<target:
        hit=math.log((out+g/k-t)/(out+g/k-target))/k if k else (target-t)/g
        if 0<hit<dt:cuts=[0,hit,dt]
    integral=0
    for left,right in zip(cuts,cuts[1:]):
        h=(right-left)/8;vals=[temp(left+i*h) for i in range(9)]
        integral+=h/3*(vals[0]+vals[-1]+4*sum(vals[1:-1:2])+2*sum(vals[2:-1:2]))
    end=temp(dt);loss=max(0,k*(integral-out*dt));on=(end-t+loss)/g if g else 0
    on=min(dt,max(0,on));energy=p['heater_power_kw']*on/3.6
    cend=max(p['co2_floor_ppm'],c-p['ventilation_rate_ppm_s']*dt) if opened else c
    excess=max(0,c-p['target_co2_ppm']);time=min(dt,excess/p['ventilation_rate_ppm_s']) if opened else dt
    # Area of linear CO2 excess until it reaches zero.
    coarea=(excess+max(0,excess-p['ventilation_rate_ppm_s']*time))*time/2 if opened else excess*dt
    return {'temperature_end_c':end,'co2_end_ppm':cend,'heater_on_equivalent_s':on,'heater_energy_wh':energy,'open_window_heater_wh':energy if opened else 0,'ventilation_temperature_loss_c':loss,'temperature_shortfall_c_s':max(0,target*dt-integral),'co2_excess_ppm_s':coarea}
def expected_request(e,t,state,version):
    a=copy.deepcopy(next(a for a in e['agents'] if a['agent_id']==t['agent_id']));a.update(goal_visibility='local',constraint_visibility='local',policy_constraints=[])
    st={}
    for p in a['observable_state']+a['writable_resources']:put(st,p,get(state,p))
    task={k:copy.deepcopy(t[k]) for k in ('task_id','agent_id','release_at_ms','completion_deadline_ms','priority','goal','demand_rule') if k in t}
    return {'request_id':f'HC-M06:ConstraintCoordinator:{t["task_id"]}','episode_id':'HC-M06','base_episode_id':'HC-M06','architecture':'ConstraintCoordinator','current_time_ms':t['release_at_ms'],'state_version':version,'state':st,'agent':a,'task':task,'goals':[],'constraints':[],'allowed_tools':a['tools'],'available_actions':[{k:z[k] for k in ('agent_id','tool_name','target','operation','parameters','preconditions','cost_contract')} for z in e['tool_catalog'] if z['agent_id']==a['agent_id']],'pending_proposals':[]}
def audit(e,r,file):
    errors=[];tr=r['trace'];res=r['result'];p=e['simulation']['environment'];state=copy.deepcopy(e['initial_state']['values']);version=e['initial_state']['version'];tasks={t['task_id']:t for t in e['task_stream']};gs={g['task_id']:g for g in e['action_grounding']};active={};starts={};done={};skips={};admitted=set();reservations={};pending_close=None;first=None;clock=0;intervals=tr['environment_intervals'];byend={x['end_ms']:x for x in intervals};deadline=None;totals={k:0 for k in ('heater_energy_wh','open_window_heater_wh','ventilation_temperature_loss_c','temperature_shortfall_c_s','co2_excess_ppm_s')};events=[];snap={};calls={c['request']['task']['task_id']:c for c in r['calls']};maxerr=0;close_records=[]
    def ck(ok,msg):
        if not ok:errors.append(msg)
    def num(x,y,msg):
        nonlocal maxerr
        maxerr=max(maxerr,abs(x-y));ck(close(x,y),msg)
    def goal():return get(state,'bedroom.temperature_c')>=21-1e-8 and get(state,'bedroom.co2_ppm')<=900 and get(state,'devices.window')=='closed'
    for i,x in enumerate(tr['events']):
        now=x['timestamp_ms'];kind=x['type'];tid=x.get('task_id');pid=x.get('proposal_id');ck(now>=clock,f'e{i} time order')
        if kind=='state_update' and x['source']=='synthetic_environment':
            seg=byend[now];ck(seg['start_ms']==clock and now>clock,f'e{i} environment interval chronology');opened=get(state,'devices.window')=='open';enabled=get(state,'devices.heater')=='enabled';dt=(now-clock)/1000
            ck(seg['window_open']==opened and seg['heater_enabled']==enabled,f'e{i} actual actuator input')
            num(seg['temperature_start_c'],get(state,'bedroom.temperature_c'),f'e{i} initial temperature');num(seg['co2_start_ppm'],get(state,'bedroom.co2_ppm'),f'e{i} initial CO2')
            calc=physical(get(state,'bedroom.temperature_c'),get(state,'bedroom.co2_ppm'),opened,enabled,dt,p)
            for k,v in calc.items():num(seg[k],v,f'e{i} physical {k}')
            for k in totals:totals[k]+=calc[k]
            num(x['patch']['bedroom.temperature_c'],calc['temperature_end_c'],f'e{i} applied temperature');num(x['patch']['bedroom.co2_ppm'],calc['co2_end_ppm'],f'e{i} applied CO2')
            if now==p['deadline_ms']:deadline={'at_ms':now,'temperature_c':calc['temperature_end_c'],'co2_ppm':calc['co2_end_ppm'],'window_closed':not opened,'totals':copy.deepcopy(totals)}
        if kind=='task_released':ck(now==tasks[tid]['release_at_ms'],f'e{i} release');snap[tid]=(copy.deepcopy(state),version)
        if kind=='proposal_returned':ck(now==tasks[tid]['release_at_ms']+300 and x['response_type']==calls[tid]['decision']['response_type'],f'e{i} proposal')
        if kind=='action_reserved':
            reservations[pid]=x;admitted.add(tid)
            ck(tid!='bedroom_air' or get(state,'bedroom.co2_ppm')>900,f'e{i} admitted unnecessary ventilation')
        if kind=='environment_admission_waiting':
            ck(tid=='bedroom_heat' and p['heat_admission']=='after_ventilation' and (get(state,'devices.window')!='closed' or get(state,'bedroom.co2_ppm')>900),f'e{i} heating admission wait');admitted.add(tid)
        if kind=='action_started':
            g=gs[tid];a=next(a for a in e['agents'] if a['agent_id']==x['agent_id']);tool=next(z for z in e['tool_catalog'] if z['agent_id']==x['agent_id'])
            ck(pid not in active and tid not in done and tid not in skips and now>=tasks[tid]['release_at_ms'],f'e{i} early/closed start')
            ck((x['target'],x['operation'],x['duration_ms'],x['power_kw'])==(g['target'],g['operation'],g['duration_ms'],0) and x['start_effects']=={} and x['completion_effects']==g['completion_effects'],f'e{i} real operation/cost/effects')
            ck(tool['tool_name'] in a['tools'] and 'devices.'+g['target'] in a['writable_resources'] and x['state_version_at_start']==version,f'e{i} permission/version')
            ck(pid in reservations and now==reservations[pid]['scheduled_start_ms'] and now>=reservations[pid]['timestamp_ms']+100,f'e{i} reservation command cost')
            ck(tid!='bedroom_air' or get(state,'bedroom.co2_ppm')>900,f'e{i} unnecessary real opening')
            ck(tid!='bedroom_heat' or p['heat_admission']=='immediate' or get(state,'devices.window')=='closed' and get(state,'bedroom.co2_ppm')<=900,f'e{i} heating gate')
            active[pid]=x;starts.setdefault(tid,now)
        if kind=='action_completed':
            ck(pid in active and tid not in done and tid not in skips,f'e{i} unmatched completion');s=active.pop(pid)
            ck(s['task_id']==tid and s['operation']==x['operation'] and s['target']==x['target'] and now==s['timestamp_ms']+s['duration_ms'] and x['effects']==gs[tid]['completion_effects'],f'e{i} grounded real receipt');done[tid]=now
        if kind=='request_satisfied_without_actuation':
            d=calls[tid]['decision'];ck(tid=='bedroom_air' and get(state,'bedroom.co2_ppm')<=900 and get(state,'devices.window')=='closed' and d['response_type'] in ('noop','defer') and not d['actions'] and d.get('defer_until_ms') is None and now==tasks[tid]['release_at_ms']+300 and tid not in starts and tid not in skips,f'e{i} skip qualification');skips[tid]=now;admitted.add(tid)
        if kind=='action_rejected' and x['reason']=='ventilation_not_needed':ck(tid=='bedroom_air' and get(state,'bedroom.co2_ppm')<=900 and tid not in starts,f'e{i} rejected unnecessary opening')
        if kind=='automatic_window_close_requested':
            ck(get(state,'devices.window')=='open' and get(state,'bedroom.co2_ppm')<=900 and now%1000==0 and pending_close is None and x['confirm_at_ms']==now+3000,f'e{i} close authority/observation/cost');pending_close=x['confirm_at_ms'];close_records.append({'request_event_index':i,'request_ms':now,'confirm_ms':pending_close})
        if kind=='state_update' and x['source']=='automatic_window_close':
            ck(now==pending_close and x['patch']=={'devices.window':'closed'},f'e{i} real closure');pending_close=None;close_records[-1]['confirmation_event_index']=i
        if kind in ('state_update','action_completed'):
            version+=1;ck(version==x['new_state_version'],f'e{i} state version')
            for path,value in (x['patch'] if kind=='state_update' else x['effects']).items():put(state,path,value)
        if now==p['deadline_ms'] and deadline:deadline['window_closed']=get(state,'devices.window')=='closed'
        if first is None and goal():first=now;first_event_index=i
        clock=now
        if not(kind=='state_update' and x.get('source')=='synthetic_environment'):events.append({'index':i,**x})
    ck(clock==900000 and not active and pending_close is None and state==tr['final_state'] and version==tr['final_state_version'],'final state/version/horizon')
    ck(len(intervals)==sum(x['type']=='state_update' and x.get('source')=='synthetic_environment' for x in tr['events']),'all physical intervals consumed')
    ck(tr['agent_requests']==[c['request'] for c in r['calls']] and len(calls)==len(tasks),'actual calls')
    for tid,c in calls.items():ss,sv=snap[tid];ck(c['request']==expected_request(e,tasks[tid],ss,sv),'full input '+tid)
    handled={**done,**skips}
    req={'task_admission_legal':{t:t in admitted for t in tasks},'task_correct_disposition':{t:t in handled for t in tasks},'task_disposition':{t:'satisfied_without_actuation' if t in skips else 'command_completed' if t in done else 'unresolved' for t in tasks},'task_disposition_latency_ms':{t:handled[t]-tasks[t]['release_at_ms'] if t in handled else None for t in tasks},'task_disposition_deadline_met':{t:t in handled and handled[t]<=tasks[t]['completion_deadline_ms'] for t in tasks}}
    cmd={'task_correct_action_started':{t:t in starts for t in tasks},'task_correct_action_completed':{t:t in done for t in tasks},'task_start_wait_ms':{t:starts[t]-tasks[t]['release_at_ms'] if t in starts else None for t in tasks},'task_completion_latency_ms':{t:done[t]-tasks[t]['release_at_ms'] if t in done else None for t in tasks},'task_completion_tardiness_ms':{t:max(0,done[t]-tasks[t]['completion_deadline_ms']) if t in done else None for t in tasks},'task_deadline_met':{t:t in done and done[t]<=tasks[t]['completion_deadline_ms'] for t in tasks}}
    for k,v in {**req,**cmd}.items():ck(res[k]==v,'result '+k)
    ck(r['audit']['request_recount']==req and set(r['audit']['skipped_without_command'])==set(skips),'author request recount')
    env=res['environment'];ck(env['common_horizon_ms']==900000 and env['deadline_ms']==360000 and env['first_joint_goal_observed_ms']==first and env['joint_goal_by_deadline']==(first is not None and first<=360000) and env['completion_tardiness_ms']==(max(0,first-360000) if first is not None else None),'environment achievement/late/null')
    for k,v in totals.items():num(env['horizon_integrals'][k],v,'horizon integral '+k);num(env['deadline_state_and_integrals']['totals'][k],deadline['totals'][k],'deadline integral '+k)
    for k in ('temperature_c','co2_ppm'):num(env['deadline_state_and_integrals'][k],deadline[k],'deadline state '+k)
    ck(env['deadline_state_and_integrals']['window_closed']==deadline['window_closed'],'deadline closure')
    return {'episode_id':e['episode_id'],'file':file,'errors':errors,'request_recount':req,'command_recount':cmd,'first_environment_goal_ms':first,'first_environment_goal_event_index':first_event_index if first is not None else None,'environment_tardiness_ms':max(0,first-360000) if first is not None else None,'computed_horizon_integrals':totals,'computed_deadline_snapshot':deadline,'interval_count':len(intervals),'largest_absolute_numeric_difference':maxerr,'closure_events':close_records,'events':events}
from homecoord_bench.task_revision.room_revision_v12 import Provider,bundle
from homecoord_bench.task_revision.event_simulator_v12 import run_event_simulation
from homecoord_bench.task_revision.room_audit_v12 import audit as author_audit
from homecoord_bench.task_revision.room_pilot import episode as old_episode,run as old_run,bundle as old_bundle
class Capture(Provider):
    def __init__(self,mode='conditional'):super().__init__(mode);self.instructions=[]
    def decide(self,r,instructions):self.instructions.append(instructions);return super().decide(r,instructions)
def rerun(e,mode='conditional'):
    c=Capture(mode);tr,res=run_event_simulation(e,c,'ConstraintCoordinator','',shared_safety_gate=True)
    return {'trace':tr,'result':res,'calls':c.calls,'audit':author_audit(e,tr,res,c.calls)},all(x=='' for x in c.instructions)
j=read(B/'inputs.json');details=[];decoding=[];captures=[];canaries=[];compat=[];saved={};pairs=[]
specs=[(e,'conditional',f'homecoord_bench/task_revision/fixtures/room_v12/runs/{e["episode_id"]}.json','main') for e in j['episodes']]+[(x['episode'],x['mode'],f'homecoord_bench/task_revision/fixtures/room_v12/diagnostics/{x["case"]}-{x["episode"]["simulation"]["environment"]["heat_admission"]}.json',x['case']) for x in j['diagnostics']]
for e,mode,file,section in specs:
    packed=read(R/file);raw=zlib.decompress(base64.b64decode(packed['trace_zlib_base64']));tr=json.loads(raw);r={k:packed[k] for k in ('result','calls','audit')};r['trace']=tr;saved[file]=r
    decoding.append({'file':file,'sha256_equal':hashlib.sha256(raw).hexdigest()==packed['trace_sha256'],'readable_events_equal':packed['readable_non_environment_events']==[x for x in tr['events'] if not(x['type']=='state_update' and x.get('source')=='synthetic_environment')]})
    d=audit(e,r,file);d['section']=section;details.append(d);fresh,empty=rerun(e,mode);captures.append({'file':file,'saved_full_equal':fresh==r,'instructions_empty':empty})
    changed=copy.deepcopy(e);changed['episode_id']='PRIVATE-future-world';changed['review_status']='PRIVATE-status';changed['task_card']['hidden']='PRIVATE-answer';changed['simulation']['environment']['source_note']='PRIVATE-provenance'
    for t in changed['task_stream']:t['action_template']['private']='PRIVATE-template'
    for t in changed['tool_catalog']:t['description']='PRIVATE-description'
    variant,_=rerun(changed,mode);canaries.append({'file':file,'calls_equal':variant['calls']==r['calls']})
    if section=='main':
        p=e['simulation']['environment'];old=old_run(old_episode(e['initial_state']['values']['bedroom']['co2_ppm'],p['ventilation_rate_ppm_s'],p['heat_rate_c_per_s'],p['heat_admission']));compat.append({'file':file,'environment_equal':old['environment']==r['result']['environment']})
for section in ['main','unnecessary_open','unhandled_high_co2','exact_threshold','above_threshold']:
    ds=[d for d in details if d['section']==section]
    for x,y in zip(ds[::2],ds[1::2]):pairs.append({'first':x['file'],'second':y['file'],'full_calls_equal':saved[x['file']]['calls']==saved[y['file']]['calls']})
negative=[]
for rule in ('immediate','after_ventilation'):
    high=next(e for e in j['episodes'] if e['initial_state']['values']['bedroom']['co2_ppm']==1600 and e['simulation']['environment']['heat_admission']==rule)
    low=next(e for e in j['episodes'] if e['initial_state']['values']['bedroom']['co2_ppm']==850 and e['simulation']['environment']['heat_admission']==rule)
    for case,e in [('fake_high_skip',high),('fake_low_command_success',low)]:
        file=f'homecoord_bench/task_revision/fixtures/room_v12/runs/{e["episode_id"]}.json';bad=copy.deepcopy(saved[file])
        if case=='fake_high_skip':
            pos=next(i for i,x in enumerate(bad['trace']['events']) if x['type']=='proposal_returned' and x['task_id']=='bedroom_air')
            bad['trace']['events'].insert(pos+1,{'type':'request_satisfied_without_actuation','timestamp_ms':300,'task_id':'bedroom_air'})
        else:bad['result']['task_correct_action_completed']['bedroom_air']=True
        try:author_audit(e,bad['trace'],bad['result'],bad['calls']);rejected=False
        except AssertionError:rejected=True
        negative.append({'case':case,'rule':rule,'author_rejected':rejected,'reviewer_rejected':bool(audit(e,bad,'reviewer_negative')['errors'])})
class AlternativeSkip(Capture):
    def __init__(self,mode):super().__init__();self.alt_mode=mode
    def decide(self,q,instructions):
        d=super().decide(q,instructions)
        if q['task']['task_id']=='bedroom_air':
            if self.alt_mode=='noop':d['response_type']='noop'
            else:d['defer_until_ms']=1000
            self.calls[-1]['decision']=copy.deepcopy(d)
        return d
extra=[]
for rule in ('immediate','after_ventilation'):
    e=next(e for e in j['episodes'] if e['initial_state']['values']['bedroom']['co2_ppm']==850 and e['simulation']['environment']['heat_admission']==rule)
    for mode in ('noop','future_defer'):
        c=AlternativeSkip(mode);tr,res=run_event_simulation(e,c,'ConstraintCoordinator','',shared_safety_gate=True);r={'trace':tr,'result':res,'calls':c.calls,'audit':author_audit(e,tr,res,c.calls)};d=audit(e,r,'reviewer_extra:'+mode)
        extra.append({'rule':rule,'mode':mode,'errors':d['errors'],'correct_terminal_skip':res['task_correct_disposition']['bedroom_air']==(mode=='noop'),'command_still_false_null':not res['task_correct_action_completed']['bedroom_air'] and res['task_completion_latency_ms']['bedroom_air'] is None,'disposition':res['task_disposition']['bedroom_air']})
preflight=[]
for case in ('different_authority','different_close_delay','different_tick','mixed_lifecycle','hook','instructions','policy','no_gate'):
    e=copy.deepcopy(j['episodes'][0]);c=Capture();pol='ConstraintCoordinator';inst='';gate=True
    if case=='different_authority':e['controller_authority']['thermostat']['switching_cost_wh']=1
    elif case=='different_close_delay':e['simulation']['environment']['close_delay_ms']=2000
    elif case=='different_tick':e['simulation']['environment']['tick_ms']=2000
    elif case=='mixed_lifecycle':e['simulation']['lifecycle_contracts']={}
    elif case=='hook':c.prepare_release_batch=lambda *a,**k:None
    elif case=='instructions':inst='PRIVATE'
    elif case=='policy':pol='IndependentMultiAgent'
    else:gate=False
    try:run_event_simulation(e,c,pol,inst,shared_safety_gate=gate);ok=False;msg=None
    except ValueError as exc:ok=not c.calls;msg=str(exc)
    preflight.append({'case':case,'rejected_before_calls':ok,'message':msg})
hash_checks=[]
for section in ('source_sha256','artifact_sha256'):
    for p,h in read(B/'manifest.json')[section].items():hash_checks.append({'reference':'v12 manifest','file':p,'equal':sha(R/p)==h})
oldmanifest=R/'docs/implementation_review_20261001/manifest.json';hash_checks.append({'reference':'prior Phase B','file':str(oldmanifest.relative_to(R)),'equal':sha(oldmanifest)==read(O/'PHASE_B_EVENT_AUDIT.json')['summary']['manifest_sha256']})
for section in ('source_sha256','artifact_sha256','historical_result_sha256'):
    for p,h in read(oldmanifest)[section].items():hash_checks.append({'reference':'Phase B manifest','file':p,'equal':sha(R/p)==h})
for version,prior in [('c4_v9','C4_V9_EVENT_AUDIT_20261003.json'),('c4_v10','C4_V10_EVENT_AUDIT_20261003.json'),('dependency_v11','DEPENDENCY_V11_EVENT_AUDIT_20261003.json')]:
    mf=R/'homecoord_bench/task_revision/fixtures'/version/'manifest.json';hash_checks.append({'reference':'prior independent '+version,'file':str(mf.relative_to(R)),'equal':sha(mf)==read(O/prior)['manifest_sha256']})
    for section in ('source_sha256','artifact_sha256','v9_frozen_sha256'):
        for p,h in read(mf).get(section,{}).items():hash_checks.append({'reference':version+' manifest','file':p,'equal':sha(R/p)==h})
reproduction={p:read(R/p)==v for p,v in bundle().items()};oldreproduction={p:read(R/p)==v for p,v in old_bundle().items()}
out={'manifest_sha256':sha(B/'manifest.json'),'details':details,'decoding':decoding,'captures':captures,'canaries':canaries,'input_pairs':pairs,'v4_compatibility':compat,'forgeries':negative,'reviewer_extra_skip_cases':extra,'preflight':preflight,'hash_checks':hash_checks,'v12_bundle_reproduction':reproduction,'v4_bundle_reproduction':oldreproduction,'scoped_tests':{'module':'homecoord_bench.tests.test_room_v12','tests':12,'failures':0,'errors':0,'full500_not_run':True}}
(O/'C2_V12_EVENT_AUDIT_20261003.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'runs':len(details),'intervals':sum(d['interval_count'] for d in details),'findings':[{'file':d['file'],'errors':d['errors']} for d in details if d['errors']],'decode32':all(x['sha256_equal'] and x['readable_events_equal'] for x in decoding),'captures32':all(x['saved_full_equal'] and x['instructions_empty'] for x in captures),'canaries32':all(x['calls_equal'] for x in canaries),'input_pairs16':all(x['full_calls_equal'] for x in pairs),'v4_compat24':all(x['environment_equal'] for x in compat),'forgeries4':all(x['author_rejected'] and x['reviewer_rejected'] for x in negative),'additional_noop_defer4':all(not x['errors'] and x['correct_terminal_skip'] and x['command_still_false_null'] for x in extra),'preflight8':all(x['rejected_before_calls'] for x in preflight),'hash_errors':[x for x in hash_checks if not x['equal']],'reproduce35':all(reproduction.values()),'old_reproduce':all(oldreproduction.values())},ensure_ascii=False,indent=2))
