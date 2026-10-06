"""Metadata-only reviewed-scope ledger; never computes pooled strategy scores."""
import json,hashlib
from pathlib import Path
from homecoord_bench.task_revision.publication_redaction import original_source_sha256
ROOT=Path(__file__).resolve().parents[2]
OUT='docs/acceptance_ledger_20261003'
REVIEW_PREFIX='docs/review_evidence/2026-10-01_to_2026-10-06'
REVIEW_BASE=ROOT/REVIEW_PREFIX
SPECS=[
 ('C1','v6','protection_v6_inputs.json','C1_V6_TARGETED_REVIEW_20261002.md',8,32,16),
 ('C3-F1','phase_b_legacy','PHASE_B','PHASE_B_REVIEW_20261002.md',8,72,0),
 ('C3-F2','v7','f2_v7/inputs.json','F2_V7_REVIEW_20261002.md',8,32,48),
 ('C3-F3','v8','f3_v8/inputs.json','F3_V8_REVIEW_20261002.md',32,192,32),
 ('C4','v9_valid_plus_v10_replacement','c4_v9/inputs.json','C4_V10_TARGETED_REVIEW_20261003.md',14,56,40),
 ('dependency','v11','dependency_v11/inputs.json','DEPENDENCY_V11_REVIEW_20261003.md',13,52,0),
 ('C2','v12','room_v12/inputs.json','C2_V12_REVIEW_20261003.md',24,24,8)]
