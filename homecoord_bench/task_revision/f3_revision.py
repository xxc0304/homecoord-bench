"""F3 v8 capability and attribution controls; deterministic, no API/holdout."""
import hashlib
import itertools
import json
from copy import deepcopy
from pathlib import Path
from homecoord_bench.task_revision.milestone import ROOT as DATA
from homecoord_bench.task_revision.f3_capability import POLICIES
from homecoord_bench.task_revision.event_simulator_v8 import run_event_simulation
from homecoord_bench.task_revision.review_packet import feasible, verify_witness
from runtime.dry_run import _decision_from_template
from evaluate import get_path, set_path

ROOT=DATA.parent
OUT='homecoord_bench/task_revision/fixtures/f3_v8'
SELECTORS=('low_resource','short_duration','capacity_pressure')


def worlds():
    rows=[]
    for p in sorted((DATA/'revision_drafts/20260930_task_family_split/development').glob('D-F3-*.json')):
        e=json.loads(p.read_text(encoding='utf-8'));assert e['split']=='development'
        rows.append(e)
    assert len(rows)==8
    return rows


def vectors(e):
    options=[[a['operation'] for a in t['acceptable_actions']] for t in e['task_stream']]
    return [dict(zip((t['task_id'] for t in e['task_stream']),v)) for v in itertools.product(*options)]


def episode(world,kind,vector=None):
    e=deepcopy(world)
    e['evaluation_world_id']=world['episode_id']
    e['episode_id']='F3R1-'+world['episode_id']+'-'+kind+(':'+','.join(vector.values()) if vector else '')
    e['review_status']='author_revision_design_and_implementation_pending'
    e['f3_capability_version']='fixed-or-selectable-v1'
    e['public_devices']=[]
    for a in e['agents']:
        tools=[x for x in e['tool_catalog'] if x['agent_id']==a['agent_id'] and x['operation']!='off']
        e['public_devices'].append({'agent_id':a['agent_id'],'role':a['role'],'target':tools[0]['target'],
                                   'service':tools[0]['provides_service'],
                                   'modes':[{'operation':x['operation'],**x['cost_contract']} for x in tools]})
    authorized={t['task_id']:[vector[t['task_id']]] if kind=='fixed' else [a['operation'] for a in t['acceptable_actions']]
                for t in e['task_stream']}
    e['mode_capability']={'kind':kind,'authorized_modes_by_task':authorized,
                          'selection_boundary':'one_proposal_before_start_no_switch',
                          'authority':'explicit_synthetic_service_delegation'}
    e['service_delegation']={'principal':'SyntheticResident','authority':'explicit_synthetic_service_delegation',
                             'rule':'Select one permitted service mode before starting; finish its full cycle without cancellation or mode switching.',
                             'equivalence_basis':'author-defined completion effect, not measured service quality or energy'}
    for a in e['agents']:
        t=next(t for t in e['task_stream'] if t['agent_id']==a['agent_id'])
        a['tools']=[name for name in a['tools'] if name.rsplit('_',1)[-1] in [*authorized[t['task_id']],'off']]
    e['tool_catalog']=[x for x in e['tool_catalog'] if x['operation']=='off' or x['operation'] in authorized[
        next(t['task_id'] for t in e['task_stream'] if t['agent_id']==x['agent_id'])]]
    # Scoring keeps BOTH physically equivalent modes. Authorization is an
    # independent capability layer; a disallowed mode cannot execute.
    return e


def inputs():
    return [e for w in worlds() for e in [*[episode(w,'fixed',v) for v in vectors(w)],episode(w,'selectable')]]


