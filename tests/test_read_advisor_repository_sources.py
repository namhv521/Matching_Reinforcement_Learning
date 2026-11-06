import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('reader',
    Path(__file__).resolve().parents[1] / 'scripts/read_advisor_repository_sources.py')
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


class SourceReadingTests(unittest.TestCase):
    def test_reads_whole_text_and_preserves_budget_misses(self):
        tree = [dict(path='src/a.py', mode='100644', oid='a', size=3),
                dict(path='src/b.py', mode='100644', oid='b', size=4),
                dict(path='vendor/a.py', mode='100644', oid='c', size=3),
                dict(path='link.py', mode='120000', oid='d', size=5)]
        calls = []
        def blob(oid):
            calls.append(oid)
            return b'abc'
        with tempfile.TemporaryDirectory() as temp:
            result = reader.read_tree(tree, blob, temp, max_file_bytes=3)
            self.assertEqual(calls, ['a'])
            self.assertEqual(result['bytes_read'], 3)
            self.assertEqual(len(result['missing_units']), 1)
            self.assertEqual(len(result['skipped_units']), 2)
            self.assertEqual(result['content_scope'], 'partial_full_text')
            self.assertFalse(result['whole_repository_audit'])

    def test_no_network_for_unsafe_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                reader.collect_source_reading('person/../evil', 'a'*40, Path(temp)/'out')

    def test_root_collection_does_not_read_nested_docs_or_code(self):
        tree = [dict(path='README.md', mode='100644', oid='a', size=3),
                dict(path='docs/README.md', mode='100644', oid='b', size=3),
                dict(path='main.py', mode='100644', oid='c', size=3)]
        calls = []
        def blob(oid):
            calls.append(oid)
            return b'abc'
        with tempfile.TemporaryDirectory() as temp:
            result = reader.read_tree(tree, blob, temp, root_readme_only=True)
        self.assertEqual(calls, ['a'])
        self.assertEqual(result['collection_scope'], 'root_readme_and_tree_only')
        self.assertEqual(len(result['skipped_units']), 2)


if __name__ == '__main__':
    unittest.main()
