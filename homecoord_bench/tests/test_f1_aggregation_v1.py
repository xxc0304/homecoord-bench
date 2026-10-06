import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from homecoord_bench.task_revision.f1_aggregation_v1 import (
    ROOT, FREEZE, OUT, EvidenceError, recount, compare_cells, compare_pair, macro, bundle, serialize,
)
from homecoord_bench.task_revision.f1_statistical_contract_v2 import CELL_ORDER, metric_rules


class F1AggregationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = json.loads((ROOT / 'docs/implementation_review_20261001/traces/D-F1-01-competition-base.json').read_text(encoding='utf-8'))
        cls.data = bundle()

    def first(self):
        return deepcopy(self.source['episode']), deepcopy(self.source['runs'][0])

    def empty_run(self):
        e, r = self.first()
        r['trace']['events'] = [x for x in r['trace']['events'] if x['type'] in ('task_released', 'proposal_returned')]
        r['trace']['event_count'] = len(r['trace']['events'])
        r['trace']['final_state'] = deepcopy(e['initial_state']['values'])
        r['trace']['final_state_version'] = e['initial_state']['version']
        return e, r

    def hypothetical_rows(self, completed):
        E = ['a', 'b']; rows = {}
        for cell, C in zip(CELL_ORDER, completed):
            metrics = {m: 0 for m in metric_rules()['four_cell_allowlist']['run_event_or_process']}
            metrics.update(service_rate=len(C)/2, timely_service_rate=len(C)/2,
                           whole_house_completion_ms=1000 if set(C) == set(E) else None)
            rows[cell] = {'required_task_ids': E, 'completed_task_ids': list(C), 'metrics': metrics,
                          'tasks': {t: {m: {'a': 100, 'b': 1000}[t] for m in
                                    metric_rules()['four_cell_allowlist']['same_four_cell_completed_population']} for t in C}}
        return rows

    def test_saved_results_exact_reproduction(self):
        for path, obj in self.data.items():
            self.assertEqual(serialize(obj), (ROOT / path).read_text(encoding='utf-8'))

    def test_scope_counts_and_fixed_weights(self):
        s = self.data[f'{OUT}/summary.json']
        self.assertEqual((72, 168, 18), (s['runs'], s['pairs'], s['four_cells']))
        self.assertIsNone(s['adapter_acceptance'])
        for p in s['template_macro'].values():
            self.assertEqual('1/2', p['template_weight'])
            self.assertEqual(2, len(p['templates']))
            for t in p['templates'].values():
                self.assertEqual(12, len(t['slot_weights']))
                self.assertTrue(all(r['weight'] == '1/12' for r in t['slot_weights']))
                self.assertEqual({'service_rate', 'timely_service_rate'}, set(t['rates']))

    def test_reported_scores_never_used(self):
        e, r = self.first(); a = recount(e, r)
        r['reported_result'] = {'all_tasks_served': 'invented'}
        r['independent_event_recount'] = None
        r['historical_comparison'] = 'bad'
        self.assertEqual(a, recount(e, r))

    def test_necessary_queue_and_real_receipt(self):
        e, r = self.first(); x = recount(e, r)
        t = x['tasks']['dishes']
        self.assertEqual(181200, t['start_ms'])
        self.assertEqual(481200, t['completion_ms'])
        self.assertTrue(t['timely'])
        self.assertEqual(1, x['metrics']['service_rate'])
        self.assertEqual(1, x['metrics']['action_rejected_count'])
        self.assertEqual(0, x['metrics']['executed_capacity_violation_duration_ms'])
        self.assertIsNone(x['coordination_compute_ms'])
        self.assertIsNone(x['API_wallclock_ms'])

    def test_zero_completion_keeps_E_and_null(self):
        e, r = self.empty_run(); x = recount(e, r)
        self.assertEqual(3, x['denominators']['required'])
        self.assertEqual(0, x['metrics']['service_rate'])
        self.assertEqual(0, x['metrics']['timely_service_rate'])
        self.assertIsNone(x['auxiliary']['conditional_timely_rate'])
        self.assertEqual('no_completed_requests', x['auxiliary']['conditional_timely_null_reason'])
        self.assertTrue(all(t['completion_latency_ms'] is None and not t['completed'] for t in x['tasks'].values()))
        self.assertIsNone(x['metrics']['whole_house_completion_ms'])

    def test_reservation_only_does_not_start_or_complete(self):
        e, r = self.empty_run()
        original = self.source['runs'][0]['trace']['events']
        r['trace']['events'] = [deepcopy(x) for x in original if x['type'] in ('task_released','proposal_returned','action_reserved')]
        r['trace']['event_count'] = len(r['trace']['events'])
        x = recount(e, r)
        self.assertGreater(x['metrics']['reservation_count'], 0)
        self.assertEqual(0, x['metrics']['actual_start_count'])
        self.assertEqual(0, x['metrics']['service_rate'])

    def test_forged_final_state_and_missing_receipt_are_data_errors(self):
        e, r = self.empty_run(); r['trace']['final_state']['devices']['laundry_device'] = 'complete'
        with self.assertRaises(EvidenceError): recount(e, r)
        e, r = self.first()
        r['trace']['events'] = [x for x in r['trace']['events'] if not (x['type'] == 'action_completed' and x['task_id'] == 'laundry')]
        r['trace']['event_count'] = len(r['trace']['events'])
        with self.assertRaises(EvidenceError): recount(e, r)

    def test_receipt_identity_and_time_tampering_rejected(self):
        for key, value in (('proposal_id', 'forged'), ('agent_id', 'bad'), ('task_id', 'dishes'),
                           ('target', 'bad'), ('operation', 'off'), ('timestamp_ms', 480901), ('effects', {})):
            e, r = self.first()
            event = next(x for x in r['trace']['events'] if x['type'] == 'action_completed' and x['task_id'] == 'laundry')
            event[key] = value
            with self.subTest(key=key), self.assertRaises(EvidenceError): recount(e, r)

    def test_start_cost_and_agent_tampering_rejected(self):
        for key, val in (('duration_ms', 1), ('power_kw', 99), ('agent_id', 'wrong')):
            e, r = self.first()
            event = next(x for x in r['trace']['events'] if x['type'] == 'action_started')
            event[key] = val
            with self.subTest(key=key), self.assertRaises(EvidenceError): recount(e, r)

    def test_deadline_boundary_and_late_completion(self):
        e, r = self.first(); e['task_stream'][0]['completion_deadline_ms'] = 480900
        x = recount(e, r); self.assertTrue(x['tasks']['laundry']['timely'])
        e['task_stream'][0]['completion_deadline_ms'] = 480899
        x = recount(e, r); t = x['tasks']['laundry']
        self.assertTrue(t['completed']); self.assertFalse(t['timely']); self.assertEqual(1, t['tardiness_ms'])

    def test_off_real_execution_is_not_service(self):
        e, r = self.empty_run(); tid = 'laundry'
        call = next(c for c in r['calls'] if c['request']['task']['task_id'] == tid)
        a = call['decision']['actions'][0]; a['operation'] = 'off'
        g = next(g for g in e['action_grounding'] if g['task_id'] == tid and g['operation'] == 'off')
        start = {'type':'action_started','timestamp_ms':1400,'task_id':tid,'agent_id':'LaundryAgent','proposal_id':a['proposal_id'],
                 'target':g['target'],'operation':'off','duration_ms':g['duration_ms'],'power_kw':g['power_kw'],
                 'start_effects':{},'completion_effects':{},'requires':a['requires'],'state_version_at_start':1}
        end = {'type':'action_completed','timestamp_ms':1500,'task_id':tid,'agent_id':'LaundryAgent','proposal_id':a['proposal_id'],
               'target':g['target'],'operation':'off','effects':{},'new_state_version':2}
        r['trace']['events'] += [start, end]; r['trace']['event_count'] += 2; r['trace']['final_state_version'] = 2
        x = recount(e, r)
        self.assertEqual(1, x['metrics']['actual_start_count'])
        self.assertEqual(0, x['metrics']['service_rate'])
        self.assertFalse(x['tasks'][tid]['started'])

    def test_capacity_integral_separate_from_gate_rejection(self):
        e, r = self.first(); e['home']['resources']['max_power_kw'] = 2
        x = recount(e, r)
        self.assertGreater(x['metrics']['executed_capacity_violation_duration_ms'], 0)
        self.assertGreater(x['metrics']['excess_resource_unit_ms'], 0)
        self.assertEqual(1, x['metrics']['action_rejected_count'])

    def test_same_timestamp_half_open_boundary_preserves_event_order(self):
        for start_first in (False, True):
            e, r = self.first()
            e['task_stream'] = e['task_stream'][:2]
            ids = [t['task_id'] for t in e['task_stream']]
            r['calls'] = [c for c in r['calls'] if c['request']['task']['task_id'] in ids]
            r['trace']['agent_requests'] = [c['request'] for c in r['calls']]
            for g in e['action_grounding']:
                if g['task_id'] in ids and g['operation'] == 'prepare': g['duration_ms'] = 100
            ev = [x for x in r['trace']['events'] if x['task_id'] in ids and x['type'] in ('task_released','proposal_returned')]
            def pair(tid, at):
                s = deepcopy(next(x for x in self.source['runs'][0]['trace']['events'] if x['type']=='action_started' and x['task_id']==tid))
                s.update(timestamp_ms=at, duration_ms=100)
                patch = {'type':'state_update','timestamp_ms':at,'task_id':tid,'source':'action_started','patch':s['start_effects']}
                end = deepcopy(next(x for x in self.source['runs'][0]['trace']['events'] if x['type']=='action_completed' and x['task_id']==tid))
                end['timestamp_ms'] = at+100
                return patch, s, end
            p0, s0, f0 = pair(ids[0], 1100); p1, s1, f1 = pair(ids[1], 1200)
            ev += [p0,s0] + ([p1,s1,f0] if start_first else [f0,p1,s1]) + [f1]
            state = deepcopy(e['initial_state']['values']); version = 1
            for x in ev:
                if x['type'] in ('state_update','action_completed'):
                    version += 1; x['new_state_version'] = version
                    patch = x['patch'] if x['type']=='state_update' else x['effects']
                    for path, value in patch.items(): state['devices'][path.split('.')[1]] = value
                elif x['type']=='action_started': x['state_version_at_start'] = version
            r['trace'].update(events=ev, event_count=len(ev), final_state=state, final_state_version=version)
            e['home']['resources']['max_power_kw'] = 2
            with self.subTest(start_first=start_first):
                x = recount(e,r)
                self.assertEqual(0, x['metrics']['executed_capacity_violation_duration_ms'])
                self.assertEqual(0, x['metrics']['excess_resource_unit_ms'])

    def test_common_K_counterexample_and_fixed_service_differences(self):
        rows = self.hypothetical_rows([['a'], ['a','b'], ['a','b'], ['a','b']])
        g = compare_cells({'slots': list(CELL_ORDER)}, rows, metric_rules())
        self.assertEqual(['a'], g['population']['common_task_ids'])
        self.assertEqual([0.5,1,1,1], g['scalar_effects']['service_rate']['cell_values'])
        self.assertEqual(0, g['conditional_time']['metrics']['completion_latency_ms']['value'])
        self.assertIsNone(g['scalar_effects']['whole_house_completion_ms']['interaction'])

    def test_empty_K_and_disjoint_two_arm_populations(self):
        rows = self.hypothetical_rows([['a'], ['a'], ['b'], ['b']])
        g = compare_cells({'slots': list(CELL_ORDER)}, rows, metric_rules())
        self.assertEqual([], g['population']['common_task_ids'])
        self.assertIsNone(g['conditional_time']['metrics']['completion_latency_ms']['value'])
        self.assertEqual('no_common_completed_requests', g['conditional_time']['metrics']['completion_latency_ms']['null_reason'])

    def test_missing_K_metric_is_hard_error(self):
        rows = self.hypothetical_rows([['a']]*4)
        del rows[CELL_ORDER[2]]['tasks']['a']['completion_latency_ms']
        with self.assertRaises(EvidenceError): compare_cells({'slots': list(CELL_ORDER)}, rows, metric_rules())

    def test_pair_failure_not_removed(self):
        rows = self.hypothetical_rows([[], ['a'], [], []])
        p = compare_pair({'left': CELL_ORDER[0], 'right': CELL_ORDER[1], 'kind':'policy'}, rows, metric_rules())
        self.assertEqual(0.5, p['scalar_deltas']['service_rate']['value'])
        self.assertIsNone(p['conditional_time']['metrics']['completion_latency_ms']['value'])

    def test_forbidden_conditional_metrics_not_emitted_in_interactions(self):
        for g in self.data[f'{OUT}/four_cells.json']['groups']:
            self.assertNotIn('conditional_timely_rate', g['scalar_effects'])
            self.assertNotIn('own_completed_means', g['scalar_effects'])

    def test_missing_macro_slot_blocks_not_reweights(self):
        rows = {r['slot_id']:r for path,d in self.data.items() if '/D-F1-' in path for r in d['runs']}
        plan = json.loads((ROOT / 'docs/f1_statistical_contract_v2_20261004/plan.json').read_text(encoding='utf-8'))
        rows.pop(next(iter(rows)))
        with self.assertRaises(EvidenceError): macro(rows, plan['configurations'], metric_rules())

    def test_hash_or_missing_source_failure_and_no_holdout_or_results(self):
        original = Path.read_text
        def guarded(path, *args, **kwargs):
            self.assertNotIn('prospective_test', path.parts)
            self.assertNotIn('results', path.parts)
            return original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', guarded): self.assertEqual(self.data, bundle())
        from homecoord_bench.task_revision import f1_aggregation_v1 as mod
        with patch.object(mod, 'digest', return_value='wrong'):
            with self.assertRaises(EvidenceError): bundle()


if __name__ == '__main__':
    unittest.main()
