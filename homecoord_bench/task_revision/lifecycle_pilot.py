"""Offline lifecycle pilot. Print artifacts for apply_patch; never call an API."""
import json
import hashlib
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.append(str(ROOT.parent))
from homecoord_bench.task_revision.milestone import c4, FixedProposals
from homecoord_bench.task_revision.event_simulator_v2 import run_event_simulation
from homecoord_bench.task_revision.lifecycle_audit import audit, metrics


def episode(kind, condition, delay=200):
    e = c4(kind, condition)
    main = e['task_stream'][0]
    ground = next(g for g in e['action_grounding'] if g['task_id'] == main['task_id'])
    device = 'devices.' + ground['target']
    e['simulation']['lifecycle_contracts'] = {main['task_id']: {
        'mode': 'restart_from_zero' if kind == 'CLEAN' else 'withdraw',
        'valid_when': deepcopy(main['action_template']['requires']),
        'stop_ack_delay_ms': delay, 'restart_delay_ms': 0,
        'stop_effects': {device: ground['completion_effects'][device]},
    }}
    e['task_card']['lifecycle']['runtime_support'] = 'versioned shared event_simulator_v2; trusted local interlock'
    e['episode_id'] += '-LC2'
    return e


def run(e, policy='IndependentMultiAgent', enabled=True):
    execution_input = deepcopy(e)
    if not enabled:
        execution_input['simulation'].pop('lifecycle_contracts', None)
    trace, result = run_event_simulation(execution_input, FixedProposals(), policy, '', shared_safety_gate=True)
    m = metrics(e, trace, result)
    a = audit(e, trace, m)
    return {'episode_id': e['episode_id'], 'policy': policy, 'lifecycle_enabled': enabled, 'metrics': m, 'audit': a,
            'trace': {k: trace[k] for k in ('episode_id', 'policy', 'events', 'final_state', 'final_state_version')}}


def bundle():
    episodes = [episode(k,c) for k in ('CLEAN','RAIN') for c in ('NOEVENT','PRESTART','INFLIGHT','POSTCOMPLETE','UNRELATED')]
    runs = [run(e,p,enabled) for e in episodes for p in ('IndependentMultiAgent','ConstraintCoordinator','DeadlineAwareCoordinator','GateRetryRule')
            for enabled in (False,True)]
    for r in runs:
        if not r['lifecycle_enabled']:
            if '-INFLIGHT-' in r['episode_id']:
                assert r['metrics']['harm_duration_ms'] == 2400
            continue
        if '-INFLIGHT-' in r['episode_id']:
            assert r['metrics']['harm_duration_ms'] == 200
            assert r['metrics']['stop_confirmed_count'] == 1
        elif '-PRESTART-' in r['episode_id']:
            assert r['metrics']['harm_duration_ms'] == 0
        assert all(r['metrics']['resolution_correct'].values()), r
    data = {'homecoord_bench/task_revision/fixtures/lifecycle_v2_inputs.json': {
                'status': 'author_defined_development_only', 'episodes': episodes},
            'homecoord_bench/results/lifecycle_v2_offline_20261001.json': {
                'status': 'offline_lifecycle_integration_not_physical_validation',
                'api_calls': 0, 'heldout_inputs_read': 0, 'configurations': 10, 'policy_runs': len(runs), 'matched_pairs': 40,
                'policy_results_are_scripted_not_independent_model_samples': True,
                'stop_delay_source': 'author synthetic 200ms; not device measurement', 'runs': runs}}
    fixture = next(iter(data))
    source_paths = [Path(__file__).with_name(name) for name in ('lifecycle_pilot.py','lifecycle_contract.py','lifecycle_audit.py','event_simulator_v2.py','milestone.py')]
    from probe_architecture_comparison_20261001 import implementation_hashes
    data['homecoord_bench/task_revision/fixtures/lifecycle_v2_manifest.json'] = {
        'status': 'author_defined_offline_development_check', 'api_calls': 0,
        'fixture_content_sha256': hashlib.sha256((json.dumps(data[fixture],ensure_ascii=False,indent=2)+'\n').encode('utf-8')).hexdigest(),
        'new_source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths},
        'frozen_v1_implementation_sha256': implementation_hashes(),
        'runtime_migration': 'explicit import of versioned task_revision.event_simulator_v2; legacy entry point not modified',
        'policy_runs': 80, 'matched_pairs': 40, 'heldout_content_read': 0,
    }
    return data


if __name__ == '__main__':
    data = bundle()
    if len(sys.argv) == 1:
        print(json.dumps({'artifacts': list(data), 'configurations': 10, 'verified_policy_runs': 80, 'matched_pairs': 40}))
    else:
        value = json.dumps(data[sys.argv[1]], ensure_ascii=False, indent=2) + '\n'
        start = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        print(json.dumps({'text': value[start:start+18000],
                          'next_offset': start+18000 if len(value)>start+18000 else None}, ensure_ascii=True))
