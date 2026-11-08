import importlib.util
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('supervision', ROOT / 'scripts/prepare_advisor_supervision.py')
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class SupervisionTests(unittest.TestCase):
    def test_label_required_and_match_is_only_candidate(self):
        roster = [{'advisor_id': 'a', 'name': 'TS PHẠM XUÂN LÂM'}]
        self.assertEqual(module.advisor_candidates([{'page': 1, 'text': 'Phạm Xuân Lâm'}], roster), {})
        result = module.advisor_candidates([{'page': 1, 'text': 'Giảng viên hướng dẫn: TS. Phạm Xuân Lâm\nSinh viên: A'}], roster)
        self.assertEqual(list(result), ['a'])
        self.assertEqual(result['a'][0]['page'], 1)

    def test_cover_window_and_pool_boundary(self):
        self.assertEqual(module.month_partition('2025-08'), ('2024', '2024.3'))
        self.assertEqual(module.month_partition('2025-09'), ('2025.1', '2025.1'))
        self.assertEqual(module.month_partition('2026-06'), ('2025.3', '2025.3'))
        with self.assertRaises(ValueError):
            module.month_partition('2026-13')

    def test_bibliography_preserved_but_excluded_from_claims(self):
        units = module.thesis_units([{'page': 1, 'text': 'We use Python.\nTÀI LIỆU THAM KHẢO\nWe use TensorFlow.'},
                                     {'page': 2, 'text': 'We use PyTorch.'}])
        self.assertIn('Python', units[0]['text'])
        self.assertEqual(units[1]['section'], 'references')
        self.assertEqual(units[2]['section'], 'references')

    def test_batch_is_pending_deduplicates_students_and_excludes_external(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / 'data'
            registry = root / 'registry.csv'
            registry.write_text('advisor_id,name\na,TS PHẠM XUÂN LÂM\n', encoding='utf-8')
            source = data / '2024/student/KLTN/thesis.pdf'
            source.parent.mkdir(parents=True)
            source.write_bytes(b'test source bytes; page reader is mocked')
            fields = ['student_id', 'source_file', 'source_type', 'source_sha256', 'reviewer_notes']
            fields += ['unused_' + str(i) for i in range(40-len(fields))]
            notes = json.dumps({'cover_date': {'date': '2025-05', 'quote': 'Hà Nội, 5/2025',
                                               'page': 1, 'status': 'resolved'}})
            row = dict(source_file='2024/student/KLTN/thesis.pdf', source_type='pdf',
                       source_sha256=module.digest(source), reviewer_notes=notes)
            before = {}
            for pool in ('2024', '2025.1', '2025.2', '2025.3'):
                target = data / pool / 'student/students_processed/students_processed.csv'
                target.parent.mkdir(parents=True)
                with target.open('w', encoding='utf-8', newline='') as stream:
                    writer = csv.DictWriter(stream, fieldnames=fields)
                    writer.writeheader()
                    if pool == '2024':
                        writer.writerows([dict(row, student_id='s1'), dict(row, student_id='s2')])
                    elif pool == '2025.3':
                        writer.writerow(dict(row, student_id='held-out', source_file='not-opened.pdf'))
                before[target] = target.read_bytes()
            pages = [{'page': 1, 'text': 'Giảng viên hướng dẫn: Phạm Xuân Lâm\nWe use Python.', 'status': 'extracted'}]
            cached = root / 'cached.jsonl'
            cached.write_text('mock fulltext', encoding='utf-8')
            with patch.object(module, 'read_pdf_pages', return_value=(pages, {'path': str(cached), 'sha256': module.digest(cached), 'method': 'existing_page_text_cache'})):
                report = module.prepare(data, registry, root / 'output')
            self.assertEqual(report['candidate_links'], 1)
            self.assertEqual(report['excluded_external_students'], 1)
            job = json.loads((root / 'output/thesis_jobs.jsonl').read_text(encoding='utf-8'))
            self.assertEqual(job['student_ids'], ['s1', 's2'])
            self.assertEqual(job['supervision_review_status'], 'pending')
            self.assertEqual(job['identity_review_status'], 'pending')
            self.assertIsNone(job['available_at'])
            self.assertIsNone(job['split'])
            self.assertEqual(job['training_eligibility'], 'unresolved')
            self.assertTrue(all(path.read_bytes() == content for path, content in before.items()))
            stop = root / 'STOP'
            stop.write_text('quota checkpoint', encoding='utf-8')
            with patch.object(module, 'read_pdf_pages', side_effect=AssertionError('STOP must avoid reading PDF')):
                stopped = module.prepare(data, registry, root / 'stopped', stop_file=stop)
            self.assertEqual(stopped['candidate_links'], 0)
            self.assertEqual(stopped['source_coverage_counts']['pending_stop_requested'], 2)
            self.assertTrue((root / 'stopped/manifest.json').is_file())


if __name__ == '__main__':
    unittest.main()
