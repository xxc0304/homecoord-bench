"""Locked existing-proposal reevaluation with own-release timing and audit views."""
import argparse
import itertools
import json
from copy import deepcopy
from probe_c3_action_choice_20260930 import POLICIES, write, digest
from probe_c3_information_baselines_20260930 import contracts, adapt, SOURCE_MODEL, OUTPUT as BASELINES
from probe_c3_scale_release_20260930 import ROOT, DIR as SOURCE_DIR, load, DEADLINES, RELEASES, PRESSURES
from probe_c3_staggered_release import release_order_records
from runtime.event_simulator import run_event_simulation
from runtime.replay_client import MemoryReplayClient
from runtime.information_contract import trace_information_audit

DIR = ROOT / 'revision_drafts' / '20260930_c3_task_response_contract'
OUTPUT = ROOT / 'results' / 'c3_task_response_contract_20260930.json'
LABELS = (*POLICIES, 'ReleasedFeasibilityStrict', 'ReleasedFeasibilityFallback')
FIELDS = ('template', 'deadline', 'release', 'pressure', 'policy')

def key(row):
    return tuple(row[f] for f in FIELDS)

def prepare():
    source, _ = load()
    design = {'version': 'task-response-contract-0.1', 'new_api_calls': 0,
              'source_sha256': {str(p.relative_to(ROOT)): digest(p) for p in
                                (SOURCE_MODEL, BASELINES, SOURCE_DIR / 'manifest.json')},
              'candidate_sha256': source['candidate_sha256'],
              'policies': list(LABELS), 'privileged_policy': 'PerfectAnnouncementReserve',
              'expected_runs': 396, 'own_release_clock': True,
              'missing_response': 'null; report missing separately, never impute zero',
              'information': 'released metadata, public equal preset costs, returned proposals, current commitments; explicit future announcement is separate',
              'snapshot_scope': 'audit projection, not controller isolation; future-deletion control tests actual prefix independence',
              'claim_limit': '54 counterfactual cells from three saved proposal batches; no resampling, no calibrated physics, no tail percentile estimate',
              'status': 'locked_before_reevaluation'}
    write(DIR / 'manifest.json', design)
    return design

def run():
    design = json.loads((DIR / 'manifest.json').read_text(encoding='utf8'))
    for name, expected in design['source_sha256'].items():
        if digest(ROOT / name) != expected:
            raise ValueError('locked source changed: ' + name)
    manifest, episodes = load()
    if manifest['candidate_sha256'] != design['candidate_sha256']:
        raise ValueError('locked candidates changed')
    saved = json.loads(SOURCE_MODEL.read_text(encoding='utf8'))
    previous = saved['replays'] + json.loads(BASELINES.read_text(encoding='utf8'))['recorded_replays']
    reference = {key(r): r for r in previous}
    rows, examples = [], []
    for batch in saved['batches']:
        if batch['sample']['errors']:
            raise ValueError('incomplete saved batch')
        template, records = batch['template'], batch['sample']['records']
        for deadline, release, pressure in itertools.product(DEADLINES, RELEASES, PRESSURES):
            episode = episodes[template, deadline, release, pressure]
            labels = (*LABELS, 'PerfectAnnouncementReserve') if release == 'urgent_late' else LABELS
            for label in labels:
                changed, policy = adapt(episode, label) if label not in POLICIES else (deepcopy(episode), label)
                client = MemoryReplayClient(deepcopy(release_order_records(episode, records)))
                trace, result = run_event_simulation(changed, client, policy, 'own-release contract replay', shared_safety_gate=True)
                client.assert_consumed()
                views = trace_information_audit(changed, trace['events'], contracts(episode),
                                                 changed['simulation'].get('potential_urgent'))
                row = {**episode['design_factors'], 'policy': label,
                       'information_class': 'perfect_announcement' if label == 'PerfectAnnouncementReserve' else 'released_only',
                       'first_safe_action_ms': result['first_action_start_latency_ms'],
                       'all_tasks_served': all(result['task_service'].values()),
                       'all_deadlines_met': result['all_deadlines_met'],
                       'final_goal_success': result['final_goal_success'],
                       'task_service': result['task_service'], 'task_deadline_met': result['task_deadline_met'],
                       'information_snapshots_checked': len(views),
                       **{k: v for k, v in result.items() if k.startswith('task_') and k not in ('task_service', 'task_deadline_met', 'task_action_finish_time_ms')},
                       'max_observed_task_start_wait_ms': result['max_observed_task_start_wait_ms']}
                old = reference[key(row)]
                for metric in ('first_safe_action_ms', 'all_tasks_served', 'all_deadlines_met',
                               'final_goal_success', 'task_service', 'task_deadline_met'):
                    if row[metric] != old[metric]:
                        raise ValueError(f'historical metric changed: {key(row)} {metric}')
                rows.append(row)
                if deadline == 'tight' and release == 'urgent_late' and pressure == 1.6 and label not in POLICIES:
                    examples.append({'cell': {f: row[f] for f in FIELDS}, 'snapshots': views})
    if len(rows) != design['expected_runs']:
        raise ValueError('incomplete grid')
    summary = []
    for label in (*LABELS, 'PerfectAnnouncementReserve'):
        selected = [r for r in rows if r['policy'] == label]
        waits = [w for r in selected for w in r['task_start_wait_ms'].values() if w is not None]
        summary.append({'policy': label, 'runs': len(selected),
                        'all_served_runs': sum(r['all_tasks_served'] for r in selected),
                        'all_deadlines_runs': sum(r['all_deadlines_met'] for r in selected),
                        'task_count': sum(len(r['task_start_wait_ms']) for r in selected),
                        'unstarted_tasks': sum(r['task_unstarted_count'] for r in selected),
                        'incomplete_tasks': sum(r['task_incomplete_count'] for r in selected),
                        'max_observed_wait_ms': max(waits, default=None),
                        'snapshot_count': sum(r['information_snapshots_checked'] for r in selected)})
    result = {'design_sha256': digest(DIR / 'manifest.json'), 'new_api_calls': 0,
              'historical_metric_pairs_unchanged': len(rows), 'rows': rows, 'summary': summary,
              'selected_information_snapshots': examples}
    write(OUTPUT, result)
    return result

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('prepare', 'run'))
    result = {'prepare': prepare, 'run': run}[parser.parse_args().stage]()
    print(json.dumps(result['summary'] if 'summary' in result else {'status': result['status']}, ensure_ascii=False))
