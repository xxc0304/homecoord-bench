"""Read-only separate event arithmetic. Same author, not independent review.

Does not import the pilot, engine, generator or main audit/scorer.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = 'docs/latency_window_pilot_v1_20261006'


def read(p):
    return json.loads((ROOT / p).read_text(encoding='utf-8'))


def check(ok, message):
    if not ok:
        raise ValueError(message)


def sha(p):
    return hashlib.sha256((ROOT / p).read_bytes()).hexdigest()


def recount(e, run):
    tasks = {t['task_id']: t for t in e['task_stream']}
    ground = {g['task_id']: g for g in e['action_grounding'] if g['operation'] == 'prepare'}
    starts, ends, releases, returns = {}, {}, {}, {}
    for i, x in enumerate(run['trace']['events']):
        tid = x.get('task_id')
        if x['type'] == 'task_released':
            check(tid not in releases and x['timestamp_ms'] == tasks[tid]['release_at_ms'], 'release')
            releases[tid] = (x, i)
        elif x['type'] == 'proposal_returned':
            check(tid in releases and tid not in returns and x['timestamp_ms'] == tasks[tid]['release_at_ms']+300, 'return')
            returns[tid] = (x, i)
        elif x['type'] == 'action_started':
            check(tid in returns and tid not in starts, 'duplicate/early start')
            check(x['timestamp_ms'] >= returns[tid][0]['timestamp_ms']+100, 'command floor')
            check(x['duration_ms'] == ground[tid]['duration_ms'] and x['power_kw'] == ground[tid]['power_kw'], 'start cost')
            starts[tid] = (x, i)
        elif x['type'] == 'action_completed':
            check(tid in starts and tid not in ends, 'unmatched/duplicate completion')
            s = starts[tid][0]
            check(all(x[k] == s[k] for k in ('task_id', 'agent_id', 'target', 'operation', 'proposal_id', 'reservation_generation')), 'receipt identity')
            check(x['timestamp_ms'] == s['timestamp_ms']+s['duration_ms'], 'receipt clock')
            ends[tid] = (x, i)
    intervals = [(x[0]['timestamp_ms'], ends[t][0]['timestamp_ms'], x[0]['power_kw']) for t, x in starts.items() if t in ends]
    check(all(sum(u for a, b, u in intervals if a <= p < b) <= e['home']['resources']['max_power_kw']
              for p in {p for a, b, _ in intervals for p in (a, b)}), 'capacity')
    rows = {}
    for t, task in tasks.items():
        S = starts[t][0]['timestamp_ms'] if t in starts else None
        F = ends[t][0]['timestamp_ms'] if t in ends else None
        R = task['release_at_ms']
        P = returns[t][0]['timestamp_ms'] if t in returns else None
        rows[t] = {'release_ms': R, 'deadline_ms': task['completion_deadline_ms'],
                   'proposal_return_ms': P, 'start_ms': S, 'completion_ms': F,
                   'completed': F is not None, 'timely': F is not None and F <= task['completion_deadline_ms'],
                   'task_start_wait_ms': S-R if S is not None else None,
                   'proposal_to_start_ms': S-P if S is not None and P is not None else None,
                   'execution_ms': F-S if F is not None else None,
                   'completion_latency_ms': F-R if F is not None else None,
                   'tardiness_ms': max(0, F-task['completion_deadline_ms']) if F is not None else None,
                   'event_indices': {'release': releases[t][1], 'return': returns[t][1],
                                     'start': starts[t][1] if t in starts else None,
                                     'completion': ends[t][1] if t in ends else None}}
    return rows


def build():
    checks = 0
    def require(ok, message):
        nonlocal checks
        check(ok, message)
        checks += 1
    plan = read(OUT + '/plan_v2_metadata.json')
    correction_lock = read(OUT + '/metadata_correction_lock_v2.json')
    for p, h in correction_lock['sha256'].items():
        require(sha(p) == h, 'correction/raw hash: '+p)
    lock_path = OUT + '/author_pre_execution_lock.json'
    lock = read(lock_path)
    for section in ('new_design_code_sha256', 'protected_sha256'):
        for p, h in lock[section].items():
            require(sha(p) == h, 'source hash: '+p)
    stat = read(OUT + '/statistics.json')
    documents = []
    for i, c in enumerate(plan['configurations']):
        path = OUT + '/config_' + str(i).zfill(2) + '.json'
        d = read(path)
        require(d['config'] == c and d['lock_sha256'] == sha(lock_path), 'identity')
        require(stat['raw_artifact_sha256'][path] == sha(path), 'raw hash')
        rows = [recount(d['input'], r) for r in d['runs']]
        require([r['arm'] for r in d['runs']] == ['retain', 'replan'], 'arms')
        require(d['runs'][0]['calls'] == d['runs'][1]['calls'], 'calls')
        for j, arm in enumerate(('retain', 'replan')):
            saved = d['pair']['audits'][j]
            for t, r in rows[j].items():
                require(saved['tasks'][t] == r, 'event metrics')
            n = len(rows[j]); nc = sum(r['completed'] for r in rows[j].values()); nt = sum(r['timely'] for r in rows[j].values())
            require(saved['denominators'] == {'required': n, 'completed': nc, 'timely': nt}, 'fixed denominator')
            require(saved['metrics']['service_rate'] == nc/n and saved['metrics']['timely_service_rate'] == nt/n, 'rates')
            house = max(r['completion_ms'] for r in rows[j].values())-d['input']['episode_release_at_ms'] if nc == n else None
            require(saved['metrics']['whole_house_completion_ms'] == house, 'whole-house eligibility')
            events = d['runs'][j]['trace']['events']
            start_index = next(k for k, x in enumerate(events) if x['type'] == 'reservation_review_started')
            commit_index = next(k for k, x in enumerate(events) if x['type'] == 'reservation_review_committed')
            require(events[commit_index]['timestamp_ms']-events[start_index]['timestamp_ms'] == c['review_delay_ms'], 'review duration')
            require(events[commit_index]['timestamp_ms'] == c['prediction']['commit_ms'], 'commit clock')
        for t in rows[0]:
            for name in ('start_ms', 'completion_ms', 'task_start_wait_ms', 'proposal_to_start_ms',
                         'execution_ms', 'completion_latency_ms', 'tardiness_ms'):
                a, b = rows[0][t][name], rows[1][t][name]
                expected = b-a if a is not None and b is not None else None
                require(d['pair']['per_task_deltas'][t][name] == expected, 'pair arithmetic')
        documents.append(d)
    require(len(documents) == 44 and len(stat['delay_contrasts']) == 36 and len(stat['adjacent_delay_contrasts']) == 36, 'counts')
    by_id = {d['config']['config_id']: d for d in documents}
    by_world_delay = {(d['world']['world_id'], d['config']['review_delay_ms']): d for d in documents}
    for item in stat['delay_contrasts'] + stat['adjacent_delay_contrasts']:
        if 'left_config_id' in item:
            a, b = by_id[item['left_config_id']], by_id[item['right_config_id']]
        else:
            a = by_world_delay[(item['world_id'], item['left_delay_ms'])]
            b = by_world_delay[(item['world_id'], item['right_delay_ms'])]
        for j, arm in enumerate(('retain', 'replan')):
            for t in a['pair']['audits'][j]['tasks']:
                for name in ('start_ms', 'completion_ms', 'completion_latency_ms', 'tardiness_ms'):
                    x, y = a['pair']['audits'][j]['tasks'][t][name], b['pair']['audits'][j]['tasks'][t][name]
                    require(item['by_arm'][arm][t][name] == (y-x if x is not None and y is not None else None), 'delay arithmetic')
            for k in item['scalar_by_arm'][arm]:
                x, y = a['pair']['audits'][j]['metrics'][k], b['pair']['audits'][j]['metrics'][k]
                require(item['scalar_by_arm'][arm][k] == (y-x if x is not None and y is not None else None), 'delay scalar')
            if 'water_finite_difference_factor' in item:
                delta = item['by_arm'][arm]['water']['completion_latency_ms']
                require(item['water_finite_difference_factor'][arm] == (delta/item['delta_review_ms'] if delta is not None else None), 'finite difference')
    for world in stat['worlds']:
        ds = sorted([d for d in documents if d['world']['world_id'] == world['world_id']], key=lambda d: d['config']['review_delay_ms'])
        audits = [a for d in ds for a in d['pair']['audits']]
        E = audits[0]['required_task_ids']
        K = [t for t in E if all(a['tasks'][t]['completed'] for a in audits)]
        require(world['all_planned_slots_common_K_time']['common_task_ids'] == K, 'world common K')
        for name, m in world['all_planned_slots_common_K_time']['metrics'].items():
            require(m['slot_means'] == [sum(a['tasks'][t][name] for t in K)/len(K) if K else None for a in audits], 'world means')
    diagnostic_count = 0
    for n in (1, 3, 5, 7):
        diag = read(OUT + '/diagnostic_world_' + str(n).zfill(2) + '.json')
        for item in diag['records']:
            main = by_world_delay[(item['world_id'], 0)]
            run = next(r for r in main['runs'] if r['arm'] == item['arm'])
            cutoff = item['cutoff_ms']
            def prefix(r):
                return {'calls': [c for c in r['calls'] if c['request']['current_time_ms'] < cutoff],
                        'events': [e for e in r['trace']['events'] if e['timestamp_ms'] < cutoff]}
            require(prefix(run) == prefix(item['run']), 'diagnostic future prefix')
            diagnostic_count += 1
    require(diagnostic_count == 24, 'diagnostic count')
    return {'status': 'same_author_separate_arithmetic_checks_passed_not_independent_review',
            'metadata_revision': 2, 'top_level_checks': checks, 'formal_runs': 88, 'reservation_pairs': 44,
            'diagnostic_runs': diagnostic_count, 'new_simulator_runs': 0, 'api_calls': 0,
            'protected_hashes_matched': len(lock['protected_sha256']),
            'statistics_sha256': sha(OUT + '/statistics.json'), 'independent_acceptance': None}


if __name__ == '__main__':
    print(json.dumps(build(), ensure_ascii=True, separators=(',', ':')))
