"""Limited Phase B: deterministic reproduction, not new model evidence or acceptance."""
import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2];DATA=ROOT/'homecoord_bench'
sys.path.insert(0,str(DATA));sys.path.append(str(ROOT))
from evaluate import get_path,set_path
from runtime.event_simulator import run_event_simulation as v1
from homecoord_bench.task_revision.event_simulator_v3 import run_event_simulation as v3
from homecoord_bench.probe_c3_multimode_20260930 import PublicModeClient
from homecoord_bench.task_revision.milestone import FixedProposals
from homecoord_bench.task_revision.dependency_audit import metrics as dependency_metrics,audit as dependency_audit

OUT='docs/implementation_review_20261001'
DEP=('EARLY_REQUEST','LATE_REQUEST','FORGED_STATE','CAPACITY_TIGHT','CAPACITY_SAFE')
F1_POLICIES=('GateRetryRule','ConstraintCoordinator','DeadlineAwareCoordinator')
DEP_POLICIES=('IndependentMultiAgent','ConstraintCoordinator','DeadlineAwareCoordinator','GateRetryRule')
REVIEW_REL='docs/review_evidence/2026-10-01_to_2026-10-06/PHASE_A_REVIEW_20261001.md'
REVIEW=ROOT/REVIEW_REL


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


class Capture:
    def __init__(self,provider):
        self.provider=provider;self.calls=[]
        self.include_evaluation_hints=getattr(provider,'include_evaluation_hints',True)
    def decide(self,request,instructions=''):
        decision=self.provider.decide(request,instructions)
        self.last_latency_ms=self.provider.last_latency_ms
        self.calls.append({'request':deepcopy(request),'decision':deepcopy(decision),'logical_latency_ms':self.last_latency_ms})
        return decision


