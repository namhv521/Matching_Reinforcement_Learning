"""Inference-only local CSV proposals using technical fixtures, never real profiles."""
import csv
import io

import numpy as np
import pytest

from src.data_pipeline.csv_contracts import HEADERS
from src.serving.rebuild_service import RebuildService, export_rows_csv


class FrozenFixture:
    def fit(self, *args, **kwargs):
        raise AssertionError('upload_must_never_fit')

    def transform_score(self, students, advisors):
        scores = np.array([[.8 if j == 0 else .4 for j in range(len(advisors))] for _ in students])
        available = np.array([[bool(r['thesis_title'] != 'unscorable')]*len(advisors) for r in students])
        return {'scores': {'E4': scores}, 'available': {'E4': available}}

    def explain_pair(self, student, advisor):
        return {'scope': 'Technical lexical overlap only', 'shared_terms': ['technical']}


@pytest.fixture
def service(tmp_path):
    advisors = [{'advisor_id': 'a', 'advisor_name': 'Technical A', 'research_description': 'technical',
                 'source_url': 'https://example.test/a', 'source_sha256': 'a'*64},
                {'advisor_id': 'b', 'advisor_name': 'Technical B', 'research_description': 'technical',
                 'source_url': 'https://example.test/b', 'source_sha256': 'b'*64}]
    return RebuildService(pipeline=FrozenFixture(), advisors=advisors, taxonomy={'groups': {'topic_tags': {'nlp': {}}}},
                          versions={'encoder_sha256': 'c'*64}, runtime_dir=tmp_path / 'runtime',
                          scorable=[True, True])


def csv_text(rows):
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=HEADERS['students'])
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, '') for key in HEADERS['students']})
    return output.getvalue()


def upload(service, title='Technical thesis'):
    return service.validate_students(csv_text([{'student_id': 's1', 'student_name': 'Technical learner', 'thesis_title': title},
                                               {'student_id': 's2', 'thesis_title': title}]), scope='owner-a')


def test_minimal_csv_observed_provenance_pending_and_no_refit(service):
    report = upload(service)
    assert report['valid'] and report['row_count'] == 2
    rows = service.get_students(report['cohort_id'], scope='owner-a')
    assert rows[0]['source_type'] == 'user_csv'
    assert len(rows[0]['source_sha256']) == 64 and rows[0]['extracted_at']
    assert rows[0]['review_status'] == 'pending' and rows[0]['semester_id'] == 'local-upload'
    assert rows[0]['skill_confidence'] == '' and rows[0]['skill_proficiency_json'] == ''
    assert len(service.template('students').decode('utf-8-sig').splitlines()) == 1


def test_quota_policy_comes_from_the_loaded_model_versions(service):
    service.versions['quota_policy_version'] = 'user-authorized-equal-quota/1'
    assert service.quotas(2, ['a', 'b'])['policy_version'] == 'user-authorized-equal-quota/1'


def test_document_proxy_upload_keeps_confidence_unknown_but_requires_evidence(service):
    row = {'student_id': 's', 'thesis_title': 'Technical thesis', 'topic_tags': 'nlp',
           'skill_evidence_type': 'inferred_from_thesis', 'skill_evidence_refs': 'page 3'}
    assert not service.validate_students(csv_text([row]))['valid']
    service.versions['allow_unknown_document_confidence'] = True
    result = service.validate_students(csv_text([row]))
    assert result['valid']
    assert service.get_students(result['cohort_id'])[0]['skill_confidence'] == ''
    row['skill_evidence_refs'] = ''
    assert not service.validate_students(csv_text([row]))['valid']
    row['skill_evidence_refs'] = 'page 3'
    row['skill_confidence'] = 'invalid'
    assert not service.validate_students(csv_text([row]))['valid']


def test_recommendations_separate_from_quota_and_compare_has_truthful_unavailable_models(service):
    report = upload(service)
    recommendations = service.recommend(report['cohort_id'], ['a', 'b'], top_k=1, scope='owner-a')
    assert [r['recommendations'][0]['advisor_id'] for r in recommendations['rankings']] == ['a', 'a']
    quotas = service.quotas(2, ['b', 'a'])
    assert [q['capacity'] for q in quotas['quotas']] == [1, 1]
    with pytest.raises(ValueError, match='coordinator_confirmation_required'):
        service.compare(report['cohort_id'], ['a', 'b'], scope='owner-a')
    result = service.compare(report['cohort_id'], ['a', 'b'], coordinator_confirmed=True, scope='owner-a')
    assert result['results']['hungarian']['metrics']['coverage'] == 1
    assert result['results']['hungarian']['trace_replay_verified']
    assert result['results']['ppo']['status'] == 'unavailable'
    assert result['results']['dqn']['status'] == 'unavailable'
    assert result['policy']['scope'] == 'coordinator_confirmed_local_proposal'
    assert service.export(result['run_id'], 'hungarian', scope='owner-a').startswith(b'\xef\xbb\xbf')


