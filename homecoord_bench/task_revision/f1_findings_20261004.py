"""Read-only descriptive extraction from accepted F1 outputs, not a new scorer."""
import hashlib
import json
from pathlib import Path
from homecoord_bench.task_revision.publication_redaction import matches_source_sha256, original_source_sha256

ROOT = Path(__file__).resolve().parents[2]
PREFIX = 'docs/f1_aggregation_v1_20261004'
REVIEW_PREFIX = 'docs/review_evidence/2026-10-01_to_2026-10-06'
REVIEW_DIR = ROOT / REVIEW_PREFIX


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract():
    audit_path = REVIEW_DIR / 'F1_AGGREGATION_V1_AUDIT_20261004.json'
    report_path = REVIEW_DIR / 'F1_AGGREGATION_V1_REVIEW_20261004.md'
    audit = json.loads(audit_path.read_text(encoding='utf-8'))
    assert not audit['errors'] and all(c['passed'] for c in audit['checks'])
    locks = {p.replace('\\', '/'): h for p, h in audit['reviewed_sha256'].items()}
    assert all(matches_source_sha256(p, h) for p, h in locks.items())
    manifest = json.loads((ROOT / PREFIX / 'manifest.json').read_text(encoding='utf-8'))
    assert all(sha(ROOT / p) == h for p, h in manifest['artifact_sha256'].items())
    source_manifest = json.loads((ROOT / 'docs/implementation_review_20261001/manifest.json').read_text(encoding='utf-8'))
    runtime_path = 'homecoord_bench/runtime/event_simulator.py'
    assert sha(ROOT / runtime_path) == source_manifest['source_sha256'][runtime_path]
    rows = {}
    for base in ('01', '02'):
        for arm in ('competition', 'no_competition'):
            for temporal in ('base', 'loose'):
                path = f'{PREFIX}/D-F1-{base}-{arm}-{temporal}.json'
                d = json.loads((ROOT / path).read_text(encoding='utf-8'))
                for r in d['runs']:
                    assert r['slot_id'] not in rows
                    rows[r['slot_id']] = r
    assert len(rows) == 72
    assert all(r['all_completed'] and r['metrics']['executed_capacity_violation_duration_ms'] == 0
               and r['invalid_precondition_start_count'] == 0 for r in rows.values())
    late = [{'slot_id': sid, 'task_id': tid, 'start_ms': t['start_ms'], 'completion_ms': t['completion_ms'],
             'deadline_ms': t['deadline_ms'], 'tardiness_ms': t['tardiness_ms'], 'event_indices': t['event_indices'],
             'source_path': r['source_path'], 'source_pointer': r['source_pointer']}
            for sid, r in rows.items() for tid, t in r['tasks'].items() if t['completed'] and not t['timely']]
    assert len(late) == 4 and all(x['task_id'] == 'water' and 'D-F1-02-competition-base|' in x['slot_id'] for x in late)
    deadlines = json.loads((ROOT / PREFIX / 'pairs_deadline.json').read_text(encoding='utf-8'))['pairs']
    capacities = json.loads((ROOT / PREFIX / 'pairs_capacity.json').read_text(encoding='utf-8'))['pairs']
    policies = json.loads((ROOT / PREFIX / 'pairs_policy.json').read_text(encoding='utf-8'))['pairs']
    groups = json.loads((ROOT / PREFIX / 'four_cells.json').read_text(encoding='utf-8'))['groups']
    assert len(deadlines) == len(capacities) == 36 and len(policies) == 48 and len(groups) == 18
    deadline_same_timing = []
    for p in deadlines:
        a, b = rows[p['left']], rows[p['right']]
        assert all(a['tasks'][tid][k] == b['tasks'][tid][k] for tid in a['tasks'] for k in
                   ('proposal_return_ms', 'start_ms', 'completion_ms', 'execution_ms'))
        deadline_same_timing.append({'left': p['left'], 'right': p['right'],
                                    'timely_service_rate_delta': p['scalar_deltas']['timely_service_rate']['value']})
    adequate = [r for r in rows.values() if '-no_competition-' in r['episode_id']]
    assert len(adequate) == 36 and all(r['all_timely'] and r['metrics']['action_rejected_count'] == 0
                                    and r['metrics']['coordination_defer_count'] == 0 for r in adequate)
    simple_vs_constraint_adequate = [p for p in policies if '-no_competition-' in p['left'] and '|ConstraintCoordinator|' in p['right']]
    assert len(simple_vs_constraint_adequate) == 12
    assert all(all(v['value'] == 0 for v in p['conditional_time']['metrics'].values()) for p in simple_vs_constraint_adequate)
    assert all(g['population']['coverage'] == 1 for g in groups)
    base = 'D-F1-02-competition-base'
    table = []
    for policy in ('GateRetryRule', 'ConstraintCoordinator', 'DeadlineAwareCoordinator'):
        rs = [rows[f'{base}|{policy}|order{o}'] for o in range(3)]
        table.append({'policy': policy, 'required_per_run': 5, 'completed_per_order': [r['denominators']['completed'] for r in rs],
                      'timely_per_order': [r['denominators']['timely'] for r in rs],
                      'water_completion_per_order_ms': [r['tasks']['water']['completion_ms'] for r in rs],
                      'whole_house_completion_per_order_ms': [r['metrics']['whole_house_completion_ms'] for r in rs],
                      'gate_rejections_per_order': [r['metrics']['action_rejected_count'] for r in rs],
                      'coordination_defers_per_order': [r['metrics']['coordination_defer_count'] for r in rs]})
    example_ids = ['D-F1-01-competition-base|GateRetryRule|order0',
                   'D-F1-01-competition-base|ConstraintCoordinator|order0',
                   'D-F1-01-competition-base|DeadlineAwareCoordinator|order0',
                   'D-F1-02-competition-base|GateRetryRule|order2',
                   'D-F1-02-competition-base|ConstraintCoordinator|order2',
                   'D-F1-02-competition-base|DeadlineAwareCoordinator|order2']
    return {'status': 'author_descriptive_findings_not_new_implementation_review',
            'scope': 'accepted_F1_72_deterministic_runs_168_pairs_18_groups',
            'review_path': f'{REVIEW_PREFIX}/{report_path.name}', 'review_sha256': sha(report_path),
            'review_source_sha256': original_source_sha256(f'{REVIEW_PREFIX}/{report_path.name}'),
            'review_audit_path': f'{REVIEW_PREFIX}/{audit_path.name}', 'review_audit_sha256': sha(audit_path),
            'review_audit_source_sha256': original_source_sha256(f'{REVIEW_PREFIX}/{audit_path.name}'),
            'reviewed_sha256': locks, 'all_completed_runs': 72, 'executed_capacity_violating_runs': 0,
            'runtime_source_sha256': {runtime_path: sha(ROOT / runtime_path)},
            'invalid_precondition_start_runs': 0, 'late_task_records': late,
            'F1_02_tight_base_by_order': table, 'adequate_capacity_all_timely_runs': 36,
            'adequate_gate_vs_constraint_identical_task_time_pairs': 12,
            'deadline_pairs_same_actual_time': deadline_same_timing,
            'four_cell_full_K_groups': 18,
            'example_runs': [{k: rows[s][k] for k in ('slot_id','source_path','source_pointer','metrics','tasks')} for s in example_ids],
            'source_proposal_return_is_synthetic': True, 'api_calls': 0, 'simulator_runs': 0,
            'rankings_or_inferential_statistics_created': False}


if __name__ == '__main__':
    print(json.dumps(extract(), ensure_ascii=True, indent=2))
