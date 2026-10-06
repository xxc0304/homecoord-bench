"""F1 correction metadata and cohort eligibility only; not a scoring adapter."""
import json
import hashlib
from copy import deepcopy

from homecoord_bench.task_revision.f1_statistical_contract_v1 import ROOT, bundle as v1_bundle

OUT = 'docs/f1_statistical_contract_v2_20261004/plan.json'
V1_PLAN_SHA = 'd8fb7fc57aacc70caa441ffda66884d6ffa143e9390574d3aa51c17892809430'
V1_CONTRACT_SHA = '23f302299922c3766bed9096f71680b2f80f91f82d408fdb21affffcf4841fb1'
CELL_ORDER = ('tight_base', 'tight_loose', 'adequate_base', 'adequate_loose')
MAIN_RATES = ('service_rate', 'timely_service_rate')
TIME_METRICS = ('task_start_wait_ms', 'execution_ms', 'completion_latency_ms', 'tardiness_ms')
RUN_METRICS = ('executed_capacity_violation_duration_ms', 'excess_resource_unit_ms',
               'coordination_accept_count', 'coordination_defer_count', 'coordination_reject_count',
               'action_rejected_count', 'retry_queued_count', 'retry_scheduled_count',
               'reservation_count', 'actual_start_count')


def metric_rules():
    return {
        'fixed_denominator': 'E=all_predeclared_required_requests_never_K',
        'cell_order': list(CELL_ORDER),
        'interaction_formula': '(adequate_loose-tight_loose)-(adequate_base-tight_base)',
        'four_cell_allowlist': {
            'fixed_E_rates': list(MAIN_RATES),
            'run_event_or_process': list(RUN_METRICS),
            'same_four_cell_completed_population': list(TIME_METRICS),
            'all_E_completed_in_all_four_cells': ['whole_house_completion_ms'],
        },
        'cohort': {
            'K': 'intersection(C_tight_base,C_tight_loose,C_adequate_base,C_adequate_loose)',
            'time_aggregation': 'equal_task_mean_on_identical_K_in_each_cell_or_per_task_interaction',
            'required_outputs': ['required_task_ids', 'completed_task_ids_by_cell', 'common_task_ids',
                                 'common_count', 'required_count', 'coverage', 'excluded_tasks',
                                 'eligible', 'null_reason'],
            'empty_K': 'null: no_common_completed_requests',
            'different_two_arm_intersections': 'forbidden_as_four_cell_population',
            'missing_metric_on_K': 'data_error_not_drop_task_not_zero',
            'missing_source_or_cell': 'data_error_keep_expected_slot_not_score_as_normal_failure',
        },
        'conditional_timely_rate': {
            'display': 'per_run_auxiliary_only_with_completed_denominator',
            'zero_completed': 'null: no_completed_requests',
            'four_cell_interaction': False,
            'template_macro_aggregation': False,
        },
        'completed_only_means_on_each_cells_own_C': {
            'display': 'per_run_auxiliary_only_with_ids_count_coverage',
            'four_cell_interaction': False,
        },
        'whole_house_completion': {
            'requires': 'C_cell=E_for_each_of_the_four_cells',
            'otherwise': 'null: not_all_required_completed_in_four_cells',
            'never_use_K_as_E': True,
        },
        'template_macro': {
            'metrics': list(MAIN_RATES), 'slots_per_template_per_policy': 12,
            'weight_each_slot': '1/12', 'weight_each_template': '1/2',
            'skip_null_or_missing_slots': False,
        },
        'unlisted_metrics': 'not_eligible_for_four_cell_interaction_in_this_version',
    }


def analysis_population(required_task_ids, completed_task_ids_by_cell):
    """Pure set eligibility for hypothetical inputs. No traces or timings read."""
    required = list(required_task_ids)
    if not required or len(required) != len(set(required)):
        raise ValueError('required set must be nonempty with unique IDs')
    if set(completed_task_ids_by_cell) != set(CELL_ORDER):
        raise ValueError('all four cells required; missing cell is a data error')
    completed = {}
    for cell in CELL_ORDER:
        ids = list(completed_task_ids_by_cell[cell])
        if len(ids) != len(set(ids)) or not set(ids) <= set(required):
            raise ValueError('completed set duplicates or unknown required task')
        completed[cell] = set(ids)
    common = set.intersection(*completed.values())
    return {
        'required_task_ids': required,
        'completed_task_ids_by_cell': {c: [t for t in required if t in completed[c]] for c in CELL_ORDER},
        'common_task_ids': [t for t in required if t in common],
        'common_count': len(common), 'required_count': len(required),
        'coverage': len(common) / len(required),
        'excluded_tasks': [{'task_id': t, 'reason': 'not_completed_in_all_four_cells',
                            'not_completed_cells': [c for c in CELL_ORDER if t not in completed[c]]}
                           for t in required if t not in common],
        'eligible': bool(common),
        'null_reason': None if common else 'no_common_completed_requests',
        'all_E_completed_in_all_four_cells': all(x == set(required) for x in completed.values()),
    }


def bundle():
    # The v1 source/identity generation remains unchanged; v2 adds static rules only.
    for path, digest in (
        ('docs/f1_statistical_contract_v1_20261004/plan.json', V1_PLAN_SHA),
        ('docs/F1_STATISTICAL_CONTRACT_V1_2026-10-04.md', V1_CONTRACT_SHA),
    ):
        if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != digest:
            raise ValueError('reviewed v1 material changed')
    p = deepcopy(v1_bundle())
    p['version'] = 'F1-statistical-contract-v2-correction-draft'
    p['metric_rules'] = metric_rules()
    p['supersedes'] = {
        'v1_plan_sha256': V1_PLAN_SHA,
        'v1_contract_sha256': V1_CONTRACT_SHA,
        'scope': 'four_cell_metric_eligibility_and_main_rate_macro_scope_only',
    }
    for g in p['four_cells']:
        g['metric_rules_ref'] = '/metric_rules'
        g['population_ref'] = 'derive_identical_four_cell_K_from_valid_completion_receipts_after_adapter_review'
    return p


if __name__ == '__main__':
    print(json.dumps(bundle(), ensure_ascii=False, indent=2))
