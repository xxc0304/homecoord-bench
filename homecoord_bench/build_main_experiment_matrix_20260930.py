"""Evidence ledger and separately validated, non-runtime research design cards."""
import json
import math
from copy import deepcopy
from pathlib import Path
from probe_c3_action_choice_20260930 import write, digest

ROOT = Path(__file__).resolve().parent
DIR = ROOT / 'revision_drafts' / '20260930_main_matrix'
OUTPUT = ROOT / 'results' / 'main_matrix_readiness_20260930.json'

def validate_certificate(card, certificate):
    capacity = card['resource_capacity_units']
    if isinstance(capacity, bool) or not isinstance(capacity, (int, float)) or not math.isfinite(capacity) or capacity <= 0:
        raise ValueError('invalid capacity')
    tasks = {t['task_id']: t for t in card['tasks']}
    if set(certificate) != set(tasks):
        raise ValueError('certificate must serve every task exactly once')
    intervals = {}
    for task_id, task in tasks.items():
        selected = certificate[task_id]
        modes = {m['mode']: m for m in task['acceptable_modes']}
        if selected['mode'] not in modes:
            raise ValueError('mode not semantically acceptable')
        mode = modes[selected['mode']]
        if not isinstance(mode['duration_ms'], int) or isinstance(mode['duration_ms'], bool) or mode['duration_ms'] <= 0:
            raise ValueError('invalid service duration')
        units = mode['resource_units']
        if isinstance(units, bool) or not isinstance(units, (int, float)) or not math.isfinite(units) or units < 0:
            raise ValueError('invalid resource cost')
        start = selected['start_ms']
        if isinstance(start, bool) or not isinstance(start, int) or start < task['release_ms']:
            raise ValueError('invalid start or start before release')
        finish = start + mode['duration_ms']
        if finish > task['deadline_ms']:
            raise ValueError('completion deadline missed')
        intervals[task_id] = {'start_ms': start, 'finish_ms': finish,
                              'resource_units': mode['resource_units']}
    for task_id, task in tasks.items():
        for predecessor in task.get('predecessors', []):
            if predecessor not in intervals or intervals[predecessor]['finish_ms'] > intervals[task_id]['start_ms']:
                raise ValueError('predecessor not completed before dependent task starts')
    boundaries = sorted({x for item in intervals.values() for x in (item['start_ms'], item['finish_ms'])})
    peak = 0
    for at in boundaries:
        use = sum(item['resource_units'] for item in intervals.values() if item['start_ms'] <= at < item['finish_ms'])
        peak = max(peak, use)
        if use > card['resource_capacity_units']:
            raise ValueError('resource capacity exceeded')
    return {'feasible_certificate': True, 'task_intervals': intervals, 'peak_resource_units': peak,
            'makespan_ms': max(item['finish_ms'] for item in intervals.values())}

def task(task_id, agent, deadline, modes, predecessors=()):
    return {'task_id': task_id, 'agent_id': agent, 'release_ms': 0, 'deadline_ms': deadline,
            'predecessors': list(predecessors), 'acceptable_modes': [
                {'mode': mode, 'duration_ms': duration, 'resource_units': units}
                for mode, duration, units in modes]}

