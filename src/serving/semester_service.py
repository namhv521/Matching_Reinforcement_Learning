"""Load completed semester research artifacts through the existing local API."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch

from src.data_pipeline.normalization import load_taxonomy
from src.data_pipeline.review_decisions import record_hash
from src.features.fresh_suite import digest, restore_encoder
from src.features.rebuild_features import preprocess_text
from src.features.semester_suite import read_csv, student_text
from src.rl.nested_learning import _load_parent, _parent, verify_round
from src.serving.rebuild_service import RebuildService

ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


class FrozenSemesterPipeline:
    def __init__(self, frozen, identities):
        self.encoder = restore_encoder(frozen)
        self.identities = identities

    def transform_score(self, students, advisors):
        left = self.encoder.transform([student_text(r,self.identities) for r in students])
        right = self.encoder.transform([preprocess_text(r['research_description'],self.identities)[0] for r in advisors])
        return {'scores':{'E4':np.clip((left@right.T).toarray(),0,1)},
                'available':{'E4':np.outer(left.getnnz(axis=1)>0,right.getnnz(axis=1)>0)}}

    def explain_pair(self, student, advisor):
        shared = sorted(set(student.get('skills_tags','').split(';')) & set(advisor.get('skills_tags','').split(';')) - {''})
        return {'method':'frozen_char_tfidf_cosine','shared_document_concepts':shared,
                'scope':'Độ tương đồng nội dung tài liệu; không phải mức thành thạo hay xác nhận học thuật.'}


def load_semester_service(run_root, *, inputs=None, runtime_dir=None):
    run_root = Path(run_root).resolve()
    training, suites = run_root/'training', run_root/'suites'
    if not (training/'status.json').is_file() or read(training/'status.json').get('training_finished') is not True:
        raise ValueError('completed_semester_training_required')
    if not (training/'final_test/results.json').is_file():
        raise ValueError('completed_external_evaluation_required')
    try:
        external = read(training/'final_test/results.json')
    except (ValueError,UnicodeError) as exc:
        raise ValueError('completed_external_evaluation_required') from exc
    if external.get('status')!='completed' or external.get('semester_id')!='2025.3':
        raise ValueError('completed_external_evaluation_required')
    from scripts.run_semester_rl import verify_suites, verify_source_audit
    status, selection = read(training/'status.json'), read(training/'selection.json')
    if digest(training/'status.json') != selection['training_status_sha256']:
        raise ValueError('serving_frozen_selection_status_mismatch')
    verify_suites(suites,expected_manifest_sha256=status['protocol']['suite_manifest_sha256'])
    binding = read(training/'source_binding.json')
    if (digest(training/'source_binding.json')!=status['source_audit_binding_sha256']
            or digest(binding['path'])!=binding['sha256']):
        raise ValueError('serving_source_audit_binding_mismatch')
    audit = verify_source_audit(binding['path'],status['protocol']['suite_manifest_sha256'])
    inputs = Path(inputs or ROOT/'data/training_prepared_20261101').resolve()
    if digest(inputs/'checksums.json') != audit['prepared_input_checksums_sha256']:
        raise ValueError('serving_prepared_input_binding_mismatch')
    for relative, sha in read(inputs/'checksums.json').items():
        path=(inputs/relative).resolve()
        if not path.is_relative_to(inputs) or digest(path)!=sha:
            raise ValueError('serving_prepared_input_hash_mismatch')
    selected = Path(selection['accepted']).resolve()
    if not selected.is_relative_to(training):
        raise ValueError('serving_checkpoint_outside_selected_run')
    opened=read(training/'final_test/opened.json')
    if (external.get('selection_sha256')!=digest(training/'selection.json')
            or Path(external.get('selected_checkpoint','')).resolve()!=selected
            or opened.get('selection_sha256')!=digest(training/'selection.json')
            or opened.get('problem_sha256')!=digest(suites/'external_test/problem.json')):
        raise ValueError('serving_external_evaluation_selection_mismatch')
    final_manifest=read(training/'final_test/manifest.json')
    if (set(final_manifest.get('artifacts',{}))!={'opened.json','results.json'}
            or final_manifest.get('selection_sha256')!=digest(training/'selection.json')):
        raise ValueError('serving_external_evaluation_inventory_mismatch')
    for relative,sha in final_manifest['artifacts'].items():
        path=(training/'final_test'/relative).resolve()
        if not path.is_relative_to(training/'final_test') or digest(path)!=sha:
            raise ValueError('serving_external_evaluation_hash_mismatch')
    report=verify_round(selected)
    if report['decision']!='accepted' or report['checkpoint_sha256']!=selection['checkpoint_sha256']:
        raise ValueError('serving_selected_checkpoint_hash_mismatch')
    contract=read(selected/'input.json')['contract']
    if record_hash(read(suites/'feature_contract.json'))!=contract['feature_contract_sha256']:
        raise ValueError('serving_frozen_feature_contract_mismatch')
    roster=sorted(read_csv(inputs/'2024/advisors_profile.csv'),key=lambda r:r['advisor_id'])
    if [r['advisor_id'] for r in roster]!=contract['state_contract']['advisor_ids']:
        raise ValueError('serving_advisor_registry_mismatch')
    records={}
    for term in ('2024','2025.1','2025.2'):
        for row in read_csv(inputs.parent/term/'advisors/faculty_corpus/advisors_corpus.csv'):
            records[row['record_id']]=row
    processed={r['advisor_id']:r for r in read_csv(inputs/'2025.2/advisors_processed.csv')}
    advisors=[]
    for seed in roster:
        row=processed[seed['advisor_id']]
        ids=read_json_list(row['source_record_ids'])
        advisors.append({**row,'advisor_name':seed['name'],'source_url':seed['university_url'],
                         'research_description':'\n'.join(records[rid]['content'] for rid in ids),
                         'source_sha256':record_hash([records[rid] for rid in ids]),
                         'skills_tags':';'.join(sorted({x for key in ('programming_languages','frameworks_libraries','databases','ml_ai_methods',
                             'data_engineering_tools','cloud_devops_tools','security_network_tools','software_engineering_methods',
                             'research_methods','math_statistics_topics') for x in row.get(key,'').split(';') if x})),
                         'expertise_topic_tags':row['topic_tags'],'expertise_confidence':''})
    torch.set_num_threads(1)
    model=_load_parent(_parent(selected))
    versions={'selection_run_id':run_root.name,'phase3_run_id':'semester-csv','phase4_run_id':run_root.name,
              'encoder_sha256':digest(suites/'encoder.json'),'parent_feature_contract_sha256':contract['feature_contract_sha256'],
              'quota_policy_version':contract['quota_policy_version'],'faculty_snapshot':'2025.2',
              'scope':'retrospective_document_proxy','prediction_time_verified':False,'production_promoted':False,
              'allow_unknown_document_confidence':True,
              'models':{'ppo':{'checkpoint_steps':report['steps_after'],'checkpoint_sha256':report['checkpoint_sha256'],
                               'source_version':report['semester_id'],'source_round':report['round_index'],
                               'seed':report['seed'],'production_promoted':False}}}
    service=RebuildService(pipeline=FrozenSemesterPipeline(read(suites/'encoder.json'),[r['name'] for r in roster]),
                          advisors=advisors,taxonomy=load_taxonomy(),versions=versions,
                          runtime_dir=runtime_dir or run_root/'runtime',models={'ppo':model},model_contracts={'ppo':contract})
    if service.tag_order!=[tuple(x) for x in read(suites/'feature_contract.json')['concept_order']]:
        raise ValueError('serving_concept_feature_order_mismatch')
    return service


def read_json_list(value):
    result=json.loads(value)
    if not isinstance(result,list):
        raise ValueError('source_record_ids_list_required')
    return result


def semester_telemetry(run_root, versions):
    run_root=Path(run_root).resolve()
    training=run_root/'training'
    status=read(training/'status.json')
    selection=read(training/'selection.json')
    if (status.get('training_finished') is not True or versions.get('selection_run_id')!=run_root.name
            or digest(training/'status.json')!=selection['training_status_sha256']):
        raise ValueError('completed_selected_training_report_required')
    rows, curves=[],{}
    for entry in status['completed_rounds']:
        artifact=Path(entry['artifact']).resolve()
        if not artifact.is_relative_to(training):
            raise ValueError('training_report_artifact_outside_run')
        spec=read(artifact/'input.json')['round']
        rows.append({k:entry[k] for k in ('version','round','decision','steps_before','steps_added','steps_after','candidate_score','parent_score','delta')})
        rows[-1]['control']=spec.get('control')
        curves[f'{entry["version"]}-R{entry["round"]}']=[json.loads(line) for line in
            (artifact/'learning_curve.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    final=read(training/'final_test/results.json')
    if final.get('selection_sha256')!=digest(training/'selection.json'):
        raise ValueError('training_report_external_selection_mismatch')
    selected=Path(selection['accepted']).resolve()
    report=verify_round(selected)
    feedback=read(Path(read(training/'feedback_binding.json')['path'])/'readiness.json')
    return {'mode':'semester_nested','run_id':run_root.name,'updated_at':(training/'status.json').stat().st_mtime,
            'status':'completed','algorithm':'ppo','results':rows,'curves':curves,
            'cohorts':read(run_root/'suites/readiness.json')['versions'],
            'rounds_per_version':status['protocol']['rounds_per_version'],
            'steps_per_round':status['protocol']['steps_per_round'],
            'total_compute_steps':sum(r['steps_added'] for r in rows),
            'selected_checkpoint':selected.relative_to(training).as_posix(),'selected_weight_steps':report['steps_after'],
            'feedback_counts':{r['version']:{'r2':r['r2_signal_students'],'r3':r['r3_status_students']} for r in feedback['versions']},
            'test':{'semester_id':'2025.3','n_test':final['n_test'],'metrics':final['metrics']},
            'scope':'retrospective_document_proxy','prediction_time_verified':False,
            'production_promoted':False,'feedback_semantics':'Known survey information only; registration status is not a verified advisor rejection.'}
