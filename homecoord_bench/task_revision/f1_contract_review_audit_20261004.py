"""Separate metadata review checks; no author generator/scorer/simulator imports."""
import hashlib
import json
from collections import Counter
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN = 'docs/f1_statistical_contract_v1_20261004/plan.json'
CONTRACT = 'docs/F1_STATISTICAL_CONTRACT_V1_2026-10-04.md'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def changed(a, b, p=''):
    if type(a) != type(b):
        return {p}
    if isinstance(a, dict):
        return set().union(*(changed(a.get(k), b.get(k), p + '/' + k) for k in a.keys() | b.keys()))
    if isinstance(a, list):
        assert len(a) == len(b)
        return set().union(*(changed(x, y, p + '/' + str(i)) for i, (x, y) in enumerate(zip(a, b))))
    return set() if a == b else {p}


def audit():
    plan = json.loads((ROOT / PLAN).read_text(encoding='utf-8'))
    locks = plan['source_sha256']
    assert len(locks) == 10
    assert all(sha(ROOT / p) == digest for p, digest in locks.items())
    configs = {c['episode_id']: c for c in plan['configurations']}
    bases = ('D-F1-01', 'D-F1-02')
    arms = ('competition', 'no_competition')
    deadlines = ('base', 'loose')
    policies = ('GateRetryRule', 'ConstraintCoordinator', 'DeadlineAwareCoordinator')
    expected_configs = {f'{b}-{a}-{d}' for b, a, d in product(bases, arms, deadlines)}
    assert len(plan['configurations']) == 8 and set(configs) == expected_configs
    docs = {eid: json.loads((ROOT / c['source_path']).read_text(encoding='utf-8')) for eid, c in configs.items()}
    rows = {r['slot_id']: r for r in plan['runs']}
    expected_rows = {f'{e}|{p}|order{o}' for e, p, o in product(expected_configs, policies, range(3))}
    assert len(plan['runs']) == 72 and set(rows) == expected_rows
    for eid, config in configs.items():
        tasks = docs[eid]['episode']['task_stream']
        fields = ('task_id', 'agent_id', 'release_at_ms', 'completion_deadline_ms', 'requested_service', 'acceptable_actions')
        assert config['required_requests'] == [{k: t[k] for k in fields} for t in tasks]
    for sid, row in rows.items():
        eid, policy, order = row['episode_id'], row['policy'], row['order']
        assert sid == f'{eid}|{policy}|order{order}'
        r = docs[eid]['runs'][int(row['source_pointer'].split('/')[-1])]
        assert (r['episode_id'], r['policy'], r['arrival_order_index']) == (eid, policy, order)
        ids = [t['task_id'] for t in docs[eid]['episode']['task_stream']]
        ids = (ids, list(reversed(ids)), ids[1:] + ids[:1])[order]
        calls = r['calls']
        assert len(calls) == len(ids)
        assert {c['request']['task']['task_id']: c['logical_latency_ms'] for c in calls} == {
            t: 800 + i * 200 for i, t in enumerate(ids)}
        events = r['trace']['events']
        for tid in ids:
            releases = [e for e in events if e['type'] == 'task_released' and e.get('task_id') == tid]
            returns = [e for e in events if e['type'] == 'proposal_returned' and e.get('task_id') == tid]
            assert len(releases) == len(returns) == 1
            call = next(c for c in calls if c['request']['task']['task_id'] == tid)
            assert releases[0]['request_id'] == returns[0]['request_id'] == call['request']['request_id']
            assert returns[0]['timestamp_ms'] - releases[0]['timestamp_ms'] == call['logical_latency_ms']
    sid = lambda e, p, o: f'{e}|{p}|order{o}'
    expected_pairs = set()
    for e in expected_configs:
        expected_pairs.update(('policy', sid(e, policies[0], o), sid(e, p, o)) for p, o in product(policies[1:], range(3)))
        expected_pairs.update(('return_order', sid(e, p, 0), sid(e, p, o)) for p, o in product(policies, (1, 2)))
    for b, p, o in product(bases, policies, range(3)):
        expected_pairs.update(('capacity', sid(f'{b}-{arms[0]}-{d}', p, o), sid(f'{b}-{arms[1]}-{d}', p, o)) for d in deadlines)
        expected_pairs.update(('deadline', sid(f'{b}-{a}-{deadlines[0]}', p, o), sid(f'{b}-{a}-{deadlines[1]}', p, o)) for a in arms)
    actual_pairs = {(p['kind'], p['left'], p['right']) for p in plan['pairs']}
    assert len(plan['pairs']) == len(actual_pairs) == 168 and actual_pairs == expected_pairs
    expected_cells = {(b, p, o, tuple(sid(f'{b}-{a}-{d}', p, o) for a, d in product(arms, deadlines)))
                      for b, p, o in product(bases, policies, range(3))}
    assert len(plan['four_cells']) == 18
    assert {(g['base_episode_id'], g['policy'], g['order'], tuple(g['slots'])) for g in plan['four_cells']} == expected_cells
    for contrast in plan['contrast_checks']:
        a = docs[contrast['left_config']]['episode']; b = docs[contrast['right_config']]['episode']
        paths = changed(a, b)
        assert paths == set(contrast['actual_changed_paths'])
        if contrast['kind'] == 'capacity':
            allowed = {'/episode_id', '/pairing/resource_arm', '/home/resources/max_power_kw',
                       '/initial_state/values/coordination_context/resource_capacity_units', '/conflict_rules/0/capacity'}
            assert paths == allowed
            assert a['home']['resources']['max_power_kw'] < b['home']['resources']['max_power_kw']
        else:
            allowed = {'/episode_id', '/pairing/temporal_arm'}
            for i, (ta, tb) in enumerate(zip(a['task_stream'], b['task_stream'])):
                allowed |= {f'/task_stream/{i}/goal', f'/task_stream/{i}/completion_deadline_ms',
                            f'/initial_state/values/coordination_context/requests/{i}/deadline_ms'}
                assert tb['completion_deadline_ms'] - ta['completion_deadline_ms'] == 1200000
                old = ta['completion_deadline_ms'] - ta['release_at_ms']
                new = tb['completion_deadline_ms'] - tb['release_at_ms']
                assert ta['goal'].replace(str(old), str(new)) == tb['goal']
            assert paths == allowed
    # Contract counterexample, not any strategy's score: differing completed populations.
    per_task = {'a': 100, 'b': 1000}
    cohorts = [{'a'}, {'a', 'b'}, {'a', 'b'}, {'a', 'b'}]
    means = [sum(per_task[t] for t in c) / len(c) for c in cohorts]
    interaction = (means[3] - means[1]) - (means[2] - means[0])
    assert interaction == -450
    return {'status': 'metadata_checks_passed_contract_requires_clarification',
            'review_nature': 'same_model_separate_check_path_not_independent_dual_review',
            'contract_sha256': sha(ROOT / CONTRACT), 'plan_sha256': sha(ROOT / PLAN),
            'source_locks_checked': 10, 'run_identities_checked': 72,
            'pair_counts': dict(Counter(p['kind'] for p in plan['pairs'])),
            'four_cells_checked': 18, 'contrast_differences_checked': 8,
            'counterexample_only': {'unchanged_task_latencies_ms': per_task,
                                    'four_completed_sets': [sorted(c) for c in cohorts],
                                    'different_population_means_ms': means,
                                    'spurious_interaction_ms': interaction,
                                    'common_four_cell_population': ['a'],
                                    'common_population_interaction_ms': 0},
            'strategy_scores_computed': False, 'api_calls': 0, 'simulator_runs': 0,
            'contract_frozen': False}


if __name__ == '__main__':
    print(json.dumps(audit(), ensure_ascii=False, indent=2))
