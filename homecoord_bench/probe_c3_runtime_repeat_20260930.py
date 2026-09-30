"""Local measured solver cost and bounded independent proposal resampling."""
import argparse
import json
import platform
import statistics
from copy import deepcopy
from time import perf_counter_ns
from probe_c3_action_choice_20260930 import digest, write
from probe_c3_scale_release_20260930 import ROOT, DIR as SOURCE_DIR, load, templates
from probe_c3_information_baselines_20260930 import adapt
from probe_c3_parallel_model_pilot import sample_parallel
from probe_c3_staggered_release import release_order_records
from probe_c3_structural_generalization import ScriptedProposalClient
from runtime import event_simulator as sim
from runtime.deepseek_client import DeepSeekResponsesClient
from runtime.event_log import EventLogger
from runtime.replay_client import MemoryReplayClient
from runtime.tool_contract import validate_tool_call

DIR = ROOT / 'revision_drafts' / '20260930_c3_runtime_repeat'
BENCH = ROOT / 'results' / 'c3_runtime_cost_20260930.json'
LIVE = ROOT / 'results' / 'c3_runtime_repeat_model_20260930.json'
LOGDIR = ROOT / 'runs' / 'c3-runtime-repeat-20260930'
LABELS = ('GateRetryRule', 'DeadlineAwareCoordinator', 'ReleasedFeasibilityStrict', 'ReleasedFeasibilityFallback')
CELLS = (('tight', 'together', 1.6), ('tight', 'urgent_late', 1.6),
         ('loose', 'urgent_late', 1.6), ('tight', 'urgent_late', 0.8))
SAMPLED = ('N2-1', 'N4-1', 'N5-1')
REPETITIONS = 3

def policy_episode(episode, label):
    return adapt(episode, label) if label not in ('GateRetryRule', 'DeadlineAwareCoordinator') else (deepcopy(episode), label)

def prepare():
    manifest, _ = load()
    design = {'version': 'runtime-repeat-0.1', 'source_manifest_sha256': digest(SOURCE_DIR / 'manifest.json'),
              'candidate_sha256': manifest['candidate_sha256'], 'policies': list(LABELS),
              'sampling_templates': list(SAMPLED), 'sampling_cell': ['tight', 'together', 1.6],
              'repetitions': REPETITIONS, 'planned_api_requests': 33, 'max_attempts': 1,
              'replay_cells': list(CELLS), 'expected_replays': 171,
              'bench_templates': list(templates()), 'bench_releases': ['together', 'urgent_late'],
              'bench_policies': ['DeadlineAwareCoordinator', 'ReleasedFeasibilityStrict', 'ReleasedFeasibilityFallback'],
              'bench_warmups_per_group': 2, 'bench_samples_per_group': 20,
              'bench_scope': 'full instrumented simulator plus individual exact-solver invocation timing; not pure complete coordinator overhead or deployment latency',
              'timing_integration': 'measure separately; no automatic padding before admission because admission is state-dependent; future integration requires asynchronous decision-ready revalidation',
              'limits': 'fresh simultaneous proposals; other cells are counterfactual replays, not fresh state-conditioned late-release reasoning',
              'status': 'locked_before_runtime_measurement_and_resampling'}
    write(DIR / 'manifest.json', design)
    return design

def locked():
    design = json.loads((DIR / 'manifest.json').read_text(encoding='utf8'))
    manifest, episodes = load()
    if digest(SOURCE_DIR / 'manifest.json') != design['source_manifest_sha256'] or manifest['candidate_sha256'] != design['candidate_sha256']:
        raise ValueError('locked input changed')
    return design, episodes

def measure_once(episode, label):
    changed, policy = policy_episode(episode, label)
    latencies = {t['task_id']: 800 + i * 200 for i, t in enumerate(episode['task_stream'])}
    timings = []
    original = sim.ideal_schedule
    def measured(*args, **kwargs):
        start = perf_counter_ns()
        try:
            return original(*args, **kwargs)
        finally:
            timings.append((perf_counter_ns() - start) / 1e6)
    sim.ideal_schedule = measured
    try:
        start = perf_counter_ns()
        _, result = sim.run_event_simulation(changed, ScriptedProposalClient(latencies), policy, '', shared_safety_gate=True)
        elapsed = (perf_counter_ns() - start) / 1e6
    finally:
        sim.ideal_schedule = original
    return {'simulator_wall_ms': elapsed, 'solver_calls_ms': timings,
            'all_tasks_served': all(result['task_service'].values()),
            'all_deadlines_met': result['all_deadlines_met'],
            'first_action_ms': result['first_action_start_latency_ms']}

