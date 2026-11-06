import contextlib
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('advisor_skill_pipeline_cli', ROOT / 'scripts/advisor_skill_pipeline.py')
pipeline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pipeline)


def claim(channel, artifact, score, **updates):
    row = dict(advisor_id='A', skill_id='python', artifact_id=artifact, channel=channel,
               score=score, usage_status='used', review_status='approved',
               available_at='2026-01-01T00:00:00+07:00', split='train',
               training_eligibility='point_in_time_verified', evidence_id=artifact)
    row.update(updates)
    return row


class AdvisorSkillPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.profile = self.directory / 'profile.jsonl'
        self.theses = self.directory / 'theses.jsonl'
        self.registry = self.directory / 'registry.csv'
        self.output = self.directory / 'snapshot'
        pipeline.write_rows(self.profile, [claim('prediction', 'p', 70), claim('evidence', 'p', 90)])
        pipeline.write_rows(self.theses, [claim('thesis', 't1', 80), claim('thesis', 't2', 100),
                                        claim('thesis', 't3', None, usage_status='not_used'),
                                        claim('thesis', 'test', 0, split='test')])
        with self.registry.open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=['advisor_id', 'name'])
            writer.writeheader()
            writer.writerow({'advisor_id': 'A', 'name': 'Advisor A'})

    def score_arguments(self):
        return ['score', '--profile-claims', str(self.profile), '--thesis-claims', str(self.theses),
                '--registry', str(self.registry), '--cutoff', '2026-05-31T23:59:59+07:00',
                '--semester', '2025.2', '--scope', 'point_in_time_verified', '--output', str(self.output)]

    def call(self, args):
        with contextlib.redirect_stdout(io.StringIO()):
            return pipeline.main(args)

    def test_cli_extract_never_grants_approval(self):
        jobs = self.directory / 'jobs.jsonl'
        pipeline.write_rows(jobs, [dict(artifact_id='paper', advisor_id='A',
            text_units=[{'unit_id': '1', 'text': 'We use Python.'}],
            content_scope='full_text_complete', expected_units=['1'],
            review_status='approved', available_at='2026-01-01T00:00:00+07:00',
            split='train', training_eligibility='point_in_time_verified')])
        self.assertEqual(self.call(['extract', '--jobs', str(jobs), '--output', str(self.output)]), 0)
        rows = pipeline.read_rows(self.output / 'skill_evidence.jsonl')
        self.assertTrue(rows)
        self.assertTrue(all(row['review_status'] == 'pending' for row in rows))
        self.assertEqual(rows[0]['content_completeness'], 'complete')

    def test_document_identity_metadata_survives_and_blocks_scoring(self):
        candidate = {'artifact_id': 'possible-paper', 'title': 'Unverified title'}
        job = dict(artifact_id='actual-document', advisor_id='A',
                   text_units=[{'unit_id': '1', 'text': 'We use Python.'}],
                   content_scope='full_text_complete', expected_units=['1'],
                   available_at='2026-01-01T00:00:00+07:00', split='train',
                   training_eligibility='point_in_time_verified',
                   identity_review_status='pending', article_person_link_status='pending',
                   article_identity_review_status='pending', downloaded_document_matches_article=None,
                   document_sha256='a' * 64, candidate_publication=candidate)
        claims, _ = pipeline.extract_jobs([job])
        self.assertTrue(claims)
        for field in ('identity_review_status', 'article_person_link_status',
                      'article_identity_review_status', 'downloaded_document_matches_article',
                      'document_sha256', 'candidate_publication'):
            self.assertEqual(claims[0][field], job[field])
        # Marking the extraction itself approved must not approve identity links.
        evidence = dict(claims[0], review_status='approved')
        rows = pipeline.build_scores([claim('prediction', 'p', 70), evidence],
                                     [claim('thesis', 't', 100)], registry=['A'],
                                     cutoff='2026-05-31T23:59:59+07:00', scope='point_in_time_verified')
        self.assertIsNone(rows[0]['final_score'])
        self.assertEqual(rows[0]['status'], 'partial')

    def test_score_formula_split_filter_manifest_and_immutable_output(self):
        self.assertEqual(self.call(self.score_arguments()), 0)
        row = pipeline.read_rows(self.output / 'advisor_skill_scores.jsonl')[0]
        self.assertEqual((row['profile_score'], row['gvhd_score'], row['final_score']), (82, 90, 86))
        self.assertEqual(row['thesis_count'], 2)
        manifest = json.loads((self.output / 'snapshot_manifest.json').read_text(encoding='utf-8'))
        self.assertFalse(manifest['production_promoted'])
        self.assertEqual(manifest['input_hashes']['profile_claims'], pipeline.digest(self.profile))
        for field, source in (
                ('extraction_code_sha256', ROOT / 'src/data_pipeline/advisor_skill_extraction.py'),
                ('normalization_code_sha256', ROOT / 'src/data_pipeline/normalization.py'),
                ('pipeline_code_sha256', ROOT / 'scripts/advisor_skill_pipeline.py')):
            self.assertEqual(manifest[field], pipeline.digest(source))
        for name, digest in manifest['output_hashes'].items():
            self.assertEqual(hashlib.sha256((self.output / name).read_bytes()).hexdigest(), digest)
        before = {path.name: path.read_bytes() for path in self.output.iterdir()}
        with self.assertRaises(FileExistsError):
            self.call(self.score_arguments())
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.output.iterdir()})

    def test_registry_membership_rejected_before_output(self):
        pipeline.write_rows(self.profile, [claim('prediction', 'p', 70, advisor_id='outside')])
        with self.assertRaisesRegex(ValueError, 'advisor_outside_registry'):
            self.call(self.score_arguments())
        self.assertFalse(self.output.exists())

    def test_taxonomy_membership_rejected_before_output(self):
        pipeline.write_rows(self.profile, [claim('prediction', 'p', 70, skill_id='invented_skill')])
        with self.assertRaisesRegex(ValueError, 'skill_outside_taxonomy'):
            self.call(self.score_arguments())
        self.assertFalse(self.output.exists())

    def test_duplicate_registry_rejected(self):
        self.registry.write_text('advisor_id,name\nA,Advisor A\nA,Advisor A\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'unique_nonempty_registry_required'):
            self.call(self.score_arguments())
        self.assertFalse(self.output.exists())

    def test_old_semester_cannot_have_future_cutoff(self):
        args = self.score_arguments()
        args[args.index('--semester') + 1] = '2024'
        with self.assertRaisesRegex(ValueError, 'cutoff_outside_semester_protocol'):
            self.call(args)
        self.assertFalse(self.output.exists())

    def test_semester_end_is_exclusive_in_any_timezone(self):
        # 17:00 UTC equals midnight Asia/Saigon: already the following semester.
        pipeline.validate_snapshot_cutoff('2025.2', '2026-05-31T16:59:59Z')
        for timestamp in ('2026-05-31T17:00:00Z', '2026-06-01T00:00:00+07:00'):
            with self.subTest(timestamp=timestamp), self.assertRaisesRegex(
                    ValueError, 'cutoff_outside_semester_protocol'):
                pipeline.validate_snapshot_cutoff('2025.2', timestamp)
        with self.assertRaisesRegex(ValueError, 'timezone_timestamp_required'):
            pipeline.validate_snapshot_cutoff('2025.2', '2026-05-31T16:59:59')

    def test_external_source_cannot_be_relabelled_as_train(self):
        for field in ('source_pool', 'academic_term'):
            with self.subTest(field=field):
                pipeline.write_rows(self.profile, [claim('prediction', 'p', 70,
                                                       **{field: '2025.3'})])
                with self.assertRaisesRegex(ValueError, 'external_test_source_forbidden'):
                    self.call(self.score_arguments())
                self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