def test_unknown_scores_are_masked_and_oov_upload_is_explicitly_infeasible(service):
    report = upload(service, 'unscorable')
    result = service.compare(report['cohort_id'], ['a', 'b'], coordinator_confirmed=True, scope='owner-a')
    assert result['results']['hungarian']['status'] == 'infeasible'
    assert result['results']['hungarian']['assignments'] == []


def test_import_strict_headers_duplicates_taxonomy_and_formula_injection(service):
    cases = [('student_id,thesis_title\ns1,title\n', 'header_contract'),
             (csv_text([{'student_id': 's', 'thesis_title': 'ok'}, {'student_id': 's', 'thesis_title': 'other'}]), 'duplicate_identity'),
             (csv_text([{'student_id': 's', 'thesis_title': '=cmd()'}]), 'spreadsheet_formula_not_allowed'),
             (csv_text([{'student_id': 's', 'thesis_title': 'ok', 'topic_tags': 'wrong'}]), 'unknown_taxonomy_tag')]
    for text, code in cases:
        report = service.validate_students(text, scope='owner-a')
        assert not report['valid'] and any(e['code'] == code for e in report['errors'])
    assert not service.validate_students('x'*(10*1024**2+1), scope='owner-a')['valid']


def test_scope_hashes_and_runtime_tampering_block_cross_session_reads(service):
    report = upload(service)
    with pytest.raises(ValueError, match='cohort_not_found'):
        service.get_students(report['cohort_id'], scope='other-owner')
    path = service.runtime_dir / 'cohorts' / (report['cohort_id'] + '.json')
    path.write_text('{}')
    with pytest.raises(ValueError, match='runtime_artifact_invalid'):
        service.get_students(report['cohort_id'], scope='owner-a')


def test_csv_export_neutralizes_spreadsheet_prefixes():
    encoded = export_rows_csv([{'name': '=cmd()', 'other': '\t+formula'}], ['name', 'other']).decode('utf-8-sig')
    assert "'=cmd()" in encoded and "'\t+formula" in encoded


def test_repeated_bytes_keep_same_cohort_and_first_observed_provenance(service):
    first = upload(service)
    before = service.get_students(first['cohort_id'], scope='owner-a')
    again = upload(service)
    assert first['cohort_id'] == again['cohort_id']
    assert service.get_students(again['cohort_id'], scope='owner-a') == before
    assert len(list((service.runtime_dir/'cohorts').iterdir())) == 1


def test_malformed_rows_count_toward_limit_and_restrictions_cannot_be_ignored(service):
    header = service.template('students').decode('utf-8-sig')
    report = service.validate_students(header+'bad-width\n'*2000)
    assert not report['valid'] and len(report['errors']) <= 501
    assert any(e['code'] == 'row_count_limit' for e in report['errors'])
    restrictions = service.validate_students(csv_text([{'student_id': 's', 'thesis_title': 'Technical', 'eligibility_flags': 'restricted'}]))
    assert not restrictions['valid']
    assert any(e['code'] == 'unsupported_eligibility_flags_require_explicit_policy' for e in restrictions['errors'])
    prefs = service.validate_students(csv_text([{'student_id': 's', 'thesis_title': 'Technical', 'preferred_advisor_ids': 'a'}]))
    assert prefs['valid'] and any('preferences' in w and 'not scored' in w for w in prefs['warnings'])
    compared = service.compare(prefs['cohort_id'], ['a'], coordinator_confirmed=True)
    assert any('preferences' in w and 'not scored' in w for w in compared['warnings'])
    assert 'not scored' in service.export(compared['run_id'], 'hungarian').decode('utf-8-sig')