def benchmark():
    design, episodes = locked()
    groups = []
    for template in design['bench_templates']:
        for release in design['bench_releases']:
            episode = episodes[template, 'tight', release, 1.6]
            for label in design['bench_policies']:
                for _ in range(design['bench_warmups_per_group']):
                    measure_once(episode, label)
                samples = [measure_once(episode, label) for _ in range(design['bench_samples_per_group'])]
                outcomes = {(r['all_tasks_served'], r['all_deadlines_met'], r['first_action_ms']) for r in samples}
                if len(outcomes) != 1:
                    raise ValueError('instrumented repeat changed logical outcome')
                values = [r['simulator_wall_ms'] for r in samples]
                solver = [t for r in samples for t in r['solver_calls_ms']]
                groups.append({'template': template, 'agent_count': len(episode['task_stream']),
                               'release': release, 'policy': label, 'samples': samples,
                               'median_simulator_wall_ms': statistics.median(values),
                               'min_simulator_wall_ms': min(values), 'max_simulator_wall_ms': max(values),
                               'solver_calls': len(solver), 'median_solver_call_ms': statistics.median(solver) if solver else None,
                               'max_solver_call_ms': max(solver, default=None)})
    result = {'design_sha256': digest(DIR / 'manifest.json'), 'new_api_calls': 0,
              'python_version': platform.python_version(), 'platform': platform.platform(),
              'measured_runs': 720, 'warmup_runs': 72, 'groups': groups,
              'status': 'measured_local_wall_time_not_injected_into_virtual_clock'}
    write(BENCH, result)
    return result

def replay_batch(episodes, batch):
    rows = []
    if batch['sample']['errors']:
        return rows
    for deadline, release, pressure in CELLS:
        episode = episodes[batch['template'], deadline, release, pressure]
        labels = (*LABELS, 'PerfectAnnouncementReserve') if release == 'urgent_late' else LABELS
        for label in labels:
            changed, policy = policy_episode(episode, label)
            client = MemoryReplayClient(deepcopy(release_order_records(episode, batch['sample']['records'])))
            trace, result = sim.run_event_simulation(changed, client, policy, 'fresh batch fixed proposal replay', shared_safety_gate=True)
            client.assert_consumed()
            rows.append({**episode['design_factors'], 'repetition': batch['repetition'], 'policy': label,
                         'information_class': 'perfect_announcement' if label == 'PerfectAnnouncementReserve' else 'released_only',
                         'all_tasks_served': all(result['task_service'].values()),
                         'all_deadlines_met': result['all_deadlines_met'],
                         'first_action_ms': result['first_action_start_latency_ms'],
                         'task_start_wait_ms': result['task_start_wait_ms'],
                         'task_completion_tardiness_ms': result['task_completion_tardiness_ms'],
                         'task_unstarted_count': result['task_unstarted_count'],
                         'start_order': [e['task_id'] for e in trace['events'] if e['type'] == 'action_started']})
    return rows

