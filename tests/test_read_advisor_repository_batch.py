import importlib.util
from pathlib import Path
import sys
import unittest
import json
import tempfile

scripts = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(scripts))
spec = importlib.util.spec_from_file_location('batch_reader', scripts / 'read_advisor_repository_batch.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BatchCodeTests(unittest.TestCase):
    def test_import_without_use_is_not_scored(self):
        claims = module.code_claims({'unit_id': 'a.py', 'text': 'import torch\n', 'sha256': 'hash'},
            artifact_id='repo', advisor_id='a', taxonomy=module.load_taxonomy())
        self.assertEqual(claims[0]['skill_id'], 'pytorch')
        self.assertIsNone(claims[0]['score'])
        self.assertEqual(claims[0]['review_status'], 'pending')

    def test_framework_call_has_exact_quote(self):
        claims = module.code_claims({'unit_id': 'a.py', 'text': 'from torch import nn\nmodel=nn.Linear(3, 4)\n', 'sha256': 'hash'},
            artifact_id='repo', advisor_id='a', taxonomy=module.load_taxonomy())
        self.assertEqual(claims[0]['score'], 80)
        self.assertEqual(claims[0]['quote'], 'nn.Linear(3, 4)')
        self.assertEqual(claims[0]['locator']['line'], 2)

    def test_rebound_alias_or_parameter_cannot_prove_framework_call(self):
        for code in ['import torch\ntorch=lambda:0\ntorch()',
                     'import torch\ndef f(torch):\n return torch()']:
            result = module.code_claims({'unit_id': 'a.py', 'text': code, 'sha256': 'hash'},
                artifact_id='repo', advisor_id='a', taxonomy=module.load_taxonomy())
            self.assertIsNone(result[0]['score'])

    def test_merge_keeps_max_and_all_evidence(self):
        base = {'artifact_id': 'repo', 'skill_id': 'pytorch', 'channel': 'evidence'}
        result = module.merge_claims([{**base, 'score': 60, 'evidence_id': 'text'},
                                      {**base, 'score': 80, 'evidence_id': 'code'}])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['score'], 80)
        self.assertEqual(result[0]['evidence_refs'], ['text', 'code'])

    def test_isolated_job_keeps_pending_partial_identity_and_merges(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            text = '# We use PyTorch.\nimport torch\nx=torch.randn(2)\n'
            unit = {'unit_id': 'a.py', 'text': text, 'sha256': module.digest(text.encode())}
            (root/'text_units.jsonl').write_text(json.dumps(unit)+'\n', encoding='utf-8')
            (root/'manifest.json').write_text(json.dumps({'missing_units': [],
                'content_scope': 'candidate_text_complete'}), encoding='utf-8')
            job = {'source_path': str(root), 'source_manifest_sha256': module.digest((root/'manifest.json').read_bytes()),
                   'artifact_id': 'repo@sha', 'advisor_id': 'a', 'claims_path': str(root/'claims.jsonl'),
                   'result_path': str(root/'result.json')}
            module.extract_job(job)
            claims = [json.loads(line) for line in (root/'claims.jsonl').read_text().splitlines()]
            pytorch = next(c for c in claims if c['skill_id'] == 'pytorch')
            self.assertEqual(pytorch['score'], 80)
            self.assertGreaterEqual(len(pytorch['evidence_refs']), 2)
            self.assertEqual(pytorch['identity_review_status'], 'pending')
            self.assertEqual(pytorch['content_completeness'], 'partial')
            self.assertIsNone(pytorch['available_at'])


if __name__ == '__main__':
    unittest.main()
