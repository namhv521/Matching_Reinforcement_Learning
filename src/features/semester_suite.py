"""Frozen CSV-to-native-RL adapter for the 2024 historical-pool protocol."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from src.data_pipeline.normalization import load_taxonomy
from src.data_pipeline.review_decisions import record_hash
from src.domain.rebuild_matching import AllocationProblem, equal_quotas, feasible
from src.environment.rebuild_env import MatchingEnv
from src.evaluation.rebuild_benchmark import problem_payload
from src.features.fresh_suite import digest, fit_encoder, restore_encoder, write_json
from src.features.rebuild_features import preprocess_text

VERSIONS = {'V1': '2024', 'V2': '2025.1', 'V3': '2025.2'}
CUTOFFS = {'2024': '2025-08-31', '2025.1': '2025-12-31', '2025.2': '2026-05-31', '2025.3': '2026-08-31'}
ADVISOR_SOURCE_POOLS = {
    '2024': ('2024',),
    '2025.1': ('2024', '2025.1'),
    # V3 intentionally learns from 2025.2 student theses only. Its fixed advisor
    # representation is inherited from the V2 source snapshot; no 2026 corpus is read.
    '2025.2': ('2024', '2025.1'),
    '2025.3': ('2024', '2025.1'),
}
SCOPE = 'retrospective_document_proxy'
QUOTA = 'user-authorized-equal-quota/1'


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def student_text(row, identities):
    text = '\n'.join(row.get(key, '') for key in ('thesis_title', 'thesis_abstract', 'thesis_keywords',
                                                 'skills_tags', 'research_domain_tags', 'topic_tags'))
    return preprocess_text(text, [*identities, row.get('student_name', ''), row['student_id']])[0]


def prepare_suites(inputs, output, *, quota_policy, seed=42):
    if quota_policy != 'equal':
        raise ValueError('explicit_user_authorized_equal_quota_required')
    inputs, output = Path(inputs).resolve(), Path(output).resolve()
    if output.exists() or output.is_relative_to(inputs):
        raise ValueError('fresh_output_outside_frozen_inputs_required')
    checksums = json.loads((inputs / 'checksums.json').read_text())
    for name, sha in checksums.items():
        path = (inputs / name).resolve()
        if not path.is_relative_to(inputs) or digest(path) != sha:
            raise ValueError('prepared_input_hash_mismatch')
    roster = sorted(read_csv(inputs / '2024/advisors_profile.csv'), key=lambda r: r['advisor_id'])
    advisor_ids = tuple(r['advisor_id'] for r in roster)
    identities = [r['name'] for r in roster]
    taxonomy = load_taxonomy(inputs / 'taxonomy_v1.yaml')
    order = sorted((group, tag) for group, entries in taxonomy['groups'].items() for tag in entries)
    taxonomy_sha = record_hash({'version': 'document-concept-presence/1', 'order': order})
    bootstrap = read_csv(inputs / '2024/students_train.csv')
    encoder, frozen = fit_encoder([student_text(r, identities) for r in bootstrap])
    frozen['fit_student_ids'] = [r['student_id'] for r in bootstrap]
    frozen['input_manifest_sha256'] = digest(inputs / 'manifest.json')
    feature_contract = {'encoder': frozen, 'concept_order': order,
                        'score': 'char_tfidf_cosine', 'student_features': 'document_concept_presence_with_known_mask'}
    feature_sha = record_hash(feature_contract)
    corpus_sources = {str((inputs.parent / t / 'advisors/faculty_corpus/advisors_corpus.csv').resolve()):
                      digest(inputs.parent / t / 'advisors/faculty_corpus/advisors_corpus.csv')
                      for pools in ADVISOR_SOURCE_POOLS.values() for t in pools}
    output.mkdir(parents=True)
    write_json(output / 'encoder.json', frozen)
    write_json(output / 'feature_contract.json', feature_contract)
    report = {'schema_version': 'semester-suites/1', 'scope': SCOPE, 'prediction_time_verified': False,
              'quota_policy': QUOTA, 'advisor_ids': list(advisor_ids), 'versions': {},
              'input_checksums_sha256': digest(inputs / 'checksums.json'), 'external_test_used_for_fit': False}
    report['faculty_corpus_sources'] = corpus_sources
    memberships = {}
    now = datetime.now(timezone.utc).isoformat()
    for version, term in [*VERSIONS.items(), ('external_test', '2025.3')]:
        directory = output / version
        directory.mkdir()
        advisor_source_term = ADVISOR_SOURCE_POOLS[term][-1]
        advisor_rows = read_csv(inputs / advisor_source_term / 'advisors_processed.csv')
        by_id = {r['advisor_id']: r for r in advisor_rows}
        if set(by_id) != set(advisor_ids):
            raise ValueError('fixed_advisor_registry_required')
        # Only records selected for this snapshot are used; raw current profiles
        # and unresolved/future records never enter the historical feature text.
        data_root = inputs.parent
        records = {}
        for historical_term in ADVISOR_SOURCE_POOLS[term]:
            for record in read_csv(data_root / historical_term / 'advisors/faculty_corpus/advisors_corpus.csv'):
                records[record['record_id']] = record
        advisor_texts = []
        used_ids = []
        for aid in advisor_ids:
            ids = json.loads(by_id[aid]['source_record_ids'])
            if any(rid not in records or records[rid]['advisor_id'] != aid for rid in ids):
                raise ValueError('advisor_record_provenance_mismatch')
            used_ids.extend(ids)
            advisor_texts.append(preprocess_text('\n'.join(records[rid]['content'] for rid in ids), identities)[0])
        write_json(directory / 'faculty_records.json', [records[rid] for rid in sorted(set(used_ids))])
        right = encoder.transform(advisor_texts)
        present = right.getnnz(axis=1) > 0
        active = [aid for aid, known in zip(advisor_ids, present) if known]
        if not active:
            raise ValueError('advisor_feature_coverage_required')
        problems = {}
        split_names = ('external_test',) if version == 'external_test' else ('train', 'validation')
        for split in split_names:
            rows = read_csv(inputs / term / ('students_' + split + '.csv'))
            if not rows:
                raise ValueError('empty_cohort')
            ids = tuple(r['student_id'] for r in rows)
            role = 'test' if split == 'external_test' else split
            for sid in ids:
                if sid in memberships and memberships[sid] != role:
                    raise ValueError('student_cross_split_leakage')
                memberships[sid] = role
            left = encoder.transform([student_text(r, identities) for r in rows])
            known = np.outer(left.getnnz(axis=1) > 0, present)
            if not known.any(axis=1).all():
                raise ValueError('student_text_feature_coverage_required')
            features = np.array([[float(tag in set(r.get(group, '').split(';'))) for group, tag in order] for r in rows])
            problems[role] = AllocationProblem(
                scores=np.clip((left @ right.T).toarray(), 0, 1), available=known,
                student_ids=ids, advisor_ids=advisor_ids, capacities=equal_quotas(len(ids), advisor_ids, active),
                eligible=np.ones((len(ids), len(advisor_ids)), dtype=bool), present=present,
                student_features=features, student_feature_known=features.astype(bool),
                metadata={'split': role, 'scope': SCOPE, 'semester_id': term, 'feature_contract_sha256': feature_sha,
                          'taxonomy_feature_order_sha256': taxonomy_sha, 'policy_version': QUOTA,
                          'quota_semantics': 'user_authorized_equal_distribution_not_observed_institutional_capacity'})
            if not feasible(problems[role]):
                raise ValueError('infeasible_prepared_cohort')
        if version == 'external_test':
            write_json(directory / 'problem.json', problem_payload(problems['test']))
            report['external_test_students'] = len(problems['test'].student_ids)
            continue
        train = [problem_payload(problems['train'])]
        validation = problem_payload(problems['validation'])
        env = MatchingEnv([problems['train']])
        contract = {'scope': SCOPE, 'state_contract': env.state_contract, 'feature_contract_sha256': feature_sha,
                    'taxonomy_feature_order_sha256': taxonomy_sha, 'quota_policy_version': QUOTA,
                    'reward_weights': env.reward_weights, 'training_student_ids': list(problems['train'].student_ids),
                    'training_semester_ids': [term], 'dataset_snapshot_sha256': digest(inputs / 'checksums.json')}
        signal_id = 'initial-' + version + '-' + record_hash({'train': train, 'advisor_records': sorted(used_ids)})[:16]
        upper = CUTOFFS[term] + 'T23:59:59+07:00'
        snapshot = {'scope': SCOPE, 'version': version, 'signal_ids': [signal_id], 'prediction_time_verified': False,
                    'initial_source_event_upper_bound': upper,
                    'event_bound_semantics': 'cohort_partition_upper_bound_including_explicit_user_overrides_not_claimed_publication_day',
                    'training_problem_sha256': [record_hash(p) for p in train],
                    'validation_problem_sha256': record_hash(validation), 'input_checksums_sha256': digest(inputs / 'checksums.json'),
                    'advisor_record_ids': sorted(used_ids)}
        write_json(directory / 'snapshot.json', snapshot)
        spec = {'calendar_protocol': 'semester-pool/1', 'semester_id': term, 'round_id': version + '-R1', 'round_index': 1,
                'algorithm': 'ppo', 'seed': seed, 'snapshot_path': str(directory / 'snapshot.json'),
                'snapshot_sha256': digest(directory / 'snapshot.json'), 'cutoff_timestamp': upper,
                'reward_version': 'native-score-preference-fairness/1.0', 'constraint_version': QUOTA,
                'signal_state_sha256': record_hash([signal_id]), 'availability_assumption': 'retrospective_event_time_proxy',
                'decision_thresholds': {'min_improvement': 0., 'max_new_drop': 0., 'max_old_drop': 0., 'accept_non_regression': True},
                'signals': [{'signal_id': signal_id, 'type': 'initial_source', 'source_path': str(directory / 'snapshot.json'),
                             'source_sha256': digest(directory / 'snapshot.json'), 'available_at': now, 'event_upper_bound': upper,
                             'review_status': 'source_verified', 'provenance': 'source_hash_verified_not_historical_availability_approval'}]}
        write_json(directory / 'suite.json', {'train': train, 'validation': validation, 'contract': contract, 'round': spec,
                                            'experiment_scope': 'source_documents_and_user_authorized_equal_capacity'})
        report['versions'][version] = {'semester_id': term, 'train': len(problems['train'].student_ids),
                                       'validation': len(problems['validation'].student_ids), 'advisor_records': len(used_ids),
                                       'advisor_source_pools': list(ADVISOR_SOURCE_POOLS[term]),
                                       'advisor_representation_origin': advisor_source_term}
    for source, sha in corpus_sources.items():
        if digest(source) != sha:
            raise ValueError('faculty_corpus_changed_during_preparation')
    write_json(output / 'readiness.json', report)
    write_json(output / 'manifest.json', {'schema_version': 'semester-suites/1', 'artifacts': {
        p.relative_to(output).as_posix(): digest(p) for p in output.rglob('*') if p.is_file()}})
    return report


def audit_existing_sources(suites, inputs, output):
    """Bind existing immutable matrices to current source bytes by exact parity.

    This is a new audit receipt, not a claim the hashes were recorded earlier.
    The already-trained R1 input/checkpoint and original suite remain untouched.
    """
    suites, inputs, output = map(lambda p: Path(p).resolve(), (suites, inputs, output))
    if output.exists():
        raise FileExistsError('immutable_source_audit_already_exists')
    frozen = json.loads((suites / 'encoder.json').read_text(encoding='utf-8-sig'))
    encoder = restore_encoder(frozen)
    roster = sorted(read_csv(inputs / '2024/advisors_profile.csv'),key=lambda r:r['advisor_id'])
    identities = [r['name'] for r in roster]
    corpus_paths = [inputs.parent / t / 'advisors/faculty_corpus/advisors_corpus.csv'
                    for t in sorted({pool for pools in ADVISOR_SOURCE_POOLS.values() for pool in pools})]
    source_hashes = {str(p.resolve()):digest(p) for p in corpus_paths}
    raw_hashes, verified = {}, []
    records = {}
    for version, term in [*VERSIONS.items(),('external_test','2025.3')]:
        for source_pool in ADVISOR_SOURCE_POOLS[term]:
            for record in read_csv(inputs.parent / source_pool / 'advisors/faculty_corpus/advisors_corpus.csv'):
                records[record['record_id']] = record
            path = (inputs.parent / record['raw_path']).resolve()
            if digest(path) != record['sha256']:
                raise ValueError('faculty_raw_source_hash_mismatch')
            raw_hashes[str(path)] = record['sha256']
        texts = []
        advisor_source_term = ADVISOR_SOURCE_POOLS[term][-1]
        processed = {r['advisor_id']:r for r in read_csv(inputs / advisor_source_term / 'advisors_processed.csv')}
        for advisor in roster:
            ids = json.loads(processed[advisor['advisor_id']]['source_record_ids'])
            texts.append(preprocess_text('\n'.join(records[rid]['content'] for rid in ids),identities)[0])
        right = encoder.transform(texts)
        present = right.getnnz(axis=1)>0
        data = json.loads((suites / version / ('problem.json' if version=='external_test' else 'suite.json')).read_text(encoding='utf-8-sig'))
        for role in ('external_test',) if version=='external_test' else ('train','validation'):
            rows = read_csv(inputs / term / ('students_'+role+'.csv'))
            left = encoder.transform([student_text(r,identities) for r in rows])
            scores = np.clip((left @ right.T).toarray(),0,1)
            problem = data if version=='external_test' else data['train'][0] if role=='train' else data['validation']
            if (list(problem['student_ids']) != [r['student_id'] for r in rows]
                    or not np.allclose(scores,np.asarray(problem['scores']),rtol=0,atol=1e-12)
                    or not np.array_equal(np.outer(left.getnnz(axis=1)>0,present),problem['available'])):
                raise ValueError('faculty_source_to_frozen_score_parity_mismatch')
            verified.append(version+'-'+role)
    for source, sha in source_hashes.items():
        if digest(source)!=sha:
            raise ValueError('faculty_corpus_changed_during_audit')
    receipt = {'schema':'semester-source-audit/1','suite_manifest_sha256':digest(suites/'manifest.json'),
               'prepared_input_checksums_sha256':digest(inputs/'checksums.json'),
               'source_files':source_hashes,'raw_files':raw_hashes,'verified_matrix_partitions':verified,
               'score_parity_verified':True,'audit_created_at':datetime.now(timezone.utc).isoformat(),
               'semantics':'new_reconstruction_audit_not_retroactive_claim_of_prior_hash_capture'}
    write_json(output,receipt)
    return receipt
