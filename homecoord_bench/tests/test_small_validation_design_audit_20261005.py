import unittest
from copy import deepcopy
from unittest.mock import patch
from homecoord_bench.task_revision import small_validation_design_audit_20261005 as a


class SmallValidationDesignAuditTests(unittest.TestCase):
    def test_saved_check_reproducible(self):
        self.assertEqual(a.audit(), a.load('docs/small_validation_plan_v1_20261005/design_check.json'))

    def test_scope_and_separate_checks(self):
        d=a.audit()
        self.assertFalse(d['errors'])
        self.assertEqual((28,28,84,72),(d['configurations_checked'],d['witnesses_checked'],d['slots_checked'],d['pairs_checked']))
        self.assertEqual(28,sum(x['name'].startswith('local_precompletion_arrival_scope:') for x in d['checks']))

    def changed_audit(self, mutation):
        original=a.load
        def reader(path):
            obj=deepcopy(original(path))
            if path==a.PLAN: mutation(obj)
            return obj
        with patch.object(a,'load',side_effect=reader): return a.audit()

    def test_wrong_certificate_caught(self):
        def change(p):p['configurations'][0]['feasibility_certificate']['intervals'][0]['end_ms']+=1
        self.assertTrue(self.changed_audit(change)['errors'])

    def test_missing_pair_caught(self):
        self.assertTrue(self.changed_audit(lambda p:p['pairs'].pop())['errors'])

    def test_illegal_change_caught_by_derived_hash(self):
        def change(p):p['configurations'][1]['value_ms']=123
        self.assertTrue(self.changed_audit(change)['errors'])

    def test_fixed_E_common_K_and_forbidden_summary(self):
        r=a.load(a.RULES)
        self.assertEqual({'main':4,'early':3,'water':1},r['fixed_populations']['denominators'])
        self.assertEqual('same_two_arm_K_intersection_of_valid_completed_requests',r['missing_rules']['time_pair_population'])
        self.assertEqual('both_arms_all_E_else_delta_null',r['missing_rules']['whole_house_pair'])
        self.assertFalse(r['comparison']['own_completed_mean_in_pair_allowlist'])
        self.assertFalse(r['comparison']['cross_config_macro'])

    def test_zero_command_and_baseline_exactness(self):
        r=a.load(a.RULES)
        self.assertEqual([0,100,500],r['logical_clock']['command_latency_levels_ms'])
        self.assertEqual(['state_update_or_completion','task_release','proposal_response','action_start'],
                         r['logical_clock']['queue_order_at_equal_time'])
        b=r['baseline_equivalence']
        self.assertTrue(b['all_fresh_baselines_required'])
        self.assertEqual('none_expected_F2_public_home_identical',b['public_identifier_normalization'])
        self.assertIn('proposal_id',b['fields_never_masked'])
        self.assertIn('trace_events_in_original_order_with_all_fields',b['compare_exact'])

    def test_not_execution_or_external_acceptance(self):
        d=a.audit()
        self.assertFalse(d['contract_frozen'])
        self.assertFalse(d['score_or_policy_execution'])
        self.assertEqual(0,d['simulator_runs'])
        self.assertEqual('author_separate_logic_design_check_not_independent_review',d['status'])


if __name__=='__main__':
    unittest.main()