def test_rl_inference_uses_mask_and_preserves_native_parent_contract(service):
    from src.environment.rebuild_env import MatchingEnv
    report = upload(service)
    _, problem = service._problem(report['cohort_id'], ['a', 'b'], 'owner-a')
    class InferenceOnly:
        def learn(self, *args):
            raise AssertionError('no_handler_training')
        def predict(self, obs, mask, deterministic=True):
            return int(np.flatnonzero(mask)[0])
        def probabilities(self, obs, mask):
            return mask.astype(float)/mask.sum()
        def q_values(self, obs):
            return np.array([1., .5])
    env = MatchingEnv([problem])
    native = {'state_contract': env.state_contract, 'reward_weights': env.reward_weights,
              'quota_policy_version': 'equal-division-canonical/1.0', 'training_student_ids': ['parent-training-only']}
    service.models = {'ppo': InferenceOnly(), 'dqn': InferenceOnly()}
    service.model_contracts = {'ppo': native, 'dqn': native}
    result = service.compare(report['cohort_id'], ['a', 'b'], coordinator_confirmed=True, scope='owner-a')
    assert all(result['results'][k]['status'] == 'feasible' for k in ('hungarian', 'ppo', 'dqn'))
    assert result['results']['ppo']['trace'][0]['policy_output']['kind'] == 'masked_policy_probability'
    assert result['results']['dqn']['trace'][0]['policy_output']['kind'] == 'q_value_not_probability'
    assert service.model_contracts['ppo'] == native
    assert 'feature_contract_sha256' not in problem.metadata
    native['quota_policy_version'] = 'foreign-policy'
    with pytest.raises(ValueError, match='inference_policy_contract_mismatch'):
        service.compare(report['cohort_id'], ['a', 'b'], coordinator_confirmed=True, scope='owner-a')


def advisor_csv(rows):
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=HEADERS['advisors'])
    writer.writeheader()
    writer.writerows([{k: row.get(k, '') for k in HEADERS['advisors']} for row in rows])
    return output.getvalue()


def test_faculty_csv_identical_catalog_preview_is_readonly_and_metadata_is_not_approval(service):
    import copy
    before = copy.deepcopy(service.advisors)
    files_before = list(service.runtime_dir.rglob('*'))
    report = service.validate_advisors(advisor_csv([before[0]]), scope='owner-a')
    assert report['valid'] and report['inference_compatible'] and not report['requires_rebuild']
    assert report['row_count'] == 1 and len(report['upload_sha256']) == 64
    assert report['rows'][0]['catalog_source_sha256'] == before[0]['source_sha256']
    assert report['registry_mutated'] is False
    assert service.advisors == before and list(service.runtime_dir.rglob('*')) == files_before


def test_new_or_changed_faculty_requires_rebuild_never_silently_reuses_checkpoint(service):
    import copy
    for change, code in [({'advisor_id': 'new-advisor'}, 'advisor_outside_frozen_registry'),
                         ({'research_description': 'A different technical subject'}, 'feature_content_changed'),
                         ({'advisor_name': 'Different identity'}, 'identity_redaction_registry_changed')]:
        row = {**copy.deepcopy(service.advisors[0]), **change}
        report = service.validate_advisors(advisor_csv([row]))
        assert report['valid'] and not report['inference_compatible'] and report['requires_rebuild']
        assert code in report['rows'][0]['reason_codes']
    assert service.advisor_ids == ('a', 'b') and not service.models


def test_faculty_csv_missing_id_unknown_header_duplicate_and_formula_are_row_errors(service):
    base = dict(service.advisors[0])
    for rows, code in [([{**base, 'advisor_id': ''}], 'text_cell_required'),
                       ([base, base], 'duplicate_identity'),
                       ([{**base, 'research_description': '=cmd()'}], 'spreadsheet_formula_not_allowed')]:
        report = service.validate_advisors(advisor_csv(rows))
        assert not report['valid'] and not report['inference_compatible']
        if code == 'text_cell_required':
            assert any(e['field'] == 'advisor_id' for e in report['errors'])
        else:
            assert any(e['code'] == code for e in report['errors'])
    assert not service.validate_advisors('advisor_id,unknown\na,value\n')['valid']
    oversized = service.validate_advisors('x'*(10*1024**2+1))
    assert not oversized['valid'] and oversized['errors'][0]['code'] == 'file_size_limit'
    malformed = service.validate_advisors(service.template('advisors').decode('utf-8-sig')+'wrong-width\n'*2000)
    assert len(malformed['errors']) <= 501 and any(e['code'] == 'row_count_limit' for e in malformed['errors'])