def cards():
    common = {'schema': 'research-design-card-0.1', 'status': 'author_design_not_runtime_episode',
              'parameter_provenance': 'E4 controlled logical service contract; no physical calibration',
              'execution': 'noninterruptible; half-open resource intervals; dependencies on completion',
              'independent_review': 'pending', 'model_tested': False, 'runtime_integrated': False}
    dependent = {**common, 'card_id': 'D-DEPENDENCY-01', 'family': 'logical_shared_service_dependency',
                 'agent_count': 3, 'resource_capacity_units': 3,
                 'story': 'Gateway service must complete before network-dependent media playback. Backup is independent. Costs are abstract admission units, not measured network or power costs.',
                 'tasks': [task('gateway', 'GatewayAgent', 240000, [('prepare', 180000, 1)]),
                           task('media', 'MediaAgent', 360000, [('play', 120000, 1)], ['gateway']),
                           task('backup', 'BackupAgent', 480000, [('backup', 240000, 2)])],
                 'certificates': [{'gateway': {'mode': 'prepare', 'start_ms': 0},
                                   'media': {'mode': 'play', 'start_ms': 180000},
                                   'backup': {'mode': 'backup', 'start_ms': 0}}],
                 'required_baseline': 'dependency-ready queue plus capacity/deadline scheduler; cannot compare only rules lacking dependency support',
                 'implementation_gaps': ['released public predecessor contract', 'retry on predecessor completion',
                                         'dependency-aware feasibility oracle', 'proposal/precondition timing controls'],
                 'claim_limit': 'early dependent proposal rejection alone is not an algorithm gap'}
    ready = deepcopy(dependent)
    ready.update({'card_id': 'D-DEPENDENCY-READY-01',
                  'story': 'The initial readiness guarantee is already satisfied; gateway refresh preserves readiness. Only the readiness requirement changes in this logical contract.',
                  'initial_readiness': True})
    ready['tasks'][1]['predecessors'] = []
    ready['certificates'] = [{'gateway': {'mode': 'prepare', 'start_ms': 0},
                              'media': {'mode': 'play', 'start_ms': 0},
                              'backup': {'mode': 'backup', 'start_ms': 120000}}]
    choices = {**common, 'card_id': 'D-MULTIMODE-01', 'family': 'multiple_valid_resource_time_modes',
               'agent_count': 3, 'resource_capacity_units': 3,
               'story': 'An ordinary laundry request permits either service mode. Eco and fast both satisfy the same declared outcome but consume different admission units for different durations.',
               'tasks': [task('laundry', 'LaundryAgent', 600000, [('eco', 480000, 1), ('fast', 240000, 2)]),
                         task('water', 'WaterAgent', 360000, [('prepare', 300000, 2)]),
                         task('meal', 'MealAgent', 660000, [('prepare', 300000, 1)])],
               'certificates': [
                   {'laundry': {'mode': 'eco', 'start_ms': 0}, 'water': {'mode': 'prepare', 'start_ms': 0}, 'meal': {'mode': 'prepare', 'start_ms': 300000}},
                   {'laundry': {'mode': 'fast', 'start_ms': 300000}, 'water': {'mode': 'prepare', 'start_ms': 0}, 'meal': {'mode': 'prepare', 'start_ms': 0}}],
               'required_baseline': 'enumerate acceptable modes then exact capacity/deadline schedule, alongside fixed-mode and greedy rules',
               'implementation_gaps': ['set-valued service acceptance scoring', 'mode-aware public cost contract',
                                       'mode-enumerating strong baseline', 'avoid hidden single required operation'],
               'claim_limit': 'fast is not always better; report service, deadlines, per-task waits and completions without inventing one universal winner'}
    relaxed = deepcopy(choices)
    relaxed.update({'card_id': 'D-MULTIMODE-CAPACITY-01', 'resource_capacity_units': 4})
    relaxed['certificates'] = [
        {'laundry': {'mode': 'eco', 'start_ms': 0}, 'water': {'mode': 'prepare', 'start_ms': 0}, 'meal': {'mode': 'prepare', 'start_ms': 0}},
        {'laundry': {'mode': 'fast', 'start_ms': 0}, 'water': {'mode': 'prepare', 'start_ms': 0}, 'meal': {'mode': 'prepare', 'start_ms': 240000}}]
    return [dependent, ready, choices, relaxed]

