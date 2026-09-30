import sys
import unittest
from pathlib import Path
from copy import deepcopy
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from probe_c3_runtime_repeat_20260930 import measure_once, replay_batch, policy_episode, LABELS, locked
from probe_c3_scale_release_20260930 import build, templates
from probe_c3_information_baselines_20260930 import SOURCE_MODEL
from probe_c3_structural_generalization import ScriptedProposalClient
from runtime import event_simulator as sim
import json

class RuntimeRepeatTests(unittest.TestCase):
    def test_instrumentation_preserves_outcomes_and_restores_solver(self):
        episode = build('N4-1', templates()['N4-1'], 'tight', 'urgent_late', 1.6)
        original = sim.ideal_schedule
        for label in LABELS:
            changed, policy = policy_episode(episode, label)
            latencies = {t['task_id']: 800 + i * 200 for i, t in enumerate(episode['task_stream'])}
            _, reference = sim.run_event_simulation(changed, ScriptedProposalClient(latencies), policy, '', shared_safety_gate=True)
            measured = measure_once(episode, label)
            self.assertIs(sim.ideal_schedule, original)
            self.assertEqual(reference['all_deadlines_met'], measured['all_deadlines_met'])
            self.assertEqual(all(reference['task_service'].values()), measured['all_tasks_served'])
            self.assertEqual(reference['first_action_start_latency_ms'], measured['first_action_ms'])
            self.assertGreater(measured['simulator_wall_ms'], 0)
            if label.startswith('Released'):
                self.assertGreater(len(measured['solver_calls_ms']), 0)

    def test_recorded_batch_generates_fixed_cells_and_separates_foresight(self):
        _, episodes = locked()
        saved = json.loads(SOURCE_MODEL.read_text(encoding='utf8'))['batches'][0]
        rows = replay_batch(episodes, {**saved, 'repetition': 1})
        self.assertEqual(19, len(rows))
        privileged = [r for r in rows if r['information_class'] == 'perfect_announcement']
        self.assertEqual(3, len(privileged))
        self.assertTrue(all(r['release'] == 'urgent_late' for r in privileged))
        broken = deepcopy(saved)
        broken['sample']['errors'] = {'task01': {'error': 'test'}}
        self.assertEqual([], replay_batch(episodes, {**broken, 'repetition': 1}))

if __name__ == '__main__':
    unittest.main()
