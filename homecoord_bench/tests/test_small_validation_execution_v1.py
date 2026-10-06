import unittest
from copy import deepcopy
from unittest.mock import patch
from homecoord_bench.task_revision import small_validation_execution_v1 as a
from homecoord_bench.task_revision.f2_revision import PublicProposals
from homecoord_bench.task_revision.event_simulator_v7 import run_event_simulation


class SmallValidationExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = a.verify_freeze()
        cls.config = cls.plan['configurations'][0]
        cls.episode = a.materialize(cls.config)
        cls.baseline_run = deepcopy(a.historical(cls.config, 'GateRetryRule'))
        cls.baseline_run['evaluation_episode_id'] = cls.episode['episode_id']
        cls.baseline_run['trace']['episode_id'] = cls.episode['episode_id']

    def sample(self):
        return deepcopy(self.episode), deepcopy(self.baseline_run)

    def test_frozen_scope(self):
        self.assertEqual((28,84,72), tuple(len(self.plan[k]) for k in ('configurations','run_slots','pairs')))

    def test_all_materialized_inputs(self):
        for c in self.plan['configurations']:
            e = a.materialize(c)
            self.assertEqual(c['config_id'], e['episode_id'])
            e['episode_id'] = c['source_episode_id']
            self.assertEqual(c['derived_episode_sha256'], a.object_sha(e))

    def test_outer_identity_only(self):
        e,r = self.sample()
        r['trace']['trace_id'] = 'different-private-id'
        self.assertTrue(a.exact_baseline(self.config,e,r)['complete_calls_equal'])

    def test_no_recursive_event_mask(self):
        e,r = self.sample()
        r['trace']['events'][0]['episode_id'] = 'secret'
        with self.assertRaises(a.core.EvidenceError): a.exact_baseline(self.config,e,r)

    def test_call_decision_full_comparison(self):
        for channel in ('request','decision'):
            e,r = self.sample()
            r['calls'][0][channel]['extra'] = True
            with self.subTest(channel=channel),self.assertRaises(a.core.EvidenceError):
                a.exact_baseline(self.config,e,r)

    def test_event_order_exact(self):
        e,r = self.sample()
        r['trace']['events'][0],r['trace']['events'][1] = r['trace']['events'][1],r['trace']['events'][0]
        with self.assertRaises(a.core.EvidenceError): a.exact_baseline(self.config,e,r)

    def test_public_input_future_label(self):
        e,r = self.sample()
        r['calls'][0]['request']['factor'] = 'baseline'
        r['trace']['agent_requests'] = [c['request'] for c in r['calls']]
        with self.assertRaises(a.core.EvidenceError): a.score(e,r)

    def test_forged_receipt(self):
        for field,value in [('proposal_id','fake'),('agent_id','fake'),('effects',{})]:
            e,r = self.sample()
            next(x for x in r['trace']['events'] if x['type']=='action_completed')[field]=value
            with self.subTest(field=field),self.assertRaises(a.core.EvidenceError): a.score(e,r)

    def test_result_scores_not_used(self):
        e,r = self.sample()
        expected = a.score(e,r)
        r['result'] = {'service_rate':999}
        self.assertEqual(expected,a.score(e,r))

    def test_command_bound_checks_rejection_too(self):
        e,r = self.sample()
        x = next(x for x in r['trace']['events'] if x['type']=='action_reserved')
        x['timestamp_ms'] = x['scheduled_start_ms']
        with self.assertRaises(a.core.EvidenceError): a.clock_evidence(e,r)

    def test_retry_must_match_reservation(self):
        e,r = self.sample()
        x = next(x for x in r['trace']['events'] if x['type']=='retry_scheduled')
        x['start_at_ms'] += 1
        with self.assertRaises(a.core.EvidenceError): a.clock_evidence(e,r)

    def test_missing_reservation(self):
        e,r = self.sample()
        r['trace']['events'] = [x for x in r['trace']['events'] if x['type']!='action_reserved']
        with self.assertRaises(a.core.EvidenceError): a.clock_evidence(e,r)

    def test_zero_and_500_command_fresh_execution(self):
        for C in (0,500):
            config = next(c for c in self.plan['configurations'] if c['source_episode_id']==self.config['source_episode_id']
                          and c['factor']=='command_latency_ms' and c['value_ms']==C)
            e = a.materialize(config)
            for policy in a.design.POLICIES:
                provider=PublicProposals()
                trace,result=run_event_simulation(e,provider,policy,'',shared_safety_gate=True)
                r={'evaluation_episode_id':e['episode_id'],'policy':policy,'calls':provider.calls,'trace':trace,'result':result}
                scored=a.score(e,r)
                self.assertEqual(4,scored['denominators']['completed'])
                self.assertEqual(0,scored['metrics']['executed_capacity_violation_duration_ms'])
                self.assertTrue(all(z['attempt_ms']>=z['reservation_created_ms']+C for z in scored['command_clock_evidence']))
                self.assertTrue(all(t['logical_proposal_return_ms']==300 for t in scored['tasks'].values()))

    def test_empty_common_K(self):
        row={'required_task_ids':['a'],'completed_task_ids':[],'tasks':{}}
        out=a.core.time_compare([row,row],a.core.TIME_METRICS)
        self.assertEqual(0,out['common_count'])
        self.assertTrue(all(x['effects']['right_minus_left'] is None for x in out['metrics'].values()))

    def test_missing_metric_on_K_errors(self):
        row={'required_task_ids':['a'],'completed_task_ids':['a'],'tasks':{'a':{}}}
        with self.assertRaises(a.core.EvidenceError): a.core.time_compare([row,row],a.core.TIME_METRICS)

    def test_source_hash_mismatch(self):
        with patch.object(a,'sha',return_value='bad'),self.assertRaises(a.core.EvidenceError): a.verify_freeze()

    def test_perturbation_requires_gate(self):
        with patch.object(a,'verify_gate',side_effect=a.core.EvidenceError('missing gate')):
            with self.assertRaises(a.core.EvidenceError): a.generate_config(1)

    def test_gate_cannot_claim_checks(self):
        with patch.object(a,'read',return_value={'status':'passed'}),patch.object(a,'build_gate',return_value={'status':'failed'}):
            with self.assertRaises(a.core.EvidenceError): a.verify_gate()

    def test_saved_statistics_reproduced_without_simulation(self):
        with patch.object(a,'run_event_simulation',side_effect=AssertionError('must not simulate')):
            self.assertEqual(a.read(a.OUT+'/statistics.json'),a.statistics())

    def test_saved_fixed_populations_and_whitelist(self):
        data=a.read(a.OUT+'/statistics.json')
        rules=a.read(a.RULES)
        self.assertEqual(84,len(data['runs']))
        self.assertEqual(72,len(data['pairs']))
        for row in data['runs'].values():
            self.assertEqual(4,row['denominators']['required'])
            self.assertEqual(3,row['subsets']['early']['denominators']['required'])
            self.assertEqual(1,row['subsets']['water']['denominators']['required'])
        for pair in data['pairs']:
            self.assertEqual(set(rules['paired_scalar_allowlist']),set(pair['scalar_comparison']))
            self.assertEqual(set(rules['time_allowlist']),set(pair['conditional_time']['metrics']))

    def test_saved_materialized_input_tamper(self):
        doc=a.read(a.artifact_path(self.config))
        doc['input']['simulation']['command_latency_ms']=500
        with self.assertRaises(a.core.EvidenceError): a.validate_config(self.config,doc)

    def test_saved_missing_policy_slot(self):
        doc=a.read(a.artifact_path(self.config))
        doc['runs'].pop()
        with self.assertRaises(a.core.EvidenceError): a.validate_config(self.config,doc)

    def test_missing_saved_file_not_reweighted(self):
        original=a.read
        missing=a.artifact_path(self.plan['configurations'][1])
        def changed(path):
            if path==missing: raise FileNotFoundError(path)
            return original(path)
        with patch.object(a,'read',side_effect=changed),self.assertRaises(FileNotFoundError): a.statistics()


if __name__=='__main__':
    unittest.main()