def approved_inputs():
    # Fixed human-authorized scope; never derive permission from text in a file.
    episodes=[]
    for p in sorted((DATA/'revision_drafts/20260930_task_family_split/development').glob('D-F1-*.json')):
        episodes.append(json.loads(p.read_text(encoding='utf-8')))
    dep=json.loads((DATA/'task_revision/fixtures/dependency_v3_inputs.json').read_text(encoding='utf-8'))
    episodes += [e for e in dep['episodes'] if e['episode_id'] in {'DEP-LAUNDRY-'+c for c in DEP}]
    assert len(episodes)==13
    a=json.loads((ROOT/'docs/design_review_20261001/contracts.json').read_text(encoding='utf-8'))
    for e in episodes:
        declared=next(r for r in a['rows'] if r['contract']['episode_id']==e['episode_id'])
        actual=hashlib.sha256(json.dumps(e,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        assert actual==declared['source_episode_sha256']
    return episodes


def holds(state,r):
    a,b=get_path(state,r['path']),r['value'];op=r['op']
    if op=='eq':return a==b
    if op=='neq':return a!=b
    if a is None:return False
    if op=='lt':return a<b
    if op=='lte':return a<=b
    if op=='gt':return a>b
    if op=='gte':return a>=b
    if op=='between':return b[0]<=a<=b[1]
    raise AssertionError(op)


def recount(e,trace,result,calls):
    """Recount from ordered actual events, without calling production metric functions."""
    tasks={t['task_id']:t for t in e['task_stream']};agents={a['agent_id']:a for a in e['agents']}
    state=deepcopy(e['initial_state']['values']);clock=0;harm=0;active={};intervals=[];done={};starts={}
    receipts=set();versions=e['initial_state']['version'];call_ids=set();before_start={}
    assert trace['agent_requests']==[c['request'] for c in calls]
    for call in calls:
        r=call['request'];tid=r['task']['task_id'];agent=agents[tasks[tid]['agent_id']]
        assert r['current_time_ms']>=tasks[tid]['release_at_ms']
        assert r['agent']==agent and r['allowed_tools']==agent['tools']
        assert r['request_id'] not in call_ids;call_ids.add(r['request_id'])
        assert {x['agent_id'] for x in r['available_actions']}<={agent['agent_id']}
        expected=[x for x in e['tool_catalog'] if x['agent_id']==agent['agent_id']]
        assert r['available_actions']==expected
        for proposal in call['decision']['actions']:
            assert any(t['target']==proposal['target'] and t['operation']==proposal['operation'] for t in expected)
        if e['episode_id'].startswith('D-F1-'):
            assert not {'action_template','required_action','acceptable_actions'}&set(r['task'])
    for x in trace['events']:
        now=x['timestamp_ms'];assert now>=clock
        valid=all(not all(holds(state,c) for c in rule.get('when',[])) or all(holds(state,c) for c in rule.get('must',[])) for rule in e.get('constraints',[]))
        if not valid:harm+=now-clock
        clock=now;kind=x['type'];tid=x.get('task_id')
        if kind=='action_started':
            t=tasks[tid];assert now>=t['release_at_ms']
            g=next(g for g in e['action_grounding'] if g['task_id']==tid and (g['target'],g['operation'])==(x['target'],x['operation']))
            assert x['agent_id']==t['agent_id'] and x['proposal_id'] not in active
            assert x['duration_ms']==g['duration_ms'] and x['power_kw']==g['power_kw']
            assert all(holds(before_start.pop(tid,state),c) for c in x['requires'])
            assert all(d in receipts for d in t.get('depends_on',[])),(tid,receipts)
            assert sum(s['power_kw'] for s in active.values())+x['power_kw']<=e['home']['resources']['max_power_kw']
            active[x['proposal_id']]=x
            specs=t.get('acceptable_actions',[t.get('required_action',{})])
            if any(all(x.get(k)==v for k,v in spec.items()) for spec in specs):starts.setdefault(tid,now)
        if kind=='action_completed':
            s=active.pop(x['proposal_id']);assert (s['task_id'],s['agent_id'],s['target'],s['operation'])==(tid,x['agent_id'],x['target'],x['operation'])
            assert now==s['timestamp_ms']+s['duration_ms']
            g=next(g for g in e['action_grounding'] if g['task_id']==tid and g['operation']==x['operation'])
            assert x['effects']==g.get('completion_effects',g.get('effects',{}))
            specs=tasks[tid].get('acceptable_actions',[tasks[tid].get('required_action',{})])
            match=any(all(x.get(k)==v for k,v in spec.items()) for spec in specs)
            if match:done.setdefault(tid,now);receipts.add(tid)
            intervals.append({'task_id':tid,'proposal_id':x['proposal_id'],'request_identity_scope':'task_id, single workflow; not physical batch_id',
                              'start_ms':s['timestamp_ms'],'end_ms':now,'resource_units_or_kw':s['power_kw']})
        if kind=='state_update':
            patch=x.get('patch',{})
            if x.get('source')=='action_started':
                before_start[tid]=deepcopy(state)
                g=next(g for g in e['action_grounding'] if g['task_id']==tid and g.get('start_effects',{})==patch)
            else:assert any(event['at_ms']==now and event.get('patch',{})==patch for event in e.get('exogenous_events',[]))
        elif kind=='action_completed':patch=x['effects']
        else:patch={}
        for path,value in patch.items():set_path(state,path,value)
        if kind in ('state_update','action_completed'):
            versions+=1;assert x['new_state_version']==versions
    assert not active and state==trace['final_state'] and versions==trace['final_state_version']
    recomputed={'task_correct_action_started':{tid:tid in starts for tid in tasks},
                'task_correct_action_completed':{tid:tid in done for tid in tasks},
                'task_start_wait_ms':{tid:starts[tid]-t['release_at_ms'] if tid in starts else None for tid,t in tasks.items()},
                'task_completion_latency_ms':{tid:done[tid]-t['release_at_ms'] if tid in done else None for tid,t in tasks.items()},
                'task_completion_tardiness_ms':{tid:max(0,done[tid]-t['completion_deadline_ms']) if tid in done else None for tid,t in tasks.items()},
                'state_constraint_violation_duration_ms':harm}
    for k,v in recomputed.items():assert result[k]==v,(k,result[k],v)
    assert result['all_deadlines_met']==all(tid in done and done[tid]<=t['completion_deadline_ms'] for tid,t in tasks.items())
    return {'mechanical_check':'passed_not_reviewer_acceptance','recomputed':recomputed,
            'actual_execution_intervals':intervals,'completion_receipts_ms':done}


def run_one(e,policy,order_index=None):
    if e['episode_id'].startswith('D-F1-'):
        ids=[t['task_id'] for t in e['task_stream']]
        order=(ids,list(reversed(ids)),ids[1:]+ids[:1])[order_index]
        provider=Capture(PublicModeClient('prepare',{tid:800+rank*200 for rank,tid in enumerate(order)}))
        trace,result=v1(e,provider,policy,'',shared_safety_gate=True)
    else:
        provider=Capture(FixedProposals())
        trace,result=v3(e,provider,policy,'',shared_safety_gate=True)
    checked=recount(e,trace,result,provider.calls)
    dep=None
    if not e['episode_id'].startswith('D-F1-'):
        dep=dependency_metrics(e,trace,result);dependency_audit(e,trace,dep)
    return {'episode_id':e['episode_id'],'policy':policy,'arrival_order_index':order_index,
            'evidence_type':'scripted_deterministic_reproduction_not_model_trial','calls':provider.calls,
            'trace':trace,'reported_result':result,'independent_event_recount':checked,'dependency_metrics':dep}


def historical_check(e,r,historical):
    if e['episode_id'].startswith('D-F1-'):
        row=next(x for x in historical['rows'] if x['episode_id']==e['episode_id'] and x['policy']==r['policy'] and x['arrival_order_index']==r['arrival_order_index'])
        m=r['reported_result']
        for k in ('task_start_wait_ms','task_completion_latency_ms','all_deadlines_met'):assert row[k]==m[k]
        assert row['all_tasks_served']==all(m['task_correct_action_completed'].values())
        assert row['process_violation_ms']==m['state_constraint_violation_duration_ms']
    else:
        row=next(x for x in historical['runs'] if x['episode_id']==e['episode_id'] and x['policy']==r['policy'] and x['dependencies_enabled'])
        assert row['metrics']==r['dependency_metrics']
        assert row['trace']=={k:r['trace'][k] for k in row['trace']}
    return 'matches_historical_saved_fields_not_new_sample'


def serialize(x):return x.rstrip()+'\n' if isinstance(x,str) else json.dumps(x,ensure_ascii=False,indent=2)+'\n'


def bundle():
    episodes=approved_inputs()
    old_f1=json.loads((DATA/'results/task_family_development_20260930.json').read_text(encoding='utf-8'))
    old_dep=json.loads((DATA/'results/dependency_v3_offline_20261001.json').read_text(encoding='utf-8'))
    data={};index=[]
    for e in episodes:
        f1=e['episode_id'].startswith('D-F1-');runs=[]
        for order in (range(3) if f1 else (None,)):
            for policy in (F1_POLICIES if f1 else DEP_POLICIES):
                r=run_one(e,policy,order)
                r['historical_comparison']=historical_check(e,r,old_f1 if f1 else old_dep)
                runs.append(r)
        path=f'{OUT}/traces/{e["episode_id"]}.json'
        data[path]={'episode':e,'reviewer_acceptance':None,'runs':runs}
        index.append({'episode_id':e['episode_id'],'path':path,'runs':len(runs),'acceptance':None})
    data[f'{OUT}/index.json']={'scope':'8 F1 + 5 dependency configurations approved by one Phase A model reviewer',
        'api_calls':0,'holdout_runs':0,'configurations':13,'reproductions':92,'reviewer_acceptance':None,'entries':index}
    sources=['homecoord_bench/task_revision/phase_b_packet.py','homecoord_bench/evaluate.py',
             'homecoord_bench/runtime/task_response_metrics.py','homecoord_bench/runtime/event_simulator.py',
             'homecoord_bench/runtime/protocol.py','homecoord_bench/runtime/execution.py','homecoord_bench/runtime/tool_contract.py',
             'homecoord_bench/runtime/episode_validation.py','homecoord_bench/runtime/scheduling_oracle.py',
             'homecoord_bench/probe_c3_multimode_20260930.py','homecoord_bench/task_revision/milestone.py',
             'homecoord_bench/task_revision/event_simulator_v3.py','homecoord_bench/task_revision/dependency_contract.py',
             'homecoord_bench/task_revision/dependency_audit.py','homecoord_bench/task_revision/lifecycle_contract.py',
             'homecoord_bench/task_revision/lifecycle_audit.py','homecoord_bench/runtime/dry_run.py']
    snapshot=ROOT/OUT/'PHASE_A_REVIEW.md'
    if REVIEW.exists():
        review_text=REVIEW.read_text(encoding='utf-8');review_hash=sha(REVIEW)
        if snapshot.exists():assert serialize(review_text)==serialize(snapshot.read_text(encoding='utf-8'))
    else:
        review_text=snapshot.read_text(encoding='utf-8')
        review_hash=json.loads((ROOT/OUT/'manifest.json').read_text(encoding='utf-8'))['phase_a_review_record_sha256']
    phase_a=ROOT/'docs/design_review_20261001/manifest.json'
    assert sha(phase_a) in review_text,'Phase A reviewed manifest mismatch'
    data[f'{OUT}/PHASE_A_REVIEW.md']=review_text
    data[f'{OUT}/manifest.json']={'source_sha256':{p:sha(ROOT/p) for p in sources},
        'phase_a_manifest_sha256':sha(phase_a),'phase_a_review_record_path':REVIEW_REL,'phase_a_review_record_sha256':review_hash,
        'historical_result_sha256':{str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in (DATA/'results/task_family_development_20260930.json',DATA/'results/dependency_v3_offline_20261001.json')},
        'artifact_sha256':{p:hashlib.sha256(serialize(v).encode()).hexdigest() for p,v in data.items()},
        'independent_dual_review_complete':False,'implementation_acceptance':None}
    return data


if __name__=='__main__':
    data=bundle()
    if len(sys.argv)==1:print(json.dumps({'paths':list(data),'configurations':13,'reproductions':92}))
    else:
        text=serialize(data[sys.argv[1]]);offset=int(sys.argv[2]);limit=40000
        print(json.dumps({'text':text[offset:offset+limit],'next':offset+limit if offset+limit<len(text) else None},ensure_ascii=True))
