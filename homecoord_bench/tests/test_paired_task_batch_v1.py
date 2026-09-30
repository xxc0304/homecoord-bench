"""Guard the information boundary and controls in the paired pilot."""

import unittest

from make_paired_task_batch_v1 import build_batch
from runtime.protocol import build_agent_request


class PairedTaskBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pairs = {}
        for episode in build_batch():
            cls.pairs.setdefault(episode["pair_id"], {})[episode["pair_condition"]] = episode

    def _request(self, episode, index):
        task = episode["task_stream"][index]
        agent = next(a for a in episode["agents"] if a["agent_id"] == task["agent_id"])
        request = build_agent_request(
            episode, agent, task, architecture="IndependentMultiAgent",
            current_time_ms=task["release_at_ms"],
        )
        for key in ("request_id", "episode_id", "base_episode_id"):
            request.pop(key, None)
        return request

    def test_each_pair_has_conflict_and_control(self):
        self.assertEqual(len(self.pairs), 4)
        for conditions in self.pairs.values():
            self.assertEqual(set(conditions), {"conflict", "control"})

    def test_local_specialist_has_identical_input_across_conditions(self):
        for pair_id, conditions in self.pairs.items():
            with self.subTest(pair_id=pair_id):
                self.assertEqual(
                    self._request(conditions["conflict"], 1),
                    self._request(conditions["control"], 1),
                )

    def test_model_input_hides_scoring_answer_and_has_choices(self):
        for conditions in self.pairs.values():
            for episode in conditions.values():
                for index in (0, 1):
                    request = self._request(episode, index)
                    self.assertNotIn("required_action", request["task"])
                    self.assertNotIn("action_template", request["task"])
                    self.assertGreaterEqual(len(request["available_actions"]), 2)


if __name__ == "__main__":
    unittest.main()
