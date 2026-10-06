"""Metadata-only F1 plan. No simulator, model call, scoring or result aggregation."""
import hashlib
import json
from copy import deepcopy
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'docs/implementation_review_20261001'
OUT = 'docs/f1_statistical_contract_v1_20261004/plan.json'
MANIFEST_SHA = 'af13e218609012115ddbc86cc0c79624047cf95d77afadccde455e5ebfe4fa02'
POLICIES = ('GateRetryRule', 'ConstraintCoordinator', 'DeadlineAwareCoordinator')
BASES = ('D-F1-01', 'D-F1-02')
ARMS = ('competition', 'no_competition')
TIMES = ('base', 'loose')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def differences(a, b, path=''):
    if type(a) is not type(b):
        return [path]
    if isinstance(a, dict):
        return sum((differences(a.get(k), b.get(k), path + '/' + k)
                    for k in sorted(a.keys() | b.keys())), [])
    if isinstance(a, list):
        if len(a) != len(b):
            return [path]
        return sum((differences(x, y, path + '/' + str(i))
                    for i, (x, y) in enumerate(zip(a, b))), [])
    return [] if a == b else [path]


def normalized_episode(episode, intervention):
    """Strip ONLY declared intervention fields and their redundant representations."""
    e = deepcopy(episode)
    e.pop('episode_id')
    if intervention == 'capacity':
        e['pairing'].pop('resource_arm')
        e['home']['resources'].pop('max_power_kw')
        e['initial_state']['values']['coordination_context'].pop('resource_capacity_units')
        for rule in e['conflict_rules']:
            if rule['type'] == 'C3':
                rule.pop('capacity')
    elif intervention == 'deadline':
        e['pairing'].pop('temporal_arm')
        for t in e['task_stream']:
            limit = t['completion_deadline_ms'] - t['release_at_ms']
            text = f'Complete within {limit} ms of this task release.'
            if text not in t['goal']:
                raise ValueError('deadline text does not match declared deadline')
            t['goal'] = t['goal'].replace(text, 'Complete within <deadline> ms of this task release.')
            t.pop('completion_deadline_ms')
        for request in e['initial_state']['values']['coordination_context']['requests']:
            request.pop('deadline_ms')
    else:
        raise ValueError(intervention)
    return e


def validate_contrast(left, right, intervention):
    unexpected = differences(normalized_episode(left, intervention),
                             normalized_episode(right, intervention))
    if unexpected:
        raise ValueError(('undeclared contrast difference', unexpected))
    if intervention == 'capacity':
        if left['home']['resources']['max_power_kw'] >= right['home']['resources']['max_power_kw']:
            raise ValueError('capacity orientation must be tight -> adequate')
    else:
        if any(b['completion_deadline_ms'] - a['completion_deadline_ms'] != 1200000
               for a, b in zip(left['task_stream'], right['task_stream'])):
            raise ValueError('deadline orientation must be base -> +1200000ms')
    return differences(left, right)


def slot(episode_id, policy, order):
    return f'{episode_id}|{policy}|order{order}'


