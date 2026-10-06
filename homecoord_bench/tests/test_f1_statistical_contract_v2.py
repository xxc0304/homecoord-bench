import json
import unittest
from copy import deepcopy

from homecoord_bench.task_revision.f1_statistical_contract_v1 import ROOT, bundle as v1_bundle
from homecoord_bench.task_revision.f1_statistical_contract_v2 import (
    OUT, CELL_ORDER, MAIN_RATES, analysis_population, bundle, metric_rules,
)


class F1CorrectionTests(unittest.TestCase):
    def cells(self, *sets):
        return dict(zip(CELL_ORDER, sets))

    def test_saved_plan_and_prior_identity_unchanged(self):
        old, new = v1_bundle(), bundle()
        self.assertEqual(new, json.loads((ROOT / OUT).read_text(encoding='utf-8')))
        for key in ('source_sha256', 'configurations', 'runs', 'pairs', 'contrast_checks'):
            self.assertEqual(old[key], new[key])
        groups = deepcopy(new['four_cells'])
        for g in groups:
            g.pop('metric_rules_ref'); g.pop('population_ref')
        self.assertEqual(old['four_cells'], groups)
        self.assertFalse(new['scores_computed'])
        self.assertEqual('pending_contract_review_not_frozen', new['status'])

    def test_counterexample_uses_same_four_cell_population(self):
        E = ['a', 'b']; C = self.cells(['a'], E, E, E)
        p = analysis_population(E, C)
        self.assertEqual(['a'], p['common_task_ids'])
        self.assertEqual(2, p['required_count'])
        self.assertEqual(0.5, p['coverage'])
        values = {'a': 100, 'b': 1000}
        means = [sum(values[t] for t in p['common_task_ids']) / p['common_count'] for _ in CELL_ORDER]
        self.assertEqual(0, (means[3]-means[1])-(means[2]-means[0]))
        # Main service denominators remain E, not K. This is synthetic, not scoring source runs.
        self.assertEqual([0.5, 1, 1, 1], [len(C[c])/p['required_count'] for c in CELL_ORDER])
        self.assertEqual(['tight_base'], p['excluded_tasks'][0]['not_completed_cells'])
        self.assertFalse(p['all_E_completed_in_all_four_cells'])

    def test_empty_four_way_intersection_stays_ineligible(self):
        p = analysis_population(['a', 'b'], self.cells(['a'], ['b'], ['a'], ['b']))
        self.assertFalse(p['eligible'])
        self.assertEqual('no_common_completed_requests', p['null_reason'])
        self.assertEqual([], p['common_task_ids'])
        self.assertEqual(2, p['required_count'])
        self.assertEqual(0, p['coverage'])

    def test_two_pair_intersections_cannot_replace_four_way(self):
        p = analysis_population(['a', 'b'], self.cells(['a'], ['a'], ['b'], ['b']))
        self.assertEqual([], p['common_task_ids'])
        self.assertFalse(p['eligible'])

    def test_full_completion_and_order(self):
        E = ['b', 'a']; p = analysis_population(E, self.cells(['a', 'b'], E, E, E))
        self.assertEqual(E, p['common_task_ids'])
        self.assertTrue(p['all_E_completed_in_all_four_cells'])
        self.assertEqual(1, p['coverage'])
        self.assertIsNone(p['null_reason'])
        self.assertEqual([], p['excluded_tasks'])

    def test_all_zero_completion(self):
        p = analysis_population(['a'], self.cells([], [], [], []))
        self.assertEqual(1, p['required_count'])
        self.assertFalse(p['eligible'])
        self.assertEqual(4, len(p['excluded_tasks'][0]['not_completed_cells']))

    def test_missing_cell_duplicate_or_unknown_request_is_error(self):
        cases = [(['a'], {}), (['a', 'a'], self.cells([], [], [], [])),
                 ([], self.cells([], [], [], [])),
                 (['a'], self.cells(['a', 'a'], [], [], [])),
                 (['a'], self.cells(['x'], [], [], []))]
        for E, C in cases:
            with self.subTest(E=E, C=C), self.assertRaises(ValueError):
                analysis_population(E, C)

    def test_conditional_rates_and_own_means_excluded(self):
        r = metric_rules()
        self.assertFalse(r['conditional_timely_rate']['four_cell_interaction'])
        self.assertFalse(r['conditional_timely_rate']['template_macro_aggregation'])
        self.assertFalse(r['completed_only_means_on_each_cells_own_C']['four_cell_interaction'])
        self.assertEqual(list(MAIN_RATES), r['template_macro']['metrics'])
        self.assertFalse(r['template_macro']['skip_null_or_missing_slots'])
        self.assertTrue(r['whole_house_completion']['never_use_K_as_E'])

    def test_metric_rules_attached_to_all_groups(self):
        p = bundle()
        self.assertEqual(18, len(p['four_cells']))
        self.assertTrue(all(g['metric_rules_ref'] == '/metric_rules' for g in p['four_cells']))
        self.assertEqual('null: no_common_completed_requests', p['metric_rules']['cohort']['empty_K'])
        self.assertEqual('data_error_not_drop_task_not_zero', p['metric_rules']['cohort']['missing_metric_on_K'])


if __name__ == '__main__':
    unittest.main()
