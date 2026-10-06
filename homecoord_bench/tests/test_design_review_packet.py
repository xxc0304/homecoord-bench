import sys
import json
import hashlib
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))
from homecoord_bench.task_revision.review_packet import inputs,bundle,verify_witness,serialize,OUT,GROUPS


class DesignReviewPacketTests(unittest.TestCase):
    def test_development_only_sources_and_counts(self):
        rows=inputs()
        self.assertEqual(71,len(rows))
        self.assertEqual(set(GROUPS),{r['group'] for r in rows})
        self.assertEqual(71,len({r['contract']['episode_id'] for r in rows}))
        for r in rows:
            self.assertNotIn('prospective_test',r['source_path'])
            self.assertNotIn('/results/',r['source_path'])
            self.assertNotIn('task_card',r['contract'])

    def test_no_result_or_holdout_or_run_content_reads(self):
        original=Path.read_text
        def guarded(p,*args,**kwargs):
            self.assertFalse({'results','runs','prospective_test'}&set(p.parts))
            return original(p,*args,**kwargs)
        with patch.object(Path,'read_text',guarded):bundle()

    def test_all_witnesses_independently_valid(self):
        data=bundle();rows={r['contract']['episode_id']:r['contract'] for r in data[f'{OUT}/contracts.json']['rows']}
        entries=data[f'{OUT}/feasibility.json']['entries']
        self.assertEqual(24,len(entries))
        self.assertEqual(40,sum(len(e['certificate']['mode_witnesses']) for e in entries))
        for e in entries:
            self.assertTrue(all(x['schedule'] is not None for x in e['certificate']['mode_witnesses']))
            verify_witness(rows[e['episode_id']],e['certificate'])

    def test_actual_pair_changes_expose_diagnostic_and_low_co2_controls(self):
        pairs=bundle()[f'{OUT}/pair_changes.json']['pairs']
        self.assertEqual(63,len(pairs))
        failed=next(p for p in pairs if p['after_id']=='DEP-LAUNDRY-FAILED_WASH')
        self.assertEqual([],failed['contract_differences'])
        low=[p for p in pairs if p['before_id'].startswith('ROOM-1600') and p['after_id'].startswith('ROOM-850')]
        self.assertEqual(12,len(low))
        for p in low:self.assertEqual(['initial_state.values.bedroom.co2_ppm'],[d['path'] for d in p['contract_differences']])

    def test_saved_packet_reproduction_and_hashes(self):
        data=bundle()
        for name,value in data.items():self.assertEqual(serialize(value),(ROOT/name).read_text(encoding='utf-8'))
        manifest=data[f'{OUT}/manifest.json']
        for name,digest in manifest['artifact_sha256'].items():
            self.assertEqual(digest,hashlib.sha256((ROOT/name).read_bytes()).hexdigest())
        self.assertIsNone(manifest['acceptance'])

    def test_f2_initial_public_requests_do_not_expose_future(self):
        for r in inputs():
            if r['group']!='C3-F2':continue
            e=r['contract'];requests=e['initial_state']['values']['coordination_context']['requests']
            self.assertTrue(all(t['release_at_ms']==0 for t in requests))


if __name__=='__main__':unittest.main()
