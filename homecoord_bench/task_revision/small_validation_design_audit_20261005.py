"""Separate static audit logic; does not import author design/simulator functions."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN = 'docs/small_validation_plan_v1_20261005/plan.json'
RULES = 'docs/small_validation_plan_v1_20261005/execution_statistics_addendum.json'
SOURCE = 'homecoord_bench/task_revision/fixtures/f2_v7/inputs.json'


def load(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def audit():
    plan, rules = load(PLAN), load(RULES)
    episodes = load(SOURCE)['episodes']
    checks = []
    def check(name, ok):
        checks.append({'name': name, 'passed': bool(ok)})
    for p, h in {**plan['source_sha256'], **plan['acceptance_sha256']}.items():
        check('source_hash:'+p, sha(p) == h)
    check('draft_not_executed', not plan['scores_computed'] and plan['simulator_runs'] == plan['api_calls'] == 0)
    check('scope', (len(plan['configurations']), len(plan['run_slots']), len(plan['pairs'])) == (28,84,72))
    config = {c['config_id']: c for c in plan['configurations']}
    slots = {r['slot_id']: r for r in plan['run_slots']}
    check('unique_config_slot', len(config) == 28 and len(slots) == 84)
    expected_settings = {('baseline',0),('water_budget_offset_ms',-30000),('water_budget_offset_ms',30000),
                         ('water_release_offset_ms',-30000),('water_release_offset_ms',30000),
                         ('command_latency_ms',0),('command_latency_ms',500)}
    derived = {}
    for c in plan['configurations']:
        idx = int(c['source_pointer'].split('/')[-1])
        source = episodes[idx]
        check('pointer:'+c['config_id'], source['episode_id'] == c['source_episode_id'])
        e = deepcopy(source); water = next(t for t in e['task_stream'] if t['task_id'] == 'water')
        before_budget = water['completion_deadline_ms']-water['release_at_ms']
        f, value = c['factor'], c['value_ms']
        if f == 'water_budget_offset_ms':
            water['completion_deadline_ms'] = water['release_at_ms']+before_budget+value
            water['goal'] = water['goal'].replace('within '+str(before_budget)+' ms', 'within '+str(before_budget+value)+' ms')
        elif f == 'water_release_offset_ms':
            water['release_at_ms'] += value
            water['completion_deadline_ms'] = water['release_at_ms']+before_budget
            e['exogenous_events'][0]['at_ms'] = water['release_at_ms']
        elif f == 'command_latency_ms':
            e['simulation']['command_latency_ms'] = value
        else:
            check('known_factor:'+c['config_id'], f == 'baseline' and value == 0)
        update = next(x for x in e['exogenous_events'][0]['patch']['coordination_context']['requests'] if x['task_id'] == 'water')
        update['release_at_ms'] = water['release_at_ms']; update['deadline_ms'] = water['completion_deadline_ms']
        derived[c['config_id']] = e
        check('derived_hash:'+c['config_id'], hashlib.sha256(json.dumps(e,sort_keys=True,ensure_ascii=True).encode()).hexdigest() == c['derived_episode_sha256'])
        req = [{'task_id':t['task_id'],'release_ms':t['release_at_ms'],'deadline_ms':t['completion_deadline_ms'],
                'own_budget_ms':t['completion_deadline_ms']-t['release_at_ms']} for t in e['task_stream']]
        check('static_requests:'+c['config_id'], req == c['required_requests'])
        check('initial_public_early_only:'+c['config_id'], len(e['initial_state']['values']['coordination_context']['requests']) == 3 and
              all(x['task_id'] != 'water' for x in e['initial_state']['values']['coordination_context']['requests']))
        check('costs_unchanged:'+c['config_id'], e['public_devices'] == source['public_devices'] and
              e['action_grounding'] == source['action_grounding'] and e['tool_catalog'] == source['tool_catalog'])
        cert = c['feasibility_certificate']; xs = cert['intervals']
        tasks = {t['task_id']:t for t in e['task_stream']}
        ground = {g['task_id']:g for g in e['action_grounding'] if g['operation']=='prepare'}
        earliest_early_end = min(t['release_at_ms']+300+e['simulation']['command_latency_ms']+
                                 ground[t['task_id']]['duration_ms']
                                 for t in e['task_stream'] if t['release_at_ms']==0)
        check('local_precompletion_arrival_scope:'+c['config_id'], water['release_at_ms'] < earliest_early_end)
        valid = len(xs)==4 and {x['task_id'] for x in xs}==set(tasks)
        for x in xs:
            t,g=tasks[x['task_id']],ground[x['task_id']]
            valid &= x['end_ms']-x['start_ms']==g['duration_ms'] and x['units']==g['power_kw']
            valid &= x['start_ms']>=t['release_at_ms']+300+e['simulation']['command_latency_ms']
            valid &= x['end_ms']<=t['completion_deadline_ms']
        for point in sorted({x['start_ms'] for x in xs}|{x['end_ms'] for x in xs}):
            valid &= sum(x['units'] for x in xs if x['start_ms']<=point<x['end_ms'])<=e['home']['resources']['max_power_kw']
        check('separate_witness_check:'+c['config_id'], valid)
    for source_id in sorted({c['source_episode_id'] for c in config.values()}):
        cs=[c for c in config.values() if c['source_episode_id']==source_id]
        check('complete_fixed_grid:'+source_id, {(c['factor'],c['value_ms']) for c in cs}==expected_settings)
    expected_pairs = set()
    policies = set(rules['expected_scope']['policies'])
    for c in config.values():
        actual={s['policy'] for s in slots.values() if s['config_id']==c['config_id']}
        check('policies:'+c['config_id'], actual==policies)
        if c['factor']!='baseline':
            for policy in policies:
                expected_pairs.add((c['source_episode_id']+'|SV1|baseline:0|'+policy,c['config_id']+'|'+policy,c['factor']))
    actual_pairs={(p['left'],p['right'],p['factor']) for p in plan['pairs']}
    check('exact_pair_set', actual_pairs==expected_pairs and len(actual_pairs)==72)
    check('pair_endpoints_and_direction', all(p['left'] in slots and p['right'] in slots and p['delta_direction']=='right_minus_left' for p in plan['pairs']))
    check('negative_capacity_controls', sum(c['capacity_units']==6 for c in config.values())==14)
    check('baseline_count', sum(config[s['config_id']]['factor']=='baseline' for s in slots.values())==12)
    check('fixed_E_and_nulls', rules['fixed_populations']['denominators']=={'main':4,'early':3,'water':1} and
          rules['missing_rules']['empty_K']=='retain_pair_metrics_null_no_common_completed_requests')
    check('no_forbidden_metrics', 'conditional_timely_rate' not in rules['paired_scalar_allowlist'] and
          not rules['comparison']['cross_config_macro'] and not rules['comparison']['factorial_interactions'])
    check('baseline_exact_events_calls', 'trace_events_in_original_order_with_all_fields' in rules['baseline_equivalence']['compare_exact'] and
          'calls_including_complete_request_and_decision' in rules['baseline_equivalence']['compare_exact'] and
          'timestamp_ms' in rules['baseline_equivalence']['fields_never_masked'])
    return {'status':'author_separate_logic_design_check_not_independent_review','date':'2026-10-05',
            'checks':checks,'errors':[c for c in checks if not c['passed']],
            'configurations_checked':28,'witnesses_checked':28,'slots_checked':84,'pairs_checked':72,
            'score_or_policy_execution':False,'api_calls':0,'simulator_runs':0,'contract_frozen':False,
            'reviewed_sha256':{p:sha(p) for p in [PLAN,RULES,'docs/SMALL_VALIDATION_PLAN_V1_2026-10-05.md',
                'homecoord_bench/task_revision/small_validation_plan_v1.py','homecoord_bench/tests/test_small_validation_plan_v1.py']}}


if __name__=='__main__':
    print(json.dumps(audit(),ensure_ascii=True,indent=2))
