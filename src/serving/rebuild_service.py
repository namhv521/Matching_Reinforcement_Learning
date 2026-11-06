"""Private local inference proposals with frozen encoders; never fit/train uploads."""
import csv
import hashlib
import io
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from src.data_pipeline.csv_contracts import HEADERS, MAX_CSV_BYTES, validate_row
from src.data_pipeline.review_decisions import record_hash
from src.domain.rebuild_matching import AllocationProblem, equal_quotas
from src.environment.rebuild_env import MatchingEnv


MAX_IMPORT_ROWS = 500
POLICY_VERSION = 'equal-division-canonical/1.0'


def _digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def export_rows_csv(rows, headers):
    def safe(value):
        text = str(value if value is not None else '')
        return "'"+text if text.lstrip().startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r', '\n')) else text
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(headers)
    writer.writerows([[safe(row.get(key, '')) for key in headers] for row in rows])
    return stream.getvalue().encode('utf-8-sig')


class RebuildService:
    def __init__(self, *, pipeline, advisors, taxonomy, versions, runtime_dir, scorable=None,
                 models=None, model_contracts=None):
        self.pipeline = pipeline
        self.advisors = json.loads(json.dumps(advisors, allow_nan=False))
        self.advisor_ids = tuple(row['advisor_id'] for row in self.advisors)
        if not self.advisor_ids or len(set(self.advisor_ids)) != len(self.advisor_ids):
            raise ValueError('invalid_advisor_registry')
        self.taxonomy = taxonomy
        self.taxonomy_groups = {group: set(entries) for group, entries in taxonomy['groups'].items()}
        self.taxonomy_ids = set().union(*self.taxonomy_groups.values()) if self.taxonomy_groups else set()
        self.tag_order = sorted((group, tag) for group, tags in self.taxonomy_groups.items() for tag in tags)
        self.versions = json.loads(json.dumps(versions, allow_nan=False))
        self.models, self.model_contracts = models or {}, model_contracts or {}
        self.scorable = np.asarray(scorable if scorable is not None else [True]*len(self.advisor_ids), dtype=bool)
        if self.scorable.shape != (len(self.advisor_ids),):
            raise ValueError('invalid_advisor_availability')
        self.runtime_dir = Path(runtime_dir).resolve()
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @classmethod
    def from_artifacts(cls, output, *, runtime_dir=None, selection_manifest=None):
        from src.data_pipeline.normalization import load_taxonomy
        from src.data_pipeline.rebuild_cohorts import build_research_suite
        from src.features.rebuild_acceptance import load_approved_features
        from src.features.rebuild_experiments import _load_snapshot
        from src.features.rebuild_features import FeaturePipeline
        from src.rl.rebuild_dqn import MaskedDQN
        from src.rl.rebuild_ppo import MaskedPPOAgent
        import torch
        torch.set_num_threads(1)
        output = Path(output).resolve()
        runtime = Path(runtime_dir or output/'runtime/rebuild').resolve()
        if not runtime.is_relative_to(output/'runtime'):
            raise ValueError('private_runtime_directory_required')
        features = load_approved_features(output)
        students, advisors, snapshot = _load_snapshot(output)
        if snapshot != features['contract']['snapshot']:
            raise ValueError('inference_snapshot_binding_mismatch')
        phase4 = Path(features['gate']['run_dir'])
        identities = sorted({str(r[k]) for r in students+advisors
                             for k in ('student_id', 'student_name', 'advisor_id', 'advisor_name') if r.get(k)})
        pipeline = FeaturePipeline.load(phase4/'transformer', known_identities=identities)
        encoder = {'transformer_json_sha256': _digest(phase4/'transformer/transformer.json'),
                   'transformer_idf_sha256': _digest(phase4/'transformer/idf.npz')}
        versions = {'phase3_run_id': snapshot['run_id'], 'phase4_run_id': features['gate']['run_id'],
                    'frozen_encoder': encoder, 'encoder_sha256': record_hash(encoder),
                    'parent_feature_contract_sha256': features['gate']['feature_contract_sha256'], 'models': {}}
        suite = build_research_suite(output)
        env = MatchingEnv(suite['train'], shuffle_students=True)
        if selection_manifest:
            from src.evaluation.rl_convergence import load_selection
            selected = load_selection(Path(selection_manifest))
            candidates = selected['candidates']
            versions['selection_run_id'] = selected['run_id']
        else:
            from src.evaluation.semester_rehearsal import load_phase5_parent
            run, parent = load_phase5_parent(output)
            contract = parent['model_contract']
            candidates = {key: {'path': str(run/f'checkpoints/{key}/seed-42'), 'native_contract': contract,
                                'frozen_encoder_sha256': versions['encoder_sha256'], 'seed': 42,
                                'checkpoint_steps': parent['budget']['timesteps_per_algorithm_seed']}
                          for key in ('ppo', 'dqn')}
        models, contracts = {}, {}
        for key in ('ppo', 'dqn'):
            candidate = candidates[key]
            contract = candidate['native_contract']
            if (candidate['frozen_encoder_sha256'] != versions['encoder_sha256']
                    or contract.get('feature_contract_sha256') != features['gate']['feature_contract_sha256']
                    or contract.get('taxonomy_feature_order_sha256') != record_hash(suite['metadata']['taxonomy_feature_order'])):
                raise ValueError('inference_encoder_contract_mismatch')
            if (contract.get('reward_weights') != env.reward_weights
                    or contract.get('quota_policy_version') != POLICY_VERSION):
                raise ValueError('inference_policy_contract_mismatch')
            models[key] = (MaskedPPOAgent.load(candidate['path'], env, expected_contract=contract) if key == 'ppo'
                           else MaskedDQN.load(candidate['path'], expected_contract=contract))
            contracts[key] = contract
            checkpoint_files = {p.name: _digest(p) for p in Path(candidate['path']).iterdir() if p.is_file()}
            versions['models'][key] = {'native_contract_sha256': record_hash(contract),
                'checkpoint_steps': candidate['checkpoint_steps'], 'seed': candidate['seed'], 'production_promoted': False,
                'checkpoint_files': checkpoint_files, 'checkpoint_sha256': record_hash(checkpoint_files)}
        return cls(pipeline=pipeline, advisors=advisors, taxonomy=load_taxonomy(), versions=versions,
                   runtime_dir=runtime, scorable=features['available'].any(axis=0), models=models,
                   model_contracts=contracts)

    def template(self, entity):
        if entity not in HEADERS:
            raise ValueError('unknown_template_entity')
        return export_rows_csv([], HEADERS[entity])

    def bootstrap(self):
        return {'advisors': [{'advisor_id': a['advisor_id'], 'advisor_name': a['advisor_name'],
                             'scorable': bool(self.scorable[j]),
                             'warnings': [] if self.scorable[j] else ['Profile has no available frozen score features.']}
                            for j, a in enumerate(self.advisors)],
                'versions': self.versions, 'template_headers': HEADERS,
                'algorithms': [{'id': key, 'ready': key == 'hungarian' or key in self.models,
                                'reason': '' if key == 'hungarian' or key in self.models else 'Native checkpoint unavailable; Hungarian remains available.'}
                               for key in ('hungarian', 'ppo', 'dqn')],
                'limits': {'max_csv_bytes': MAX_CSV_BYTES, 'max_rows': MAX_IMPORT_ROWS},
                'scope': 'Local inference proposals; uploaded profiles remain outside approved gold.'}

    def _persist(self, kind, payload, scope):
        identity = {'kind': kind, 'scope_hash': record_hash(scope)}
        if kind == 'cohorts':
            identity.update(upload_sha256=payload['upload_sha256'], versions=payload['versions'])
        else:
            identity['payload_sha256'] = record_hash(payload)
        key = record_hash(identity)
        body = {'identity': identity, 'payload': payload, 'payload_sha256': record_hash(payload)}
        if getattr(self, 'record_store', None) is not None:
            self.record_store.put(kind, key, body)
            self._get(kind, key, scope)
            return key
        folder = self.runtime_dir/kind
        if folder.is_symlink():
            raise ValueError('runtime_artifact_invalid')
        folder.mkdir(exist_ok=True)
        path = folder/(key+'.json')
        if path.is_symlink():
            raise ValueError('runtime_artifact_invalid')
        if not path.exists():
            with path.open('x', encoding='utf-8') as stream:
                json.dump(body, stream, ensure_ascii=False, allow_nan=False)
        self._get(kind, key, scope)
        return key

    def _get(self, kind, key, scope):
        if not isinstance(key, str) or not re.fullmatch('[0-9a-f]{64}', key):
            raise ValueError('cohort_not_found' if kind == 'cohorts' else 'run_not_found')
        if getattr(self, 'record_store', None) is not None:
            body = self.record_store.get(kind, key, record_hash(scope))
        else:
            path = self.runtime_dir/kind/(key+'.json')
            if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(self.runtime_dir):
                raise ValueError('cohort_not_found' if kind == 'cohorts' else 'run_not_found')
            body = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(body, dict) or 'payload' not in body or 'identity' not in body
                or record_hash(body['identity']) != key or record_hash(body['payload']) != body.get('payload_sha256')):
            raise ValueError('runtime_artifact_invalid')
        identity = body['identity']
        if identity.get('scope_hash') != record_hash(scope):
            raise ValueError('cohort_not_found' if kind == 'cohorts' else 'run_not_found')
        if (identity.get('kind') != kind or (kind == 'cohorts' and any(
                identity.get(k) != body['payload'].get(k) for k in ('upload_sha256', 'versions')))
                or (kind != 'cohorts' and identity.get('payload_sha256') != body['payload_sha256'])):
            raise ValueError('runtime_artifact_invalid')
        return body['payload']

    def validate_students(self, csv_text, *, scope='local'):
        errors, rows, seen = [], [], set()
        ignored_preferences, ignored_proficiency = False, False
        def error(row, field, code):
            if len(errors) < 1000:
                errors.append({'row': row, 'column': field, 'field': field, 'code': code, 'message': code})
        if not isinstance(csv_text, str) or len(csv_text.encode('utf-8')) > MAX_CSV_BYTES:
            error(0, '__file__', 'file_size_limit')
            return {'valid': False, 'errors': errors, 'row_count': 0, 'warnings': []}
        raw = csv_text.encode('utf-8')
        source_sha = hashlib.sha256(raw).hexdigest()
        captured = datetime.now(timezone.utc).isoformat()
        try:
            reader = csv.reader(io.StringIO(csv_text.lstrip('\ufeff'), newline=''), strict=True)
            headers = next(reader, [])
            if len(headers) != len(set(headers)) or set(headers) != set(HEADERS['students']):
                error(1, '__header__', 'header_contract')
            else:
                count = 0
                for values in reader:
                    if not values or not any(v.strip() for v in values):
                        continue
                    count += 1
                    if count > MAX_IMPORT_ROWS:
                        error(reader.line_num, '__file__', 'row_count_limit')
                        break
                    if len(values) != len(headers):
                        error(reader.line_num, '__row__', 'row_width')
                        continue
                    row = dict(zip(headers, values))
                    if row['eligibility_flags'].strip():
                        error(reader.line_num, 'eligibility_flags', 'unsupported_eligibility_flags_require_explicit_policy')
                    ignored_preferences |= bool(row['preferred_advisor_ids'].strip())
                    ignored_proficiency |= bool(row['skill_proficiency_json'].strip())
                    defaults = {'schema_version': '1.0', 'semester_id': 'local-upload', 'source_type': 'user_csv',
                                'source_file': 'upload-'+source_sha[:12]+'.csv', 'source_sha256': source_sha,
                                'extracted_at': captured, 'review_status': 'pending'}
                    for field, value in defaults.items():
                        if not row[field].strip():
                            row[field] = value
                    for item in validate_row(row, 'students', mode='staging', taxonomy_ids=self.taxonomy_ids,
                                             taxonomy_groups=self.taxonomy_groups,
                                             allow_unknown_document_confidence=self.versions.get('allow_unknown_document_confidence', False)):
                        error(reader.line_num, item['field'], item['code'])
                    key = row['student_id'].strip()
                    if key in seen:
                        error(reader.line_num, 'student_id', 'duplicate_identity')
                    seen.add(key)
                    row = {field: value.strip() for field, value in row.items()}
                    rows.append(row)
                    if len(errors) >= 1000:
                        break
        except (csv.Error, UnicodeError):
            error(0, '__file__', 'malformed_csv')
        if not rows and not errors:
            error(1, '__file__', 'empty_dataset')
        warnings = ['Local upload metadata is not a verified academic semester; input review claims do not approve gold.',
                    'Missing tags, confidence, proficiency and preferences remain unknown.']
        if ignored_preferences:
            warnings.append('Provided preferences are retained but not scored: confirmation is outside this frozen inference contract.')
        if ignored_proficiency:
            warnings.append('Provided proficiency is retained but not used by this frozen topic/term representation.')
        if errors:
            return {'valid': False, 'errors': errors, 'row_count': len(rows), 'warnings': warnings}
        payload = {'rows': rows, 'upload_sha256': source_sha, 'captured_at': captured,
                   'versions': self.versions, 'scope': 'user_csv_inference_only', 'warnings': warnings}
        with self._lock:
            key = self._persist('cohorts', payload, scope)
        return {'valid': True, 'cohort_id': key, 'row_count': len(rows), 'errors': [], 'warnings': warnings,
                'students': [{field: row[field] for field in ('student_id', 'student_name', 'thesis_title')} for row in rows]}

    def get_students(self, cohort_id, *, scope='local'):
        payload = self._get('cohorts', cohort_id, scope)
        if payload['versions'] != self.versions:
            raise ValueError('cohort_encoder_version_changed')
        return payload['rows']

    def validate_advisors(self, csv_text, *, scope='local'):
        """Read-only faculty intake; no uploaded row replaces the frozen catalog."""
        from src.features.rebuild_features import TECH_COLUMNS
        errors, reports, seen = [], [], set()
        warnings = ['Read-only intake: uploaded profiles do not change gold, advisor registry, models or roster selection.',
                    'User-provided source/review fields are claims; no profile verification or academic approval is inferred.',
                    'Participation, capacity and existing-load CSV fields are not applied; coordinator roster selection remains authoritative.']
        def error(row, field, code):
            if len(errors) < 1000:
                errors.append({'row': row, 'column': field, 'field': field, 'code': code, 'message': code})
        def feature_content(row):
            values = {field: sorted(set(str(row.get(field) or '').split(';')) - {''})
                      for field in ('research_domain_tags', 'expertise_topic_tags', *TECH_COLUMNS)}
            values['research_description'] = ' '.join(str(row.get('research_description') or '').split())
            confidence = row.get('expertise_confidence')
            values['expertise_confidence'] = float(confidence) if confidence not in ('', None) else None
            return values
        upload_sha = None
        count = 0
        if not isinstance(csv_text, str) or len(csv_text.encode('utf-8')) > MAX_CSV_BYTES:
            error(0, '__file__', 'file_size_limit')
        else:
            upload_sha = hashlib.sha256(csv_text.encode('utf-8')).hexdigest()
            catalog = {row['advisor_id']: row for row in self.advisors}
            try:
                reader = csv.reader(io.StringIO(csv_text.lstrip('\ufeff'), newline=''), strict=True)
                headers = next(reader, [])
                if len(headers) != len(set(headers)) or set(headers) != set(HEADERS['advisors']):
                    error(1, '__header__', 'header_contract')
                else:
                    for values in reader:
                        if not values or not any(v.strip() for v in values):
                            continue
                        count += 1
                        if count > MAX_IMPORT_ROWS:
                            error(reader.line_num, '__file__', 'row_count_limit')
                            break
                        if len(values) != len(headers):
                            error(reader.line_num, '__row__', 'row_width')
                            continue
                        row = dict(zip(headers, values))
                        defaults = {'schema_version': '1.0', 'semester_id': 'local-upload', 'source_type': 'user_csv',
                                    'source_sha256': upload_sha, 'review_status': 'pending'}
                        for field, value in defaults.items():
                            if not row[field].strip():
                                row[field] = value
                        row_errors = validate_row(row, 'advisors', mode='staging', taxonomy_ids=self.taxonomy_ids,
                                                  taxonomy_groups=self.taxonomy_groups)
                        for item in row_errors:
                            error(reader.line_num, item['field'], item['code'])
                        key = row['advisor_id'].strip()
                        if key in seen:
                            error(reader.line_num, 'advisor_id', 'duplicate_identity')
                        seen.add(key)
                        reasons, provided_hash, catalog_hash = [], None, None
                        original = catalog.get(key)
                        if row_errors:
                            reasons.append('invalid_profile_fields')
                        elif original is None:
                            reasons.append('advisor_outside_frozen_registry')
                        else:
                            provided_hash = record_hash(feature_content(row))
                            catalog_hash = record_hash(feature_content(original))
                            if provided_hash != catalog_hash:
                                reasons.append('feature_content_changed')
                            if row['advisor_name'].strip() != original['advisor_name'].strip():
                                reasons.append('identity_redaction_registry_changed')
                        requires_rebuild = any(code in reasons for code in ('advisor_outside_frozen_registry',
                                                                 'feature_content_changed', 'identity_redaction_registry_changed'))
                        reports.append({'row': reader.line_num, 'advisor_id': key, 'advisor_name': row['advisor_name'].strip(),
                            'inference_compatible': not reasons, 'requires_rebuild': requires_rebuild, 'reason_codes': reasons,
                            'provided_feature_sha256': provided_hash, 'catalog_feature_sha256': catalog_hash,
                            'catalog_source_sha256': original.get('source_sha256') if original else None})
            except (csv.Error, UnicodeError):
                error(0, '__file__', 'malformed_csv')
        if count == 0 and not errors:
            error(1, '__file__', 'empty_dataset')
        requires_rebuild = any(row['requires_rebuild'] for row in reports)
        if requires_rebuild:
            warnings.append('New IDs or changed feature/identity content require a reviewed rebuild; current checkpoints/catalog are not silently reused for those rows.')
        return {'valid': not errors, 'row_count': min(count, MAX_IMPORT_ROWS), 'errors': errors, 'warnings': warnings,
                'inference_compatible': bool(reports) and not errors and all(row['inference_compatible'] for row in reports),
                'requires_rebuild': requires_rebuild, 'rows': reports, 'registry_mutated': False,
                'upload_sha256': upload_sha, 'versions': self.versions}

    def quotas(self, student_count, advisor_ids):
        if not isinstance(advisor_ids, list):
            raise ValueError('advisor_ids_list_required')
        capacities = equal_quotas(student_count, self.advisor_ids, advisor_ids)
        return {'student_count': student_count, 'policy_version': self.versions.get('quota_policy_version', POLICY_VERSION),
                'quotas': [{'advisor_id': a['advisor_id'], 'advisor_name': a['advisor_name'],
                            'capacity': int(capacities[j]), 'selected': a['advisor_id'] in advisor_ids,
                            'scorable': bool(self.scorable[j])} for j, a in enumerate(self.advisors)],
                'total_capacity': int(capacities.sum()),
                'warnings': ['Selected profile has no frozen scoring features.'] if any(not self.scorable[self.advisor_ids.index(a)] for a in advisor_ids) else []}

    def _problem(self, cohort_id, advisor_ids, scope):
        if not isinstance(advisor_ids, list):
            raise ValueError('advisor_ids_list_required')
        students = self.get_students(cohort_id, scope=scope)
        capacities = equal_quotas(len(students), self.advisor_ids, advisor_ids)
        scored = self.pipeline.transform_score(students, self.advisors)
        features = np.zeros((len(students), len(self.tag_order)), np.float32)
        known = np.zeros(features.shape, bool)
        for i, student in enumerate(students):
            for j, (group, tag) in enumerate(self.tag_order):
                if tag in str(student.get(group) or '').split(';'):
                    features[i, j], known[i, j] = 1, True
        problem = AllocationProblem(scores=scored['scores']['E4'], available=scored['available']['E4'],
            student_ids=tuple(row['student_id'].strip() for row in students), advisor_ids=self.advisor_ids,
            capacities=capacities, eligible=np.ones((len(students), len(self.advisors)), bool),
            present=np.array([a in advisor_ids for a in self.advisor_ids], bool),
            student_features=features, student_feature_known=known,
            metadata={'scope': 'local_inference_proposal', 'cohort_id': cohort_id,
                'inference_input_sha256': record_hash(students), 'frozen_encoder_sha256': self.versions['encoder_sha256'],
                'native_training_contracts_unchanged': True,
                'eligibility_scope': 'Coordinator selected roster is the explicit local eligibility scope; no official academic claim.'})
        return students, problem

    def recommend(self, cohort_id, advisor_ids, *, top_k=5, scope='local'):
        if type(top_k) is not int or not 1 <= top_k <= 35:
            raise ValueError('invalid_top_k')
        students, problem = self._problem(cohort_id, advisor_ids, scope)
        rankings = []
        for i, student in enumerate(students):
            candidates = sorted(np.flatnonzero(problem.allowed[i]), key=lambda j: (-problem.scores[i, j], self.advisor_ids[j]))[:top_k]
            rankings.append({'student_id': student['student_id'], 'recommendations': [
                {'advisor_id': self.advisor_ids[j], 'advisor_name': self.advisors[j]['advisor_name'],
                 'score': float(problem.scores[i, j]), 'explanation': self.pipeline.explain_pair(student, self.advisors[j]),
                 'source_url': self.advisors[j].get('source_url', ''),
                 'scope': 'Topic compatibility only; independent ranking ignores allocation quota.'} for j in candidates]})
        return {'versions': self.versions, 'rankings': rankings, 'quota_applied': False,
                'warnings': ['No scorable selected candidate for one or more students.'] if any(not r['recommendations'] for r in rankings) else []}

    def compare(self, cohort_id, advisor_ids, *, coordinator_confirmed=False, scope='local'):
        from src.evaluation.rebuild_benchmark import evaluate_problem
        if coordinator_confirmed is not True:
            raise ValueError('coordinator_confirmation_required')
        policy_version = self.versions.get('quota_policy_version', POLICY_VERSION)
        with self._lock:
            students, problem = self._problem(cohort_id, advisor_ids, scope)
            results = {}
            inference_env = MatchingEnv([problem])
            env_contract = inference_env.state_contract
            for algorithm in ('hungarian', 'ppo', 'dqn'):
                model = self.models.get(algorithm)
                if algorithm != 'hungarian' and model is None:
                    results[algorithm] = {'status': 'unavailable', 'assignments': [], 'trace': [], 'metrics': {},
                                          'diagnostics': {'reason': 'Native checkpoint not loaded.', 'fallback': 'hungarian'}}
                    continue
                if model is not None and self.model_contracts.get(algorithm, {}).get('state_contract') != env_contract:
                    raise ValueError('inference_state_contract_mismatch')
                if model is not None and (self.model_contracts[algorithm].get('reward_weights') != inference_env.reward_weights
                                         or self.model_contracts[algorithm].get('quota_policy_version') != policy_version):
                    raise ValueError('inference_policy_contract_mismatch')
                results[algorithm] = evaluate_problem(problem, algorithm, model=model, seed=42)
                for assignment in results[algorithm]['assignments']:
                    i, j = problem.student_ids.index(assignment['student_id']), self.advisor_ids.index(assignment['advisor_id'])
                    assignment.update(student_name=students[i].get('student_name', ''), advisor_name=self.advisors[j]['advisor_name'],
                                      score=float(problem.scores[i, j]), preference=None, preference_known=False)
            payload = {'cohort_id': cohort_id, 'versions': self.versions, 'results': results,
                       'policy': {'version': policy_version, 'scope': 'coordinator_confirmed_local_proposal',
                                  'advisor_ids': list(advisor_ids), 'capacities': problem.capacities.tolist(),
                                  'academic_approval': False},
                       'inference_contract_sha256': record_hash({'input': problem.metadata, 'state': env_contract, 'versions': self.versions}),
                       'warnings': list(self._get('cohorts', cohort_id, scope).get('warnings', [])) +
                                   ['Proposals only. No uploaded record was added to approved gold; no model was trained or promoted.']}
            run_id = self._persist('runs', payload, scope)
            return {'run_id': run_id, **payload}

    def export(self, run_id, algorithm, *, scope='local'):
        if algorithm not in ('hungarian', 'ppo', 'dqn'):
            raise ValueError('unknown_algorithm')
        payload = self._get('runs', run_id, scope)
        result = payload['results'][algorithm]
        rows = [{**row, 'proposal_scope': payload['policy']['scope'], 'warnings': ' | '.join(payload['warnings'])}
                for row in result['assignments']]
        return export_rows_csv(rows, ['student_id', 'student_name', 'advisor_id', 'advisor_name', 'score', 'proposal_scope', 'warnings'])
