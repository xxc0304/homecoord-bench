"""C1 revision: new inputs/snapshots; prior versions untouched; zero API."""
import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];DATA=ROOT/'homecoord_bench'
sys.path.insert(0,str(DATA));sys.path.append(str(ROOT))
from homecoord_bench.task_revision.milestone import c1,FixedProposals
from homecoord_bench.task_revision.event_simulator_v5 import run_event_simulation
from evaluate import get_path,set_path

POLICIES=('IndependentMultiAgent','ConstraintCoordinator','DeadlineAwareCoordinator','GateRetryRule')


def episode(kind,condition,budget='legality'):
    e=c1(kind,condition);low=e['task_stream'][1]
    e['episode_id']=f'C1R2-{kind}-{budget}-{condition}'
    e['review_status']='revised_author_draft_pending_phase_A'
    e['variant']={'structure':'persistent_protection','device_scene':kind,'condition':condition,'budget':budget,'split':'development'}
    p=low['action_template']['requires'][0]['path'];target=low['action_template']['target']
    delegation={'policy_id':f'user-protection-{kind}','authority':'explicit_synthetic_user_delegation',
        'principal':'SyntheticResident','target':target,'protected_path':p,
        'scope':'maintain declared protected device state while current protection boolean is true; only one protection request',
        'request_semantics':'reject_terminal_at_release_no_wait','expiry_visibility':'current_boolean_only',
        'new_request_rule':'later action after expiry requires a new task_id; closed original request never revives',
        'parameter_basis':'author-defined device-state contract, not measured illumination/privacy or real user study'}
    e['user_delegations']=[delegation]
    contract={'policy_id':delegation['policy_id'],'admit_when':deepcopy(low['action_template']['requires']),'rejection_terminal':True}
    low['request_contract']=deepcopy(contract)
    low['goal']='Synthetic user policy: if protection is active at release, terminally reject this request; do not wait or revive it after expiry. Otherwise send the authorized action.'
    e['tool_catalog'][1]['description']=low['goal']
    e['simulation']['request_disposition_contracts']={low['task_id']:contract}
    if budget=='equal_response':low['completion_deadline_ms']=low['release_at_ms']+1500
    elif budget!='legality':raise ValueError('unknown budget group')
    for a in e['agents']:
        a['goal_visibility']='local';a['constraint_visibility']='local'
        a['policy_constraints']=deepcopy(e['constraints'])
    e['task_card']={'status':'pending design review, not acceptance','mechanism_count':1,
        'disposition':'trusted user policy, release-time terminal rejection; no agent reasoning claim',
        'budget':budget,'legality':'fixed8000 deadline is not an equal response-budget contrast',
        'equal_response':'deadline=own release+1500; rejection has no action completion time',
        'information':'same current boolean and target; expiry event/time not included in decision inputs',
        'limitations':['single protection request','no multiple-user arbitration','synthetic authority','device state only']}
    return e


def audit(e,trace,result):
    state=deepcopy(e['initial_state']['values']);closed=set();expected={};complete={};clock=0;harm=0
    contracts=e['simulation']['request_disposition_contracts'];tasks={t['task_id']:t for t in e['task_stream']}
    active={}
    for x in trace['events']:
        now=x['timestamp_ms'];assert now>=clock
        for p in e['user_delegations']:
            protected=get_path(state,p['protected_path'])
            safe='reading' if p['target']=='study_light' else 'closed'
            if protected and get_path(state,'devices.'+p['target'])!=safe:harm+=now-clock
        clock=now;tid=x.get('task_id');kind=x['type']
        if kind=='task_released' and tid in contracts:
            path=contracts[tid]['admit_when'][0]['path']
            expected[tid]='rejected_terminal' if get_path(state,path) else 'completed'
        if kind=='request_terminal_rejected':
            assert expected[tid]=='rejected_terminal' and tid not in closed
            assert now==tasks[tid]['release_at_ms'] and x['terminal'] is True
            closed.add(tid)
        if kind=='action_started':
            assert tid not in closed
            active[x['proposal_id']]=x
        if kind=='action_completed':
            assert tid not in closed
            start=active.pop(x['proposal_id']);assert now==start['timestamp_ms']+start['duration_ms']
            complete[tid]=now
        patch=x.get('patch',{}) if kind=='state_update' else x.get('effects',{}) if kind=='action_completed' else {}
        for path,value in patch.items():set_path(state,path,value)
    assert state==trace['final_state'] and not active
    assert harm==result['state_constraint_violation_duration_ms']
    statuses={tid:'rejected_terminal' if tid in closed else 'completed' if tid in complete else 'unresolved' for tid in contracts}
    assert statuses==result['request_status']
    for tid in closed:
        assert result['task_correct_action_completed'][tid] is False
        assert result['task_completion_latency_ms'][tid] is None
        assert all(r['task']['task_id']!=tid for r in trace['agent_requests'])
    return {'request_status':statuses,'expected_from_release_state':expected,
            'correct_disposition':{tid:statuses[tid]==expected[tid] for tid in expected},
            'protection_loss_ms':harm,'completed_at_ms':complete,'audit':'passed_not_review_acceptance'}


def run(e,policy='ConstraintCoordinator',provider=None):
    trace,result=run_event_simulation(e,provider or FixedProposals(),policy,'',shared_safety_gate=True)
    return {'episode_id':e['episode_id'],'policy':policy,'trace':trace,'result':result,'audit':audit(e,trace,result)}


def bundle():
    episodes=[episode(k,c,b) for k in ('LIGHT','BLINDS') for b in ('legality','equal_response') for c in ('CONFLICT','SAFE')]
    runs=[run(e,p) for e in episodes for p in POLICIES]
    data={'homecoord_bench/task_revision/fixtures/protection_v5_inputs.json':{'status':'pending_phase_A','episodes':episodes},
          'homecoord_bench/results/protection_v5_offline_20261002.json':{'api_calls':0,'holdout_runs':0,'configurations':8,
              'scripted_runs':32,'mechanisms':1,'reviewer_acceptance':None,'runs':runs}}
    source=('protection_revision.py','protection_contract.py','event_simulator_v5.py')
    data['homecoord_bench/task_revision/fixtures/protection_v5_manifest.json']={
        'source_sha256':{n:hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in source},
        'artifact_sha256':{p:hashlib.sha256(serialize(v).encode()).hexdigest() for p,v in data.items()},
        'prior_versions':'v1-v4 and frozen Phase A/B unchanged','acceptance':None}
    return data


def serialize(value):return json.dumps(value,ensure_ascii=False,indent=2)+'\n'


if __name__=='__main__':
    data=bundle()
    if len(sys.argv)==1:print(json.dumps({'paths':list(data),'configurations':8,'scripted_runs':32}))
    else:
        text=serialize(data[sys.argv[1]]);offset=int(sys.argv[2]);limit=35000
        print(json.dumps({'text':text[offset:offset+limit],'next':offset+limit if offset+limit<len(text) else None},ensure_ascii=True))
