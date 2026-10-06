"""Versioned F2 local sensitivity entry. Frozen policy/runtime code stays untouched.

Emission is stdout only; callers save artifacts using apply_patch. Baselines are
materialized first. Perturbation generation requires the saved exact-match gate.
The new adapter binds the reused event-recount primitives to this new contract;
historical adapter acceptance does not transfer to this implementation.
"""
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from homecoord_bench.task_revision import small_validation_plan_v1 as design
from homecoord_bench.task_revision import f2_aggregation_v1 as core
from homecoord_bench.task_revision.f2_revision import PublicProposals
from homecoord_bench.task_revision.event_simulator_v7 import run_event_simulation

ROOT = design.ROOT
DESIGN = 'docs/small_validation_plan_v1_20261005'
OUT = 'docs/small_validation_execution_v1_20261005'
FREEZE = DESIGN + '/freeze_20261005.json'
PLAN = DESIGN + '/plan.json'
RULES = DESIGN + '/execution_statistics_addendum.json'
GATE = OUT + '/baseline_gate.json'
CODE = 'homecoord_bench/task_revision/small_validation_execution_v1.py'


def read(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def object_sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def serialize(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':')) + '\n'


def verify_freeze():
    f = read(FREEZE)
    core.require(f['status'] == 'frozen_design_execution_pending_review', 'design not frozen')
    for section in ('reviewed_sha256', 'protected_sha256', 'source_sha256', 'external_review_sha256'):
        for path, digest in f[section].items():
            core.require(sha(path) == digest, 'source protection mismatch: ' + path)
    plan = read(PLAN)
    core.require((len(plan['configurations']), len(plan['run_slots']), len(plan['pairs'])) == (28, 84, 72), 'scope mismatch')
    core.require(read(RULES)['expected_scope']['baseline_slots'] == 12, 'baseline scope mismatch')
    return plan


def artifact_path(config):
    # Private labels remain only in evaluation artifacts, never public calls.
    index = next(i for i, c in enumerate(read(PLAN)['configurations']) if c['config_id'] == config['config_id'])
    return OUT + '/config_' + str(index).zfill(2) + '.json'


def materialize(config):
    source = next(e for e in read(design.SOURCE)['episodes'] if e['episode_id'] == config['source_episode_id'])
    episode = design.variant(source, config['factor'], config['value_ms'])
    core.require(object_sha(episode) == config['derived_episode_sha256'], 'derived input mismatch')
    core.require(design.differences(source, episode) == config['changed_paths_excluding_private_identity'], 'unexpected input changes')
    episode['episode_id'] = config['config_id']
    return episode


