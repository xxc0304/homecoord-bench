"""Static sensitivity design and constructive feasibility, not policy execution."""
import hashlib
import itertools
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICIES = ('GateRetryRule', 'ConstraintCoordinator', 'DeadlineAwareCoordinator')
SOURCE = 'homecoord_bench/task_revision/fixtures/f2_v7/inputs.json'
OUT = 'docs/small_validation_plan_v1_20261005/plan.json'


def read(p):
    return json.loads((ROOT / p).read_text(encoding='utf-8'))


def sha(p):
    return hashlib.sha256((ROOT / p).read_bytes()).hexdigest()


def differences(a, b, path=''):
    if isinstance(a, dict) and isinstance(b, dict):
        result = []
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                result.append(path+'/'+k)
            else:
                result += differences(a[k], b[k], path+'/'+k)
        return result
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b): return [path+'/length']
        return sum((differences(x, y, path+'/'+str(i)) for i, (x, y) in enumerate(zip(a, b))), [])
    return [] if a == b else [path]


def variant(source, factor, value):
    e = deepcopy(source)
    water = next(t for t in e['task_stream'] if t['task_id'] == 'water')
    window = water['completion_deadline_ms'] - water['release_at_ms']
    if factor == 'water_budget_offset_ms':
        water['completion_deadline_ms'] += value
        water['goal'] = water['goal'].replace(f'within {window} ms', f'within {window+value} ms')
    elif factor == 'water_release_offset_ms':
        water['release_at_ms'] += value
        water['completion_deadline_ms'] += value
        assert water['release_at_ms'] > 0
        e['exogenous_events'][0]['at_ms'] = water['release_at_ms']
    elif factor == 'command_latency_ms':
        e['simulation']['command_latency_ms'] = value
    elif factor != 'baseline':
        raise ValueError('unknown factor')
    ctx = e['exogenous_events'][0]['patch']['coordination_context']['requests']
    request = next(t for t in ctx if t['task_id'] == 'water')
    request.update(release_at_ms=water['release_at_ms'], deadline_ms=water['completion_deadline_ms'])
    return e


def intervals_ok(intervals, capacity):
    bounds = sorted({v for x in intervals for v in (x['start_ms'], x['end_ms'])})
    return all(sum(x['units'] for x in intervals if x['start_ms'] < right and x['end_ms'] > left) <= capacity
               for left, right in zip(bounds, bounds[1:]))


def verify_witness(e, intervals):
    tasks = {t['task_id']: t for t in e['task_stream']}
    ground = {g['task_id']: g for g in e['action_grounding'] if g['operation'] == 'prepare'}
    assert len(intervals) == len(tasks) and {x['task_id'] for x in intervals} == set(tasks)
    for x in intervals:
        t, g = tasks[x['task_id']], ground[x['task_id']]
        assert x['end_ms'] - x['start_ms'] == g['duration_ms'] and x['units'] == g['power_kw']
        assert x['start_ms'] >= t['release_at_ms'] + 300 + e['simulation']['command_latency_ms']
        assert x['end_ms'] <= t['completion_deadline_ms']
    assert intervals_ok(intervals, e['home']['resources']['max_power_kw'])


def feasible_witness(e):
    tasks = {t['task_id']: t for t in e['task_stream']}
    ground = {g['task_id']: g for g in e['action_grounding'] if g['operation'] == 'prepare'}
    for order in itertools.permutations(tasks):
        intervals = []
        for tid in order:
            t, g = tasks[tid], ground[tid]
            ready = t['release_at_ms'] + 300 + e['simulation']['command_latency_ms']
            candidates = sorted({ready, *(x['end_ms'] for x in intervals if x['end_ms'] >= ready)})
            choices = []
            for start in candidates:
                x = {'task_id': tid, 'start_ms': start, 'end_ms': start+g['duration_ms'], 'units': g['power_kw']}
                if x['end_ms'] <= t['completion_deadline_ms'] and intervals_ok(intervals+[x], e['home']['resources']['max_power_kw']):
                    choices.append(x)
            if not choices: break
            intervals.append(choices[0])
        if len(intervals) == len(tasks):
            verify_witness(e, intervals)
            return {'status': 'constructive_schedule_found', 'information': 'offline_all_requests_not_online_input_or_baseline',
                    'proposal_offset_ms': 300, 'command_latency_ms': e['simulation']['command_latency_ms'],
                    'intervals': intervals}
    return {'status': 'witness_not_found_not_proof_of_infeasibility'}


