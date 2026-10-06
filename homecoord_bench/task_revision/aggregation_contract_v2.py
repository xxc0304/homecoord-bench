"""Proposed F3 aggregation contract metadata only; no metric calculations."""
import json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT='docs/aggregation_contract_v2_20261003'
POLICIES=('IndependentMultiAgent','ConstraintCoordinator','DeadlineAwareCoordinator','GateRetryRule')
SELECTORS=('low_resource','short_duration','capacity_pressure')
def read(p):return json.loads((ROOT/p).read_text(encoding='utf-8'))
def digest(p):return hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
def serialize(v):return json.dumps(v,ensure_ascii=False,indent=2)+'\n'
def service_rate_boundary(required, completed, on_time):
    """Count-only contract reference, not an event adapter or run aggregator."""
    if any(type(n) is not int for n in (required, completed, on_time)) or not 0 <= on_time <= completed <= required:
        raise ValueError('invalid service coverage counts')
    def field(value, status):
        return {'value':value,'status':status,'required':required,'completed':completed,'on_time':on_time}
    if required == 0:
        return {k:field(None,'no_eligible_requests') for k in ('service_completion_rate','timely_service_rate','timely_among_completed')}
    return {'service_completion_rate':field(completed/required,'ok'),
            'timely_service_rate':field(on_time/required,'ok'),
            'timely_among_completed':field(on_time/completed,'ok') if completed else field(None,'no_completed_requests')}