def clock_evidence(episode, run):
    """Check EVERY attempted start including gate rejections, plus retry binding."""
    C = episode['simulation']['command_latency_ms']
    core.require(C in (0, 100, 500), 'command clock outside contract')
    events = run['trace']['events']
    evidence = []
    for i, event in enumerate(events):
        if event['type'] not in ('action_started', 'action_rejected'):
            continue
        pid, tid, now = event['proposal_id'], event['task_id'], event['timestamp_ms']
        matching = [(j, r) for j, r in enumerate(events[:i]) if r['type'] == 'action_reserved'
                    and r['proposal_id'] == pid and r['task_id'] == tid and r['scheduled_start_ms'] == now]
        core.require(len(matching) == 1, 'missing/ambiguous matching command reservation')
        j, reservation = matching[0]
        previous_outcomes = [r for r in events[:j] if r['type'] in ('action_started', 'action_rejected')
                             and r.get('proposal_id') == pid]
        returns = [(k, r) for k, r in enumerate(events[:j]) if r['type'] == 'proposal_returned' and r['task_id'] == tid]
        core.require(len(returns) == 1, 'missing/ambiguous return before command')
        pi, proposal = returns[0]
        Q = reservation['timestamp_ms']
        core.require(now >= Q + C and Q >= proposal['timestamp_ms'], 'command lower bound violated')
        if previous_outcomes:
            core.require(run['policy'] == 'GateRetryRule' and previous_outcomes[-1]['type'] == 'action_rejected', 'invalid retry lifecycle')
            retries = [(k, r) for k, r in enumerate(events[j+1:i], j+1) if r['type'] == 'retry_scheduled'
                       and r['task_id'] == tid and r['timestamp_ms'] == Q and r['start_at_ms'] == now]
            core.require(len(retries) == 1, 'retry not bound to matching reservation')
            queued = [r for r in events[:j] if r['type'] == 'retry_queued' and r['task_id'] == tid
                      and previous_outcomes[-1]['timestamp_ms'] <= r['timestamp_ms'] <= Q]
            core.require(bool(queued), 'missing queued retry')
        else:
            core.require(now >= proposal['timestamp_ms'] + C, 'initial command lower bound violated')
        core.require(reservation['duration_ms'] == next(g['duration_ms'] for g in episode['action_grounding']
                     if g['task_id'] == tid and g['operation'] == 'prepare'), 'reservation duration changed')
        core.require(reservation['power_kw'] == next(g['power_kw'] for g in episode['action_grounding']
                     if g['task_id'] == tid and g['operation'] == 'prepare'), 'reservation units changed')
        evidence.append({'task_id': tid, 'proposal_id': pid, 'outcome_event_index': i,
                         'reservation_event_index': j, 'return_event_index': pi,
                         'reservation_created_ms': Q, 'attempt_ms': now, 'command_latency_ms': C,
                         'retry': bool(previous_outcomes), 'outcome': event['type']})
    return evidence


def score(episode, run):
    core.require(run['policy'] in design.POLICIES, 'policy outside new scope')
    row = core.recount(episode, run)
    core.require(row['denominators']['required'] == 4, 'fixed E changed')
    core.require(row['invalid_precondition_start_count'] == 0, 'invalid physical start')
    row['command_clock_evidence'] = clock_evidence(episode, run)
    return row


def historical(config, policy):
    path = 'homecoord_bench/task_revision/fixtures/f2_v7/runs/' + config['source_episode_id'] + '.json'
    rows = [r for r in read(path)['runs'] if r['policy'] == policy]
    core.require(len(rows) == 1, 'historical policy identity mismatch')
    return rows[0]


def exact_baseline(config, episode, run):
    core.require(config['factor'] == 'baseline', 'not baseline')
    old = historical(config, run['policy'])
    core.require(run['evaluation_episode_id'] == config['config_id'] and episode['episode_id'] == config['config_id'], 'new baseline identity mismatch')
    core.require(run['calls'] == old['calls'], 'baseline complete calls differ')
    # Only these TWO outer trace metadata fields may differ.
    lhs = {k: v for k, v in run['trace'].items() if k not in ('trace_id', 'episode_id')}
    rhs = {k: v for k, v in old['trace'].items() if k not in ('trace_id', 'episode_id')}
    core.require(lhs == rhs, 'baseline complete trace differs')
    source = next(e for e in read(design.SOURCE)['episodes'] if e['episode_id'] == config['source_episode_id'])
    new_metrics = core.recount(episode, run)
    old_metrics = core.recount(source, old)
    core.require(new_metrics == old_metrics, 'baseline event-derived statistics differ')
    score(episode, run)
    return {'slot_id': config['config_id'] + '|' + run['policy'], 'complete_calls_equal': True,
            'complete_trace_except_two_outer_fields_equal': True, 'complete_event_derived_statistics_equal': True}


def generate_config(index):
    plan = verify_freeze()
    config = plan['configurations'][index]
    if config['factor'] != 'baseline':
        verify_gate()
    episode = materialize(config)
    runs = []
    for policy in design.POLICIES:
        provider = PublicProposals()
        trace, result = run_event_simulation(episode, provider, policy, '', shared_safety_gate=True)
        run = {'evaluation_episode_id': episode['episode_id'], 'policy': policy,
               'calls': provider.calls, 'trace': trace, 'result': result}
        score(episode, run)
        if config['factor'] == 'baseline':
            exact_baseline(config, episode, run)
        runs.append(run)
    return {'config_id': config['config_id'], 'input': episode,
            'materialized_input_sha256': object_sha(episode), 'runs': runs,
            'entry_sha256': sha(CODE), 'freeze_sha256': sha(FREEZE),
            'status': 'author_execution_pending_implementation_review', 'api_calls': 0}


