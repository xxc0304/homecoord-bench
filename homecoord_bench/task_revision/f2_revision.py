"""Development-only F2 information-boundary repair, explicit v7, zero API."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from homecoord_bench.task_revision.milestone import ROOT as DATA
from homecoord_bench.task_revision.f2_information import POLICIES
from homecoord_bench.task_revision.event_simulator_v7 import run_event_simulation
from homecoord_bench.task_revision.review_packet import feasible, verify_witness
from runtime.dry_run import _decision_from_template
from evaluate import set_path

ROOT = DATA.parent
OUT = 'homecoord_bench/task_revision/fixtures/f2_v7'


def inputs():
    rows = []
    directory = DATA/'revision_drafts/20260930_task_family_split/development'
    for p in sorted(directory.glob('D-F2-*.json')):
        e = json.loads(p.read_text(encoding='utf-8'))
        assert e['split'] == 'development'
        e['episode_id'] = 'F2R1-' + e['episode_id']
        e['review_status'] = 'revised_design_and_implementation_pending_review'
        e['f2_information_contract'] = 'request-only-whitelist-v1'
        e['public_devices'] = []
        for a in e['agents']:
            tool = next(t for t in e['tool_catalog'] if t['agent_id'] == a['agent_id'] and t['operation'] == 'prepare')
            e['public_devices'].append({'agent_id': a['agent_id'], 'role': a['role'],
                                       'target': tool['target'], 'service': tool['provides_service'],
                                       **tool['cost_contract']})
        e['nonpreemptive_delegation'] = {
            'principal': 'SyntheticResident', 'authority': 'explicit_synthetic_service_contract',
            'rule': 'Once an authorized prepare cycle starts, finish its declared duration; no cancellation, preemption or mode switching.',
            'arrival_basis': 'external predetermined releases independent of policy actions, not an empirical arrival distribution',
            'scope': 'synthetic scheduling, not actual appliance interruption constraints'}
        rows.append(e)
    assert len(rows) == 8
    return rows


class PublicProposals:
    """Rule from public authorized capability only, no hidden answer template."""
    include_evaluation_hints = False
    last_latency_ms = 300

    def __init__(self): self.calls = []

    def decide(self, request, instructions):
        tool = next(t for t in request['available_actions'] if t['operation'] == 'prepare')
        template = {'target': tool['target'], 'operation': tool['operation'], 'parameters': {},
                    'duration_ms': tool['cost_contract']['duration_ms'],
                    'power_kw': tool['cost_contract']['resource_units'], 'requires': tool['preconditions']}
        decision = _decision_from_template(request, template, request['state_version'])
        self.calls.append({'request': deepcopy(request), 'decision': deepcopy(decision)})
        return decision


def recount(e, trace, result, calls):
    tasks = {t['task_id']: t for t in e['task_stream']}
    assert trace['agent_requests'] == [c['request'] for c in calls]
    for r in trace['agent_requests']:
        now = r['current_time_ms']
        assert now == tasks[r['task']['task_id']]['release_at_ms']
        published = {t['task_id'] for t in e['task_stream'] if t['release_at_ms'] <= now}
        assert {t['task_id'] for t in r['state']['coordination_context']['requests']} == published
        assert not {'action_template', 'acceptable_actions', 'required_action'} & set(r['task'])
        assert r['episode_id'] == r['base_episode_id'] == 'F2-public-home'
    active = {}; started = {}; done = {}; intervals = []; clock = 0
    state = deepcopy(e['initial_state']['values']); version = e['initial_state']['version']
    for x in trace['events']:
        now = x['timestamp_ms']; assert now >= clock; clock = now
        tid = x.get('task_id')
        if x['type'] == 'action_started':
            assert now >= tasks[tid]['release_at_ms'] and x['proposal_id'] not in active
            g = next(g for g in e['action_grounding'] if g['task_id'] == tid and g['operation'] == x['operation'])
            assert x['duration_ms'] == g['duration_ms'] and x['power_kw'] == g['power_kw']
            assert x['operation'] == 'prepare'
            assert sum(s['power_kw'] for s in active.values()) + x['power_kw'] <= e['home']['resources']['max_power_kw']
            active[x['proposal_id']] = x; started[tid] = now
        if x['type'] == 'action_completed':
            s = active.pop(x['proposal_id'])
            assert (s['task_id'], s['operation'], s['target']) == (tid, x['operation'], x['target'])
            assert now == s['timestamp_ms'] + s['duration_ms']
            ground = next(g for g in e['action_grounding'] if g['task_id'] == tid and g['operation'] == x['operation'])
            assert x['effects'] == ground['completion_effects']
            done[tid] = now
            intervals.append({'task_id': tid, 'start_ms': s['timestamp_ms'], 'end_ms': now, 'units': s['power_kw']})
        if x['type'] == 'state_update':
            patch = x['patch']
            if x.get('source') == 'action_started':
                assert any(g['task_id'] == tid and g['start_effects'] == patch for g in e['action_grounding'])
            else:
                assert any(event['at_ms'] == now and event['patch'] == patch for event in e['exogenous_events'])
        elif x['type'] == 'action_completed': patch = x['effects']
        else: patch = {}
        for path, value in patch.items(): set_path(state,path,value)
        if x['type'] in ('state_update','action_completed'):
            version += 1; assert x['new_state_version'] == version
    assert not active and state == trace['final_state'] and version == trace['final_state_version']
    values = {
        'task_correct_action_completed': {tid: tid in done for tid in tasks},
        'task_start_wait_ms': {tid: started[tid]-t['release_at_ms'] if tid in started else None for tid,t in tasks.items()},
        'task_completion_latency_ms': {tid: done[tid]-t['release_at_ms'] if tid in done else None for tid,t in tasks.items()},
        'task_completion_tardiness_ms': {tid: max(0,done[tid]-t['completion_deadline_ms']) if tid in done else None for tid,t in tasks.items()},
        'task_deadline_met': {tid: tid in done and done[tid] <= t['completion_deadline_ms'] for tid,t in tasks.items()},
    }
    for key, value in values.items(): assert result[key] == value, (key, result[key], value)
    assert result['all_deadlines_met'] == all(values['task_deadline_met'].values())
    return {'recount': values, 'resource_intervals': intervals, 'status': 'author_verified_not_acceptance'}


def run(e, policy='ConstraintCoordinator', provider=None):
    provider = provider or PublicProposals()
    trace, result = run_event_simulation(e, provider, policy, '', shared_safety_gate=True)
    calls = provider.calls
    return {'evaluation_episode_id': e['episode_id'], 'policy': policy, 'calls': calls,
            'trace': trace, 'result': result, 'audit': recount(e, trace, result, calls)}


def counterfactual(e, case):
    x = deepcopy(e); future = [t for t in x['task_stream'] if t['release_at_ms'] > 0]
    assert len(future) == 1
    t = future[0]
    x['episode_id'] = 'SECRET-future-condition'; x['base_episode_id'] = 'SECRET-private-base'
    # These free-form/evaluator fields are outside the frozen public whitelist.
    x['goals'].append({'path': 'SECRET-future-goal', 'op': 'eq', 'value': True})
    x['initial_state']['values']['coordination_context']['secret'] = 'SECRET-future-context'
    x['home']['resources']['task_power_bounds_kw'][t['task_id']] = 999
    for tool in x['tool_catalog']: tool['description'] = 'SECRET-future-description'
    for a in x['agents']: a['private_note'] = 'SECRET-future-agent'
    if case == 'different_arrival':
        allowance = t['completion_deadline_ms'] - t['release_at_ms']
        t['release_at_ms'] += 30000; t['completion_deadline_ms'] = t['release_at_ms'] + allowance
        x['exogenous_events'][0]['at_ms'] = t['release_at_ms']
    elif case == 'different_request':
        t['goal'] = 'SECRET-future-goal'; t['priority'] += 1
        t['completion_deadline_ms'] += 10000
    elif case == 'no_future_request':
        tid = t['task_id']; x['task_stream'] = [v for v in x['task_stream'] if v['task_id'] != tid]
        x['action_grounding'] = [v for v in x['action_grounding'] if v['task_id'] != tid]
        x['home']['resources']['task_power_bounds_kw'].pop(tid)
        x['exogenous_events'] = []
    else: raise ValueError(case)
    return x


def prefix(r, before):
    return {'calls': [c for c in r['calls'] if c['request']['current_time_ms'] < before],
            'events': [x for x in r['trace']['events'] if x['timestamp_ms'] < before]}


def serialize(v): return json.dumps(v, ensure_ascii=False, indent=2) + '\n'


def bundle():
    episodes = inputs(); runs = [run(e,p) for e in episodes for p in POLICIES]
    certificates = []
    for e in episodes:
        cert = feasible(e); verify_witness(e, cert)
        assert all(w['status'] == 'witness_found' for w in cert['mode_witnesses'])
        certificates.append({'evaluation_episode_id': e['episode_id'], **cert})
    checks = []; diagnostic_artifacts = {}
    for e in episodes:
        if e['pairing']['temporal_arm'] != 'late': continue
        before = min(t['release_at_ms'] for t in e['task_stream'] if t['release_at_ms'] > 0)
        for p in POLICIES:
            original = run(e,p)
            for case in ('different_arrival','different_request','no_future_request'):
                changed = counterfactual(e,case); diagnostic = run(changed,p)
                a,b = prefix(original,before),prefix(diagnostic,before)
                assert a == b, (e['episode_id'],p,case)
                checks.append({'evaluation_episode_id':e['episode_id'],'policy':p,'case':case,
                               'before_ms':before,'full_inputs_and_online_events_equal':True,
                               'prefix_sha256':hashlib.sha256(serialize(a).encode()).hexdigest()})
                path = OUT+'/diagnostics/'+e['episode_id']+'-'+case+'.json'
                diagnostic_artifacts.setdefault(path, {'case':case, 'before_ms':before, 'episode':changed, 'runs':[]})['runs'].append(diagnostic)
    artifacts = {
        OUT+'/inputs.json': {'episodes':episodes,'acceptance':None},
        OUT+'/feasibility.json': {'offline_only':True,'certificates':certificates},
        OUT+'/index.json': {
            'api_calls':0,'holdout_runs':0,'configurations':8,'scripted_runs':32,
            'counterfactual_runs':48,'reviewer_acceptance':None,
            'run_files':[OUT+'/runs/'+e['episode_id']+'.json' for e in episodes],
            'diagnostic_files':list(diagnostic_artifacts),'counterfactual_checks':checks},
    }
    for i,e in enumerate(episodes):
        artifacts[OUT+'/runs/'+e['episode_id']+'.json'] = {'evaluation_episode_id':e['episode_id'], 'runs':runs[i*4:i*4+4]}
    artifacts.update(diagnostic_artifacts)
    paths = ['homecoord_bench/task_revision/'+n for n in ('f2_information.py','f2_revision.py','event_simulator_v7.py')]
    paths += ['homecoord_bench/runtime/'+n for n in ('event_simulator.py','protocol.py','execution.py','episode_validation.py','tool_contract.py','task_response_metrics.py','dry_run.py')]
    paths += ['homecoord_bench/evaluate.py','homecoord_bench/task_revision/review_packet.py']
    sources = sorted((DATA/'revision_drafts/20260930_task_family_split/development').glob('D-F2-*.json'))
    paths += [str(p.relative_to(ROOT)).replace('\\','/') for p in sources]
    artifacts[OUT+'/manifest.json'] = {
        'source_sha256': {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},
        'artifact_sha256': {p:hashlib.sha256(serialize(v).encode()).hexdigest() for p,v in artifacts.items()},
        'acceptance':None,'prior_versions':'all frozen source/inputs/results and Phase A/B unchanged'}
    return artifacts


if __name__ == '__main__':
    import sys
    data = bundle()
    print(json.dumps(list(data) if len(sys.argv) == 1 else serialize(data[sys.argv[1]]), ensure_ascii=True))
