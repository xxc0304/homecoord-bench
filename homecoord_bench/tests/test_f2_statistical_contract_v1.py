import json
import unittest
from collections import Counter
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from homecoord_bench.task_revision.f2_statistical_contract_v1 import (
    ROOT, SOURCE, OUT, POLICIES, bundle, metric_rules, validate_contrast,
)


class F2ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan=bundle()
        cls.episodes={e['episode_id']:e for e in json.loads((ROOT/f'{SOURCE}/inputs.json').read_text(encoding='utf-8'))['episodes']}

    def test_saved_plan_reproducible(self):
        self.assertEqual(self.plan,json.loads((ROOT/OUT).read_text(encoding='utf-8')))

    def test_scope_static_E_and_diagnostic_separation(self):
        p=self.plan
        self.assertEqual((8,32,48,8),(len(p['configurations']),len(p['runs']),len(p['diagnostic_runs']),len(p['four_cells'])))
        self.assertTrue(all(len(c['required_requests'])==4 and len(c['early_task_ids'])==3 and c['arrival_task_ids']==['water'] for c in p['configurations']))
        self.assertFalse(p['scores_computed']);self.assertEqual(0,p['api_calls']);self.assertEqual(0,p['simulator_runs'])
        self.assertTrue(all(not r['in_main_service_denominator'] for r in p['diagnostic_runs']))

    def test_main_pointers_and_policies(self):
        self.assertEqual(32,len({r['slot_id'] for r in self.plan['runs']}))
        for row in self.plan['runs']:
            d=json.loads((ROOT/row['source_path']).read_text(encoding='utf-8'))
            r=d['runs'][int(row['source_pointer'].split('/')[-1])]
            self.assertEqual((row['episode_id'],row['policy']),(r['evaluation_episode_id'],r['policy']))

    def test_pair_endpoints_directions_and_coverage(self):
        pairs=self.plan['pairs']; rows={r['slot_id']:r for r in self.plan['runs']}
        self.assertEqual({'policy':24,'strong_rule':16,'capacity':16,'release':16},Counter(p['kind'] for p in pairs))
        self.assertEqual(72,len({(p['kind'],p['left'],p['right']) for p in pairs}))
        for p in pairs:
            a,b=rows[p['left']],rows[p['right']]
            if p['kind'] in ('policy','strong_rule'):
                self.assertEqual(a['episode_id'],b['episode_id'])
                self.assertEqual('IndependentMultiAgent' if p['kind']=='policy' else 'GateRetryRule',a['policy'])
            else:
                self.assertEqual(a['policy'],b['policy'])
                x,y=self.episodes[a['episode_id']],self.episodes[b['episode_id']]
                self.assertEqual(x['base_episode_id'],y['base_episode_id'])
                axis='resource_arm' if p['kind']=='capacity' else 'temporal_arm'
                other='temporal_arm' if axis=='resource_arm' else 'resource_arm'
                self.assertEqual(x['pairing'][other],y['pairing'][other])
                self.assertEqual(('competition','no_competition') if axis=='resource_arm' else ('simultaneous','late'),(x['pairing'][axis],y['pairing'][axis]))

    def test_own_release_windows_preserved(self):
        for p in self.plan['contrast_checks']:
            a,b=self.episodes[p['left_config']],self.episodes[p['right_config']]
            self.assertEqual(p['actual_changed_paths'],validate_contrast(a,b,p['kind']))
            if p['kind']=='release':
                ta,tb=a['task_stream'][-1],b['task_stream'][-1]
                self.assertEqual(ta['completion_deadline_ms']-ta['release_at_ms'],tb['completion_deadline_ms']-tb['release_at_ms'])

    def test_hidden_cost_or_permission_or_context_change_rejected(self):
        a=self.episodes['F2R1-D-F2-01-competition-late']
        b=self.episodes['F2R1-D-F2-01-no_competition-late']
        for case in ('cost','permission','context'):
            m=deepcopy(b)
            if case=='cost': m['action_grounding'][0]['duration_ms']+=1
            elif case=='permission':m['agents'][0]['tools'].append('extra')
            else:m['exogenous_events'][0]['patch']['coordination_context']['requests'][-1]['deadline_ms']+=1
            with self.subTest(case=case),self.assertRaises(ValueError):validate_contrast(a,m,'capacity')

    def test_release_shift_without_budget_shift_rejected(self):
        a=self.episodes['F2R1-D-F2-01-competition-simultaneous']
        b=deepcopy(self.episodes['F2R1-D-F2-01-competition-late'])
        b['task_stream'][-1]['completion_deadline_ms']+=1
        b['exogenous_events'][0]['patch']['coordination_context']['requests'][-1]['deadline_ms']+=1
        with self.assertRaises(ValueError):validate_contrast(a,b,'release')

    def test_four_cell_and_metric_rules(self):
        rows={r['slot_id'] for r in self.plan['runs']}
        for g in self.plan['four_cells']:
            self.assertEqual(4,len(set(g['slots'])))
            self.assertTrue(set(g['slots'])<=rows)
            self.assertEqual(['tight_simultaneous','tight_late','adequate_simultaneous','adequate_late'],g['cell_order'])
        r=metric_rules()
        self.assertFalse(r['own_C_means_and_conditional_rates_in_four_cell_interaction'])
        self.assertEqual(['service_rate','timely_service_rate'],r['macro_weights']['metrics'])
        self.assertFalse(r['macro_weights']['skip_missing'])
        self.assertEqual('null: no_common_completed_requests',r['empty_K'])

    def test_diagnostic_prefix_plan_not_performance_pairs(self):
        ps=self.plan['diagnostic_prefix_pairs']
        self.assertEqual(48,len(ps));self.assertEqual(48,len({p['diagnostic_slot'] for p in ps}))
        self.assertTrue(all(not p['performance_pair'] for p in ps))
        self.assertEqual({60000:24,120000:24},Counter(p['before_ms'] for p in ps))
        self.assertTrue(all('strict_timestamp_less_than_cutoff' in p['comparison'] for p in ps))

    def test_no_holdout_historical_results_or_simulator_reads(self):
        original=Path.read_text
        def guarded(path,*args,**kwargs):
            self.assertNotIn('prospective_test',path.parts)
            self.assertNotIn('results',path.parts)
            self.assertFalse(path.name.startswith('event_simulator'))
            return original(path,*args,**kwargs)
        with patch.object(Path,'read_text',guarded):self.assertEqual(self.plan,bundle())


if __name__=='__main__':unittest.main()
