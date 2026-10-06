import json,hashlib,unittest
from homecoord_bench.task_revision.acceptance_ledger import build,ROOT,OUT
class AcceptanceLedgerTests(unittest.TestCase):
    def test_seven_scoped_groups_not_seven_independent_structures(self):
        r=build()[OUT+'/registry.json'];self.assertEqual(7,len(r['groups']))
        self.assertTrue(r['family_group_count_is_not_structure_count'])
        self.assertFalse(r['performance_aggregation_computed'])
        self.assertTrue(all(not g['independent_dual_review'] and g['aggregation_acceptance'] is None and not g['model_comparison_authorized'] for g in r['groups']))
    def test_c4_replacement_no_duplicate_validation_samples(self):
        r=build()[OUT+'/registry.json']['replacement']
        self.assertEqual(96,r['effective_original_cohort_runs']);self.assertTrue(r['do_not_add_targeted_28_as_new_samples'])
        self.assertIn('v10',r['replacement_source'])
    def test_infeasible_and_terminal_cases_not_success_denominator(self):
        r=build()[OUT+'/registry.json'];c={x['episode_id']:x for x in r['configurations'] if x['family']=='dependency'}
        self.assertEqual('infeasible_pressure_excluded',c['DEP11-INFEASIBLE_8000']['role'])
        for k in ('CANCEL_NO_RESTORE','CANCEL_RESTORE','RESTART_NO_RESTORE','INVALID_PROPOSAL'):
            self.assertEqual('lifecycle_or_invalid_proposal_diagnostic',c['DEP11-'+k]['role'])
        self.assertEqual('feasible_adversarial_correctness_control',c['DEP11-FORGED_STATE']['role'])
    def test_policy_and_answer_hint_limitations_preserved(self):
        g={x['family']:x for x in build()[OUT+'/registry.json']['groups']}
        self.assertIn('action_template',g['C1']['model_input_warning'])
        self.assertIn('ConstraintCoordinator only',g['C3-F3']['diagnostic_policy_scope'])
        self.assertIn('ConstraintCoordinator only',g['C2']['policy_scope'])
    def test_ledger_reproduces_and_evidence_files_locked(self):
        b=build()
        for p,v in b.items():self.assertEqual(v,json.loads((ROOT/p).read_text(encoding='utf-8')))
        l=b[OUT+'/evidence_locks.json']
        for group in ('relative_artifact_sha256','source_sha256'):
            for p,h in l[group].items():self.assertEqual(h,hashlib.sha256((ROOT/p).read_bytes()).hexdigest())
if __name__=='__main__':unittest.main()