def build():
    acceptance = read('docs/F2_AGGREGATION_V1_ACCEPTANCE_2026-10-05.json')
    for p, h in acceptance['reviewed_sha256'].items(): assert sha(p) == h
    freeze = read('docs/f2_statistical_contract_v1_20261004/freeze_20261004.json')
    locks = {**freeze['source_sha256'], **freeze['runtime_source_sha256']}
    for p, h in locks.items(): assert sha(p) == h
    sources = [e for e in read(SOURCE)['episodes'] if e['episode_id'].endswith('-late')]
    assert len(sources) == 4
    settings = [('baseline', 0), ('water_budget_offset_ms', -30000), ('water_budget_offset_ms', 30000),
                ('water_release_offset_ms', -30000), ('water_release_offset_ms', 30000),
                ('command_latency_ms', 0), ('command_latency_ms', 500)]
    configs, slots, pairs = [], [], []
    for source in sources:
        for factor, value in settings:
            e = variant(source, factor, value)
            cid = source['episode_id'] + '|SV1|' + factor + ':' + str(value)
            delta = differences(source, e)
            if factor == 'baseline': assert not delta
            elif factor == 'command_latency_ms': assert delta == ['/simulation/command_latency_ms']
            else:
                allowed = {'/task_stream/3/completion_deadline_ms',
                           '/exogenous_events/0/patch/coordination_context/requests/3/deadline_ms'}
                if factor == 'water_budget_offset_ms': allowed.add('/task_stream/3/goal')
                else: allowed |= {'/task_stream/3/release_at_ms', '/exogenous_events/0/at_ms',
                                  '/exogenous_events/0/patch/coordination_context/requests/3/release_at_ms'}
                assert set(delta) == allowed
            certificate = feasible_witness(e)
            assert certificate['status'] == 'constructive_schedule_found'
            configs.append({'config_id': cid, 'source_episode_id': source['episode_id'],
                'source_path': SOURCE, 'source_pointer': '/episodes/'+str(read(SOURCE)['episodes'].index(source)),
                'factor': factor, 'value_ms': value, 'changed_paths_excluding_private_identity': delta,
                'derived_episode_sha256': hashlib.sha256(json.dumps(e, sort_keys=True, ensure_ascii=True).encode()).hexdigest(),
                'required_requests': [{'task_id': t['task_id'], 'release_ms': t['release_at_ms'],
                    'deadline_ms': t['completion_deadline_ms'], 'own_budget_ms': t['completion_deadline_ms']-t['release_at_ms']}
                    for t in e['task_stream']], 'capacity_units': e['home']['resources']['max_power_kw'],
                'proposal_offset_ms': 300, 'command_latency_ms': e['simulation']['command_latency_ms'],
                'feasibility_certificate': certificate, 'new_identity_assigned_only_on_future_materialization': True})
            for policy in POLICIES:
                sid = cid+'|'+policy
                slots.append({'slot_id': sid, 'config_id': cid, 'policy': policy, 'role': 'main'})
                if factor != 'baseline':
                    baseline = source['episode_id']+'|SV1|baseline:0|'+policy
                    pairs.append({'left': baseline, 'right': sid, 'factor': factor, 'delta_direction': 'right_minus_left'})
    assert (len(configs), len(slots), len(pairs)) == (28, 84, 72)
    return {'status': 'draft_static_plan_not_frozen_or_executed', 'date': '2026-10-05',
            'scope': 'F2_late_only_one_factor_at_a_time_no_new_structure',
            'research_question': 'conflict_service_latency_robustness',
            'source_sha256': locks, 'acceptance_sha256': {'docs/F2_AGGREGATION_V1_ACCEPTANCE_2026-10-05.json': sha('docs/F2_AGGREGATION_V1_ACCEPTANCE_2026-10-05.json')},
            'configurations': configs, 'run_slots': slots, 'pairs': pairs,
            'execution_policy_count': 3, 'static_configs': 28, 'planned_runs': 84, 'planned_pairs': 72,
            'historical_runs_reused_as_new_baselines': False, 'scores_computed': False,
            'api_calls': 0, 'simulator_runs': 0, 'holdout_read': False,
            'new_provider_or_policy_implemented': False, 'feasibility_is_online_guarantee': False,
            'factorial_interactions_planned': False, 'cross_family_pooling_planned': False,
            'gate': 'accept_design_then_explicit_freeze_then_versioned_execution_and_adapter',
            'future_stages_not_in_this_scope': ['F2_unstarted_reservation_replan_ablation', 'F1_sorting_vs_batch_wait_ablation']}


if __name__ == '__main__':
    import sys
    text = json.dumps(build(), ensure_ascii=False, indent=2)+'\n'
    offset = int(sys.argv[1]) if len(sys.argv)>1 else 0
    print(json.dumps({'text': text[offset:offset+40000], 'next': offset+40000 if offset+40000<len(text) else None}, ensure_ascii=True))

