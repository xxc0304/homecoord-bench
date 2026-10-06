"""F2 static statistical plan only; no simulator import or strategy scoring."""
import hashlib
import json
from copy import deepcopy
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'homecoord_bench/task_revision/fixtures/f2_v7'
OUT = 'docs/f2_statistical_contract_v1_20261004/plan.json'
MANIFEST_SHA = '72fb856244894bc55b599bac5e59756346b2bff934fad713c76ba10b1272c824'
POLICIES = ('IndependentMultiAgent', 'ConstraintCoordinator', 'DeadlineAwareCoordinator', 'GateRetryRule')
BASES = ('D-F2-01', 'D-F2-02')
ARMS = ('competition', 'no_competition')
ARRIVALS = ('simultaneous', 'late')


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def differences(a, b, path=''):
    if type(a) is not type(b): return [path]
    if isinstance(a, dict):
        return sum((differences(a.get(k), b.get(k), path+'/'+k) for k in sorted(a.keys() | b.keys())), [])
    if isinstance(a, list):
        if len(a) != len(b): return [path]
        return sum((differences(x, y, path+'/'+str(i)) for i, (x, y) in enumerate(zip(a, b))), [])
    return [] if a == b else [path]


def check_public_context(e):
    """Check redundant context before stripping any allowed intervention fields."""
    expected = []
    for t in e['task_stream']:
        g = next(g for g in e['action_grounding'] if g['task_id']==t['task_id'] and g['operation']=='prepare')
        expected.append({'task_id':t['task_id'], 'deadline_ms':t['completion_deadline_ms'],
                         'release_at_ms':t['release_at_ms'], 'requested_service':t['requested_service'],
                         'modes':[{'operation':'prepare','duration_ms':g['duration_ms'],'resource_units':g['power_kw']}]})
    ctx = e['initial_state']['values']['coordination_context']
    if ctx['resource_capacity_units'] != e['home']['resources']['max_power_kw']:
        raise ValueError('context capacity mismatch')
    if ctx['requests'] != [r for r in expected if r['release_at_ms']==0]:
        raise ValueError('initial request publication mismatch')
    future = [r for r in expected if r['release_at_ms']>0]
    if future:
        if len(future)!=1 or future[0]['task_id']!='water': raise ValueError('outside F2 release scope')
        expected_events = [{'event':'new_public_request','at_ms':future[0]['release_at_ms'],
                            'patch':{'coordination_context':{**ctx,'requests':expected}}}]
    else:
        expected_events = []
    if e['exogenous_events'] != expected_events:
        raise ValueError('exogenous publication mismatch')


def normalized(e, kind):
    check_public_context(e)
    e = deepcopy(e); e.pop('episode_id')
    if kind=='capacity':
        e['pairing'].pop('resource_arm')
        e['home']['resources'].pop('max_power_kw')
        e['initial_state']['values']['coordination_context'].pop('resource_capacity_units')
        for event in e['exogenous_events']:
            event['patch']['coordination_context'].pop('resource_capacity_units')
        for rule in e['conflict_rules']:
            if rule['type']=='C3': rule.pop('capacity')
    elif kind=='release':
        e['pairing'].pop('temporal_arm')
        # Context/event changes have already been exactly checked against declared releases.
        e['initial_state']['values']['coordination_context'].pop('requests')
        e.pop('exogenous_events')
        for task in e['task_stream']:
            if task['task_id']=='water':
                task['completion_deadline_ms'] -= task['release_at_ms']
                task['release_at_ms'] = 0
    else:
        raise ValueError(kind)
    return e


def validate_contrast(a, b, kind):
    changes = differences(normalized(a, kind), normalized(b, kind))
    if changes: raise ValueError(('undeclared intervention',changes))
    if kind=='capacity':
        if (a['home']['resources']['max_power_kw'], b['home']['resources']['max_power_kw']) != (3,6):
            raise ValueError('capacity must be tight3 -> adequate6')
    else:
        wa = next(t for t in a['task_stream'] if t['task_id']=='water')
        wb = next(t for t in b['task_stream'] if t['task_id']=='water')
        shift = 60000 if a['base_episode_id']=='D-F2-01' else 120000
        if wa['release_at_ms']!=0 or wb['release_at_ms']!=shift:
            raise ValueError('release orientation mismatch')
        if wb['completion_deadline_ms']-wa['completion_deadline_ms']!=shift:
            raise ValueError('service window not preserved')
    return differences(a,b)


