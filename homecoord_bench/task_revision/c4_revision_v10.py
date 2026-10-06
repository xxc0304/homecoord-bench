"""Targeted C4 implementation correction; accepted v9 design unchanged."""
import hashlib,json
from copy import deepcopy
from pathlib import Path
from homecoord_bench.task_revision.c4_revision_v9 import episode,diagnostic_inputs,PublicC4,serialize,WINDOWS
from homecoord_bench.task_revision.c4_contract_v9 import POLICIES
from homecoord_bench.task_revision.event_simulator_v10 import run_event_simulation
from homecoord_bench.task_revision.c4_audit_v10 import audit

ROOT=Path(__file__).resolve().parents[2]
OUT='homecoord_bench/task_revision/fixtures/c4_v10'
OLD=ROOT/'homecoord_bench/task_revision/fixtures/c4_v9'

def run(e,policy='ConstraintCoordinator',latency=300):
    provider=PublicC4(latency)
    trace,result=run_event_simulation(e,provider,policy,'',shared_safety_gate=True)
    return {'policy':policy,'trace':trace,'result':result,'calls':provider.calls,
            'audit':audit(e,trace,result,provider.calls)}

def cases():
    data=[]
    for name in ('late_race','before_recovery','never_restore','restore_before_natural_end','just_before_end','exact_boundary','just_after_end'):
        e=episode('CLEAN','BOUNDARY' if name=='exact_boundary' else 'LATE',1000)
        if name=='before_recovery':e['exogenous_events']=[x for x in e['exogenous_events'] if x['at_ms']<=4000]
        if name=='never_restore':e['exogenous_events']=[x for x in e['exogenous_events'] if x['event']!='validity_restored']
        if name=='restore_before_natural_end':
            next(x for x in e['exogenous_events'] if x['event']=='validity_restored')['at_ms']=3300
        if name in ('just_before_end','just_after_end'):
            next(x for x in e['exogenous_events'] if x['event']=='validity_lost')['at_ms']=3399 if name=='just_before_end' else 3401
        e['episode_id']='C4R2-CLEAN-'+name
        data.append({'case':name,'episode':e})
    return data

def bundle():
    selected=cases()
    data={OUT+'/inputs.json':{'cases':selected,'design':'accepted v9 synthetic contract unchanged','acceptance':None}}
    for x in selected:
        data[OUT+'/runs/'+x['case']+'.json']={'runs':[run(x['episode'],p) for p in POLICIES]}
    checks=[]
    sources=[(episode(k,w),300,'runs') for k in ('CLEAN','RAIN') for w in WINDOWS]
    sources += [(x['episode'],x['latency'],'diagnostics') for x in diagnostic_inputs()]
    for e,latency,folder in sources:
        old=json.loads((OLD/folder/(e['episode_id']+'.json')).read_text(encoding='utf-8'))['runs']
        for p,previous in zip(POLICIES,old):
            current=run(e,p,latency)
            changed={k:{'old':previous['result'].get(k),'new':current['result'].get(k)}
                     for k in sorted(set(previous['result'])|set(current['result']))
                     if previous['result'].get(k)!=current['result'].get(k)}
            affected=e['episode_id']=='C4R1-CLEAN-LATE-late_natural_race'
            if not affected:assert not changed,(e['episode_id'],p,changed)
            else:
                tid=e['task_stream'][0]['task_id']
                assert current['result']['task_completion_latency_ms'][tid]==8100
                assert current['audit']['physical_completions_after_invalidation'][0]['timestamp_ms']==3400
            assert current['calls']==previous['calls']
            checks.append({'episode_id':e['episode_id'],'policy':p,'input_capture_equal':True,
                           'result_equal':not changed,'changed_result_fields':changed,
                           'audit':current['audit']})
    data[OUT+'/regression.json']={'replays':96,'unaffected_result_equal':92,'corrected':4,
                                  'checks':checks,'api_calls':0,'holdout_runs':0,'acceptance':None}
    old_paths=list(OLD.rglob('*.json'))+[ROOT/'homecoord_bench/task_revision'/n for n in
        ('event_simulator_v9.py','c4_audit_v9.py','c4_revision_v9.py','c4_contract_v9.py','c4_lifecycle_contract_v9.py','c4_evaluate_v9.py')]
    paths=['homecoord_bench/task_revision/'+n for n in ('event_simulator_v10.py','c4_audit_v10.py','c4_revision_v10.py')]
    paths += ['homecoord_bench/tests/test_c4_v10.py']
    data[OUT+'/manifest.json']={'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},
        'v9_frozen_sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in old_paths},
        'artifact_sha256':{p:hashlib.sha256(serialize(v).encode()).hexdigest() for p,v in data.items()},
        'acceptance':None}
    return data

if __name__=='__main__':
    import sys
    b=bundle()
    print(json.dumps(list(b) if len(sys.argv)==1 else serialize(b[sys.argv[1]]),ensure_ascii=True))