def build():
    sources = [
        ('C3-scale', 'results/c3_scale_release_offline_20260930.json', 'scripted_grid', 'six structures; 108 cells; 26280 runs; no new model decisions'),
        ('C3-scale-model', 'results/c3_scale_release_model_20260930.json', 'fresh_canonical_plus_counterfactual', '11 saved proposals; 270 replays'),
        ('strong-information', 'results/c3_information_baselines_20260930.json', 'scripted_and_reused_proposals', 'perfect announcement explicitly privileged'),
        ('own-task-metrics', 'results/c3_task_response_contract_20260930.json', 'existing_proposal_reevaluation', '396 replays; not independent model samples'),
        ('local-compute', 'results/c3_runtime_cost_20260930.json', 'local_wall_timer', '720 timed runs; not deployment latency'),
        ('fresh-repeats', 'results/c3_runtime_repeat_audit_20260930.json', 'fresh_canonical_plus_counterfactual', '33 fresh proposals; 171 replays; late cells counterfactual'),
        ('late-release', 'results/c3_release_state_audit_20260930.json', 'hybrid_fresh_late', '36 provider attempts;35 valid;1 protocol failure; local state unchanged'),
        ('visible-update', 'results/c3_visible_request_update_audit_20260930.json', 'hybrid_fresh_late_plus_counterfactual', '24 fresh proposals;12 visible updated views; all correct;96 replays'),
        ('C1-core-control', 'results/core_paired_baselines_20260930.json', 'historical_mechanism_control', 'do not merge old outcome metrics into latest C3 totals'),
        ('C2-physics-pilot', 'results/c2_recorded_model_physics_20260928.json', 'historical_separate_physics_exploration', 'not integrated into the C3 categorical service contracts'),
        ('C4-message', 'results/c4_agent_message_pilot_20260928.json', 'historical_lifecycle_exploration', 'not evidence of implemented cancellation or general multi-turn repair'),
        ('multimode', 'results/c3_multimode_audit_20260930.json', 'fresh_all_released_proposals_and_policy_replay', '18 fresh calls;30 policy runs;one structure;mode revision authority separated'),
        ('multimode_replication', 'results/c3_multimode_replication_audit_20260930.json', 'fresh_dual_mode_structure_proposals_and_policy_replay', '18 requests;17 successes;1 SSL failure;25 policy runs;second author-designed structure;not held-out'),
        ('compute_clock', 'results/c3_compute_clock_audit_20260930.json', 'measured_compute_charged_paired_replay', '30 measurements;60 paired runs;4 controls;no fresh API;only exact batch plan cost;not online replanning'),
        ('ordinary_compute', 'results/c3_ordinary_compute_audit_20260930.json', 'calibrated_dispatch_retry_compute_replay', '48 calibration;32 paired runs;2 controls;no API;FIFO worker;partial callback cost not architecture latency'),
        ('task_family_split', 'results/task_family_split_audit_20260930.json', 'prospective_structural_split_development_only', '12 structures;48 candidate episodes;24 dev;24 unexecuted prospective test;360 scripted dev runs;no API'),
        ('development_model', 'results/development_model_audit_20260930.json', 'fresh_development_parallel_and_release_state_model_pilot', '26 new successful API calls;26 policy runs;6 dev conditions;single model;one repetition;not full architecture ranking'),
        ('central_batch_adapter', 'results/central_batch_adapter_audit_20260930.json', 'scripted_release_batch_interface_identity_control', '240 scripted executions;120 matched pairs;no API;batch adapter not architecture/model efficacy')]
    ledger = []
    for name, path, kind, note in sources:
        file = ROOT / path
        value = json.loads(file.read_text(encoding='utf8'))
        ledger.append({'evidence_id': name, 'path': path, 'sha256': digest(file),
                       'execution_kind': kind, 'limit': note, 'source_status': value.get('status', 'see original source')})
    checks = []
    candidate_hashes = {}
    for card in cards():
        certificates = [validate_certificate(card, cert) for cert in card['certificates']]
        file = DIR / (card['card_id'] + '.json')
        write(file, card)
        candidate_hashes[file.name] = digest(file)
        checks.append({'card_id': card['card_id'], 'family': card['family'], 'certificates': certificates,
                       'runtime_integrated': False, 'model_tested': False})
    matrix = {'version': 'main-experiment-matrix-0.1', 'status': 'author_pilot_design_not_frozen_benchmark',
              'research_question': 'How does coordination affect correct, safe and timely service when home agents act asynchronously?',
              'axes': {'agent_count': [2, 4, 5], 'release': ['together', 'urgent_late', 'urgent_first'],
                       'pressure': [0.8, 1.2, 1.6], 'deadline': ['tight', 'loose'],
                       'requirement': ['fixed', 'visible_at_release_update'],
                       'note': 'structured blocks, not complete Cartesian product; device composition confounds agent-count-only effects'},
              'blocks': [
                  {'id': 'B1', 'purpose': 'rule-sufficient same-device control', 'coverage': 'C1', 'status': 'historical_pilot'},
                  {'id': 'B2', 'purpose': 'asynchronous pooled resource admission', 'coverage': 'C3', 'status': 'largest_existing_pilot'},
                  {'id': 'B3', 'purpose': 'late arrivals and information limits', 'coverage': 'C3', 'status': 'hybrid_late_calls_and_counterfactuals'},
                  {'id': 'B4', 'purpose': 'visible current demand selection vs scheduling', 'coverage': 'C3_context', 'status': 'simple_semantics_negative_result'},
                  {'id': 'B5', 'purpose': 'indirect environment influence', 'coverage': 'C2', 'status': 'separate_exploration_not_uniform_core'},
                  {'id': 'B6', 'purpose': 'state validity and lifecycle', 'coverage': 'C4', 'status': 'historical_pilot_missing_cancellation'},
                  {'id': 'E1', 'purpose': 'shared-service dependency', 'status': 'design_card_only_not_in_main_score'},
                  {'id': 'E2', 'purpose': 'multiple acceptable modes with unequal costs', 'status': 'single_structure_runtime_pilot_not_frozen_main_data'}],
              'information_contract': {'specialists': 'local device plus explicitly declared visible records; no hidden scoring answer',
                                       'scheduler': 'released metadata/public costs/returned proposals/current state and reservations',
                                       'privileged': 'perfect future announcements and known-future oracle separated',
                                       'limitations': 'audit views are not a read-isolation sandbox; shared gate has synthetic exact costs'},
              'baselines': ['shared gate only', 'gate retry', 'constraint scheduling', 'deadline batching',
                            'capacity-aware deadline', 'released feasibility strict', 'released feasibility fallback'],
              'metrics': ['protocol validity', 'authorized and semantically correct service', 'actual task service',
                          'all/per-task deadline success', 'own-release correct-start wait', 'actual completion latency',
                          'completion tardiness', 'missing start/completion', 'process safety', 'solver compute cost separately'],
              'analysis_units': 'task structure and independent model batch; variants, permutations and reused-proposal replays are dependent',
              'required_controls': ['noncontending resource capacity', 'looser deadline', 'stable requirement',
                                    'both update directions', 'rule-sufficient structure', 'oracle feasibility',
                                    'explicitly impossible tasks excluded from avoidable-failure claims'],
              'held_out_status': 'all current candidates are development; no independent held-out split claimed',
              'evidence': ledger, 'new_design_cards_sha256': candidate_hashes,
              'next_implementation': 'preregister same-model central/functional pilot with common executor and pooled-information ablation, preserve failures and budgets, then second structures/repeats/model; prospective test unopened; E1 optional'}
    write(DIR / 'manifest.json', matrix)
    result = {'status': 'source_ledger_and_design_certificates_validated', 'new_api_calls': 0,
              'source_files_checked': len(ledger), 'new_design_cards': len(checks),
              'feasible_certificates': sum(len(c['certificates']) for c in checks),
              'main_matrix_sha256': digest(DIR / 'manifest.json'), 'cards': checks,
              'claim_limit': 'feasible declared schedules are not deployed simulator experiments or optimality proofs'}
    write(OUTPUT, result)
    return result

if __name__ == '__main__':
    result = build()
    print(json.dumps({k: v for k, v in result.items() if k != 'cards'}, ensure_ascii=False))
