from datetime import date

import pytest

from src.data_pipeline.advisor_skill_snapshot import storage_pool_for_date


def test_calendar_2025_advisor_artifacts_are_stored_in_2025_1():
    assert storage_pool_for_date('2025-01-01') == '2025.1'
    assert storage_pool_for_date('2025-12-31') == '2025.1'


@pytest.mark.parametrize('event_date', [date(2026, 1, 1), date(2026, 5, 31), date(2026, 8, 31)])
def test_calendar_2026_advisor_artifacts_are_excluded(event_date):
    with pytest.raises(ValueError, match='calendar_year_2026_or_later_excluded_from_advisor_corpus'):
        storage_pool_for_date(event_date.isoformat())