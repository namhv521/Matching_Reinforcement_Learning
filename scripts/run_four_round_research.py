"""Run source-bound V1/V2/V3 x R1..R4; never invent missing feedback.

R2/R3 are complete engine suites with verified, applied feedback sources.
R4 repeats R3 unchanged as an explicit optimization-only control.
"""
import argparse
import copy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.rl.nested_learning import decode_problem, run_round
from src.rl.model_retention import create_retention

VERSIONS = ('V1', 'V2', 'V3')
TERMS = ('2024.1', '2024.2', '2025.1')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def readiness(suites, feedback):
    rows = []
    for version in VERSIONS:
        for round_id in ('R1', 'R2', 'R3', 'R4'):
            source = (Path(suites) / version / 'suite.json' if round_id == 'R1'
                      else Path(feedback) / version / f'{round_id}.json')
            rows.append({'version': version, 'round': round_id,
                         'status': ('optimization_only_same_as_R3' if round_id == 'R4'
                                    else 'input_present_unvalidated' if source.is_file() else 'missing_input'),
                         'required_signal': {'R1': 'initial_source', 'R2': 'student_preference',
                                             'R3': 'advisor_feedback', 'R4': 'none'}[round_id]})
    return {'schema': 'four-round-research/1', 'ready': not any(
        row['status'] == 'missing_input' for row in rows), 'rounds': rows,
        'test_evaluated': False, 'serving_model_changed': False}


def prepare(payload, version, round_index, algorithm, seed):
    data = copy.deepcopy(payload)
    spec = data['round']
    if spec['semester_id'] != TERMS[VERSIONS.index(version)]:
        raise ValueError('suite_semester_mismatch')
    spec.update(round_index=round_index, algorithm=algorithm, seed=seed,
                round_id=f'{version}-R{round_index}-{algorithm}')
    if round_index in (2, 3):
        kind = 'student_preference' if round_index == 2 else 'advisor_feedback'
        if not any(s['type'] == kind for s in spec['signals']):
            raise ValueError('required_round_feedback_missing: ' + kind)
        spec.pop('control', None)
    if round_index == 4:
        spec['control'] = 'extra_steps_no_new_signal'
    return data


def run(suites, feedback, output, *, timesteps=131072, eval_interval=8192, seed=42,
        algorithms=('ppo', 'dqn')):
    status = readiness(suites, feedback)
    if not status['ready']:
        raise ValueError('missing_real_feedback_inputs; run --preflight for details')
    if timesteps < 1 or eval_interval < 1 or not algorithms or len(set(algorithms)) != len(algorithms) or set(algorithms) - {'ppo', 'dqn'}:
        raise ValueError('positive_budgets_and_unique_supported_algorithms_required')
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('new_output_required; previous_experiments_are_immutable')
    # Load all requested inputs before spending training time. Engine checks source
    # hashes, holdout separation and exact applied deltas again at each round.
    inputs = {v: {1: read(Path(suites) / v / 'suite.json'),
                  2: read(Path(feedback) / v / 'R2.json'),
                  3: read(Path(feedback) / v / 'R3.json')} for v in VERSIONS}
    recipes = {inputs[v][i].get('mock_recipe', 'top_similarity_preference_0.8_and_one_extra_advisor_seat')
               for v in VERSIONS for i in (2, 3)}
    if len(recipes) != 1:
        raise ValueError('one_consistent_feedback_recipe_required')
    for version in VERSIONS:
        for index in (1, 2, 3):
            prepare(inputs[version][index], version, index, algorithms[0], seed)
    output.mkdir(parents=True)
    protocol = {'timesteps_per_fit': timesteps, 'eval_interval': eval_interval, 'seed': seed,
                'feedback_recipe': next(iter(recipes)),
                'feedback_scope': ('simulated_feedback_not_human' if any(
                    inputs[v][i].get('experiment_scope') == 'simulated_feedback_not_human'
                    for v in VERSIONS for i in (2, 3)) else 'source_bound_feedback'),
                'evaluation_scope': 'reused_development_validation_no_new_independent_test',
                'algorithms': list(algorithms), 'round4': 'extra_steps_no_new_signal',
                'checkpoint_selection': 'final_only', 'final_test': 'not_opened',
                'thresholds': {'min_improvement': 0, 'max_new_drop': 0, 'max_old_drop': 0,
                               'accept_non_regression': True}}
    write(output / 'protocol.json', protocol)
    summary = {**status, 'status': 'running', 'results': [], 'protocol': protocol}
    for algorithm in algorithms:
        parent, accepted, history = None, None, {}
        for version in VERSIONS:
            for index in (1, 2, 3, 4):
                data = prepare(inputs[version][min(index, 3)], version, index, algorithm, seed)
                data['round']['decision_thresholds'] = protocol['thresholds']
                folder = output / version / f'R{index}' / algorithm
                result = run_round([decode_problem(p) for p in data['train']],
                    decode_problem(data['validation']), data['contract'], data['round'], folder,
                    parent=parent, total_timesteps=timesteps, eval_interval=eval_interval,
                    historical_validation={k: decode_problem(p) for k, p in history.items()})
                if result['decision'] == 'accepted':
                    accepted = parent = folder
                elif accepted is not None:
                    parent = folder.parent / f'{algorithm}-retained.json'
                    create_retention(accepted, folder, parent)
                else:
                    raise RuntimeError('bootstrap_not_accepted; no_safe_parent')
                summary['results'].append({'version': version, 'round': f'R{index}',
                    'algorithm': algorithm, 'artifact': folder.relative_to(output).as_posix(),
                    'effective_weight_source': accepted.relative_to(output).as_posix(),
                    **{key: result.get(key) for key in ('decision', 'candidate_score', 'parent_score',
                        'delta', 'steps_before', 'steps_added', 'steps_after', 'start_weights_equal_parent',
                        'forgetting_status', 'training_elapsed_seconds', 'improvement_attribution')}})
                write(output / 'comparison.json', summary)
            history[version] = inputs[version][1]['validation']
    summary['status'] = 'completed'
    write(output / 'comparison.json', summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suites', type=Path, required=True)
    parser.add_argument('--feedback', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--preflight', action='store_true')
    parser.add_argument('--timesteps', type=int, default=131072)
    parser.add_argument('--eval-interval', type=int, default=8192)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--algorithms', nargs='+', choices=('ppo', 'dqn'), default=['ppo', 'dqn'])
    args = parser.parse_args()
    if args.preflight:
        result = readiness(args.suites, args.feedback)
    else:
        if not args.output:
            parser.error('--output required for training')
        result = run(args.suites, args.feedback, args.output, timesteps=args.timesteps,
                     eval_interval=args.eval_interval, seed=args.seed, algorithms=tuple(args.algorithms))
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
