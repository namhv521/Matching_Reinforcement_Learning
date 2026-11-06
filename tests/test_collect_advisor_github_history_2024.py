import importlib.util
from pathlib import Path
import sys
import unittest

scripts = Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0, str(scripts))
from complete_advisor_github_history_2024 import select_git_log
spec = importlib.util.spec_from_file_location('history2024', scripts/'collect_advisor_github_history_2024.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class HistoryTests(unittest.TestCase):
    def test_creation_boundary_and_unknown(self):
        self.assertEqual(module.classify_repository({'created_at': '2024-12-31T16:59:59Z'}), 'eligible_event_date')
        self.assertEqual(module.classify_repository({'created_at': '2024-12-31T17:00:00Z'}), 'excluded_created_2025_or_later')
        self.assertEqual(module.classify_repository({'created_at': None}), 'unresolved_creation_date')

    def test_commit_date_is_event_not_historical_availability(self):
        row = {'sha': 'a'*40, 'commit': {'author': {'date': '2024-12-31T16:59:59Z'},
                                       'committer': {'date': '2024-12-31T16:59:59Z'}}}
        result = module.select_commit([row])
        self.assertFalse(result['historical_public_availability_verified'])
        row['commit']['author']['date'] = '2025-01-01T00:00:00Z'
        with self.assertRaises(ValueError):
            module.select_commit([row])

    def test_empty_and_fork_are_not_promoted(self):
        self.assertIsNone(module.select_commit([]))
        self.assertEqual(module.classify_repository({'created_at': '2020-01-01T00:00:00Z', 'fork': True}),
                         'excluded_fork_without_verified_contribution')

    def test_git_fallback_never_uses_future_head(self):
        body=('a'*40+'\t2026-01-01T00:00:00+00:00\t2026-01-01T00:00:00+00:00\n'
              +'b'*40+'\t2024-02-01T00:00:00+00:00\t2024-02-02T00:00:00+00:00\n').encode()
        self.assertEqual(select_git_log(body)['sha'], 'b'*40)


if __name__ == '__main__':
    unittest.main()
