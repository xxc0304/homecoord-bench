"""C1 v6 author repair and reproducible review packet; no API or holdout."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from homecoord_bench.task_revision.protection_revision import episode as old_episode, audit as old_audit, POLICIES
from homecoord_bench.task_revision.milestone import FixedProposals
from homecoord_bench.task_revision.event_simulator_v6 import run_event_simulation

ROOT = Path(__file__).resolve().parents[2]


def episode(kind, condition, budget='legality'):
    e = old_episode(kind, condition, budget)
    e['episode_id'] = e['episode_id'].replace('C1R2-', 'C1R3-')
    e['review_status'] = 'design_accepted_single_review_v6_implementation_pending'
    return e


def audit(e, trace, result):
    # Reuse frozen checks of real completion, terminal closure and exposure.
    # Discard its known-bad disposition metric; replace it with event evidence.
    previous = old_audit(e, trace, result)
    expected = {tid: 'rejected_terminal' if value == 'rejected_terminal' else 'admitted'
                for tid, value in previous['expected_from_release_state'].items()}
    observed = {}
    for event in trace['events']:
        if event['type'] in ('request_admitted', 'request_terminal_rejected'):
            tid = event['task_id']
            assert tid not in observed, 'duplicate admission disposition'
            observed[tid] = 'admitted' if event['type'] == 'request_admitted' else 'rejected_terminal'
            task = next(t for t in e['task_stream'] if t['task_id'] == tid)
            assert event['timestamp_ms'] == task['release_at_ms']
    assert set(observed) == set(expected)
    return {
        'expected_admission': expected,
        'observed_admission': observed,
        'admission_correct': {tid: observed[tid] == value for tid, value in expected.items()},
        'request_status': previous['request_status'],
        'task_correct_action_completed': deepcopy(result['task_correct_action_completed']),
        'task_completion_latency_ms': deepcopy(result['task_completion_latency_ms']),
        'task_deadline_met': deepcopy(result['task_deadline_met']),
        'protection_loss_ms': previous['protection_loss_ms'],
        'completed_at_ms': previous['completed_at_ms'],
        'audit': 'author_checks_passed_not_review_acceptance',
    }


def run(e, policy='ConstraintCoordinator', provider=None):
    trace, result = run_event_simulation(e, provider or FixedProposals(), policy, '', shared_safety_gate=True)
    return {'evaluation_episode_id': e['episode_id'], 'policy': policy,
            'trace': trace, 'result': result, 'audit': audit(e, trace, result)}


class NoAction(FixedProposals):
    def decide(self, request, instructions):
        if request['task'].get('request_contract'):
            return {'response_type': 'noop', 'actions': [], 'accepted_proposal_ids': [],
                    'rejected_proposal_ids': [], 'defer_until_ms': None,
                    'reason_code': 'no_applicable_action'}
        return super().decide(request, instructions)


class Slow(FixedProposals):
    last_latency_ms = 7000


def bundle():
    episodes = [episode(k, c, b) for k in ('LIGHT', 'BLINDS')
                for b in ('legality', 'equal_response') for c in ('CONFLICT', 'SAFE')]
    runs = [run(e, p) for e in episodes for p in POLICIES]
    diagnostics = [dict(case=case, **run(episode(k, 'SAFE'), p, provider()))
                   for k in ('LIGHT', 'BLINDS') for p in POLICIES
                   for case, provider in (('admitted_no_action', NoAction),
                                          ('start_precondition_rejected_and_late_completion', Slow))]
    comparisons = []
    for k in ('LIGHT', 'BLINDS'):
        for p in POLICIES:
            matched = [r for e, group in zip(episodes, [runs[i:i+4] for i in range(0,32,4)])
                       if e['variant']['device_scene'] == k for r in group if r['policy'] == p]
            first = [r['trace']['agent_requests'][0] for r in matched]
            assert all(x == first[0] for x in first), 'future condition/budget leaked into full input'
            comparisons.append({'scene': k, 'policy': p, 'paired_conditions': 4,
                                'complete_first_request_equal': True,
                                'request_sha256': hashlib.sha256(serialize(first[0]).encode()).hexdigest()})
    data = {
        'homecoord_bench/task_revision/fixtures/protection_v6_inputs.json': {'episodes': episodes},
        'homecoord_bench/results/protection_v6_offline_20261002.json': {
            'api_calls': 0, 'holdout_runs': 0, 'configurations': 8, 'scripted_runs': 32,
            'diagnostic_runs': 16, 'reviewer_acceptance': None, 'runs': runs,
            'diagnostics': diagnostics, 'full_input_counterfactual_checks': comparisons},
    }
    sources = ['protection_revision_v6.py', 'event_simulator_v6.py', 'protection_revision.py',
               'event_simulator_v5.py', 'protection_contract.py', 'milestone.py']
    data['homecoord_bench/task_revision/fixtures/protection_v6_manifest.json'] = {
        'source_sha256': {n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in sources},
        'artifact_sha256': {p: hashlib.sha256(serialize(v).encode()).hexdigest() for p, v in data.items()},
        'acceptance': None, 'prior_versions': 'v1-v5 and Phase A/B unchanged',
    }
    return data


def serialize(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


if __name__ == '__main__':
    print(json.dumps(bundle(), ensure_ascii=True))
