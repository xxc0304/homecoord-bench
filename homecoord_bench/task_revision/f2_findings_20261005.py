"""Descriptive extraction from accepted F2 statistics; no scorer or simulation."""
import hashlib
import json
from pathlib import Path
from homecoord_bench.task_revision.publication_redaction import matches_source_sha256, original_source_sha256

ROOT = Path(__file__).resolve().parents[2]
PREFIX = 'docs/f2_aggregation_v1_20261004'
REVIEW_PREFIX = 'docs/review_evidence/2026-10-01_to_2026-10-06'
REVIEW_DIR = ROOT / REVIEW_PREFIX


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def extract():
    report = REVIEW_DIR / 'F2_AGGREGATION_V1_REVIEW_20261005.md'
    audit_path = REVIEW_DIR / 'F2_AGGREGATION_V1_AUDIT_20261005.json'
    audit = read(audit_path)
    assert not audit['errors'] and all(c['passed'] for c in audit['checks'])
    locks = {p.replace('\\', '/'): h for p, h in audit['reviewed_sha256'].items()}
    assert all(matches_source_sha256(p, h) for p, h in locks.items())
    manifest = read(ROOT / PREFIX / 'manifest.json')
    assert all(sha(ROOT / p) == h for p, h in manifest['artifact_sha256'].items())
    freeze = read(ROOT / 'docs/f2_statistical_contract_v1_20261004/freeze_20261004.json')
    assert all(sha(ROOT / p) == h for p, h in {**freeze['source_sha256'], **freeze['runtime_source_sha256']}.items())
    rows = {}
    for p in manifest['artifact_sha256']:
        if '/F2R1-' not in p:
            continue
        for r in read(ROOT / p)['runs']:
            assert r['slot_id'] not in rows
            rows[r['slot_id']] = r
    assert len(rows) == 32
    assert all(r['denominators']['required'] == 4 and
               r['subsets']['early']['denominators']['required'] == 3 and
               r['subsets']['water']['denominators']['required'] == 1 for r in rows.values())
    assert all(r['metrics']['executed_capacity_violation_duration_ms'] == 0 and
               r['invalid_precondition_start_count'] == 0 for r in rows.values())
    references = []
    for r in rows.values():
        references.append({k: r[k] for k in ('slot_id', 'episode_id', 'policy', 'source_path',
                          'source_pointer', 'denominators', 'subsets', 'tasks', 'metrics',
                          'arrival_background')})
    adequate = [r for r in rows.values() if '-no_competition-' in r['episode_id']]
    assert len(adequate) == 16 and all(r['all_timely'] and
        r['metrics']['action_rejected_count'] == r['metrics']['coordination_defer_count'] == 0 for r in adequate)
    failures, late = [], []
    for r in rows.values():
        for tid, t in r['tasks'].items():
            dst = failures if not t['completed'] else late if not t['timely'] else None
            if dst is not None:
                dst.append({'slot_id': r['slot_id'], 'task_id': tid, **t,
                            'source_path': r['source_path'], 'source_pointer': r['source_pointer']})
    assert len(failures) == 8 and len(late) == 10
    assert all(x['task_id'] == 'water' for x in late)
    release = read(ROOT / PREFIX / 'pairs_release.json')['pairs']
    assert len(release) == 16
    release_evidence = []
    clock_only, worsened, invariant = [], [], []
    keys = ('start_ms', 'completion_ms', 'execution_ms')
    for p in release:
        left, right = rows[p['left']], rows[p['right']]
        lw, rw = left['tasks']['water'], right['tasks']['water']
        L = rw['release_ms'] - lw['release_ms']
        assert L in (60000, 120000)
        assert lw['deadline_ms'] - lw['release_ms'] == rw['deadline_ms'] - rw['release_ms']
        same_execution = all(left['tasks'][t][k] == right['tasks'][t][k]
                             for t in left['tasks'] for k in keys)
        item = {'left': p['left'], 'right': p['right'], 'release_shift_ms': L,
                'all_task_absolute_execution_identical': same_execution,
                'water_completion_latency': p['conditional_subset_time']['water']['metrics']['completion_latency_ms'],
                'early_completion_latency': p['conditional_subset_time']['early']['metrics']['completion_latency_ms'],
                'whole_house': p['scalar_comparison']['whole_house_completion_ms'],
                'common_task_ids': p['conditional_time']['common_task_ids']}
        release_evidence.append(item)
        if '-no_competition-' in p['left']:
            assert rw['completion_latency_ms'] == lw['completion_latency_ms']
            assert rw['task_start_wait_ms'] == lw['task_start_wait_ms'] == 400
            assert rw['completion_ms'] - lw['completion_ms'] == L
            invariant.append(item)
        elif left['policy'] in ('ConstraintCoordinator', 'GateRetryRule'):
            assert same_execution
            assert rw['completion_latency_ms'] - lw['completion_latency_ms'] == -L
            clock_only.append(item)
        elif left['policy'] == 'DeadlineAwareCoordinator':
            assert rw['completion_latency_ms'] > lw['completion_latency_ms']
            assert lw['timely'] and not rw['timely']
            worsened.append(item)
    assert (len(invariant), len(clock_only), len(worsened)) == (8, 4, 2)
    groups = read(ROOT / PREFIX / 'four_cells.json')['groups']
    assert len(groups) == 8
    group_evidence = [{'base_episode_id': g['base_episode_id'], 'policy': g['policy'], 'slots': g['slots'],
        'timely_service': g['scalar_comparison']['timely_service_rate'],
        'common_task_ids': g['conditional_time']['common_task_ids'],
        'coverage': g['conditional_time']['coverage'],
        'water_completion_latency': g['conditional_subset_time']['water']['metrics']['completion_latency_ms']}
        for g in groups]
    assert sum(g['coverage'] == 1 for g in group_evidence) == 6
    assert sum(g['coverage'] == 0.5 for g in group_evidence) == 2
    assert all(g['timely_service']['effects']['interaction'] == 0.25
               for g in group_evidence if g['policy'] == 'DeadlineAwareCoordinator')
    diagnostics = read(ROOT / PREFIX / 'information_diagnostics.json')['pairs']
    assert len(diagnostics) == 48 and all(d['equal'] and not d['performance_comparison'] for d in diagnostics)
    return {'status': 'author_descriptive_findings_from_accepted_F2_not_new_review',
            'date': '2026-10-05', 'research_scope': 'multi_agent_conflict_service_latency_scheduling',
            'review_path': f'{REVIEW_PREFIX}/{report.name}', 'review_sha256': sha(report),
            'review_source_sha256': original_source_sha256(f'{REVIEW_PREFIX}/{report.name}'),
            'review_audit_path': f'{REVIEW_PREFIX}/{audit_path.name}', 'review_audit_sha256': sha(audit_path),
            'review_audit_source_sha256': original_source_sha256(f'{REVIEW_PREFIX}/{audit_path.name}'),
            'reviewed_sha256': locks, 'source_sha256': freeze['source_sha256'],
            'runtime_source_sha256': freeze['runtime_source_sha256'],
            'scope': {'runs': 32, 'pairs': 72, 'four_cells': 8, 'diagnostic_prefix_pairs': 48},
            'executed_capacity_violating_runs': 0, 'invalid_precondition_start_runs': 0,
            'adequate_all_timely_runs': 16, 'failed_task_records': failures, 'late_task_records': late,
            'run_evidence': references, 'release_pair_evidence': release_evidence,
            'clock_only_tight_release_pairs': clock_only, 'worsened_water_tight_release_pairs': worsened,
            'invariant_water_adequate_release_pairs': invariant, 'four_cell_evidence': group_evidence,
            'diagnostics_equal_count': 48, 'api_calls': 0, 'simulator_runs': 0,
            'cross_family_analysis_created': False,
            'interpretation_limits': ['arrival intervention also changes published information and absolute deadline',
                                     'not an isolated reservation-replanning ablation',
                                     '500ms tardiness is a boundary-sensitive synthetic result',
                                     'no classification of unavoidable loss'],
            'rankings_or_inferential_statistics_created': False}


if __name__ == '__main__':
    import sys
    text = json.dumps(extract(), ensure_ascii=False, indent=2) + '\n'
    offset = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    print(json.dumps({'text': text[offset:offset+40000],
                      'next': offset+40000 if offset+40000 < len(text) else None}, ensure_ascii=True))