class ModeRule:
    include_evaluation_hints=False
    last_latency_ms=300

    def __init__(self,selector='low_resource',diagnostic=None):
        if selector not in SELECTORS:raise ValueError(selector)
        self.selector=selector;self.diagnostic=diagnostic;self.calls=[]

    def decide(self,r,instructions):
        tools=[x for x in r['available_actions'] if x['provides_service']!='none']
        low=min(tools,key=lambda x:(x['cost_contract']['resource_units'],x['cost_contract']['duration_ms'],x['operation']))
        short=min(tools,key=lambda x:(x['cost_contract']['duration_ms'],x['cost_contract']['resource_units'],x['operation']))
        ctx=r['state']['coordination_context'];ds={d['agent_id']:d for d in ctx.get('static_devices',[])}
        if self.selector=='low_resource':tool=low
        elif self.selector=='short_duration':tool=short
        else:
            # All-fast simultaneous load is a public heuristic, not a solver.
            peak=sum(min((m for m in ds[t['agent_id']]['modes'] if m['operation'] in t['authorized_modes']),
                         key=lambda m:(m['duration_ms'],m['resource_units']))['resource_units'] for t in ctx['requests'])
            tool=short if peak<=ctx['resource_capacity_units'] else low
        if self.diagnostic=='off':tool=next(x for x in r['available_actions'] if x['operation']=='off')
        if self.diagnostic=='forbidden_fast':
            own=ds[r['task']['agent_id']]
            fast=next((m for m in own['modes'] if m['operation']=='fast'),None)
            if fast:
                tool={'target':own['target'],'operation':'fast','cost_contract':fast,'preconditions':tools[0]['preconditions']}
        template={'target':tool['target'],'operation':tool['operation'],'parameters':{},
                  'duration_ms':tool['cost_contract']['duration_ms'],'power_kw':tool['cost_contract']['resource_units'],
                  'requires':tool['preconditions']}
        d=_decision_from_template(r,template,r['state_version'])
        if self.diagnostic=='cost_lie':d['actions'][0]['estimated_duration_ms']+=1
        if self.diagnostic=='noop':
            d={'response_type':'noop','actions':[],'accepted_proposal_ids':[],'rejected_proposal_ids':[],
               'defer_until_ms':None,'reason_code':'no_applicable_action'}
        self.calls.append({'request':deepcopy(r),'decision':deepcopy(d)})
        return d


def audit(e,trace,result,calls):
    tasks={t['task_id']:t for t in e['task_stream']};allowed=e['mode_capability']['authorized_modes_by_task']
    assert trace['agent_requests']==[c['request'] for c in calls]
    for r in trace['agent_requests']:
        assert r['mode_capability']==e['mode_capability'] and r['current_time_ms']==0
        assert r['episode_id']==r['base_episode_id']=='F3-public-home'
        tid=r['task']['task_id'];assert r['task']['authorized_modes']==allowed[tid]
        assert {x['operation'] for x in r['available_actions']}==set(allowed[tid])|{'off'}
        assert not {'action_template','required_action','acceptable_actions'}&set(r['task'])
    state=deepcopy(e['initial_state']['values']);version=e['initial_state']['version']
    active={};committed={};starts={};done={};realized={};costs={tid:None for tid in tasks};intervals=[];clock=0
    for x in trace['events']:
        now=x['timestamp_ms'];assert now>=clock;clock=now;tid=x.get('task_id')
        if x['type']=='mode_selection_committed':
            assert tid not in committed and x['operation'] in allowed[tid]
            committed[tid]=x
        if x['type']=='action_started':
            assert now>=tasks[tid]['release_at_ms'] and x['proposal_id'] not in active
            g=next(g for g in e['action_grounding'] if g['task_id']==tid and g['operation']==x['operation'])
            assert x['target']==g['target'] and x['duration_ms']==g['duration_ms'] and x['power_kw']==g['power_kw']
            # The source emits the trusted start state patch just before this event.
            assert get_path(state,'devices.'+x['target'])==('idle' if x['operation']=='off' else 'running')
            assert sum(s['power_kw'] for s in active.values())+x['power_kw']<=e['home']['resources']['max_power_kw']
            active[x['proposal_id']]=x
            if x['operation']!='off':
                c=committed[tid];assert c['operation']==x['operation'] and c['proposal_id']==x['proposal_id'] and c['timestamp_ms']<now
                assert tid not in starts;starts[tid]=now;realized[tid]=x['operation']
        if x['type']=='action_completed':
            s=active.pop(x['proposal_id']);assert (s['task_id'],s['operation'],s['target'])==(tid,x['operation'],x['target'])
            assert now==s['timestamp_ms']+s['duration_ms']
            g=next(g for g in e['action_grounding'] if g['task_id']==tid and g['operation']==x['operation'])
            assert x['effects']==g['completion_effects']
            intervals.append({'task_id':tid,'operation':x['operation'],'start_ms':s['timestamp_ms'],'end_ms':now,'units':s['power_kw']})
            if x['operation']!='off':
                done[tid]=now;costs[tid]=s['power_kw']*(now-s['timestamp_ms'])
        if x['type']=='state_update':
            patch=x['patch'];assert x['source']=='action_started'
            assert any(g['task_id']==tid and g['start_effects']==patch for g in e['action_grounding'])
        elif x['type']=='action_completed':patch=x['effects']
        else:patch={}
        for path,value in patch.items():set_path(state,path,value)
        if x['type'] in ('state_update','action_completed'):
            version+=1;assert x['new_state_version']==version
    assert not active and state==trace['final_state'] and version==trace['final_state_version']
    metrics={
        'task_correct_action_completed':{tid:tid in done for tid in tasks},
        'task_start_wait_ms':{tid:starts[tid]-t['release_at_ms'] if tid in starts else None for tid,t in tasks.items()},
        'task_completion_latency_ms':{tid:done[tid]-t['release_at_ms'] if tid in done else None for tid,t in tasks.items()},
        'task_completion_tardiness_ms':{tid:max(0,done[tid]-t['completion_deadline_ms']) if tid in done else None for tid,t in tasks.items()},
        'task_deadline_met':{tid:tid in done and done[tid]<=t['completion_deadline_ms'] for tid,t in tasks.items()}}
    for key,value in metrics.items():assert result[key]==value,(key,result[key],value)
    assert result['all_deadlines_met']==all(metrics['task_deadline_met'].values())
    return {'status':'author_recount_passed_not_acceptance','recount':metrics,
            'selected_mode_by_task':{tid:committed[tid]['operation'] if tid in committed else None for tid in tasks},
            'realized_mode_by_task':{tid:realized.get(tid) for tid in tasks},'resource_intervals':intervals,
            'task_executed_resource_time_units_ms':costs,
            'total_executed_resource_time_units_ms':sum(x['units']*(x['end_ms']-x['start_ms']) for x in intervals),
            'all_services_completed':len(done)==len(tasks),
            'all_service_completion_ms':max(done.values()) if len(done)==len(tasks) else None,
            'latest_observed_service_completion_ms':max(done.values(),default=None),
            'cost_scope':'actual operation resource-time, not energy; command/proposal overhead excluded; incomplete services not ranked as better'}


