import sys
import unittest
from copy import deepcopy
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_main_experiment_matrix_20260930 import cards, validate_certificate

class MainExperimentMatrixTests(unittest.TestCase):
    def test_all_declared_certificates_serve_every_task_feasibly(self):
        count = 0
        for card in cards():
            for certificate in card['certificates']:
                result = validate_certificate(card, certificate)
                self.assertTrue(result['feasible_certificate'])
                self.assertLessEqual(result['peak_resource_units'], card['resource_capacity_units'])
                count += 1
        self.assertEqual(6, count)

    def test_early_dependent_service_is_rejected(self):
        card = cards()[0]
        certificate = deepcopy(card['certificates'][0])
        certificate['media']['start_ms'] = 0
        with self.assertRaisesRegex(ValueError, 'predecessor'):
            validate_certificate(card, certificate)

    def test_fast_mode_does_not_bypass_capacity(self):
        card = cards()[2]
        certificate = deepcopy(card['certificates'][0])
        certificate['laundry']['mode'] = 'fast'
        with self.assertRaisesRegex(ValueError, 'capacity'):
            validate_certificate(card, certificate)

    def test_both_modes_are_accepted_but_have_different_waits(self):
        card = cards()[2]
        eco, fast = [validate_certificate(card, cert) for cert in card['certificates']]
        self.assertEqual(0, eco['task_intervals']['laundry']['start_ms'])
        self.assertEqual(300000, fast['task_intervals']['laundry']['start_ms'])
        self.assertEqual(600000, eco['makespan_ms'])
        self.assertEqual(540000, fast['makespan_ms'])

    def test_missing_task_and_deadline_failure_are_rejected(self):
        card = cards()[0]
        certificate = deepcopy(card['certificates'][0])
        certificate.pop('backup')
        with self.assertRaisesRegex(ValueError, 'every task'):
            validate_certificate(card, certificate)
        certificate = deepcopy(card['certificates'][0])
        certificate['backup']['start_ms'] = 300000
        with self.assertRaisesRegex(ValueError, 'deadline'):
            validate_certificate(card, certificate)

    def test_invalid_resource_cost_cannot_fake_a_certificate(self):
        card = cards()[0]
        card['tasks'][0]['acceptable_modes'][0]['resource_units'] = -1
        with self.assertRaisesRegex(ValueError, 'resource cost'):
            validate_certificate(card, card['certificates'][0])

if __name__ == '__main__':
    unittest.main()
