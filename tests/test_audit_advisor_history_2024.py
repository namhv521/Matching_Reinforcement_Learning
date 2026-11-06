import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('history2024_audit',
    Path(__file__).resolve().parents[1] / 'scripts/audit_advisor_history_2024.py')
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class CalendarHistoryAuditTests(unittest.TestCase):
    def test_exclusive_boundary_in_local_timezone(self):
        self.assertEqual(module.classify_date('2024-12-31T23:59:59+07:00')['status'], 'calendar_eligible')
        self.assertEqual(module.classify_date('2024-12-31T16:59:59Z')['status'], 'calendar_eligible')
        self.assertEqual(module.classify_date('2024-12-31T17:00:00Z')['status'], 'after_2024')
        self.assertEqual(module.classify_date('2025-01-01T00:00:00+07:00')['status'], 'after_2024')

    def test_year_only_is_enough_for_calendar_not_academic_term(self):
        result = module.classify_date('2024')
        self.assertEqual(result['status'], 'calendar_eligible')
        self.assertIsNone(result['academic_term'])
        self.assertEqual(module.classify_date('2025')['status'], 'after_2024')

    def test_unknown_and_reference_year_not_inferred(self):
        status, _ = module.classify_corpus({'content': 'References 2023', 'title': 'Paper 2024',
                                           'collected_at': '2024-01-01', 'academic_term': '2024.1'})
        self.assertEqual(status, 'unknown_date')
        self.assertEqual(module.classify_date('2024-12-31T23:00:00')['status'], 'invalid')

    def test_conflict_not_silently_resolved(self):
        self.assertEqual(module.classify_corpus({'published_at': '2024', 'event_date': '2025-01-01'})[0], 'conflicting_dates')


if __name__ == '__main__':
    unittest.main()