def bundle(root=ROOT):
    root = Path(root)
    manifest_path = root / SOURCE / 'manifest.json'
    if sha(manifest_path) != MANIFEST_SHA:
        raise ValueError('Phase B manifest changed')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    index_path = f'{SOURCE}/index.json'
    if sha(root / index_path) != manifest['artifact_sha256'][index_path]:
        raise ValueError('Phase B index changed')
    index = json.loads((root / index_path).read_text(encoding='utf-8'))
    entries = [x for x in index['entries'] if x['episode_id'].startswith('D-F1-')]
    expected = {f'{b}-{a}-{t}' for b, a, t in product(BASES, ARMS, TIMES)}
    if {x['episode_id'] for x in entries} != expected or len(entries) != 8:
        raise ValueError('F1 scope changed')
    configurations, runs, episodes, locks = [], [], {}, {f'{SOURCE}/manifest.json': MANIFEST_SHA,
                                                        index_path: sha(root / index_path)}
    for entry in entries:
        path = entry['path']
        if sha(root / path) != manifest['artifact_sha256'][path]:
            raise ValueError(('trace changed', path))
        locks[path] = sha(root / path)
        d = json.loads((root / path).read_text(encoding='utf-8'))
        e = d['episode']; eid = e['episode_id']; episodes[eid] = e
        tasks = e['task_stream']; ids = [t['task_id'] for t in tasks]
        if len(set(ids)) != len(ids):
            raise ValueError('duplicate required task')
        required = [{k: t[k] for k in ('task_id', 'agent_id', 'release_at_ms',
                                     'completion_deadline_ms', 'requested_service', 'acceptable_actions')}
                    for t in tasks]
        configurations.append({'episode_id': eid, 'base_episode_id': e['base_episode_id'],
                               'source_path': path, 'pairing': e['pairing'],
                               'capacity_units': e['home']['resources']['max_power_kw'],
                               'required_requests': required,
                               'proposal_return_orders': [ids, list(reversed(ids)), ids[1:] + ids[:1]],
                               'logical_return_offset_rule_ms': '800 + 200 * rank'})
        found = set()
        for i, r in enumerate(d['runs']):
            key = (r['policy'], r['arrival_order_index'])
            if key in found or key not in set(product(POLICIES, range(3))):
                raise ValueError('duplicate/unexpected run identity')
            found.add(key)
            if r['evidence_type'] != 'scripted_deterministic_reproduction_not_model_trial':
                raise ValueError('not approved scripted evidence')
            runs.append({'slot_id': slot(eid, *key), 'episode_id': eid,
                         'policy': key[0], 'order': key[1], 'source_path': path,
                         'source_pointer': f'/runs/{i}', 'required_set_ref': eid})
        if found != set(product(POLICIES, range(3))):
            raise ValueError('missing run; do not silently reduce denominator')
    pairs, contrasts, cells = [], [], []
    def pair(kind, left, right):
        pairs.append({'kind': kind, 'left': left, 'right': right})
    for eid in sorted(expected):
        for order, policy in product(range(3), POLICIES[1:]):
            pair('policy', slot(eid, POLICIES[0], order), slot(eid, policy, order))
        for policy, order in product(POLICIES, (1, 2)):
            pair('return_order', slot(eid, policy, 0), slot(eid, policy, order))
    for base in BASES:
        for temporal in TIMES:
            left, right = (f'{base}-{a}-{temporal}' for a in ARMS)
            contrasts.append({'kind': 'capacity', 'left_config': left, 'right_config': right,
                              'actual_changed_paths': validate_contrast(episodes[left], episodes[right], 'capacity')})
            for policy, order in product(POLICIES, range(3)):
                pair('capacity', slot(left, policy, order), slot(right, policy, order))
        for arm in ARMS:
            left, right = (f'{base}-{arm}-{t}' for t in TIMES)
            contrasts.append({'kind': 'deadline', 'left_config': left, 'right_config': right,
                              'actual_changed_paths': validate_contrast(episodes[left], episodes[right], 'deadline')})
            for policy, order in product(POLICIES, range(3)):
                pair('deadline', slot(left, policy, order), slot(right, policy, order))
        for policy, order in product(POLICIES, range(3)):
            cells.append({'base_episode_id': base, 'policy': policy, 'order': order,
                          'slots': [slot(f'{base}-{a}-{t}', policy, order) for a, t in product(ARMS, TIMES)],
                          'cell_order': ['tight_base', 'tight_loose', 'adequate_base', 'adequate_loose']})
    return {'version': 'F1-statistical-contract-v1-draft', 'status': 'pending_contract_review_not_frozen',
            'scope': '8 configurations / 2 templates / 72 deterministic legacy replays',
            'api_calls': 0, 'simulator_runs': 0, 'scores_computed': False,
            'baseline': POLICIES[0], 'delta_orientation': 'right minus left',
            'source_sha256': locks, 'configurations': configurations,
            'runs': runs, 'pairs': pairs, 'four_cells': cells, 'contrast_checks': contrasts}


if __name__ == '__main__':
    print(json.dumps(bundle(), ensure_ascii=False, indent=2))
