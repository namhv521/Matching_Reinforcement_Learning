import unittest

from src.data_pipeline.advisor_skill_extraction import extract_skill_claims


def extract(text, scope='title_only', **kwargs):
    return extract_skill_claims([{'unit_id': '1', 'text': text}], content_scope=scope,
                                artifact_id='paper-a', advisor_id='advisor-a', **kwargs)


class ExtractionTests(unittest.TestCase):
    def test_title_does_not_guess_framework(self):
        result = extract('Phân tích cảm xúc tiếng Việt bằng học sâu')
        claims = {c['skill_id']: c for c in result['claims']}
        self.assertEqual(claims['nlp']['score'], 50)
        self.assertNotIn('pytorch', claims)
        self.assertNotIn('tensorflow', claims)
        self.assertTrue(all(c['review_status'] == 'pending' for c in claims.values()))

    def test_title_direct_framework(self):
        tf = next(c for c in extract('Phân loại sử dụng TensorFlow')['claims']
                  if c['skill_id'] == 'tensorflow')
        self.assertEqual(tf['score'], 100)
        self.assertEqual(tf['channel'], 'prediction')

    def test_fulltext_reads_inventory_and_preserves_offsets(self):
        text = 'We implemented using PyTorch and evaluated accuracy.'
        result = extract(text, 'full_text_complete', expected_units=['1'])
        self.assertEqual(result['content_scope'], 'full_text_complete')
        claim = next(c for c in result['claims'] if c['skill_id'] == 'pytorch')
        self.assertEqual(claim['score'], 100)
        self.assertEqual(text[claim['locator']['start']:claim['locator']['end']], claim['quote'])
        self.assertEqual(text[claim['locator']['mention_start']:claim['locator']['mention_end']], 'PyTorch')

    def test_missing_pages_and_unknown_inventory_are_not_complete(self):
        result = extract('We use Python.', 'full_text_complete', expected_units=['1', '2'])
        self.assertEqual(result['content_scope'], 'partial_full_text')
        self.assertEqual(result['missing_units'], ['2'])
        self.assertEqual(result['content_completeness'], .5)
        self.assertEqual(extract('Python', 'full_text_complete')['content_scope'], 'partial_full_text')

    def test_unsupported_contexts_not_scored(self):
        for text in ['Related work\nWe use TensorFlow.', 'We did not use TensorFlow.',
                     'We plan to use TensorFlow.', 'Dependency: TensorFlow.']:
            with self.subTest(text=text):
                claim = next(c for c in extract(text, 'abstract_only')['claims']
                             if c['skill_id'] == 'tensorflow')
                self.assertIsNone(claim['score'])
                self.assertNotEqual(claim['usage_status'], 'used')

    def test_duplicate_and_invalid_units_rejected(self):
        with self.assertRaises(ValueError):
            extract_skill_claims([{'unit_id': '1', 'text': 'Python'}] * 2,
                                 content_scope='title_only', artifact_id='a', advisor_id='b')

    def test_conservative_negation_future_and_comparisons(self):
        for text in ['We do not employ TensorFlow.', 'We will implement using TensorFlow.',
                     'Compared with TensorFlow, we use PyTorch.']:
            with self.subTest(text=text):
                result = extract(text, 'abstract_only')
                self.assertTrue(result['claims'])
                self.assertTrue(all(c['score'] is None and c['usage_status'] != 'used'
                                    for c in result['claims']))
        result = extract('A survey of TensorFlow')
        self.assertTrue(all(c['score'] is None and c['usage_status'] != 'used'
                            for c in result['claims']))

    def test_claim_completeness_is_scorer_compatible(self):
        complete = extract('We use Python.', 'full_text_complete', expected_units=['1'])
        partial = extract('We use Python.', 'full_text_complete', expected_units=['1', '2'])
        self.assertEqual(complete['claims'][0]['content_completeness'], 'complete')
        self.assertEqual(partial['claims'][0]['content_completeness'], 'partial')
        self.assertEqual(partial['content_completeness'], .5)


if __name__ == '__main__':
    unittest.main()
