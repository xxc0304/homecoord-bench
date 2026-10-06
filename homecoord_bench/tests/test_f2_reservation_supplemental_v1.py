"""Post-run correctness probes, not benchmark configurations/performance samples.

The old-callback-after-new-completion case was specified before execution.
This adds its concrete synthetic construction without changing the locked grid.
"""
import unittest
from copy import deepcopy

from homecoord_bench.task_revision import f2_reservation_ablation_v1 as exp


class SupplementalReservationTests(unittest.TestCase):
    def example(self):
        d = exp.read(exp.config_path(0)); e = deepcopy(d['input'])
        # A long urgent 1-unit action delays a 3-unit unstarted reservation,
        # opening a backfill window for the smaller laundry service.
        costs = {'laundry': (480000, 1), 'cleaning': (360000, 3), 'water': (800000, 1)}
        for t in e['task_stream']:
            tid = t['task_id']
            if tid not in costs: continue
            duration, units = costs[tid]
            t['action_template'].update(duration_ms=duration, power_kw=units)
            e['home']['resources']['task_power_bounds_kw'][tid] = units
            for tool in e['tool_catalog']:
                if tool['agent_id'] == t['agent_id'] and tool['operation'] == 'prepare':
                    tool['cost_contract'] = {'duration_ms': duration, 'resource_units': units}
            for g in e['action_grounding']:
                if g['task_id'] == tid and g['operation'] == 'prepare':
                    g.update(duration_ms=duration, power_kw=units)
            for device in e['public_devices']:
                if device['agent_id'] == t['agent_id']:
                    device.update(duration_ms=duration, resource_units=units)
            if tid == 'water': t['completion_deadline_ms'] = 900000
        for context in [e['initial_state']['values']['coordination_context'],
                        e['exogenous_events'][0]['patch']['coordination_context']]:
            for r in context['requests']:
                if r['task_id'] in costs:
                    duration, units = costs[r['task_id']]
                    r['modes'] = [{'operation': 'prepare', 'duration_ms': duration, 'resource_units': units}]
                if r['task_id'] == 'water': r['deadline_ms'] = 900000
        return e

    def test_old_callback_after_new_valid_completion_has_no_effect(self):
        e = self.example(); runs = [exp.simulate(e, arm, 0) for arm in exp.ARMS]
        pair = exp.pair_audit(e, runs); audit = pair['audits'][1]
        laundry = audit['tasks']['laundry']; events = runs[1]['trace']['events']
        old = next(x for x in events if x['type'] == 'reservation_callback_suppressed' and x['task_id'] == 'laundry')
        self.assertLess(laundry['completion_ms'], old['timestamp_ms'])
        self.assertEqual(1, sum(x['type'] == 'action_started' and x.get('task_id') == 'laundry' for x in events))
        self.assertEqual(1, sum(x['type'] == 'action_completed' and x.get('task_id') == 'laundry' for x in events))
        self.assertEqual('complete', runs[1]['trace']['final_state']['devices']['laundry_device'])

    def test_semantic_precondition_mutation_rejected_not_just_null_metadata(self):
        d = exp.read(exp.config_path(0)); run = deepcopy(d['runs'][0])
        x = next(x for x in run['trace']['events'] if x['type'] == 'action_started')
        x['requires'][0]['value'] = 'running'
        with self.assertRaisesRegex(ValueError, 'start preconditions'):
            exp.audit(d['input'], run)

    def test_non_null_range_metadata_rejected(self):
        d = exp.read(exp.config_path(0)); run = deepcopy(d['runs'][0])
        run['calls'][0]['decision']['actions'][0]['requires'][0]['range_min'] = 1
        with self.assertRaisesRegex(ValueError, 'non-null range'):
            exp.audit(d['input'], run)


if __name__ == '__main__': unittest.main()
