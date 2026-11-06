"""Synthetic contract checks for the historical-pool semester protocol."""
import copy

import pytest

from test_nested_learning import fixture
from src.rl.nested_learning import validate_round


def test_historical_pool_bootstrap_and_frozen_external_test(tmp_path):
    train, val, contract, spec = fixture(tmp_path)
    spec.update(calendar_protocol='semester-pool/1', semester_id='2024',
                cutoff_timestamp='2025-08-31T23:59:59+07:00')
    assert validate_round(train, val, contract, spec)['ready']
    for term, cutoff in [('2024', '2025-09-01T00:00:00+07:00'),
                         ('2025.3', '2026-08-31T23:59:59+07:00')]:
        changed = copy.deepcopy(spec)
        changed.update(semester_id=term, cutoff_timestamp=cutoff)
        with pytest.raises(ValueError):
            validate_round(train, val, contract, changed)


def test_main_training_rejects_small_budgets():
    from scripts.run_semester_rl import validate_budget
    with pytest.raises(ValueError, match='100000'):
        validate_budget(99999)
    assert validate_budget(100000) == 100000


def test_v3_advisor_source_policy_inherits_v2_snapshot_without_2025_2_corpus():
    from src.features.semester_suite import ADVISOR_SOURCE_POOLS
    assert ADVISOR_SOURCE_POOLS['2024'] == ('2024',)
    assert ADVISOR_SOURCE_POOLS['2025.1'] == ('2024', '2025.1')
    assert ADVISOR_SOURCE_POOLS['2025.2'] == ('2024', '2025.1')
    assert '2025.2' not in ADVISOR_SOURCE_POOLS['2025.2']


def test_survey_selection_keeps_latest_train_only_before_cutoff():
    from src.features.survey_feedback import select_rows
    rows = [
        {'student_id': '11220001', 'timestamp': '2026-01-01 10:00:00', 'source_row': 2},
        {'student_id': '11220001', 'timestamp': '2026-02-01 10:00:00', 'source_row': 3},
        {'student_id': '11220001', 'timestamp': '2026-06-01 10:00:00', 'source_row': 4},
        {'student_id': '11220002', 'timestamp': '2026-01-01 10:00:00', 'source_row': 5},
    ]
    selected, audit = select_rows(rows, {'11220001'}, '2026-05-31T23:59:59+07:00', '2025.2')
    assert [r['source_row'] for r in selected] == [3]
    assert audit['future_rows'] == 1 and audit['not_in_train'] == 1


def test_external_test_cannot_open_before_training_completion(tmp_path):
    from scripts.run_semester_rl import evaluate_final
    with pytest.raises(ValueError, match='completed_training'):
        evaluate_final(tmp_path / 'suites', tmp_path / 'training')
    assert not (tmp_path / 'training/final_test').exists()


def test_survey_mssv_join_keeps_known_information_and_audits_term_label():
    from src.features.survey_feedback import select_rows
    row = {'student_id': '11220001', 'timestamp': '2025-12-13T10:00:00', 'source_row': 2,
           'declared_term': 'Học kỳ 2 năm học 2025-2026 (Kỳ mùa xuân)', 'priority_1': 'Teacher A'}
    selected, audit = select_rows([row], {'11220001'}, '2025-12-31T23:59:59+07:00', '2025.1')
    assert selected == [row]
    assert audit['declared_term_mismatch'] == 1


def test_historical_supervision_outcome_updates_only_observed_student_advisor_preference():
    from src.features.survey_feedback import supervision_outcome_changes
    data = {'train': [{'student_ids': ['student-1'], 'advisor_ids': ['advisor-1', 'advisor-2'],
                       'preferences': [[0.0, 0.0]], 'preference_known': [[False, False]]}]}
    changes = supervision_outcome_changes(data, [{'student_id': 'student-1', 'advisor_id': 'advisor-2',
                                                   'status': 'matched_needs_review'}])
    assert changes == [
        {'student_id': 'student-1', 'advisor_id': 'advisor-2', 'field': 'preferences', 'old': 0.0, 'new': 1.0},
        {'student_id': 'student-1', 'advisor_id': 'advisor-2', 'field': 'preference_known', 'old': False, 'new': True},
    ]


def test_a_different_self_consistent_suite_is_not_the_frozen_suite(tmp_path):
    import json
    from scripts.run_semester_rl import verify_suites
    (tmp_path / 'manifest.json').write_text(json.dumps({'artifacts': {}}))
    with pytest.raises(ValueError, match='frozen_suite_manifest'):
        verify_suites(tmp_path, expected_manifest_sha256='0' * 64)


def test_bound_corpus_content_cannot_change_under_same_record_id(tmp_path):
    import json
    from src.features.fresh_suite import digest
    from scripts.run_semester_rl import verify_source_audit
    corpus = tmp_path / 'corpus.csv'
    corpus.write_text('record_id,content\na,original\n')
    audit = tmp_path / 'audit.json'
    audit.write_text(json.dumps({'suite_manifest_sha256':'a'*64, 'score_parity_verified':True,
                                'source_files':{str(corpus):digest(corpus)},'raw_files':{}}))
    corpus.write_text('record_id,content\na,changed\n')
    with pytest.raises(ValueError, match='source_audit_hash'):
        verify_source_audit(audit, 'a'*64)


def test_serving_does_not_load_an_unfinished_training_run(tmp_path):
    from src.serving.semester_service import load_semester_service
    with pytest.raises(ValueError, match='completed'):
        load_semester_service(tmp_path)


def test_serving_refuses_an_existing_but_incomplete_external_result(tmp_path):
    import json
    from src.serving.semester_service import load_semester_service
    (tmp_path/'training/final_test').mkdir(parents=True)
    (tmp_path/'training/status.json').write_text(json.dumps({'training_finished':True}))
    (tmp_path/'training/final_test/results.json').write_text('{}')
    with pytest.raises(ValueError, match='completed_external'):
        load_semester_service(tmp_path)