def metric_rules():
    return {
        'static_E': 'four_main_requests_including_late_water_never_policy_selected',
        'fixed_subsets': {'early':'three_zero_release_non_water_requests','arrival_request':['water']},
        'primary_rates':['service_rate','timely_service_rate'],
        'conditional_timely_rate':'per_run_auxiliary_only_null_if_zero_completed',
        'time_origin':'each_tasks_own_release_not_episode_time',
        'paired_time_eligibility':'same_completed_task_ids_intersection_of_both_arms',
        'four_cell_time_K':'intersection_of_valid_completed_task_ids_in_all_four_cells',
        'four_cell_order':['tight_simultaneous','tight_late','adequate_simultaneous','adequate_late'],
        'four_cell_formula':'(adequate_late-tight_late)-(adequate_simultaneous-tight_simultaneous)',
        'time_allowlist':['task_start_wait_ms','proposal_to_start_ms','execution_ms','completion_latency_ms','tardiness_ms'],
        'process_allowlist':['executed_capacity_violation_duration_ms','excess_resource_unit_ms',
                             'coordination_defer_count','action_rejected_count','retry_queued_count','retry_scheduled_count'],
        'four_cell_whole_house_completion':'descriptive_global_clock_only_require_all_E_completed_in_each_arm',
        'empty_K':'null: no_common_completed_requests',
        'missing_metric_on_K_or_missing_slot':'data_error_not_reweight_or_drop_or_zero',
        'own_C_means_and_conditional_rates_in_four_cell_interaction':False,
        'macro_weights':{'per_policy_per_template_slots':4,'slot_weight':'1/4','template_weight':'1/2',
                         'metrics':['service_rate','timely_service_rate'],'skip_missing':False},
        'unknown_wallclock_or_coordination_compute':'null: not_instrumented',
        'arrival_resource_snapshot':'descriptive_not_causal_not_unavoidable',
        'reservation_is_actual_resource_load':False,
        'offline_certificate':'reference_only_no_regret_no_online_baseline_no_avoidability_claim',
        'diagnostics_in_service_denominator':False,
        'unlisted_four_cell_metrics':'not_eligible',
    }


def slot(eid, policy): return f'{eid}|{policy}'


