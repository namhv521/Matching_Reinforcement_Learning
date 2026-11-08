import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('document_jobs', ROOT / 'scripts/prepare_advisor_document_jobs.py')
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)


class DocumentJobTests(unittest.TestCase):
    def test_failed_page_remains_empty_and_downgrades(self):
        records = [{'kind': 'block', 'page': 1, 'text': 'We use Python.'},
                   {'kind': 'page_outcome', 'page': 1, 'status': 'extracted'},
                   {'kind': 'block', 'page': 2, 'text': 'Unreliable partial text'},
                   {'kind': 'page_outcome', 'page': 2, 'status': 'failed'}]
        units, expected, complete, unread = bridge.text_inventory(records, 2)
        self.assertEqual(expected, ['page:1', 'page:2'])
        self.assertEqual(units[1]['text'], '')
        self.assertFalse(complete)
        self.assertEqual(unread[0]['unit_id'], 'page:2')

    def fixture(self, root, publications):
        raw = root / 'paper.pdf'
        raw.write_bytes(b'%PDF-placeholder-for-bridge-only')
        extracted = root / 'records.jsonl'
        rows = [{'kind': 'block', 'page': 1, 'text': 'We use Python.', 'source_sha256': bridge.digest(raw)},
                {'kind': 'page_outcome', 'page': 1, 'status': 'extracted', 'source_sha256': bridge.digest(raw)}]
        extracted.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
        receipt = {'status': 'pdf_extracted', 'request_id': 'r', 'page_count': 1,
                   'raw_path': raw.name, 'sha256': bridge.digest(raw),
                   'extraction_path': extracted.name, 'extracted_sha256': bridge.digest(extracted),
                   'publications': publications, 'url': 'https://example.org/paper.pdf'}
        (root / 'downloads.jsonl').write_text(json.dumps(receipt) + '\n', encoding='utf-8')
        return receipt

    def test_jobs_never_approve_title_match_or_availability(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'collection'
            root.mkdir()
            self.fixture(root, [{'advisor_id': 'A', 'artifact_id': 'candidate', 'title': 'Unverified title'}])
            out = Path(tmp) / 'jobs'
            report = bridge.prepare(root, out)
            row = bridge.read_rows(out / 'document_jobs.jsonl')[0]
            self.assertTrue(row['artifact_id'].startswith('document_'))
            self.assertEqual(row['candidate_publication_title'], 'Unverified title')
            self.assertNotIn('title', row)
            self.assertIsNone(row['downloaded_document_matches_article'])
            self.assertIsNone(row['available_at'])
            self.assertEqual(row['identity_review_status'], 'pending')
            self.assertEqual(row['content_scope'], 'full_text_complete')
            self.assertEqual(report['identity_approvals_granted'], 0)
            with self.assertRaises(FileExistsError):
                bridge.prepare(root, out)

    def test_missing_association_is_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'collection'
            root.mkdir()
            self.fixture(root, [])
            output = Path(tmp) / 'jobs'
            self.assertEqual(bridge.prepare(root, output)['jobs'], 0)
            self.assertEqual(bridge.read_rows(output / 'unresolved.jsonl')[0]['reason'], 'no_publication_association')

    def test_source_hash_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'collection'
            root.mkdir()
            self.fixture(root, [])
            (root / 'paper.pdf').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'artifact_path_or_hash_mismatch'):
                bridge.prepare(root, Path(tmp) / 'jobs')


if __name__ == '__main__':
    unittest.main()
