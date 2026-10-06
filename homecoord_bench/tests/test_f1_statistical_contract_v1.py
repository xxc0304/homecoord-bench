import json
import unittest
from collections import Counter
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from homecoord_bench.task_revision.f1_statistical_contract_v1 import (
    ROOT, OUT, POLICIES, bundle, validate_contrast,
)


class F1StatisticalPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = bundle()

    def episode(self, suffix):
        path = ROOT / 'docs/implementation_review_20261001/traces' / (suffix + '.json')
        return json.loads(path.read_text(encoding='utf-8'))['episode']

    def test_saved_plan_reproducible(self):
        self.assertEqual(self.plan, json.loads((ROOT / OUT).read_text(encoding='utf-8')))

    def test_scope_and_fixed_required_sets(self):
        p = self.plan
        self.assertEqual(8, len(p['configurations']))
        self.assertEqual(72, len(p['runs']))
        self.assertEqual(72, len({r['slot_id'] for r in p['runs']}))
        self.assertEqual({3: 4, 5: 4}, Counter(len(c['required_requests']) for c in p['configurations']))
        self.assertTrue(all(r['episode_id'].startswith('D-F1-') for r in p['runs']))
        self.assertFalse(p['scores_computed'])
        self.assertEqual(0, p['api_calls'])
        self.assertEqual(0, p['simulator_runs'])
        self.assertEqual('pending_contract_review_not_frozen', p['status'])

    def test_all_pairs_have_unique_real_endpoints_and_direction(self):
        rows = {r['slot_id']: r for r in self.plan['runs']}
        pairs = self.plan['pairs']
        self.assertEqual({'policy': 48, 'capacity': 36, 'deadline': 36, 'return_order': 48},
                         Counter(p['kind'] for p in pairs))
        self.assertEqual(len(pairs), len({(p['kind'], p['left'], p['right']) for p in pairs}))
        configs = {c['episode_id']: c for c in self.plan['configurations']}
        for p in pairs:
            a, b = rows[p['left']], rows[p['right']]
            if p['kind'] == 'policy':
                self.assertEqual((a['episode_id'], a['order']), (b['episode_id'], b['order']))
                self.assertEqual(POLICIES[0], a['policy'])
                self.assertIn(b['policy'], POLICIES[1:])
            elif p['kind'] == 'return_order':
                self.assertEqual((a['episode_id'], a['policy']), (b['episode_id'], b['policy']))
                self.assertEqual(0, a['order']); self.assertIn(b['order'], (1, 2))
            else:
                self.assertEqual((a['policy'], a['order']), (b['policy'], b['order']))
                x, y = configs[a['episode_id']], configs[b['episode_id']]
                self.assertEqual(x['base_episode_id'], y['base_episode_id'])
                axis = 'resource_arm' if p['kind'] == 'capacity' else 'temporal_arm'
                other = 'temporal_arm' if p['kind'] == 'capacity' else 'resource_arm'
                self.assertEqual(x['pairing'][other], y['pairing'][other])
                self.assertEqual(('competition', 'no_competition') if axis == 'resource_arm' else ('base', 'loose'),
                                 (x['pairing'][axis], y['pairing'][axis]))

    def test_four_cells_complete(self):
        self.assertEqual(18, len(self.plan['four_cells']))
        real = {r['slot_id'] for r in self.plan['runs']}
        for group in self.plan['four_cells']:
            self.assertEqual(4, len(set(group['slots'])))
            self.assertTrue(set(group['slots']) <= real)
            self.assertEqual(['tight_base', 'tight_loose', 'adequate_base', 'adequate_loose'], group['cell_order'])

    def test_source_pointers_match_policy_order_and_static_tasks(self):
        configs = {c['episode_id']: c for c in self.plan['configurations']}
        for row in self.plan['runs']:
            d = json.loads((ROOT / row['source_path']).read_text(encoding='utf-8'))
            r = d['runs'][int(row['source_pointer'].split('/')[-1])]
            self.assertEqual((row['episode_id'], row['policy'], row['order']),
                             (r['episode_id'], r['policy'], r['arrival_order_index']))
            c = configs[row['episode_id']]
            expected = {tid: 800 + 200 * i for i, tid in enumerate(c['proposal_return_orders'][row['order']])}
            actual = {call['request']['task']['task_id']: call['logical_latency_ms'] for call in r['calls']}
            self.assertEqual(expected, actual)

    def test_hidden_cost_or_permission_change_rejected(self):
        left = self.episode('D-F1-01-competition-base')
        right = self.episode('D-F1-01-no_competition-base')
        for field in ('cost', 'permission'):
            mutated = deepcopy(right)
            if field == 'cost':
                mutated['action_grounding'][0]['duration_ms'] += 1
            else:
                mutated['agents'][0]['tools'].append('unauthorized_tool')
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_contrast(left, mutated, 'capacity')

    def test_undeclared_deadline_change_rejected(self):
        left = self.episode('D-F1-01-competition-base')
        right = self.episode('D-F1-01-competition-loose')
        right['task_stream'][0]['release_at_ms'] += 1
        with self.assertRaises(ValueError):
            validate_contrast(left, right, 'deadline')

    def test_no_scores_or_holdout_reads(self):
        original = Path.read_text
        def guarded(path, *args, **kwargs):
            self.assertNotIn('prospective_test', path.parts)
            self.assertNotIn('results', path.parts)
            return original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', guarded):
            self.assertEqual(self.plan, bundle())


if __name__ == '__main__':
    unittest.main()
