import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from probe_c3_visible_request_update_20260930 import build, ReferenceSelector
from probe_c3_scale_release_20260930 import load, checked_schedule
from probe_c3_information_baselines_20260930 import contracts
from runtime.protocol import build_agent_request
from runtime.event_simulator import _apply_patch
from runtime.episode_validation import validate_event_episode

class VisibleRequestUpdateTests(unittest.TestCase):
    def test_updated_request_differs_but_goal_tools_and_costs_do_not(self):
        _, episodes = load()
        for template in ('N2-1', 'N4-1', 'N5-1'):
            source = episodes[template, 'tight', 'urgent_late', 1.6]
            stable, update = [build(source, arm) for arm in ('stable_A', 'A_to_B')]
            task_id = update['visible_update_design']['late_task_id']
            views = []
            for episode in (stable, update):
                self.assertEqual([], validate_event_episode(episode))
                self.assertIsNotNone(checked_schedule(episode))
                state = episode['initial_state']['values'].copy()
                # A deep copy prevents state projection changes from altering candidate inputs.
                from copy import deepcopy
                state = deepcopy(state)
                for event in episode['exogenous_events']:
                    _apply_patch(state, event['patch'])
                task = next(t for t in episode['task_stream'] if t['task_id'] == task_id)
                agent = next(a for a in episode['agents'] if a['agent_id'] == task['agent_id'])
                view = build_agent_request(episode, agent, task, architecture='ObservedTaskFeasibilityCoordinator',
                                          current_time_ms=60000, current_state=state,
                                          released_task_ids={t['task_id'] for t in episode['task_stream']})
                self.assertNotIn('required_action', view['task'])
                self.assertNotIn('action_template', view['task'])
                views.append(view)
            self.assertEqual(views[0]['task'], views[1]['task'])
            self.assertEqual(views[0]['available_actions'], views[1]['available_actions'])
            self.assertNotEqual(views[0]['state'], views[1]['state'])
            self.assertEqual(contracts(stable), contracts(update))

    def test_both_update_directions_and_stable_controls(self):
        _, episodes = load()
        source = episodes['N2-1', 'tight', 'urgent_late', 0.8]
        for arm, updated in (('stable_A', False), ('A_to_B', True), ('stable_B', False), ('B_to_A', True)):
            episode = build(source, arm)
            self.assertEqual(updated, bool(episode['exogenous_events']))
            self.assertEqual(updated, episode['visible_update_design']['updated'])
            self.assertIsNotNone(checked_schedule(episode))

if __name__ == '__main__':
    unittest.main()
