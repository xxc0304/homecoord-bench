"""Family-separated evidence index. No pooled score, simulation or new scorer."""
import hashlib
import json
from pathlib import Path
from homecoord_bench.task_revision.publication_redaction import matches_source_sha256, original_source_sha256

ROOT = Path(__file__).resolve().parents[2]
REVIEW_PREFIX = 'docs/review_evidence/2026-10-01_to_2026-10-06'
REVIEW_DIR = ROOT / REVIEW_PREFIX


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract():
    protected, reviews = {}, {}
    for family, date in [('F1', '20261004'), ('F2', '20261005'), ('F3', '20261004')]:
        report = REVIEW_DIR / f'{family}_AGGREGATION_V1_REVIEW_{date}.md'
        audit_path = REVIEW_DIR / f'{family}_AGGREGATION_V1_AUDIT_{date}.json'
        audit = read(audit_path)
        assert not audit['errors'] and all(c['passed'] for c in audit['checks'])
        locks = {p.replace('\\', '/'): h for p, h in audit['reviewed_sha256'].items()}
        for p, h in locks.items():
            assert p not in protected or protected[p] == h
            assert matches_source_sha256(p, h)
            protected[p] = h
        report_rel = f'{REVIEW_PREFIX}/{report.name}'
        audit_rel = f'{REVIEW_PREFIX}/{audit_path.name}'
        reviews[family] = {'report_path': report_rel, 'report_sha256': sha(report),
                           'report_source_sha256': original_source_sha256(report_rel),
                           'audit_path': audit_rel, 'audit_sha256': sha(audit_path),
                           'audit_source_sha256': original_source_sha256(audit_rel)}
        acceptance = 'docs/' + family + '_AGGREGATION_V1_ACCEPTANCE_2026-' + ('10-05' if family == 'F2' else '10-04') + '.json'
        accepted = read(ROOT / acceptance)
        if family == 'F3':
            assert accepted.get('review_report_sha256') == sha(report)
            assert accepted.get('review_audit_sha256') == sha(audit_path)
            assert accepted.get('source_review_report_sha256') == reviews[family]['report_source_sha256']
        else:
            assert accepted.get('review_sha256') == sha(report)
            assert accepted.get('review_audit_sha256') == sha(audit_path)
        protected[acceptance] = sha(ROOT / acceptance)
    p1 = 'docs/f1_findings_20261004/evidence.json'
    p2 = 'docs/f2_findings_20261005/evidence.json'
    f1, f2 = read(ROOT / p1), read(ROOT / p2)
    for obj in (f1, f2):
        for field in ('reviewed_sha256', 'source_sha256', 'runtime_source_sha256'):
            for p, h in obj.get(field, {}).items():
                assert matches_source_sha256(p, h)
                assert p not in protected or protected[p] == h
                protected[p] = h
    for p in [p1, p2, 'docs/F1_FINDINGS_2026-10-04.md',
              'docs/F2_FINDINGS_2026-10-05.md', 'docs/F3_FINDINGS_2026-10-04.md',
              'docs/RESEARCH_SCOPE_AND_EVIDENCE_2026-10-04.md']:
        protected[p] = sha(ROOT / p)
    f1rows = {r['slot_id']: r for r in f1['example_runs']}
    f1a = f1rows['D-F1-02-competition-base|GateRetryRule|order2']
    f1b = f1rows['D-F1-02-competition-base|ConstraintCoordinator|order2']
    assert f1b['metrics']['whole_house_completion_ms'] - f1a['metrics']['whole_house_completion_ms'] == -239800
    assert f1b['tasks']['water']['completion_ms'] - f1a['tasks']['water']['completion_ms'] == 240200
    f2rows = {r['slot_id']: r for r in f2['run_evidence']}
    f2a = f2rows['F2R1-D-F2-02-competition-simultaneous|DeadlineAwareCoordinator']
    f2b = f2rows['F2R1-D-F2-02-competition-late|DeadlineAwareCoordinator']
    assert f2b['metrics']['whole_house_completion_ms'] - f2a['metrics']['whole_house_completion_ms'] == -60000
    assert f2b['tasks']['water']['completion_latency_ms'] - f2a['tasks']['water']['completion_latency_ms'] == 420000
    f3rows, f3worlds = {}, {}
    for base in ('01', '02'):
        for capacity in ('competition', 'no_competition'):
            for deadline in ('base', 'loose'):
                p = f'docs/f3_aggregation_v1_20261004/D-F3-{base}-{capacity}-{deadline}.json'
                d = read(ROOT / p)
                f3worlds[d['world']] = d
                for sid, r in d['runs'].items():
                    assert sid not in f3rows
                    f3rows[sid] = r
    assert len(f3rows) == 224
    assert sum(r['identity']['role'] == 'primary' for r in f3rows.values()) == 192
    examples = []
    for base in ('01', '02'):
        world = f'D-F3-{base}-competition-base'
        selected = [r for r in f3worlds[world]['runs'].values() if
                    r['identity']['policy'] == 'ConstraintCoordinator' and
                    r['identity']['capability_kind'] == 'selectable' and
                    r['identity']['role'] == 'primary' and
                    r['identity']['selector'] in ('low_resource', 'short_duration')]
        assert len(selected) == 2
        selected.sort(key=lambda r: r['identity']['selector'])
        a, b = selected
        assert b['tasks']['water']['wait_ms']['value'] - a['tasks']['water']['wait_ms']['value'] == (240000 if base == '01' else 300000)
        examples.append({'world': world, 'control_low_resource': a, 'candidate_short_duration': b})
    summary = read(ROOT / 'docs/f3_aggregation_v1_20261004/summary.json')
    assert summary['equal_world_factorial_summary']['all_service_completion_ms']['T']['value'] is None
    adequate = [r for r in f3rows.values() if '-no_competition-' in r['identity']['base_world_id'] and r['identity']['role'] == 'primary']
    assert all(r['coverage']['on_time'] == r['coverage']['required'] for r in adequate)
    return {'status': 'author_family_separated_synthesis_not_new_implementation_or_claim_review',
            'date': '2026-10-05', 'research_question': 'multi_agent_conflict_service_latency_tradeoffs',
            'reviews': reviews, 'protected_sha256': protected,
            'historical_F3_acceptance_path_encoding_issue': {
                'historical_record_preserved': True,
                'canonical_report_path': reviews['F3']['report_path'],
                'canonical_report_source_sha256': reviews['F3']['report_source_sha256'],
                'canonical_report_published_sha256': reviews['F3']['report_sha256'],
                'canonical_report_hash_matches_historical_record': True},
            'family_scopes': {'F1': {'runs': 72, 'pairs': 168, 'four_cells': 18},
                              'F2': {'main_runs': 32, 'pairs': 72, 'four_cells': 8, 'prefix_diagnostics': 48},
                              'F3': {'main_runs': 192, 'diagnostic_runs': 32, 'pairs': 424, 'four_cells': 24}},
            'global_vs_individual_examples': {'F1': {'control': f1a, 'candidate': f1b},
                                            'F2': {'simultaneous': f2a, 'late': f2b}, 'F3': examples},
            'negative_controls': {
                'F1_adequate_all_timely_runs': f1['adequate_capacity_all_timely_runs'],
                'F1_adequate_identical_gate_constraint_pairs': f1['adequate_gate_vs_constraint_identical_task_time_pairs'],
                'F1_deadline_pairs_same_actual_time': len(f1['deadline_pairs_same_actual_time']),
                'F2_adequate_all_timely_runs': f2['adequate_all_timely_runs'],
                'F2_adequate_release_water_invariant_pairs': len(f2['invariant_water_adequate_release_pairs']),
                'F2_tight_clock_only_pairs': len(f2['clock_only_tight_release_pairs']),
                'F3_adequate_all_timely_primary_runs': len(adequate)},
            'F3_predefined_summary': summary,
            'pooled_cross_family_scores_created': False, 'rankings_created': False,
            'new_simulator_runs': 0, 'api_calls': 0, 'holdout_read': False,
            'claims_independently_accepted': False}


if __name__ == '__main__':
    import sys
    s = json.dumps(extract(), ensure_ascii=False, indent=2) + '\n'
    offset = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    print(json.dumps({'text': s[offset:offset+40000], 'next': offset+40000 if offset+40000 < len(s) else None}, ensure_ascii=True))
