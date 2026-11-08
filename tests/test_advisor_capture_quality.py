import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('capture_quality', ROOT / 'scripts/audit_advisor_capture_quality.py')
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class CaptureQualityTests(unittest.TestCase):
    def test_long_vietnamese_block_notice_is_not_readable_content(self):
        result = audit.classify_capture({'text': 'Lưu lượng truy cập bất thường. ' * 100,
                                         'source_title': 'Paper'}, '1')
        self.assertEqual(result['access_status'], 'blocked')
        self.assertFalse(result['full_text_verified'])

    def test_url_and_multilingual_access_blocks(self):
        for source in ('https://www.google.com/sorry/index', 'https://site.test/captcha/'):
            self.assertEqual(audit.classify_capture({'text': 'x' * 400, 'url': source}, '1')['access_status'], 'blocked')
        for text in ('Security check required', 'Verify you are human', '异常流量', 'Trafic inhabituel'):
            self.assertEqual(audit.classify_capture({'text': text}, '1')['access_status'], 'blocked')

    def test_generic_label_never_becomes_verified_title_or_identity(self):
        result = audit.classify_capture({'text': 'Article content ' * 40, 'source_title': 'View'}, '1')
        self.assertTrue(result['generic_title'])
        self.assertEqual(result['article_person_status'], 'needs_review')
        self.assertFalse(result['historical_training_ready'])

    def test_audit_preserves_sources_hashes_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            details = root / 'details'
            details.mkdir()
            source = details / '15.json'
            source.write_text(json.dumps({'source_title': audit.KNOWN_REVIEWER_FLAGS['15'][0],
                                           'text': 'Content ' * 60}), encoding='utf-8')
            before = source.read_bytes()
            output = root / 'output'
            report = audit.audit(details, output)
            self.assertEqual(report['known_reviewer_attribution_flags'], 1)
            self.assertEqual(source.read_bytes(), before)
            manifest = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['input_hashes'][str(source.resolve())], audit.digest(source))
            with self.assertRaises(FileExistsError):
                audit.audit(details, output)


if __name__ == '__main__':
    unittest.main()
