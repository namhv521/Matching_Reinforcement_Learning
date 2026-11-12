"""Serve the six frozen Strict research checkpoints on one cohort API."""

from pathlib import Path
from urllib.parse import urlsplit

import numpy as np

from src.data_pipeline.normalization import load_taxonomy
from src.features.fresh_suite import digest
from src.features.rebuild_features import preprocess_text
from src.rl.nested_learning import _load_parent, _parent, verify_round
from src.serving.rebuild_service import RebuildService
from src.serving.semester_service import FrozenSemesterPipeline, read, read_csv

VERSIONS = ('V1', 'V2', 'V3')
ALGORITHMS = ('ppo', 'dqn')


class CatalogAssistant:
    def __init__(self, service, records):
        self.pipeline = service.pipeline
        self.names = {a['advisor_id']: a['advisor_name'] for a in service.advisors}
        self.documents = []
        for record in records:
            url = urlsplit(record['source_url'])
            if url.scheme != 'https' or not url.hostname or url.username or url.password:
                continue
            text = record['content']
            for start in range(0, min(len(text), 24000), 900):
                self.documents.append((record, text[start:start+900]))
        self.index = self.pipeline.encoder.transform([
            preprocess_text(record['title']+' '+text, self.pipeline.identities)[0]
            for record, text in self.documents
        ])

    def answer(self, question, *, advisor_ids=None, top_k=5, **_):
        query = preprocess_text(question, self.pipeline.identities)[0]
        scores = (self.pipeline.encoder.transform([query]) @ self.index.T).toarray()[0]
        allowed = set(self.names if advisor_ids is None else advisor_ids)
        citations, rankings, seen = [], [], set()
        for index in np.argsort(-scores, kind='stable'):
            if scores[index] < .12 or len(rankings) >= top_k:
                break
            record, snippet = self.documents[index]
            aid = record['advisor_id']
            if aid not in allowed or aid in seen:
                continue
            seen.add(aid)
            rankings.append({'advisor_name':self.names[aid], 'score':float(scores[index])})
            citations.append({'title':record['title'], 'url':record['source_url'],
                              'snippet':' '.join(snippet.split())[:220]})
        return {'answer': ('Các hồ sơ dưới đây có nguồn hồi cứu liên quan đến truy vấn.'
                           if citations else 'Chưa tìm thấy nguồn đủ liên quan trong danh mục hồi cứu.'),
                'rankings':rankings, 'citations':citations}


def load_catalog(outputs, runtime):
    from scripts.run_semester_rl import verify_source_audit, verify_suites

    outputs = Path(outputs).resolve()
    bundle = outputs / 'semester_rl_20261111_trusted_year_github'
    strict = bundle / 'strict'
    suites = strict / 'suites'
    inputs = bundle / 'inputs_strict'
    suite_sha = digest(suites / 'manifest.json')
    verify_suites(suites)
    audit = verify_source_audit(strict / 'source_audit.json', suite_sha)
    if digest(inputs / 'checksums.json') != audit['prepared_input_checksums_sha256']:
        raise ValueError('catalog_inputs_binding_mismatch')
    roster_path = inputs / '2024/advisors_profile.csv'
    if digest(roster_path) != read(inputs / 'checksums.json')['2024/advisors_profile.csv']:
        raise ValueError('catalog_roster_hash_mismatch')
    roster = sorted(read_csv(roster_path), key=lambda r: r['advisor_id'])
    ids = [row['advisor_id'] for row in roster]
    pipeline = FrozenSemesterPipeline(read(suites / 'encoder.json'), [row['name'] for row in roster])
    report = read(outputs / 'external_2025.3_strict_github_all_versions.json')
    if report['suite_manifest_sha256'] != suite_sha or report['problem_sha256'] != digest(suites/'external_test/problem.json'):
        raise ValueError('catalog_evaluation_binding_mismatch')
    catalog, metadata = {}, {}
    for version in VERSIONS:
        models, contracts = {}, {}
        records = read(suites/version/'faculty_records.json')
        advisors = [{**row, 'advisor_name': row['name'], 'source_url': row['university_url'],
                     'research_description': '\n'.join(r['content'] for r in records if r['advisor_id']==row['advisor_id'])}
                    for row in roster]
        spec = read(suites/version/'suite.json')['contract']
        for algorithm in ALGORITHMS:
            folder = outputs/f'train_strict_github_{algorithm}'/version/'R4'
            run = folder.parent.parent
            status = read(run/'status.json')
            if (status.get('training_finished') is not True or len(status['completed_rounds']) != 12
                    or status['protocol_sha256'] != digest(run/'protocol.json')
                    or read(run/'protocol.json')['suite_manifest_sha256'] != suite_sha):
                raise ValueError('catalog_training_protocol_mismatch')
            trained = verify_round(folder)
            contract = read(folder/'input.json')['contract']
            expected = report['models'][f'{algorithm}_{version}']
            if (trained['decision'] != 'accepted' or trained['checkpoint_sha256'] != expected['checkpoint_sha256']
                    or contract['state_contract']['advisor_ids'] != ids
                    or any(contract[k] != spec[k] for k in ('state_contract', 'feature_contract_sha256',
                           'taxonomy_feature_order_sha256', 'reward_weights', 'quota_policy_version'))):
                raise ValueError('catalog_checkpoint_contract_mismatch')
            models[algorithm] = _load_parent(_parent(folder))
            contracts[algorithm] = contract
            metadata[f'{algorithm}_{version}'] = {'checkpoint_steps': trained['steps_after'],
                                                   'checkpoint_sha256': trained['checkpoint_sha256']}
        catalog[version] = models, contracts, advisors
    versions = {'scope': 'retrospective_document_proxy', 'encoder_sha256': digest(suites/'encoder.json'),
                'quota_policy_version': catalog['V3'][1]['ppo']['quota_policy_version'],
                'checkpoint_catalog': metadata, 'suite_manifest_sha256': suite_sha}
    service, assistant = assemble_catalog(pipeline, load_taxonomy(inputs/'taxonomy_v1.yaml'), catalog, versions,
                                          runtime, read(suites/'V3/faculty_records.json'))
    if service.tag_order != [tuple(item) for item in read(suites/'feature_contract.json')['concept_order']]:
        raise ValueError('catalog_feature_order_mismatch')
    return service, assistant


def assemble_catalog(pipeline, taxonomy, catalog, versions, runtime, faculty_records):
    models, contracts, advisors = catalog['V3']
    known = pipeline.encoder.transform([preprocess_text(a['research_description'], pipeline.identities)[0] for a in advisors])
    service = RebuildService(pipeline=pipeline, advisors=advisors, taxonomy=taxonomy, versions=versions,
                             runtime_dir=runtime, models=models, model_contracts=contracts,
                             scorable=known.getnnz(axis=1)>0)
    service.checkpoint_versions = catalog
    return service, CatalogAssistant(service, faculty_records)