def run(e,policy='ConstraintCoordinator',selector='low_resource',diagnostic=None):
    provider=ModeRule(selector,diagnostic)
    trace,result=run_event_simulation(e,provider,policy,'',shared_safety_gate=True)
    return {'evaluation_episode_id':e['episode_id'],'policy':policy,'selector':selector,'diagnostic':diagnostic,
            'calls':provider.calls,'trace':trace,'result':result,'audit':audit(e,trace,result,provider.calls)}


def contrasts(r,control):
    a,b=r['audit'],control['audit']
    def difference(x,y):return x-y if x is not None and y is not None else None
    return {'all_service_completion_ms_delta':difference(a['all_service_completion_ms'],b['all_service_completion_ms']),
            'resource_time_units_ms_delta':a['total_executed_resource_time_units_ms']-b['total_executed_resource_time_units_ms'],
            'both_all_services_completed':a['all_services_completed'] and b['all_services_completed'],
            'task_start_wait_ms_delta':{tid:difference(v,b['recount']['task_start_wait_ms'][tid]) for tid,v in a['recount']['task_start_wait_ms'].items()},
            'task_completion_tardiness_ms_delta':{tid:difference(v,b['recount']['task_completion_tardiness_ms'][tid]) for tid,v in a['recount']['task_completion_tardiness_ms'].items()},
            'scope':'controlled script difference, not LLM superiority or general causal attribution'}


def serialize(v):return json.dumps(v,ensure_ascii=False,indent=2)+'\n'


