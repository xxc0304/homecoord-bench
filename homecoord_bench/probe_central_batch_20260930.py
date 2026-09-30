"""No-API interface equivalence across prospective development families."""
import argparse
import itertools
import json
from copy import deepcopy
from pathlib import Path
from build_task_family_split_20260930 import locked_development, DIR as SOURCE_DIR, FamilyScriptClient
from probe_c3_multimode_20260930 import PublicModeClient
from probe_c3_action_choice_20260930 import write, digest
from runtime.central_batch import ReleaseBatchAdapter
from runtime.event_simulator import run_event_simulation

ROOT = Path(__file__).resolve().parent
DIR = ROOT / 'revision_drafts' / '20260930_central_batch'
OUTPUT = ROOT / 'results' / 'central_batch_adapter_20260930.json'
PREREG = ROOT.parent / 'docs' / 'CENTRAL_BATCH_PREREG_2026-09-30.md'
POLICIES = ('GateRetryRule', 'ConstraintCoordinator', 'DeadlineAwareCoordinator')

class ScriptBatchProvider:
    scripted_batch_latency_ms = 1000
    def __init__(self, modes):
        self.modes, self.calls = modes, 0
    def decide_batch(self, request, instructions=''):
        self.calls += 1
        entries = []
        for child in request['task_requests']:
            tid = child['task']['task_id']
            client = PublicModeClient(self.modes[tid], {tid: 1000})
            entries.append({'task_id': tid, 'decision': client.decide(child)})
        return {'task_decisions': entries}

class CountingSpecialists(FamilyScriptClient):
    def __init__(self, modes):
        super().__init__(modes, {tid: 1000 for tid in modes})
        self.calls = 0
    def decide(self, request, instructions=''):
        self.calls += 1
        return super().decide(request, instructions)

def prepare():
    if (DIR / 'manifest.json').exists():
        raise ValueError('adapter protocol already locked')
    _, episodes = locked_development()
    manifest = {'status': 'locked_before_central_adapter_runs', 'prereg_sha256': digest(PREREG),
        'source_split_manifest_sha256': digest(SOURCE_DIR / 'manifest.json'), 'development_episodes': len(episodes),
        'scripted_runs': 240, 'test_episodes_run': 0, 'new_api_calls': 0, 'matched_proposal_latency_ms': 1000,
        'policies': list(POLICIES)}
    write(DIR / 'manifest.json', manifest)
    return manifest