def build():
    prefix='homecoord_bench/task_revision/fixtures/f3_v8/'
    inp=read(prefix+'inputs.json');episodes={e['episode_id']:e for e in inp['episodes']}
    idx=read(prefix+'index.json');slots=[];lookup={};sources={}
    for role,paths in [('primary',idx['run_files']),('diagnostic',idx['diagnostic_files'])]:
        for path in paths:
            data=read(path);sources[path]=digest(path)
            for n,r in enumerate(data['runs']):
                eid=r['evaluation_episode_id'];e=episodes[eid]
                slot='F3|v8|'+eid+'|'+r['policy']+'|'+r['selector']+'|'+(r['diagnostic'] or 'primary')
                row={'canonical_slot_id':slot,'family':'C3-F3','source_version':'v8',
                     'source_path':path,'source_row_pointer':f'/runs/{n}','source_sha256':sources[path],
                     'base_world_id':e['evaluation_world_id'],'config_id':eid,'policy':r['policy'],
                     'selector':r['selector'],'diagnostic_id':r['diagnostic'],'role':role,
                     'capability_kind':e['mode_capability']['kind'],
                     'authorized_modes_by_task':e['mode_capability']['authorized_modes_by_task'],
                     'requests':[{'task_id':t['task_id'],'release_at_ms':t['release_at_ms'],'deadline_ms':t['completion_deadline_ms']} for t in e['task_stream']],
                     'return_order_id':'declared_v8_provider_latency_contract',
                     'observation_end_contract':'v8_queue_drained_no_cross_horizon_pool',
                     'cost_unit':'synthetic_resource_unit_ms',
                     'metric_eligibility':'all_declared_required_services' if role=='primary' else 'diagnostic_only'}
                slots.append(row)
                if role=='primary':lookup[(eid,r['policy'],r['selector'])]=slot
    assert len(slots)==224 and len({x['canonical_slot_id'] for x in slots})==224
    worlds=sorted({x['base_world_id'] for x in slots})
    pairs=[];factorial=[]
    for w in worlds:
        fixed=sorted([e for e in episodes.values() if e['evaluation_world_id']==w and e['mode_capability']['kind']=='fixed'],key=lambda e:e['episode_id'])
        selected=next(e for e in episodes.values() if e['evaluation_world_id']==w and e['mode_capability']['kind']=='selectable')
        def key(e,p,q='low_resource'):return lookup[(e['episode_id'],p,q)]
        for e in fixed:
            for p in POLICIES[1:]:
                pairs.append({'contrast_type':'fixed_mode_scheduling','world':w,'candidate':key(e,p),'control':key(e,POLICIES[0]),'direction':'candidate_minus_control'})
        for p in POLICIES:
            for q in SELECTORS[1:]:
                pairs.append({'contrast_type':'selectable_selector','world':w,'candidate':key(selected,p,q),'control':key(selected,p),'direction':'candidate_minus_control'})
        eco=next(e for e in fixed if all(v!=['fast'] for v in e['mode_capability']['authorized_modes_by_task'].values()))
        fast=next(e for e in fixed if all(v!=['eco'] for v in e['mode_capability']['authorized_modes_by_task'].values()))
        for p in POLICIES[1:]:
            factorial.append({'world':w,'baseline_policy':POLICIES[0],'candidate_policy':p,
                'baseline_vector_source':'fixed_eco; predefined low_resource rule',
                'candidate_vector_source':'fixed_fast; predefined short_duration rule',
                'Y00':key(eco,POLICIES[0]),'Y10':key(eco,p),'Y01':key(fast,POLICIES[0]),'Y11':key(fast,p),
                'role':'primary' if p=='ConstraintCoordinator' else 'predeclared_sensitivity'})
    replacement=[]
    legacy=read(prefix+'contrasts.json')
    for x in legacy['mode_matched_controls']:
        selected=next(e for e in episodes.values() if e['evaluation_world_id']==x['world'] and e['mode_capability']['kind']=='selectable')
        pairs.append({'contrast_type':'mode_matched_control','world':x['world'],
            'candidate':lookup[(selected['episode_id'],x['policy'],x['selector'])],
            'control':lookup[(x['matched_fixed_episode'],x['policy'],'low_resource')],
            'planned_vector_from_reviewed_v8_control':x['selected_vector'],
            'requires_exact_complete_actual_vector_recheck':True,'capability_contract_differs':True,
            'direction':'candidate_minus_control'})
    for x in legacy['same_policy_mode_selection']:
        selected=next(e for e in episodes.values() if e['evaluation_world_id']==x['world'] and e['mode_capability']['kind']=='selectable')
        pairs.append({'contrast_type':'capability_and_selection_intervention','world':x['world'],
            'candidate':lookup[(selected['episode_id'],x['policy'],x['selector'])],
            'control':lookup[(x['fixed_control'],x['policy'],'low_resource')],
            'capability_contract_differs':True,'direction':'candidate_minus_control'})
    old='homecoord_bench/task_revision/fixtures/c4_v9/diagnostics/C4R1-CLEAN-LATE-late_natural_race.json'
    new='homecoord_bench/task_revision/fixtures/c4_v10/runs/late_race.json'
    for i,p in enumerate(POLICIES):
        assert read(old)['runs'][i]['policy']==read(new)['runs'][i]['policy']==p
        replacement.append({'canonical_slot_id':'C4|original-v9|C4R1-CLEAN-LATE-late_natural_race|'+p,
            'old_source':{'version':'v9','path':old,'row_pointer':f'/runs/{i}','sha256':digest(old),'valid_for_scores':False},
            'effective_source':{'version':'v10','path':new,'row_pointer':f'/runs/{i}','sha256':digest(new)},
            'role':'diagnostic','aggregation_scope':'out_of_current_F3_scope'})
    common=['base_world_id','required_service_set','release_deadline_contract','public_observation_schema','provider_latency_contract','physical_service_cost_contract','observation_end_contract']
    for pair in pairs:
        kind=pair['contrast_type']
        extra={'fixed_mode_scheduling':['unique_predeclared_fixed_authorization','all_started_actions_match_authorization'],
               'selectable_selector':['policy','selectable_authorization'],
               'mode_matched_control':['policy','complete_actual_mode_vector'],
               'capability_and_selection_intervention':['policy']}[kind]
        changes={'fixed_mode_scheduling':['policy','architecture_identity'],
                 'selectable_selector':['selector','selected_mode_vector'],
                 'mode_matched_control':['capability_contract','selection_opportunity'],
                 'capability_and_selection_intervention':['capability_contract','selector','selected_mode_vector']}[kind]
        pair.update({'fixed_fields':common+extra,'allowed_differences':changes,
                     'primary_metric':'timely_service_rate_with_static_required_request_denominator',
                     'secondary_metrics':['service_completion_rate','all_service_completion_ms','individual_wait_and_tardiness','observed_cost_delta','matched_service_cost_saving']})
        if kind=='fixed_mode_scheduling':
            pair['primary_pair_qualification']={'requires_complete_actual_vector':False,'retain_not_started_requests_and_pairs':True,'match_on':'unique_predeclared_authorized_vector','validate_all_started_actions_against_authorization':True}
    return {OUT+'/run_inventory.json':{'status':'proposed_contract_pending_review','analysis_scope':'F3_v8_only',
        'all_other_families':'out_of_scope_until_own_run_manifests_reviewed','slots':slots,
        'metric_calculation_implemented':False,'source_sha256':sources},
        OUT+'/pair_plan.json':{'status':'proposed_no_differences_computed','pairs':pairs,'factorial_cells':factorial,
            'rate_boundary_rule':'empty E: all rates null/no_eligible_requests; nonempty E and zero completed: main rates 0/ok, conditional timely null/no_completed_requests',
            'qualification_is_per_metric':True,
            'mode_matched_rule':'resolve only exact complete actual vectors; capability changes explicit; never nearest or partial vector',
            'capability_intervention_rule':'legacy 192 selectable-vs-fixed contrasts separate from pure selector differences',
            'primary_world_weight':'1/8 each; no policy/selector/replay inflation; no significance tests'},
        OUT+'/c4_replacement_map.json':{'mapping':replacement,'original_cohort_slots':96,
            'ordinary_success_denominator_is_not_96':True,'targeted_extra_24_role':'validation_only',
            'aggregation_implemented':False}}
if __name__=='__main__':
    import sys
    b=build();print(json.dumps(list(b) if len(sys.argv)==1 else serialize(b[sys.argv[1]]),ensure_ascii=True))