def validate_config(config, document):
    episode = materialize(config)
    core.require(document['config_id'] == config['config_id'] and document['input'] == episode, 'materialized input mismatch')
    core.require(document['materialized_input_sha256'] == object_sha(episode), 'materialized hash mismatch')
    core.require(document['entry_sha256'] == sha(CODE) and document['freeze_sha256'] == sha(FREEZE), 'entry/freeze binding mismatch')
    core.require([r['policy'] for r in document['runs']] == list(design.POLICIES), 'missing/duplicate policy slot')
    return episode


def build_gate():
    plan = verify_freeze()
    checks, files = [], {}
    for config in plan['configurations']:
        if config['factor'] != 'baseline':
            continue
        path = artifact_path(config)
        doc = read(path)
        episode = validate_config(config, doc)
        checks += [exact_baseline(config, episode, run) for run in doc['runs']]
        files[path] = sha(path)
    core.require(len(checks) == 12, 'missing fresh baseline')
    return {'status': 'all_12_fresh_baselines_exact_author_checked', 'checks': checks,
            'baseline_sha256': files, 'entry_sha256': sha(CODE), 'freeze_sha256': sha(FREEZE),
            'gate_before_perturbation': True, 'implementation_acceptance': None}


def verify_gate():
    saved = read(GATE)
    core.require(saved == build_gate(), 'baseline gate changed or invalid')
    return saved


def statistics():
    plan = verify_freeze()
    verify_gate()
    rows, input_hashes, files = {}, {}, {}
    for config in plan['configurations']:
        path = artifact_path(config)
        doc = read(path)
        episode = validate_config(config, doc)
        files[path] = sha(path)
        input_hashes[config['config_id']] = doc['materialized_input_sha256']
        for run in doc['runs']:
            sid = config['config_id'] + '|' + run['policy']
            core.require(sid not in rows, 'duplicate slot')
            rows[sid] = {'slot_id': sid, 'config_id': config['config_id'], 'policy': run['policy'],
                         'source_episode_id': config['source_episode_id'], 'factor': config['factor'],
                         'value_ms': config['value_ms'], **score(episode, run)}
    core.require(set(rows) == {s['slot_id'] for s in plan['run_slots']}, 'fixed slots missing or extra')
    rules = read(RULES)
    pairs = [core.compare(p, rows, rules) for p in plan['pairs']]
    core.require(len(pairs) == 72, 'fixed pair count changed')
    core.require(all(set(p['scalar_comparison']) == set(rules['paired_scalar_allowlist']) for p in pairs), 'pair whitelist changed')
    return {'status': 'author_statistics_pending_implementation_review', 'runs': rows, 'pairs': pairs,
            'scope': {'configurations': 28, 'runs': 84, 'fresh_baselines': 12, 'perturbations': 72, 'pairs': 72},
            'materialized_input_sha256': input_hashes, 'raw_artifact_sha256': files,
            'baseline_gate_sha256': sha(GATE), 'entry_adapter_sha256': sha(CODE),
            'freeze_sha256': sha(FREEZE), 'api_calls': 0, 'cross_config_macro': False,
            'cross_family_pooling': False, 'ranking': False, 'implementation_acceptance': None}


if __name__ == '__main__':
    import sys
    mode = sys.argv[1]
    if mode == 'config':
        result = generate_config(int(sys.argv[2]))
    elif mode == 'gate':
        result = build_gate()
    elif mode == 'statistics':
        result = statistics()
    else:
        raise ValueError('unknown explicit entry mode')
    text = json.dumps(result, ensure_ascii=True, separators=(',', ':'))
    offset = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    print(json.dumps({'text': text[offset:offset+40000],
                      'next': offset+40000 if offset+40000 < len(text) else None}, ensure_ascii=True))

