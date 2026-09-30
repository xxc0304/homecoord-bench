import sys
import unittest
from copy import deepcopy
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_task_family_split_20260930 import (blueprints, build, public_context, structure_signature,
                                             static_check, records_for, locked_development)
from probe_c3_staggered_release import release_order_records
from runtime.event_simulator import run_event_simulation
from runtime.replay_client import MemoryReplayClient
from evaluate import task_accepts_action

class TaskFamilySplitTests(unittest.TestCase):
    def dev_card(self, family):
        return next(c for c in blueprints() if c['split'] == 'development' and c['family'] == family)

    def test_structure_fingerprint_detects_renaming_reordering_and_uniform_rescaling(self):
        card = self.dev_card('F3')
        modified = deepcopy(card)
        modified['competition_capacity'] *= 3
        for index, task in enumerate(modified['tasks']):
            task['name'] = 'renamed' + str(index)
            task['release_min'] *= 7
            task['deadline_min'] *= 7
            for mode in task['modes']:
                mode['duration_min'] *= 7
                mode['units'] *= 3
                mode['operation'] = 'renamed_op'
        modified['tasks'].reverse()
        self.assertEqual(structure_signature(card), structure_signature(modified))
        modified['tasks'][0]['deadline_min'] += 1
        self.assertNotEqual(structure_signature(card), structure_signature(modified))

    def test_split_has_unique_topologies_and_development_loader_never_returns_test(self):
        cards = blueprints()
        self.assertEqual(12, len({structure_signature(c) for c in cards}))
        _, episodes = locked_development()
        self.assertEqual(24, len(episodes))
        self.assertTrue(all(e['split'] == 'development' for e in episodes))
        self.assertEqual(6, len({e['base_episode_id'] for e in episodes}))

    def test_no_competition_budget_covers_maximum_mode_of_all_tasks(self):
        for card in blueprints():  # static validation only, no held-out solver or execution
            e = build(card, 'no_competition', 'simultaneous' if card['family'] == 'F2' else 'base')
            static_check(e)
            self.assertEqual(sum(e['home']['resources']['task_power_bounds_kw'].values()),
                             e['home']['resources']['max_power_kw'])

    def test_late_request_context_excludes_future_and_updates_before_release(self):
        card = self.dev_card('F2')
        e = build(card, 'competition', 'late')
        ids = [t['task_id'] for t in e['task_stream']]
        modes = {t['task_id']: t['action_template']['operation'] for t in e['task_stream']}
        records = records_for(e, modes, {tid: 800 for tid in ids})
        client = MemoryReplayClient(release_order_records(e, records))
        trace, _ = run_event_simulation(e, client, 'DeadlineAwareCoordinator', '', shared_safety_gate=True)
        client.assert_consumed()
        for request in trace['agent_requests']:
            visible = {r['task_id'] for r in request['state']['coordination_context']['requests']}
            expected = {t['task_id'] for t in e['task_stream'] if t['release_at_ms'] <= request['current_time_ms']}
            self.assertEqual(expected, visible)
            self.assertFalse(any(k in request['task'] for k in ('acceptable_actions', 'action_template', 'required_action')))

    def test_release_pair_preserves_own_deadline_budget(self):
        card = self.dev_card('F2')
        simultaneous, late = (build(card, 'competition', arm) for arm in ('simultaneous', 'late'))
        for before, after in zip(simultaneous['task_stream'], late['task_stream']):
            self.assertEqual(before['completion_deadline_ms'] - before['release_at_ms'],
                             after['completion_deadline_ms'] - after['release_at_ms'])

    def test_acceptable_modes_and_authorized_off_have_separate_semantics(self):
        e = build(self.dev_card('F3'), 'competition', 'base')
        for task in e['task_stream']:
            for spec in task['acceptable_actions']:
                self.assertTrue(task_accepts_action(spec, task))
            self.assertFalse(task_accepts_action({'target': task['action_template']['target'], 'operation': 'off'}, task))

if __name__ == '__main__':
    unittest.main()