def run():
    manifest = json.loads((DIR / 'manifest.json').read_text(encoding='utf8'))
    _, episodes = locked_development()
    if digest(PREREG) != manifest['prereg_sha256'] or digest(SOURCE_DIR / 'manifest.json') != manifest['source_split_manifest_sha256']:
        raise ValueError('locked adapter inputs changed')
    pairs = []
    for episode in episodes:
        ids = [t['task_id'] for t in episode['task_stream']]
        choices = [[tool['operation'] for tool in episode['tool_catalog'] if tool['agent_id'] == task['agent_id']
                    and tool['provides_service'] == task['requested_service']] for task in episode['task_stream']]
        for selected in itertools.product(*choices):
            modes = dict(zip(ids, selected))
            for policy in POLICIES:
                batch_provider = ScriptBatchProvider(modes)
                central = ReleaseBatchAdapter(batch_provider)
                specialist = CountingSpecialists(modes)
                traces, results = {}, {}
                for label, client in (('central_batch_proposals', central), ('functional_proposals', specialist)):
                    trace, result = run_event_simulation(deepcopy(episode), client, policy, '', shared_safety_gate=True)
                    traces[label], results[label] = trace, result
                central.assert_consumed()
                first, second = results.values()
                fields = ('task_service', 'all_deadlines_met', 'task_start_wait_ms', 'task_completion_latency_ms',
                          'model_latency_by_task_ms', 'state_constraint_violation_duration_ms')
                if any(first[f] != second[f] for f in fields):
                    raise ValueError('matched action/timing interface changed execution metrics')
                if batch_provider.calls != len({t['release_at_ms'] for t in episode['task_stream']}) or specialist.calls != len(ids):
                    raise ValueError('batch or specialist call count incorrect')
                for batch in central.batches:
                    at = batch['request']['current_time_ms']
                    if {r['task']['task_id'] for r in batch['request']['task_requests']} != {t['task_id'] for t in episode['task_stream'] if t['release_at_ms'] == at}:
                        raise ValueError('batch covered a task from wrong release group')
                    for child in batch['request']['task_requests']:
                        if any(k in child['task'] for k in ('acceptable_actions', 'required_action', 'action_template')):
                            raise ValueError('hidden scoring leaked')
                        expected = {t['task_id'] for t in episode['task_stream'] if t['release_at_ms'] <= at}
                        visible = {t['task_id'] for t in child['state']['coordination_context']['requests']}
                        if expected != visible:
                            raise ValueError('future request leaked into central views')
                starts = {label: {e['task_id']: e['timestamp_ms'] for e in trace['events'] if e['type'] == 'action_started'}
                          for label, trace in traces.items()}
                if starts['central_batch_proposals'] != starts['functional_proposals']:
                    raise ValueError('action starts differ for identical proposals/clock')
                pairs.append({'episode_id': episode['episode_id'], 'structure_id': episode['base_episode_id'],
                    'family': episode['family_block'], 'policy': policy, 'modes': modes,
                    'central_script_calls': batch_provider.calls, 'specialist_script_calls': specialist.calls,
                    'central_batches': central.batches, 'metrics_equal': True, 'action_starts_ms': starts['central_batch_proposals'],
                    'all_tasks_served': all(first['task_service'].values()), 'all_deadlines_met': first['all_deadlines_met'],
                    'task_start_wait_ms': first['task_start_wait_ms'], 'task_completion_latency_ms': first['task_completion_latency_ms']})
    if len(pairs) * 2 != manifest['scripted_runs']:
        raise ValueError('incomplete adapter grid')
    result = {'status': 'audited_central_adapter_identity_control', 'new_api_calls': 0,
        'manifest_sha256': digest(DIR / 'manifest.json'), 'scripted_runs': 240, 'matched_pairs': len(pairs),
        'development_episodes': 24, 'test_episodes_run': 0, 'matched_metrics_pairs': sum(p['metrics_equal'] for p in pairs),
        'all_served_pairs': sum(p['all_tasks_served'] for p in pairs), 'all_deadlines_pairs': sum(p['all_deadlines_met'] for p in pairs),
        'pairs': pairs, 'limits': 'scripted equal actions and timings; interface validation not model/architecture efficacy; pooled release-group views; no cross-batch memory'}
    write(OUTPUT, result)
    return result

def audit():
    _, episodes = locked_development()
    manifest = json.loads((DIR / 'manifest.json').read_text(encoding='utf8'))
    result = json.loads(OUTPUT.read_text(encoding='utf8'))
    if (digest(PREREG) != manifest['prereg_sha256']
            or digest(SOURCE_DIR / 'manifest.json') != manifest['source_split_manifest_sha256']
            or digest(DIR / 'manifest.json') != result['manifest_sha256']):
        raise ValueError('adapter audit lock mismatch')
    by_id = {e['episode_id']: e for e in episodes}
    if len(result['pairs']) != 120 or result['test_episodes_run'] != 0:
        raise ValueError('invalid or exposed-test result count')
    for pair in result['pairs']:
        if pair['episode_id'] not in by_id or not pair['metrics_equal']:
            raise ValueError('test task or unequal interface result')
        previous = set()
        for batch in pair['central_batches']:
            from runtime.central_batch import assert_batch_decision
            assert_batch_decision(batch['decision'], batch['request'], by_id[pair['episode_id']])
            ids = {a['proposal_id'] for entry in batch['decision']['task_decisions'] for a in entry['decision']['actions']}
            if ids & previous:
                raise ValueError('cross-batch proposal collision')
            previous.update(ids)
    audited = {k: v for k, v in result.items() if k != 'pairs'}
    audited.update(status='audited_release_batch_interface', source_sha256=digest(OUTPUT),
        central_script_calls=sum(p['central_script_calls'] for p in result['pairs']),
        specialist_script_calls=sum(p['specialist_script_calls'] for p in result['pairs']))
    write(ROOT / 'results' / 'central_batch_adapter_audit_20260930.json', audited)
    return audited

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('prepare', 'run', 'audit'))
    stage = parser.parse_args().stage
    result = {'prepare': prepare, 'run': run, 'audit': audit}[stage]()
    print(json.dumps({k: v for k, v in result.items() if k != 'pairs'}, ensure_ascii=False))