def bundle():
    episodes=inputs();artifacts={OUT+'/inputs.json':{'episodes':episodes,'underlying_worlds':8,'capability_configurations':32,'acceptance':None}}
    groups={};certificates=[]
    for e in episodes:
        selectors=('low_resource',) if e['mode_capability']['kind']=='fixed' else SELECTORS
        rows=[run(e,p,s) for s in selectors for p in POLICIES];groups[e['episode_id']]=rows
        name=OUT+'/runs/'+e['episode_id'].replace(':','--').replace(',','-')+'.json'
        artifacts[name]={'episode_id':e['episode_id'],'runs':rows}
    for w in worlds():
        cert=feasible(w);verify_witness(w,cert);assert all(x['status']=='witness_found' for x in cert['mode_witnesses'])
        certificates.append({'evaluation_world_id':w['episode_id'],**cert})
    scheduling=[];selection=[];matched=[];diagnostic_files=[]
    for w in worlds():
        fixed=[e for e in episodes if e['evaluation_world_id']==w['episode_id'] and e['mode_capability']['kind']=='fixed']
        selectable=next(e for e in episodes if e['evaluation_world_id']==w['episode_id'] and e['mode_capability']['kind']=='selectable')
        for e in fixed:
            rows=groups[e['episode_id']];control=next(r for r in rows if r['policy']=='ConstraintCoordinator')
            for r in rows:
                if r is control:continue
                scheduling.append({'world':w['episode_id'],'fixed_vector':{tid:ops[0] for tid,ops in e['mode_capability']['authorized_modes_by_task'].items()},
                                   'policy':r['policy'],'control_policy':control['policy'],**contrasts(r,control)})
        for r in groups[selectable['episode_id']]:
            vector=r['audit']['selected_mode_by_task']
            same=next(e for e in fixed if {tid:ops[0] for tid,ops in e['mode_capability']['authorized_modes_by_task'].items()}==vector)
            control=next(x for x in groups[same['episode_id']] if x['policy']==r['policy'])
            assert r['audit']['recount']==control['audit']['recount']
            assert r['audit']['total_executed_resource_time_units_ms']==control['audit']['total_executed_resource_time_units_ms']
            matched.append({'world':w['episode_id'],'policy':r['policy'],'selector':r['selector'],
                            'selected_vector':vector,'matched_fixed_episode':same['episode_id'],'core_metrics_equal':True})
            for baseline in (fixed[0],fixed[-1]):
                control=next(x for x in groups[baseline['episode_id']] if x['policy']==r['policy'])
                selection.append({'world':w['episode_id'],'policy':r['policy'],'selector':r['selector'],
                                  'fixed_control':baseline['episode_id'],**contrasts(r,control)})
        name=OUT+'/diagnostics/'+w['episode_id']+'.json';diagnostic_files.append(name)
        artifacts[name]={'evaluation_world_id':w['episode_id'],
                         'fixed_diagnostic_episode':fixed[0]['episode_id'],'selectable_diagnostic_episode':selectable['episode_id'],
                         'runs':[dict(case=case,**run(fixed[0] if case=='forbidden_fast' else selectable,diagnostic=case))
                                 for case in ('forbidden_fast','cost_lie','off','noop')]}
    artifacts[OUT+'/feasibility.json']={'offline_only':True,'certificates':certificates}
    artifacts[OUT+'/contrasts.json']={'fixed_mode_scheduling':scheduling,'same_policy_mode_selection':selection,
                                     'mode_matched_controls':matched,'reviewer_acceptance':None}
    artifacts[OUT+'/index.json']={'underlying_worlds':8,'capability_configurations':32,'main_runs':192,'diagnostic_runs':32,
                                'api_calls':0,'holdout_runs':0,'run_files':[p for p in artifacts if '/runs/' in p],
                                'diagnostic_files':diagnostic_files,'diagnostic_scope':'ConstraintCoordinator only, not all-policy certification',
                                'fixed_scheduling_contrasts':72,'mode_selection_contrasts':192,'mode_matched_controls':96,'acceptance':None}
    paths=['homecoord_bench/task_revision/'+n for n in ('f3_capability.py','f3_revision.py','event_simulator_v8.py','review_packet.py')]
    paths+=['homecoord_bench/runtime/'+n for n in ('event_simulator.py','protocol.py','execution.py','episode_validation.py','tool_contract.py','task_response_metrics.py','dry_run.py')]
    paths+=['homecoord_bench/evaluate.py','homecoord_bench/tests/test_f3_v8.py']
    paths += [str(p.relative_to(ROOT)).replace('\\','/') for p in sorted((DATA/'revision_drafts/20260930_task_family_split/development').glob('D-F3-*.json'))]
    artifacts[OUT+'/manifest.json']={'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},
                                    'artifact_sha256':{p:hashlib.sha256(serialize(v).encode()).hexdigest() for p,v in artifacts.items()},
                                    'acceptance':None,'prior_versions':'v1-v7, source inputs, results and Phase A/B unchanged'}
    return artifacts


if __name__=='__main__':
    import sys
    data=bundle();print(json.dumps(list(data) if len(sys.argv)==1 else serialize(data[sys.argv[1]]),ensure_ascii=True))