def live(retry_network=False):
    design, episodes = locked()
    design_hash = digest(DIR / 'manifest.json')
    if LIVE.exists():
        result = json.loads(LIVE.read_text(encoding='utf8'))
        if result['design_sha256'] != design_hash:
            raise ValueError('existing model run uses different design')
    else:
        result = {'design_sha256': design_hash, 'planned_api_requests': 33, 'batches': [], 'status': 'partial'}
    if retry_network:
        blocked = [b for b in result['batches'] if not b['sample']['records']
                   and b['sample']['errors'] and all('10013' in e.get('error', '') for e in b['sample']['errors'].values())]
        result.setdefault('blocked_network_attempts', []).extend(blocked)
        result['batches'] = [b for b in result['batches'] if b not in blocked]
        write(LIVE, result)
    LOGDIR.mkdir(parents=True, exist_ok=True)
    client = DeepSeekResponsesClient(model='deepseek-flash', max_attempts=1,
                                    logger=EventLogger(LOGDIR / 'model_events.jsonl', 'c3-runtime-repeat-20260930'))
    if not client.api_key:
        raise RuntimeError('DEEPSEEK_API_KEY is not configured in this process')
    for template in SAMPLED:
        for rep in range(1, REPETITIONS + 1):
            if any(b['template'] == template and b['repetition'] == rep for b in result['batches']):
                continue
            episode = deepcopy(episodes[template, 'tight', 'together', 1.6])
            episode['episode_id'] = episode['base_episode_id']
            episode['simulation'].pop('blind_future_task_arrivals')
            sample = sample_parallel(client, episode, rep + 100)
            scores = []
            for task in episode['task_stream']:
                record = sample['records'].get(task['task_id'])
                actions = record['decision']['actions'] if record else []
                authorized = len(actions) == 1 and validate_tool_call(episode, task['agent_id'], task['task_id'], actions[0]) is None
                correct = authorized and all(actions[0].get(k) == v for k, v in task['required_action'].items())
                scores.append({'task_id': task['task_id'], 'authorized': authorized, 'correct': correct})
            batch = {'template': template, 'repetition': rep, 'sample': sample, 'proposal_scores': scores}
            result['batches'].append(batch)
            result['replays'] = [r for b in result['batches'] for r in replay_batch(episodes, b)]
            write(LIVE, result)
            print(json.dumps({'template': template, 'repetition': rep, 'errors': sample['errors'], 'scores': scores}), flush=True)
    result['status'] = 'complete' if len(result['replays']) == design['expected_replays'] else 'partial_with_errors'
    result['completed_api_decisions'] = sum(len(b['sample']['records']) for b in result['batches'])
    write(LIVE, result)
    return result

def audit():
    design, _ = locked()
    model = json.loads(LIVE.read_text(encoding='utf8'))
    bench = json.loads(BENCH.read_text(encoding='utf8'))
    if model['status'] != 'complete' or len(model['replays']) != design['expected_replays']:
        raise ValueError('model evidence incomplete')
    groups = {}
    for row in model['replays']:
        key = '|'.join(str(row[k]) for k in ('template', 'deadline', 'release', 'pressure', 'policy'))
        cell = groups.setdefault(key, {k: row[k] for k in ('template', 'deadline', 'release', 'pressure', 'policy')})
        cell['runs'] = cell.get('runs', 0) + 1
        for metric in ('all_tasks_served', 'all_deadlines_met'):
            cell[metric] = cell.get(metric, 0) + int(row[metric])
    if any(c['runs'] != REPETITIONS for c in groups.values()):
        raise ValueError('unbalanced replicate group')
    logs = [json.loads(line) for line in (LOGDIR / 'model_events.jsonl').read_text(encoding='utf8').splitlines() if line.strip()]
    completed = [e for e in logs if e['event_type'] == 'model_call_completed']
    scores = [s for b in model['batches'] for s in b['proposal_scores']]
    if len(completed) != 33 or len(scores) != 33 or len(bench['groups']) != 36:
        raise ValueError('unexpected audit counts')
    controls = [r for r in model['replays'] if r['deadline'] == 'loose' or r['pressure'] == 0.8]
    result = {'status': 'audited_runtime_and_fresh_proposal_repeats',
              'sources_sha256': {str(p.relative_to(ROOT)): digest(p) for p in (BENCH, LIVE, DIR / 'manifest.json')},
              'fresh_api_completed': len(completed), 'authorized': sum(s['authorized'] for s in scores),
              'semantic_correct': sum(s['correct'] for s in scores),
              'input_tokens': sum(e.get('input_tokens') or 0 for e in completed),
              'output_tokens': sum(e.get('output_tokens') or 0 for e in completed),
              'control_runs': len(controls), 'control_all_deadlines_runs': sum(r['all_deadlines_met'] for r in controls),
              'groups': list(groups.values()), 'runtime_measured_runs': sum(len(g['samples']) for g in bench['groups']),
              'limitations': design['limits'], 'timing_integration': design['timing_integration']}
    write(ROOT / 'results' / 'c3_runtime_repeat_audit_20260930.json', result)
    return result

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('prepare', 'benchmark', 'live', 'retry-network', 'audit'))
    stage = parser.parse_args().stage
    result = {'prepare': prepare, 'benchmark': benchmark, 'live': live,
              'retry-network': lambda: live(retry_network=True), 'audit': audit}[stage]()
    print(json.dumps({'stage': stage, 'status': result['status'], 'groups': len(result.get('groups', [])),
                      'replays': len(result.get('replays', []))}))
