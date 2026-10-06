import sys,json,copy
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(r'.')
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'homecoord_bench'))
from homecoord_bench.task_revision.protection_revision import run
from homecoord_bench.task_revision.milestone import FixedProposals
from homecoord_bench.task_revision.protection_contract import validate
inputs=json.loads((ROOT/'homecoord_bench/task_revision/fixtures/protection_v5_inputs.json').read_text(encoding='utf-8'))['episodes']
class Slow(FixedProposals):last_latency_ms=7000
class NoLowAction(FixedProposals):
    def decide(self,req,instructions=''):
        d=super().decide(req,instructions)
        if req['task'].get('request_contract'):
            d.update(response_type='noop',actions=[],reason_code='no_applicable_action')
        return d
out=[]
for kind in ['LIGHT','BLINDS']:
    def base(arm):return copy.deepcopy(next(e for e in inputs if e['episode_id']==f'C1R2-{kind}-legality-{arm}'))
    e=base('CONFLICT');old=e['task_stream'][1];new=copy.deepcopy(old)
    new['task_id']=old['task_id']+'_new';new['release_at_ms']=6500;e['task_stream'].append(new)
    g=copy.deepcopy(e['action_grounding'][1]);g['task_id']=new['task_id'];e['action_grounding'].append(g)
    e['simulation']['request_disposition_contracts'][new['task_id']]=copy.deepcopy(new['request_contract'])
    r=run(e);assert r['result']['request_status'][old['task_id']]=='rejected_terminal' and r['result']['request_status'][new['task_id']]=='completed'
    out.append({'case':kind+'_new_identity','provenance':'reviewer-generated deterministic boundary, not author-frozen main replay','episode':e,'run':r})
    e=base('SAFE');e['task_stream'][1]['release_at_ms']=6000;r=run(e)
    assert r['result']['request_status'][e['task_stream'][1]['task_id']]=='completed'
    out.append({'case':kind+'_expiry_same_release','episode':e,'run':r})
    for arm in ['CONFLICT','SAFE']:
        e=base(arm);r=run(e,provider=Slow());tid=e['task_stream'][1]['task_id']
        if arm=='CONFLICT':assert r['result']['request_status'][tid]=='rejected_terminal' and tid not in r['result']['model_latency_by_task_ms']
        else:assert r['result']['task_completion_tardiness_ms'][tid]>0 and not r['result']['task_deadline_met'][tid]
        out.append({'case':kind+'_slow_'+arm,'episode':e,'run':r})
    e=base('SAFE');r=run(e,provider=NoLowAction());tid=e['task_stream'][1]['task_id']
    assert r['result']['request_status'][tid]=='unresolved'
    assert not r['result']['task_correct_action_completed'][tid] and r['result']['task_completion_latency_ms'][tid] is None
    assert any(x['type']=='request_admitted' and x['task_id']==tid for x in r['trace']['events'])
    assert r['audit']['correct_disposition'][tid] is False
    out.append({'case':kind+'_admitted_no_action','episode':e,'run':r,'reviewer_expected_admission_correct':True,'finding':'author correct_disposition couples legal admission to service completion'})
    for case in ['missing_authority','duplicate_task','non_boolean','mismatched_policy']:
        e=base('CONFLICT')
        if case=='missing_authority':e['user_delegations']=[]
        elif case=='duplicate_task':e['task_stream'].append(copy.deepcopy(e['task_stream'][1]))
        elif case=='non_boolean':
            path=e['user_delegations'][0]['protected_path'];parent,key=path.split('.');e['initial_state']['values'][parent][key]='true'
        else:e['task_stream'][1]['request_contract']['policy_id']='unauthorized-policy'
        try:run(e)
        except ValueError as err:out.append({'case':kind+'_'+case,'episode':e,'rejected_before_execution':True,'exception_type':'ValueError','message':str(err)})
        else:raise AssertionError(case+' failed to reject')
Path('outputs/C1_V5_REVIEWER_BOUNDARIES_20261002.json').write_text(json.dumps({'provenance':'Independent reviewer generated after design acceptance. Explicit deterministic providers only; no API/model. Modified inputs kept only in this artifact; production files unchanged. Strategy ConstraintCoordinator only; not all policies or all boundary cases.','cases':out},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps([{'case':x['case'],'preflight_rejected':x.get('rejected_before_execution'),'status':x.get('run',{}).get('result',{}).get('request_status'),'correct_disposition':x.get('run',{}).get('audit',{}).get('correct_disposition')} for x in out],ensure_ascii=False,indent=2))
