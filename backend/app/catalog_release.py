"""Private, relocatable inference release for the six semester checkpoints."""
import io
import json
from pathlib import Path

import numpy as np
import torch

from src.data_pipeline.review_decisions import record_hash
from src.domain.rebuild_matching import AllocationProblem
from src.environment.rebuild_env import MatchingEnv
from src.features.semester_suite import QUOTA
from src.rl.rebuild_dqn import MaskedDQN
from src.rl.rebuild_ppo import MaskedPPOAgent
from src.serving.semester_catalog import ALGORITHMS, VERSIONS, assemble_catalog, load_catalog
from src.serving.semester_service import FrozenSemesterPipeline, read

from .production_release import write_release


def training_summary(outputs, release, suites):
    run = outputs/'train_strict_github_ppo'
    status = read(run/'status.json')
    external = read(outputs/'external_2025.3_strict_github_all_versions.json')
    feedback = read(Path(read(run/'feedback_binding.json')['path'])/'readiness.json')
    rows, curves = [], {}
    for entry in status['completed_rounds']:
        version, round_number = entry['version'], entry['round']
        artifact = run/version/f'R{round_number}'
        rows.append({key: entry[key] for key in
                     ('version', 'round', 'decision', 'steps_added', 'parent_score', 'candidate_score')})
        curves[f'{version}-R{round_number}'] = [
            {key: point[key] for key in ('relative_step', 'validation_objective_per_student', 'hungarian_objective_per_student')}
            for point in map(json.loads, (artifact/'learning_curve.jsonl').read_text(encoding='utf-8').splitlines())
        ]
    metrics = {}
    for name, row in {**external['models'], **external['baselines']}.items():
        metrics[name] = {'objective_per_student': row['objective_per_student'],
                         'metrics': {key: row['metrics'][key] for key in ('coverage', 'constraint_violations')}}
    return {
        'mode': 'semester_nested', 'run_id': release,
        'results': rows, 'curves': curves,
        'cohorts': {v: {k: row[k] for k in ('semester_id', 'train', 'validation')}
                    for v, row in read(suites/'readiness.json')['versions'].items()},
        'rounds_per_version': status['protocol']['rounds_per_version'],
        'steps_per_round': status['protocol']['steps_per_round'],
        'total_compute_steps': sum(row['steps_added'] for row in rows),
        'selected_checkpoint': 'PPO V3 / R4',
        'selected_weight_steps': read(run/'V3/R4/report.json')['steps_after'],
        'feedback_counts': {row['version']: {'r2': row['r2_signal_students'], 'r3': row['r3_outcome_students']}
                            for row in feedback['versions']},
        'test': {'semester_id': external['semester'], 'n_test': external['n_test'], 'metrics': metrics},
    }


def export_catalog_release(outputs, destination, release):
    outputs = Path(outputs).resolve()
    suites = outputs/'semester_rl_20261111_trusted_year_github/strict/suites'
    torch.set_num_threads(1)
    service, _ = load_catalog(outputs, Path(destination).parent/'verify')
    versions = {**service.versions, 'model_release': release}
    files = {}

    def add(name, value):
        files[name] = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()

    encoder = read(suites/'encoder.json')
    add('encoder.json', {key: encoder[key] for key in ('schema_version', 'vocabulary', 'idf')})
    add('taxonomy.json', service.taxonomy)
    add('versions.json', versions)
    add('training_report.json', training_summary(outputs, release, suites))
    add('faculty.json', [{key: row[key] for key in ('advisor_id', 'title', 'content', 'source_url')}
                         for row in read(suites/'V3/faculty_records.json')])
    for version, (models, contracts, advisors) in service.checkpoint_versions.items():
        add(f'{version}/advisors.json', advisors)
        for algorithm, model in models.items():
            contract = {key: contracts[algorithm][key] for key in
                        ('state_contract', 'feature_contract_sha256', 'taxonomy_feature_order_sha256',
                         'quota_policy_version', 'reward_weights')}
            config = model.config if algorithm == 'ppo' else {'hidden_sizes': model.hidden_sizes}
            add(f'{version}/{algorithm}.json', {'contract': contract, 'config': config})
            buffer = io.BytesIO()
            torch.save((model.model.policy if algorithm == 'ppo' else model.online).state_dict(), buffer)
            files[f'{version}/{algorithm}.pt'] = buffer.getvalue()
    return write_release(files, {'kind': 'semester-catalog'}, destination)


def load_catalog_release(folder, runtime):
    folder = Path(folder)
    versions, taxonomy = read(folder/'versions.json'), read(folder/'taxonomy.json')
    tag_order = sorted((group, tag) for group, tags in taxonomy['groups'].items() for tag in tags)
    taxonomy_hash = record_hash({'version': 'document-concept-presence/1', 'order': tag_order})
    if set(versions['checkpoint_catalog']) != {f'{a}_{v}' for v in VERSIONS for a in ALGORITHMS}:
        raise ValueError('incomplete_checkpoint_catalog')
    torch.set_num_threads(1)
    catalog = {}
    advisor_ids = [row['advisor_id'] for row in read(folder/'V3/advisors.json')]
    for version in VERSIONS:
        advisors = read(folder/version/'advisors.json')
        if [row['advisor_id'] for row in advisors] != advisor_ids:
            raise ValueError('catalog_advisor_registry_mismatch')
        models, contracts = {}, {}
        for algorithm in ALGORITHMS:
            item = read(folder/version/f'{algorithm}.json')
            contract, config = item['contract'], item['config']
            if (contract['taxonomy_feature_order_sha256'] != taxonomy_hash
                    or contract['quota_policy_version'] != QUOTA
                    or versions['quota_policy_version'] != QUOTA):
                raise ValueError('catalog_policy_contract_mismatch')
            count = len(advisor_ids)
            env = MatchingEnv([AllocationProblem(
                scores=np.zeros((1, count)), available=np.zeros((1, count), dtype=bool),
                student_ids=('synthetic',), advisor_ids=advisor_ids, capacities=np.ones(count, dtype=int),
                eligible=np.ones((1, count), dtype=bool), present=np.ones(count, dtype=bool),
                student_features=np.zeros((1, len(tag_order))),
                metadata={key: contract[key] for key in ('feature_contract_sha256', 'taxonomy_feature_order_sha256')},
            )])
            if contract['state_contract'] != env.state_contract or contract['reward_weights'] != env.reward_weights:
                raise ValueError('catalog_inference_contract_mismatch')
            if algorithm == 'ppo':
                model = MaskedPPOAgent(env, contract=contract, **{**config, 'n_steps': 2, 'batch_size': 2})
                network = model.model.policy
                network.set_training_mode(False)
            else:
                model = MaskedDQN(env.observation_space.shape[0], count, contract=contract,
                                  **config, buffer_size=1, batch_size=1)
                network = model.online.eval()
            network.load_state_dict(torch.load(folder/version/f'{algorithm}.pt', map_location='cpu', weights_only=True))
            if any(not torch.isfinite(value).all() for value in network.parameters()):
                raise ValueError('catalog_nonfinite_model_weights')
            models[algorithm], contracts[algorithm] = model, contract
        catalog[version] = models, contracts, advisors
    pipeline = FrozenSemesterPipeline(read(folder/'encoder.json'), [row['name'] for row in advisors])
    return assemble_catalog(pipeline, taxonomy, catalog, versions, runtime, read(folder/'faculty.json'))
