"""Prepare and execute source-bound semester RL with immutable round artifacts."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.features.fresh_suite import digest, write_json
from src.features.semester_suite import VERSIONS, prepare_suites
from src.rl.model_retention import create_retention
from src.rl.nested_learning import decode_problem, run_round, validate_round, verify_round


def validate_budget(steps):
    if type(steps) is not int or steps < 100000:
        raise ValueError('at_least_100000_steps_per_main_training_round_required')
    return steps


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def verify_suites(suites, *, expected_manifest_sha256=None):
    suites = Path(suites).resolve()
    if expected_manifest_sha256 is not None and digest(suites / 'manifest.json') != expected_manifest_sha256:
        raise ValueError('frozen_suite_manifest_hash_mismatch')
    manifest = read(suites / 'manifest.json')
    for relative, sha in manifest['artifacts'].items():
        path = (suites / relative).resolve()
        if not path.is_relative_to(suites) or digest(path) != sha:
            raise ValueError('frozen_suite_hash_mismatch')
    return manifest


def verify_source_audit(path, expected_suite_sha256):
    audit = read(path)
    if audit.get('suite_manifest_sha256') != expected_suite_sha256 or audit.get('score_parity_verified') is not True:
        raise ValueError('source_audit_suite_or_parity_mismatch')
    for source, sha in {**audit['source_files'], **audit['raw_files']}.items():
        if digest(source) != sha:
            raise ValueError('source_audit_hash_mismatch')
    return audit


def train(suites, output, *, steps=131072, rounds=4, stop_after=None, feedback=None, seed=42, source_audit=None):
    validate_budget(steps)
    if rounds not in (3, 4):
        raise ValueError('three_or_four_rounds_required')
    suites, output = Path(suites).resolve(), Path(output).resolve()
    verify_suites(suites)
    protocol = {'schema': 'semester-training/1', 'calendar_protocol': 'semester-pool/1', 'algorithm': 'ppo',
                'seed': seed, 'steps_per_round': steps, 'rounds_per_version': rounds,
                'versions': VERSIONS, 'suite_manifest_sha256': digest(suites / 'manifest.json'),
                'checkpoint_selection': 'final_only', 'test_protocol': 'external_2025.3_once_after_freeze',
                'feedback_mode': 'real_survey_registration_status_not_invented_advisor_response'}
    if output.exists():
        if read(output / 'protocol.json') != protocol:
            raise ValueError('resume_protocol_must_match_frozen_run')
    else:
        output.mkdir(parents=True)
        write_json(output / 'protocol.json', protocol)
    audit_binding = output / 'source_binding.json'
    if source_audit is None and audit_binding.exists():
        source_audit = read(audit_binding)['path']
    if source_audit is not None:
        source_audit = Path(source_audit).resolve()
        verify_source_audit(source_audit, protocol['suite_manifest_sha256'])
        binding = {'path':str(source_audit),'sha256':digest(source_audit)}
        if audit_binding.exists() and read(audit_binding) != binding:
            raise ValueError('resume_source_audit_binding_mismatch')
        if not audit_binding.exists():
            write_json(audit_binding,binding)
    elif feedback is not None:
        raise ValueError('source_audit_required_before_multi_round_continuation')
    if feedback is not None:
        feedback = Path(feedback).resolve()
        if read(feedback / 'readiness.json').get('ready') is not True:
            raise ValueError('complete_historical_feedback_or_explicit_empty_optimization_decision_required')
        manifest = read(feedback / 'manifest.json')
        for relative, sha in manifest['artifacts'].items():
            path = (feedback / relative).resolve()
            if not path.is_relative_to(feedback) or digest(path) != sha:
                raise ValueError('frozen_feedback_hash_mismatch')
        binding = {'path': str(feedback), 'manifest_sha256': digest(feedback / 'manifest.json')}
        binding_path = output / 'feedback_binding.json'
        if binding_path.exists() and read(binding_path) != binding:
            raise ValueError('resume_feedback_must_match_first_attached_source')
        if not binding_path.exists():
            write_json(binding_path, binding)
    parent = accepted = None
    history, results = {}, []
    for version in VERSIONS:
        initial = read(suites / version / 'suite.json')
        for index in range(1, rounds + 1):
            folder = output / version / f'R{index}'
            feedback_path = Path(feedback) / version / f'R{min(index,3)}.json' if feedback else None
            data = initial if index == 1 else read(feedback_path) if feedback_path and feedback_path.is_file() else None
            if data is None:
                write_json(output / 'status.json', {'status': 'waiting_for_feedback', 'version': version, 'round': index,
                                                    'completed_rounds': results, 'training_finished': False})
                return {'status': 'waiting_for_feedback', 'completed_rounds': len(results), 'next': f'{version}-R{index}'}
            spec = dict(data['round'])
            spec.update(round_id=f'{version}-R{index}', round_index=index, seed=seed)
            if index == 4:
                spec['control'] = 'extra_steps_no_new_signal'
            if (folder / 'manifest.json').exists():
                result = verify_round(folder)
                saved = read(folder / 'input.json')
                if saved['requested_timesteps'] != steps or saved['round'] != spec:
                    raise ValueError('resume_round_input_mismatch')
            elif folder.exists():
                raise ValueError('interrupted_round_requires_review_preserve_partial_artifacts')
            else:
                validate_round([decode_problem(p) for p in data['train']], decode_problem(data['validation']),
                               data['contract'], spec, parent=parent)
                print(f'START {version} R{index}: {steps} new steps', flush=True)
                result = run_round([decode_problem(p) for p in data['train']], decode_problem(data['validation']),
                                   data['contract'], spec, folder, parent=parent, total_timesteps=steps,
                                   historical_validation={k: decode_problem(p) for k,p in history.items()}, eval_interval=8192)
                if result['steps_added'] < 100000:
                    raise ValueError('actual_main_round_budget_not_met')
            if result['decision'] == 'accepted':
                accepted = parent = folder
            elif accepted is not None:
                ledger = output / version / f'R{index}-retained.json'
                if not ledger.exists():
                    create_retention(accepted, folder, ledger)
                parent = ledger
            else:
                raise RuntimeError('bootstrap_not_accepted_no_safe_weight_source')
            results.append({'version': version, 'round': index, 'artifact': str(folder), 'effective_weight_source': str(accepted),
                            **{k: result[k] for k in ('decision','steps_before','steps_added','steps_after','candidate_score',
                                                     'parent_score','delta','start_weights_equal_parent','training_elapsed_seconds')}})
            write_json(output / 'status.json', {'status': 'running', 'completed_rounds': results, 'training_finished': False})
            print(f'DONE {version} R{index}: {result["decision"]}; added={result["steps_added"]}', flush=True)
            if stop_after == f'{version}-R{index}':
                write_json(output / 'status.json', {'status': 'stopped_at_requested_round', 'completed_rounds': results,
                                                    'training_finished': False, 'accepted': str(accepted),
                                                    'next_round_requires_source_or_explicit_optimization_only': True})
                return {'status': 'stopped_at_requested_round', 'completed_rounds': len(results), 'accepted': str(accepted)}
        history[version] = initial['validation']
    final = {'status': 'completed', 'completed_rounds': results, 'training_finished': True,
             'accepted': str(accepted), 'test_evaluated': False, 'protocol': protocol,
             'protocol_sha256': digest(output / 'protocol.json'),
             'source_audit_binding_sha256':digest(output/'source_binding.json'),
             'feedback_binding_sha256':digest(output/'feedback_binding.json')}
    write_json(output / 'status.json', final)
    write_json(output / 'selection.json', {'accepted': str(accepted), 'checkpoint_sha256': verify_round(accepted)['checkpoint_sha256'],
                                         'training_status_sha256': digest(output / 'status.json'), 'test_evaluated': False})
    return final


def evaluate_final(suites, training):
    """Open the external cohort once, after complete training and selection."""
    suites, training = Path(suites).resolve(), Path(training).resolve()
    if not (training / 'status.json').is_file():
        raise ValueError('completed_training_required_before_external_test')
    status = read(training / 'status.json')
    if status.get('status') != 'completed' or status.get('training_finished') is not True:
        raise ValueError('completed_training_required_before_external_test')
    protocol = read(training / 'protocol.json')
    if digest(training / 'protocol.json') != status['protocol_sha256']:
        raise ValueError('frozen_training_protocol_hash_mismatch')
    for name,key in [('source_binding.json','source_audit_binding_sha256'),('feedback_binding.json','feedback_binding_sha256')]:
        if digest(training/name) != status.get(key):
            raise ValueError('frozen_training_source_binding_hash_mismatch')
    source_binding=read(training/'source_binding.json')
    if digest(source_binding['path'])!=source_binding['sha256']:
        raise ValueError('frozen_source_audit_receipt_hash_mismatch')
    verify_source_audit(source_binding['path'],protocol['suite_manifest_sha256'])
    if len(status['completed_rounds']) != len(VERSIONS) * protocol['rounds_per_version']:
        raise ValueError('all_main_rounds_required_before_external_test')
    for entry in status['completed_rounds']:
        report = verify_round(entry['artifact'])
        if report['steps_added'] < 100000:
            raise ValueError('main_round_budget_incomplete')
    selection = read(training / 'selection.json')
    if selection['training_status_sha256'] != digest(training / 'status.json'):
        raise ValueError('frozen_selection_training_hash_mismatch')
    verify_suites(suites, expected_manifest_sha256=protocol['suite_manifest_sha256'])
    selected = Path(selection['accepted']).resolve()
    if not selected.is_relative_to(training):
        raise ValueError('selected_checkpoint_outside_training_run')
    report = verify_round(selected)
    if report['decision'] != 'accepted' or report['checkpoint_sha256'] != selection['checkpoint_sha256']:
        raise ValueError('accepted_selected_checkpoint_hash_mismatch')
    from src.rl.nested_learning import _parent, _load_parent
    from src.evaluation.rebuild_benchmark import evaluate_problem
    problem = decode_problem(read(suites / 'external_test/problem.json'))
    selected_contract = read(selected / 'input.json')['contract']
    if (problem.metadata.get('semester_id') != '2025.3'
            or any(problem.metadata.get(key) != selected_contract.get(key)
                   for key in ('feature_contract_sha256','taxonomy_feature_order_sha256'))):
        raise ValueError('external_test_semester_or_feature_contract_mismatch')
    learned = {sid for entry in status['completed_rounds'] for sid in read(Path(entry['artifact']) / 'input.json')['memberships']['train']}
    if problem.metadata.get('split') != 'test' or set(problem.student_ids) & learned:
        raise ValueError('external_holdout_training_overlap')
    destination = training / 'final_test'
    destination.mkdir(exist_ok=False)
    # Exclusive marker is written before evaluating; an interrupted opening is
    # retained and cannot silently be repeated under the same protocol.
    write_json(destination / 'opened.json', {'protocol':'external_2025.3_once_after_freeze',
                                            'selection_sha256':digest(training / 'selection.json'),
                                            'problem_sha256':digest(suites / 'external_test/problem.json')})
    model = _load_parent(_parent(selected))
    metrics = {}
    for algorithm in ('ppo','hungarian','greedy','random'):
        result = evaluate_problem(problem,algorithm,model=model if algorithm=='ppo' else None,seed=protocol['seed'])
        metrics[algorithm] = {'objective_per_student':result['metrics']['objective']/len(problem.student_ids),
                              'metrics':result['metrics'],'invalid_action_count':result['invalid_action_count'],
                              'status':result['status']}
    final = {'status':'completed','semester_id':'2025.3','n_test':len(problem.student_ids),'metrics':metrics,
             'selected_checkpoint':str(selected),'selection_sha256':digest(training/'selection.json'),
             'scope':'retrospective_document_proxy','prediction_time_verified':False,
             'test_used_for_training_or_selection':False,'test_openings':1,'production_promoted':False}
    write_json(destination/'results.json',final)
    write_json(destination/'manifest.json',{'selection_sha256':digest(training/'selection.json'),
                                          'artifacts':{name:digest(destination/name) for name in ('opened.json','results.json')}})
    return final


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare')
    prep.add_argument('--inputs', type=Path, required=True)
    prep.add_argument('--output', type=Path, required=True)
    prep.add_argument('--quota-policy', choices=('equal',), required=True)
    audit = commands.add_parser('audit-sources')
    audit.add_argument('--inputs',type=Path,required=True)
    audit.add_argument('--suites',type=Path,required=True)
    audit.add_argument('--output',type=Path,required=True)
    survey = commands.add_parser('feedback')
    survey.add_argument('--suites', type=Path, required=True)
    survey.add_argument('--survey', type=Path, required=True)
    survey.add_argument('--inputs', type=Path, required=True)
    survey.add_argument('--output', type=Path, required=True)
    survey.add_argument('--allow-empty-optimization', action='store_true', help='Requires explicit authorization to continue rounds without historical feedback.')
    fit = commands.add_parser('train')
    fit.add_argument('--suites', type=Path, required=True)
    fit.add_argument('--output', type=Path, required=True)
    fit.add_argument('--feedback', type=Path)
    fit.add_argument('--timesteps', type=int, default=131072)
    fit.add_argument('--rounds', type=int, choices=(3,4), default=4)
    fit.add_argument('--stop-after')
    fit.add_argument('--source-audit',type=Path)
    final = commands.add_parser('evaluate')
    final.add_argument('--suites', type=Path, required=True)
    final.add_argument('--training', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        result = prepare_suites(args.inputs, args.output, quota_policy=args.quota_policy)
    elif args.command == 'audit-sources':
        from src.features.semester_suite import audit_existing_sources
        verify_suites(args.suites)
        result = audit_existing_sources(args.suites,args.inputs,args.output)
    elif args.command == 'feedback':
        from src.features.survey_feedback import prepare_feedback
        verify_suites(args.suites)
        result = prepare_feedback(args.suites,args.survey,args.output,inputs=args.inputs,allow_empty=args.allow_empty_optimization)
    elif args.command == 'evaluate':
        result = evaluate_final(args.suites,args.training)
    else:
        result = train(args.suites,args.output,steps=args.timesteps,rounds=args.rounds,stop_after=args.stop_after,feedback=args.feedback,source_audit=args.source_audit)
    print(json.dumps(result,ensure_ascii=True,indent=2))


if __name__ == '__main__':
    main()