def bundle():
    manifest_path = f'{SOURCE}/manifest.json'
    if sha(ROOT/manifest_path)!=MANIFEST_SHA: raise ValueError('F2 source manifest changed')
    manifest = json.loads((ROOT/manifest_path).read_text(encoding='utf-8'))
    locks = {manifest_path: MANIFEST_SHA, **manifest['artifact_sha256']}
    if any(sha(ROOT/p)!=h for p,h in locks.items()): raise ValueError('F2 source artifact changed')
    index = json.loads((ROOT/f'{SOURCE}/index.json').read_text(encoding='utf-8'))
    inputs = json.loads((ROOT/f'{SOURCE}/inputs.json').read_text(encoding='utf-8'))['episodes']
    expected = {f'F2R1-{b}-{a}-{t}' for b,a,t in product(BASES,ARMS,ARRIVALS)}
    es = {e['episode_id']:e for e in inputs}
    if len(inputs)!=8 or set(es)!=expected: raise ValueError('source configuration mismatch')
    configurations, runs, diagnostic_runs = [], [], []
    for eid in sorted(expected):
        e = es[eid]; check_public_context(e)
        tasks=e['task_stream']; ids=[t['task_id'] for t in tasks]
        if len(ids)!=4 or len(set(ids))!=4 or ids[-1]!='water': raise ValueError('required requests mismatch')
        path=f'{SOURCE}/runs/{eid}.json'
        if path not in index['run_files']: raise ValueError('unindexed main source')
        d=json.loads((ROOT/path).read_text(encoding='utf-8'))
        if d['evaluation_episode_id']!=eid or len(d['runs'])!=4: raise ValueError('main file identity mismatch')
        fields=('task_id','agent_id','release_at_ms','completion_deadline_ms','requested_service','acceptable_actions')
        required=[{**{k:t[k] for k in fields},'service_window_ms':t['completion_deadline_ms']-t['release_at_ms']} for t in tasks]
        configurations.append({'episode_id':eid,'base_episode_id':e['base_episode_id'],'pairing':e['pairing'],
                               'source_path':path,'input_pointer':f'/episodes/{inputs.index(e)}',
                               'required_requests':required,'early_task_ids':ids[:-1],'arrival_task_ids':['water'],
                               'capacity_units':e['home']['resources']['max_power_kw']})
        for i,r in enumerate(d['runs']):
            if r['evaluation_episode_id']!=eid or r['policy']!=POLICIES[i]: raise ValueError('run identity mismatch')
            runs.append({'slot_id':slot(eid,r['policy']),'episode_id':eid,'policy':r['policy'],
                         'source_path':path,'source_pointer':f'/runs/{i}','required_set_ref':eid})
    pairs, cells, contrasts = [], [], []
    def pair(kind,a,b): pairs.append({'kind':kind,'left':a,'right':b,'delta':'right_minus_left'})
    for eid in sorted(expected):
        for p in POLICIES[1:]: pair('policy',slot(eid,POLICIES[0]),slot(eid,p))
        for p in POLICIES[1:3]: pair('strong_rule',slot(eid,POLICIES[3]),slot(eid,p))
    for base in BASES:
        for timing in ARRIVALS:
            a,b=(f'F2R1-{base}-{arm}-{timing}' for arm in ARMS)
            contrasts.append({'kind':'capacity','left_config':a,'right_config':b,'actual_changed_paths':validate_contrast(es[a],es[b],'capacity')})
            for p in POLICIES: pair('capacity',slot(a,p),slot(b,p))
        for arm in ARMS:
            a,b=(f'F2R1-{base}-{arm}-{t}' for t in ARRIVALS)
            contrasts.append({'kind':'release','left_config':a,'right_config':b,'actual_changed_paths':validate_contrast(es[a],es[b],'release')})
            for p in POLICIES: pair('release',slot(a,p),slot(b,p))
        for p in POLICIES:
            cells.append({'base_episode_id':base,'policy':p,
                          'slots':[slot(f'F2R1-{base}-{a}-{t}',p) for a,t in product(ARMS,ARRIVALS)],
                          'cell_order':metric_rules()['four_cell_order'],'metric_rules_ref':'/metric_rules'})
    diagnostic_pairs=[]
    for path in index['diagnostic_files']:
        d=json.loads((ROOT/path).read_text(encoding='utf-8'))
        case=d['case']; eid=Path(path).stem.removesuffix('-'+case)
        if eid not in expected or not eid.endswith('-late') or case not in ('different_arrival','different_request','no_future_request'):
            raise ValueError('diagnostic identity mismatch')
        original_water=next(t for t in es[eid]['task_stream'] if t['task_id']=='water')
        if d['before_ms']!=original_water['release_at_ms'] or len(d['runs'])!=4:
            raise ValueError('diagnostic cutoff mismatch')
        for i,r in enumerate(d['runs']):
            if r['policy']!=POLICIES[i]: raise ValueError('diagnostic policy mismatch')
            sid=f'{eid}|{r["policy"]}|diagnostic:{case}'
            diagnostic_runs.append({'slot_id':sid,'source_path':path,'source_pointer':f'/runs/{i}',
                                    'case':case,'policy':r['policy'],'identity_scope':'isolated_diagnostic_run',
                                    'in_main_service_denominator':False})
            diagnostic_pairs.append({'main_slot':slot(eid,r['policy']),'diagnostic_slot':sid,
                                     'before_ms':d['before_ms'],'comparison':'full_calls_requests_and_decisions_and_events_strict_timestamp_less_than_cutoff',
                                     'performance_pair':False})
    if len(runs)!=32 or len(pairs)!=72 or len(diagnostic_runs)!=48: raise ValueError('plan count mismatch')
    return {'status':'pending_contract_review_not_frozen','version':'F2-statistical-contract-v1-draft',
            'source_sha256':locks,'scope':'8_configurations_32_main_48_diagnostic_not_random_replicates',
            'api_calls':0,'simulator_runs':0,'scores_computed':False,'metric_rules':metric_rules(),
            'configurations':configurations,'runs':runs,'pairs':pairs,'four_cells':cells,
            'contrast_checks':contrasts,'diagnostic_runs':diagnostic_runs,'diagnostic_prefix_pairs':diagnostic_pairs}


if __name__=='__main__':
    print(json.dumps(bundle(),ensure_ascii=True,indent=2))