def read(p):return json.loads((ROOT/p).read_text(encoding='utf-8'))
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def build():
    groups=[];configs=[];locks={}
    for family,version,input_name,review_name,count,main,diag in SPECS:
        if input_name=='PHASE_B':
            input_path='docs/implementation_review_20261001/index.json'
            entries=[x for x in read(input_path)['entries'] if x['episode_id'].startswith('D-F1-')]
            episodes=[read(x['path'])['episode'] for x in entries]
            for x in entries:locks[x['path']]=digest(ROOT/x['path'])
        else:
            input_path='homecoord_bench/task_revision/fixtures/'+input_name
            episodes=read(input_path)['episodes']
        assert len(episodes)==count
        locks[input_path]=digest(ROOT/input_path)
        report=REVIEW_BASE/review_name
        assert report.is_file()
        review_rel=f'{REVIEW_PREFIX}/{review_name}'
        group={'family':family,'effective_version':version,'configuration_count':count,
               'reviewed_primary_runs':main,'diagnostic_or_counterfactual_runs':diag,
               'review_status':'accepted_in_submitted_scope_single_model',
               'independent_dual_review':False,'aggregation_acceptance':None,
               'model_comparison_authorized':False,
               'review_record':{'relative_path':review_rel,'sha256':digest(report),
                               'source_sha256':original_source_sha256(review_rel),
                               'portability':'bundled public copy; path-only redactions are recorded in the publication manifest'},
               'input_path':input_path}
        if family=='C1':group['model_input_warning']='reviewed scripted requests contain action_template and required_action; require answer-free preflight'
        if family=='C3-F1':group['model_input_warning']='legacy three policies and three proposal-return orders; input/latency normalization not covered by new model evaluation'
        if family=='C3-F3':group['diagnostic_policy_scope']='ConstraintCoordinator only; fixed/selectable not independent task structures'
        if family=='C4':
            group['original_invalid_runs']=4;group['valid_original_runs']=92;group['replacement_runs']=4
            group['targeted_validation_runs']=28;group['targeted_validation_not_extra_samples']=True
            v9_path=REVIEW_BASE/'C4_V9_REVIEW_20261003.md'
            v9_rel=f'{REVIEW_PREFIX}/C4_V9_REVIEW_20261003.md'
            group['v9_design_and_partial_review']={'relative_path':v9_rel,'sha256':digest(v9_path),'source_sha256':original_source_sha256(v9_rel)}
        if family=='C2':group['policy_scope']='ConstraintCoordinator only, two trusted-controller admission arms; 12 parameter worlds'
        groups.append(group)
        for e in episodes:
            eid=e['episode_id'];role='reviewed_primary'
            denominator='family_specific_not_pooled'
            if family=='C1':
                role='legality_pair_not_equal_time_budget' if '-legality-' in eid else 'equal_response_budget_pair'
                denominator='admission_and_protection_separate_from_valid_admitted_service_completion'
            if family=='C3-F1':denominator='constructively_feasible_legacy_configs_per_policy_and_return_order'
            if family=='C3-F2':denominator='constructively_feasible_configs_per_policy; counterfactuals_separate'
            if family=='C3-F3':denominator='within_world_and_capability; mode_choice_and_scheduling_separate'
            if family=='C4':
                k=e['c4_scene'];w=e['nominal_window']
                denominator='withdrawal_separate_no_unconditional_all_service_rate' if k=='RAIN' and w in ('EARLY','MID','LATE') else 'scene_specific_service_and_exposure_separate'
            if family=='dependency':
                condition=eid.removeprefix('DEP11-')
                kind=read('homecoord_bench/task_revision/fixtures/dependency_v11/certificates.json')[condition]['kind']
                if condition=='INFEASIBLE_8000':role='infeasible_pressure_excluded';denominator='not_feasible_success_denominator'
                elif condition in ('CANCEL_NO_RESTORE','CANCEL_RESTORE','RESTART_NO_RESTORE','INVALID_PROPOSAL'):
                    role='lifecycle_or_invalid_proposal_diagnostic';denominator='withdrawal_pending_blocked_not_unconditional_all_service'
                elif condition in ('FORGED_STATE','STALE_NATURAL_RACE'):
                    role='feasible_adversarial_correctness_control';denominator='separate_correctness_subset_not_normal_success_pool'
                else:denominator='feasible_single_batch_contract; compare_within_matched_subset'
            if family=='C2':denominator='environment_24_primary_runs_only; 12_world_pairs; command_and_disposition_separate'
            configs.append({'family':family,'version':version,'episode_id':eid,'role':role,
                            'denominator_rule':denominator,'aggregation_acceptance':None})
    extra_paths=['homecoord_bench/results/protection_v6_offline_20261002.json',
                 'homecoord_bench/task_revision/fixtures/protection_v6_manifest.json',
                 'docs/implementation_review_20261001/manifest.json',
                 'homecoord_bench/task_revision/fixtures/c4_v10/runs/late_race.json',
                 'homecoord_bench/task_revision/fixtures/c4_v10/regression.json']
    for folder in ('f2_v7','f3_v8','c4_v9','c4_v10','dependency_v11','room_v12'):
        extra_paths+=['homecoord_bench/task_revision/fixtures/'+folder+'/'+p.name for p in
                      (ROOT/'homecoord_bench/task_revision/fixtures'/folder).glob('*.json')]
    for p in sorted(set(extra_paths)):locks[p]=digest(ROOT/p)
    c1=read('homecoord_bench/results/protection_v6_offline_20261002.json')
    assert len(c1['runs'])==32 and len(c1['diagnostics'])==16
    hint_fields=set(c1['runs'][0]['trace']['agent_requests'][0]['task'])&{'action_template','required_action'}
    assert hint_fields=={'action_template','required_action'}
    old=read('homecoord_bench/task_revision/fixtures/c4_v9/diagnostics/C4R1-CLEAN-LATE-late_natural_race.json')
    new=read('homecoord_bench/task_revision/fixtures/c4_v10/runs/late_race.json')
    assert len(old['runs'])==len(new['runs'])==4
    replacement={'invalid_source':'homecoord_bench/task_revision/fixtures/c4_v9/diagnostics/C4R1-CLEAN-LATE-late_natural_race.json',
        'invalid_selector':'runs[0..3]','replacement_source':'homecoord_bench/task_revision/fixtures/c4_v10/runs/late_race.json',
        'replacement_selector':'runs[0..3]','scope':'four matching policies; original scores invalid, no retroactive acceptance',
        'effective_original_cohort_runs':96,'formula':'92 valid v9 originals + 4 v10 replacements',
        'do_not_add_targeted_28_as_new_samples':True}
    registry={'date':'2026-10-03','kind':'metadata_only_author_ledger_pending_review',
        'family_group_count_is_not_structure_count':True,'performance_aggregation_computed':False,
        'aggregation_acceptance':None,'api_calls':0,'holdout_runs':0,'groups':groups,
        'configurations':configs,'replacement':replacement,
        'superseded':{'C1_v5':'information leakage and mixed disposition metric; use v6 scoped fields',
            'C4_v9_four_clean_race_runs':'invalid; use only v10 correction',
            'dependency_v3':'historical five approved configs; v11 is current revised scope; no duplicate cohort',
            'C2_v4':'historical physics/interface reference, not demand-aware task acceptance'}}
    return {OUT+'/registry.json':registry,OUT+'/evidence_locks.json':{'relative_artifact_sha256':locks,
        'review_sources':{g['family']:g['review_record'] for g in groups},'source_sha256':{
            p:digest(ROOT/p) for p in ('homecoord_bench/task_revision/acceptance_ledger.py','homecoord_bench/tests/test_acceptance_ledger.py')},
        'acceptance':None}}
if __name__=='__main__':
    import sys
    b=build();print(json.dumps(list(b) if len(sys.argv)==1 else json.dumps(b[sys.argv[1]],ensure_ascii=False,indent=2)+'\n',ensure_ascii=True))
