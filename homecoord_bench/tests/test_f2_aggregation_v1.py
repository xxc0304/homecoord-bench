import json
import unittest
from copy import deepcopy
from unittest.mock import patch

from homecoord_bench.task_revision import f2_aggregation_v1 as a


class F2AggregationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = a.bundle()
        cls.plan = a.read(a.read(a.FREEZE)['plan_path'])
        cls.episodes = {e['episode_id']: e for e in a.read('homecoord_bench/task_revision/fixtures/f2_v7/inputs.json')['episodes']}
        cls.rows = {r['slot_id']: r for p, doc in cls.data.items() if '/F2R1-' in p for r in doc['runs']}

    def sample(self, template='01', capacity='competition', release='simultaneous', policy=0):
        eid = f'F2R1-D-F2-{template}-{capacity}-{release}'
        item = next(c for c in self.plan['configurations'] if c['episode_id'] == eid)
        return deepcopy(self.episodes[eid]), deepcopy(a.read(item['source_path'])['runs'][policy])

    def empty(self):
        e, r = self.sample()
        r['trace']['events'] = [x for x in r['trace']['events'] if x['type'] in ('task_released', 'proposal_returned')]
        for call in r['calls']:
            call['decision']['actions'] = []
        r['trace']['event_count'] = len(r['trace']['events'])
        r['trace']['final_state'] = deepcopy(e['initial_state']['values'])
        r['trace']['final_state_version'] = e['initial_state']['version']
        return e, r

    def test_saved_results_exact_reproduction(self):
        for p, obj in self.data.items():
            self.assertEqual(a.serialize(obj), (a.ROOT / p).read_text(encoding='utf-8'))

    def test_off_receipt_is_not_service(self):
        e, original = self.sample(); _, r = self.empty()
        action = deepcopy(original['calls'][0]['decision']['actions'][0])
        action.update(operation='off', requires=[], estimated_duration_ms=100, estimated_power_kw=0)
        r['calls'][0]['decision']['actions'] = [action]
        g = next(g for g in e['action_grounding'] if g['task_id'] == 'laundry' and g['operation'] == 'off')
        start = {'type': 'action_started', 'timestamp_ms': 400, 'task_id': 'laundry',
                 'agent_id': g['agent_id'], 'proposal_id': action['proposal_id'], 'target': g['target'],
                 'operation': 'off', 'duration_ms': 100, 'power_kw': 0, 'start_effects': {},
                 'completion_effects': {}, 'requires': [], 'state_version_at_start': 1}
        end = {'type': 'action_completed', 'timestamp_ms': 500, 'task_id': 'laundry',
               'agent_id': g['agent_id'], 'proposal_id': action['proposal_id'], 'target': g['target'],
               'operation': 'off', 'effects': {}, 'new_state_version': 2}
        r['trace']['events'] += [start, end]
        r['trace']['event_count'] = len(r['trace']['events'])
        r['trace']['final_state_version'] = 2
        x = a.recount(e, r)
        self.assertEqual(1, len(x['physical_intervals']))
        self.assertEqual(0, x['denominators']['completed'])
        self.assertIsNone(x['tasks']['laundry']['completion_ms'])

    def test_scope_and_fixed_macro_weights(self):
        s = self.data[f'{a.OUT}/summary.json']
        self.assertEqual((32, 72, 8, 48), (s['runs'], s['pairs'], s['four_cells'], s['diagnostic_prefix_pairs']))
        self.assertEqual((0, 0, None), (s['api_calls'], s['simulator_runs'], s['adapter_acceptance']))
        for x in s['template_macro'].values():
            self.assertEqual('1/2', x['template_weight'])
            for t in x['templates'].values():
                self.assertEqual(4, len(t['slot_weights']))
                self.assertTrue(all(w['weight'] == '1/4' for w in t['slot_weights']))
                self.assertEqual({'service_rate', 'timely_service_rate'}, set(t['rates']))

    def test_reported_scores_ignored(self):
        e, r = self.sample(); expected = a.recount(e, r)
        r['result'] = {'service_rate': 999}; r['audit'] = None
        self.assertEqual(expected, a.recount(e, r))

    def test_fixed_E_failure_and_water_subset(self):
        e, r = self.sample(release='late')
        x = a.recount(e, r)
        self.assertEqual(4, x['denominators']['required'])
        self.assertEqual(1, x['subsets']['water']['denominators']['required'])
        self.assertFalse(x['tasks']['water']['completed'])
        self.assertIsNone(x['tasks']['water']['completion_latency_ms'])
        self.assertIsNone(x['metrics']['whole_house_completion_ms'])

    def test_zero_completion_null_conditionals(self):
        e, r = self.empty(); x = a.recount(e, r)
        self.assertEqual(0, x['metrics']['service_rate'])
        self.assertEqual(0, x['metrics']['timely_service_rate'])
        self.assertIsNone(x['auxiliary']['conditional_timely_rate'])
        self.assertTrue(all(v is None for v in x['auxiliary']['own_completed_means'].values()))

    def test_reservation_not_service(self):
        e, r = self.sample()
        r['trace']['events'] = [x for x in r['trace']['events'] if x['type'] in
                               ('task_released', 'proposal_returned', 'coordination_decision', 'action_reserved')]
        r['trace']['event_count'] = len(r['trace']['events'])
        r['trace']['final_state'] = deepcopy(e['initial_state']['values'])
        r['trace']['final_state_version'] = e['initial_state']['version']
        self.assertEqual(0, a.recount(e, r)['denominators']['completed'])

    def test_necessary_queue_still_success(self):
        e, r = self.sample(policy=2); x = a.recount(e, r)['tasks']['cleaning']
        self.assertGreater(x['task_start_wait_ms'], 0)
        self.assertTrue(x['completed']); self.assertTrue(x['timely'])

    def test_water_own_release_clock_and_tardy(self):
        e, r = self.sample(template='02', release='late', policy=3)
        x = a.recount(e, r)['tasks']['water']
        self.assertEqual(120000, x['release_ms'])
        self.assertEqual(x['completion_ms'] - 120000, x['completion_latency_ms'])
        self.assertEqual(500, x['tardiness_ms']); self.assertFalse(x['timely'])

    def test_receipt_tampering_rejected(self):
        for field, value in [('proposal_id', 'fake'), ('agent_id', 'fake'), ('task_id', 'water'),
                             ('target', 'fake'), ('operation', 'off'), ('effects', {}),
                             ('timestamp_ms', 9999999)]:
            e, r = self.sample()
            receipt = next(x for x in r['trace']['events'] if x['type'] == 'action_completed')
            receipt[field] = value
            with self.subTest(field=field), self.assertRaises(a.EvidenceError):
                a.recount(e, r)

    def test_missing_receipt_rejected(self):
        e, r = self.sample()
        r['trace']['events'] = [x for x in r['trace']['events'] if x['type'] != 'action_completed']
        r['trace']['event_count'] = len(r['trace']['events'])
        with self.assertRaises(a.EvidenceError): a.recount(e, r)

    def test_forged_final_state_rejected(self):
        e, r = self.sample(); r['trace']['final_state'] = {}
        with self.assertRaises(a.EvidenceError): a.recount(e, r)

    def test_missing_exogenous_publication_rejected(self):
        e, r = self.sample(release='late')
        r['trace']['events'] = [x for x in r['trace']['events']
                               if not (x['type'] == 'state_update' and x.get('source') == 'new_public_request')]
        r['trace']['event_count'] = len(r['trace']['events'])
        with self.assertRaises(a.EvidenceError): a.recount(e, r)

    def test_complete_request_future_leak_rejected(self):
        e, r = self.sample(release='late')
        r['calls'][0]['request']['extra_future_label'] = 'late'
        r['trace']['agent_requests'] = [c['request'] for c in r['calls']]
        with self.assertRaises(a.EvidenceError): a.recount(e, r)

    def test_physical_crossing_strict_boundaries(self):
        e, r = self.sample(release='late')
        x = a.recount(e, r); L = x['tasks']['water']['release_ms']
        tid = x['subsets']['early']['required_task_ids'][0]
        base = {'task_id': tid, 'operation': 'prepare', 'units': 2}
        ints = [{**base, 'start_ms': L-10, 'end_ms': L},
                {**base, 'start_ms': L, 'end_ms': L+10},
                {**base, 'start_ms': L-10, 'end_ms': L+10}]
        bg = a.arrival_background(e, r, ints, x['tasks'])
        self.assertEqual(2, bg['physical_units_crossing_L'])
        self.assertEqual(1, len(bg['crossing_actual_intervals']))
        self.assertEqual(10, bg['crossing_actual_intervals'][0]['remaining_ms'])

    def test_reservation_not_physical_load(self):
        e, r = self.sample(release='late', policy=1)
        x = a.recount(e, r)['arrival_background']
        self.assertTrue(x['future_reservations_created_before_L'])
        self.assertTrue(all(not z['counts_as_physical_load_at_L'] for z in x['future_reservations_created_before_L']))
        self.assertEqual(sum(z['units'] for z in x['crossing_actual_intervals']), x['physical_units_crossing_L'])

    def test_common_K_empty(self):
        x = {'required_task_ids': ['a'], 'completed_task_ids': [], 'tasks': {}}
        t = a.time_compare([x, x], a.TIME_METRICS)
        self.assertFalse(t['eligible']); self.assertEqual(0, t['coverage'])
        self.assertTrue(all(v['effects']['right_minus_left'] is None for v in t['metrics'].values()))

    def test_common_K_four_arm_intersection(self):
        E = ['a', 'b']; rs = []
        for C in [E, ['a'], E, E]:
            rs.append({'required_task_ids': E, 'completed_task_ids': C,
                       'tasks': {t: {m: 10 if t == 'a' else 100 for m in a.TIME_METRICS} for t in C}})
        x = a.time_compare(rs, a.TIME_METRICS)
        self.assertEqual(['a'], x['common_task_ids'])
        self.assertEqual([10]*4, x['metrics']['completion_latency_ms']['arm_means'])
        self.assertEqual(0, x['metrics']['completion_latency_ms']['effects']['interaction'])

    def test_missing_K_metric_is_error(self):
        x = {'required_task_ids': ['a'], 'completed_task_ids': ['a'], 'tasks': {'a': {}}}
        with self.assertRaises(a.EvidenceError): a.time_compare([x, x], a.TIME_METRICS)

    def test_whole_house_missing_and_metric_whitelist(self):
        for p in self.data[f'{a.OUT}/pairs_release.json']['pairs']:
            self.assertNotIn('conditional_timely_rate', p['scalar_comparison'])
            h = p['scalar_comparison']['whole_house_completion_ms']
            if any(v is None for v in h['arm_values']):
                self.assertIsNone(h['effects']['right_minus_left'])

    def test_prefix_all_pass_and_diagnostics_isolated(self):
        doc = self.data[f'{a.OUT}/information_diagnostics.json']
        self.assertEqual('prefix_only_not_service_scores', doc['scope'])
        self.assertTrue(all(x['equal'] and not x['performance_comparison'] for x in doc['pairs']))
        self.assertEqual(32, len(self.rows))

    def test_prefix_complete_request_decision_and_event_mutations(self):
        _, r = self.sample(release='late')
        for channel in ('request', 'decision', 'event'):
            d = deepcopy(r)
            if channel == 'event': d['trace']['events'][0]['extra'] = True
            else: d['calls'][0][channel]['extra'] = True
            with self.subTest(channel=channel):
                x = a.prefix_check(r, d, 60000)
                self.assertFalse(x['equal']); self.assertIsNotNone(x['first_difference_channel'])

    def test_prefix_cutoff_is_exclusive(self):
        _, r = self.sample(release='late'); d = deepcopy(r)
        next(x for x in d['trace']['events'] if x['timestamp_ms'] == 60000)['extra'] = True
        self.assertTrue(a.prefix_check(r, d, 60000)['equal'])

    def test_missing_macro_slot_not_reweighted(self):
        rows = deepcopy(self.rows); rows.pop(next(iter(rows)))
        with self.assertRaises(a.EvidenceError): a.macro(rows, self.plan['configurations'])

    def test_freeze_hash_failure(self):
        with patch.object(a, 'digest', return_value='bad'), self.assertRaises(a.EvidenceError): a.bundle()

    def test_bundle_read_scope_no_holdout_or_scores(self):
        original = a.read; paths = []
        def observed(path, root=a.ROOT):
            paths.append(path); return original(path, root)
        with patch.object(a, 'read', side_effect=observed): a.bundle()
        self.assertFalse(any('holdout' in p or '.env' in p or '/f1_' in p or '/f3_' in p for p in paths))


if __name__ == '__main__':
    unittest.main()
