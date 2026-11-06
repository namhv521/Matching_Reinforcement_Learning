"""Source-bound nested RL rounds, isolated from legacy data and serving.

An accepted research checkpoint is not institutional approval or a production
promotion. Future human signals are never fabricated to complete a round chain.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import random
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch

from src.data_pipeline.review_decisions import record_hash
from src.domain.rebuild_matching import AllocationProblem, feasible
from src.environment.rebuild_env import MatchingEnv
from src.evaluation.rebuild_benchmark import evaluate_problem, problem_payload
from src.rl.rebuild_dqn import MaskedDQN, ReplayBuffer
from src.rl.rebuild_ppo import MaskedPPOAgent


SCHEMA = 'nested-rl-round/1.0'
TERM_ORDER = ('2024.1', '2024.2', '2025.1', '2025.2')
TERM_LIMITS = {'2024.1': (None, '2025-01-01T00:00:00+07:00'),
               '2024.2': ('2025-01-01T00:00:00+07:00', '2025-07-01T00:00:00+07:00'),
               # Academic source cohorts may start in June; model snapshot
               # cutoffs and chronological parent inheritance remain separate.
               '2025.1': ('2025-06-01T00:00:00+07:00', '2026-01-01T00:00:00+07:00'),
               '2025.2': ('2026-01-01T00:00:00+07:00', '2026-07-01T00:00:00+07:00')}
REPRESENTATION_KEYS = ('state_contract', 'feature_contract_sha256', 'taxonomy_feature_order_sha256')
SIGNAL_TYPES = {'initial_source', 'student_preference', 'advisor_feedback', 'coordinator_correction', 'verified_outcome'}
POOL_TERM_ORDER = ('2024', '2025.1', '2025.2')
POOL_TERM_LIMITS = {'2024': (None, '2025-09-01T00:00:00+07:00'),
                    '2025.1': ('2025-09-01T00:00:00+07:00', '2026-01-01T00:00:00+07:00'),
                    '2025.2': ('2026-01-01T00:00:00+07:00', '2026-06-01T00:00:00+07:00')}


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def _digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _time(value):
    if not isinstance(value, str):
        raise ValueError('timezone_timestamp_required')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timezone_timestamp_required')
    return parsed


def _hash(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('explicit_sha256_required')
    return value


def decode_problem(payload):
    value = copy.deepcopy(payload)
    for name in ('scores', 'student_features', 'preferences'):
        value[name] = np.asarray(value[name], dtype=float)
    for name in ('available', 'eligible', 'present', 'student_feature_known', 'preference_known'):
        value[name] = np.asarray(value[name], dtype=bool)
    value['capacities'] = np.asarray(value['capacities'], dtype=int)
    return AllocationProblem(**value)


def verify_round(directory):
    directory = Path(directory).resolve()
    manifest = _read(directory / 'manifest.json')
    if manifest.get('schema_version') != SCHEMA:
        raise ValueError('nested_round_manifest_required')
    artifacts = manifest.get('artifacts')
    if not isinstance(artifacts, dict) or not {'input.json', 'report.json', 'decision.json'} <= set(artifacts):
        raise ValueError('complete_round_artifact_inventory_required')
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob('*')
              if p.is_file() and p != directory / 'manifest.json'}
    if actual != set(artifacts):
        raise ValueError('artifact_hash_inventory_mismatch')
    for relative, expected in artifacts.items():
        path = directory / relative
        if path.is_symlink() or not path.resolve().is_relative_to(directory) or _digest(path) != expected:
            raise ValueError('artifact_hash_mismatch: ' + relative)
    report = _read(directory / 'report.json')
    if _read(directory / 'decision.json')['decision'] != report['decision']:
        raise ValueError('decision_report_mismatch')
    return report


def _parent(directory):
    if directory is None:
        return None
    directory = Path(directory).resolve()
    if directory.is_file():
        from src.rl.model_retention import resolve_retention
        return resolve_retention(directory)
    report = verify_round(directory)
    if report['decision'] != 'accepted':
        raise ValueError('accepted_parent_required')
    return {'path': directory, 'report': report, 'input': _read(directory / 'input.json')}


def _memberships(train, validation):
    return {'train': sorted(s for p in train for s in p.student_ids), 'validation': sorted(validation.student_ids)}


def _thresholds(spec):
    supplied = spec.get('decision_thresholds')
    if not isinstance(supplied, dict):
        raise ValueError('explicit_decision_thresholds_required')
    result = {}
    for name in ('min_improvement', 'max_new_drop', 'max_old_drop'):
        value = supplied.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError('nonnegative_decision_threshold_required: ' + name)
        result[name] = float(value)
    result['accept_non_regression'] = supplied.get('accept_non_regression', False)
    if type(result['accept_non_regression']) is not bool:
        raise ValueError('boolean_accept_non_regression_required')
    return result


def _feedback_values(problems):
    values = {}
    for problem in problems:
        anchor = min(problem.student_ids)
        for field in ('present', 'capacities'):
            for j, advisor in enumerate(problem.advisor_ids):
                values[(field, anchor, advisor)] = getattr(problem, field)[j].item()
        for field in ('scores', 'available', 'eligible', 'preferences', 'preference_known'):
            for i, student in enumerate(problem.student_ids):
                for j, advisor in enumerate(problem.advisor_ids):
                    values[(field, student, advisor)] = getattr(problem, field)[i, j].item()
    return values


def _validate_applied_feedback(previous, train, contract, spec, snapshot):
    old_spec = previous['input']['round']
    old_ids = {signal['signal_id'] for signal in old_spec['signals']}
    new_signals = [s for s in spec['signals'] if s['signal_id'] not in old_ids]
    human = [s for s in new_signals if s['type'] != 'initial_source']
    if not human:
        if spec['semester_id'] == old_spec['semester_id']:
            before = previous['input']['train']
            after = [problem_payload(p) for p in train]
            if spec.get('control') == 'extra_steps_no_new_signal' and record_hash(before) != record_hash(after):
                raise ValueError('extra_steps_control_requires_identical_inputs')
            if spec.get('control') != 'extra_steps_no_new_signal':
                raise ValueError('same_semester_typed_feedback_required')
        return []
    if spec.get('control') == 'extra_steps_no_new_signal':
        raise ValueError('feedback_cannot_be_extra_steps_control')
    if spec['semester_id'] != old_spec['semester_id']:
        raise ValueError('human_feedback_requires_same_semester_parent')
    if contract['reward_weights'] != previous['input']['contract']['reward_weights']:
        raise ValueError('unsupported_feedback_reward_change')
    old = [decode_problem(p) for p in previous['input']['train']]
    old_cohorts = {tuple(sorted(p.student_ids)): p for p in old}
    for p in train:
        q = old_cohorts.get(tuple(sorted(p.student_ids)))
        if q is None:
            raise ValueError('feedback_cohort_partition_changed')
        # Feature migrations, fixed assignments and reward-weight changes need a
        # separate explicit adapter; a human signal cannot silently authorize them.
        for field in ('student_features', 'student_feature_known'):
            if any(not np.array_equal(getattr(p, field)[p.student_ids.index(s)], getattr(q, field)[q.student_ids.index(s)]) for s in p.student_ids):
                raise ValueError('unsupported_feedback_feature_change')
        if dict(p.fixed_assignments) != dict(q.fixed_assignments) or p.preference_weight != q.preference_weight:
            raise ValueError('unsupported_feedback_fixed_or_weight_change')
    before, after = _feedback_values(old), _feedback_values(train)
    actual = {key: (before[key], after[key]) for key in before if before[key] != after[key]}
    declared = {}
    allowed = {'student_preference': {'preferences', 'preference_known'},
               'verified_outcome': {'preferences', 'preference_known'},
               'advisor_feedback': {'eligible', 'present', 'capacities'},
               'coordinator_correction': {'eligible', 'present', 'capacities', 'scores', 'available'}}
    expected_sources = {s['signal_id']: s['source_sha256'] for s in human}
    if snapshot.get('applied_signal_source_sha256') != expected_sources:
        raise ValueError('applied_signal_source_binding_required')
    student_cohort = {s: min(p.student_ids) for p in train for s in p.student_ids}
    for signal in human:
        if signal['type'] not in allowed:
            raise ValueError('unsupported_feedback_signal_type')
        source = _read(signal['source_path'])
        if (signal['type'] == 'verified_outcome'
                and source.get('provenance') != 'historical_thesis_supervision_outcome_proxy_not_independent_advisor_acceptance'):
            raise ValueError('unsupported_feedback_signal_type')
        if source.get('signal_id') != signal['signal_id'] or not isinstance(source.get('changes'), list) or not source['changes']:
            raise ValueError('typed_signal_changes_required')
        for row in source['changes']:
            field, student, advisor = row.get('field'), row.get('student_id'), row.get('advisor_id')
            if field not in allowed[signal['type']] or student not in student_cohort:
                raise ValueError('unsupported_feedback_target_or_holdout')
            key = (field, student_cohort[student] if field in ('present', 'capacities') else student, advisor)
            delta = (row.get('old'), row.get('new'))
            if key not in actual or record_hash(delta) != record_hash(actual[key]) or key in declared:
                raise ValueError('feedback_change_not_applied_or_duplicate')
            declared[key] = delta
    if declared.keys() != actual.keys():
        raise ValueError('unattributed_training_input_changes')
    return [signal['signal_id'] for signal in human]


def validate_round(train_problems, validation_problem, contract, round_spec, *, parent=None):
    if not train_problems or not isinstance(validation_problem, AllocationProblem):
        raise ValueError('nonempty_train_and_validation_required')
    memberships = _memberships(train_problems, validation_problem)
    if len(set(memberships['train'])) != len(memberships['train']):
        raise ValueError('duplicate_training_students')
    if not memberships['validation'] or set(memberships['train']) & set(memberships['validation']):
        raise ValueError('holdout_overlap_or_empty_validation')
    if any(p.metadata.get('split') != 'train' for p in train_problems) or validation_problem.metadata.get('split') != 'validation':
        raise ValueError('explicit_train_validation_splits_required')
    if not all(feasible(p) for p in [*train_problems, validation_problem]):
        raise ValueError('feasible_cohorts_required')
    env = MatchingEnv(train_problems, reward_weights=contract.get('reward_weights'))
    if (contract.get('state_contract') != env.state_contract
            or contract.get('reward_weights') != env.reward_weights
            or sorted(contract.get('training_student_ids', [])) != memberships['train']):
        raise ValueError('current_training_contract_mismatch')
    if (tuple(validation_problem.advisor_ids) != env.advisor_ids
            or validation_problem.student_features.shape[1] != env.feature_dimension):
        raise ValueError('validation_representation_mismatch')
    for name in ('feature_contract_sha256', 'taxonomy_feature_order_sha256'):
        _hash(contract.get(name))
        if any(p.metadata.get(name) != contract[name] for p in [*train_problems, validation_problem]):
            raise ValueError('cohort_feature_contract_mismatch: ' + name)
    if not contract.get('quota_policy_version') or any(p.metadata.get('policy_version') != contract['quota_policy_version'] for p in [*train_problems, validation_problem]):
        raise ValueError('cohort_quota_policy_mismatch')
    algorithm, seed = round_spec.get('algorithm'), round_spec.get('seed')
    index, term = round_spec.get('round_index'), round_spec.get('semester_id')
    if algorithm not in ('ppo', 'dqn') or type(seed) is not int or seed < 0:
        raise ValueError('algorithm_and_nonnegative_seed_required')
    if type(index) is not int or index < 1 or not isinstance(round_spec.get('round_id'), str) or not round_spec['round_id'].strip():
        raise ValueError('positive_round_index_and_id_required')
    calendar = round_spec.get('calendar_protocol', 'legacy/1')
    if calendar not in ('legacy/1', 'semester-pool/1'):
        raise ValueError('known_calendar_protocol_required')
    term_order, term_limits = (POOL_TERM_ORDER, POOL_TERM_LIMITS) if calendar == 'semester-pool/1' else (TERM_ORDER, TERM_LIMITS)
    if term not in term_order:
        raise ValueError('known_semester_id_required')
    cutoff = _time(round_spec.get('cutoff_timestamp'))
    lower, upper = term_limits[term]
    if cutoff >= _time(upper) or (lower and cutoff < _time(lower)):
        raise ValueError('round_cutoff_outside_semester_window')
    for name in ('reward_version', 'constraint_version'):
        if not isinstance(round_spec.get(name), str) or not round_spec[name].strip():
            raise ValueError('explicit_reward_and_constraint_versions_required')
    _hash(round_spec.get('signal_state_sha256'))
    thresholds = _thresholds(round_spec)
    previous = _parent(parent)
    if previous is None and index != 1:
        raise ValueError('parent_required_for_later_round')
    if previous is None and term != term_order[0] and round_spec.get('control') != 'from_scratch':
        raise ValueError('parent_required_after_bootstrap_semester')
    proxy = (contract.get('scope') == 'retrospective_document_proxy'
             and round_spec.get('availability_assumption') == 'retrospective_event_time_proxy')
    signals = round_spec.get('signals')
    if not isinstance(signals, list) or not signals:
        raise ValueError('observed_signals_required')
    signal_ids = [r.get('signal_id') for r in signals]
    if any(not isinstance(x, str) or not x.strip() for x in signal_ids) or len(set(signal_ids)) != len(signal_ids):
        raise ValueError('unique_signal_id_required')
    for signal in signals:
        kind = signal.get('type')
        if kind not in SIGNAL_TYPES:
            raise ValueError('known_signal_type_required')
        if signal.get('review_status') not in ({'verified', 'source_verified'} if kind == 'initial_source' else {'verified'}):
            raise ValueError('unverified_signal')
        if signal.get('split', 'train') != 'train':
            raise ValueError('signal_must_not_be_holdout')
        available = _time(signal.get('available_at'))
        if available > cutoff:
            year = signal.get('event_year')
            event_upper = signal.get('event_upper_bound')
            bounded_event = event_upper is not None and _time(event_upper) <= cutoff
            year_event = type(year) is int and 1900 <= year <= cutoff.year
            if not (proxy and kind == 'initial_source' and (bounded_event or year_event)):
                raise ValueError('future_signal_at_cutoff')
            # A coarse event-year proxy cannot be assigned to a half-year end.
            if not bounded_event and cutoff.month < 12 and year == cutoff.year:
                raise ValueError('ambiguous_event_year_for_half_year_cutoff')
        source = Path(signal.get('source_path', ''))
        if not source.is_file() or _digest(source) != _hash(signal.get('source_sha256')):
            raise ValueError('signal_source_hash_mismatch')
    snapshot_path = Path(round_spec.get('snapshot_path', ''))
    if not snapshot_path.is_file() or _digest(snapshot_path) != _hash(round_spec.get('snapshot_sha256')):
        raise ValueError('snapshot_hash_mismatch')
    snapshot = _read(snapshot_path)
    for signal in signals:
        if 'event_upper_bound' in signal:
            bound = _time(signal['event_upper_bound'])
            if (not proxy or signal['type'] != 'initial_source' or bound > cutoff
                    or snapshot.get('initial_source_event_upper_bound') != signal['event_upper_bound']):
                raise ValueError('source_event_upper_bound_binding_mismatch')
    if (snapshot.get('training_problem_sha256') != [record_hash(problem_payload(p)) for p in train_problems]
            or snapshot.get('validation_problem_sha256') != record_hash(problem_payload(validation_problem))
            or sorted(snapshot.get('signal_ids', [])) != sorted(signal_ids)):
        raise ValueError('snapshot_problem_or_signal_binding_mismatch')
    if previous is None and any(s['type'] != 'initial_source' for s in signals):
        raise ValueError('human_feedback_requires_same_semester_parent')
    cross_semester = False
    applied_signals = []
    if previous:
        old = previous['input']
        old_spec = old['round']
        if old_spec.get('calendar_protocol', 'legacy/1') != calendar:
            raise ValueError('parent_calendar_protocol_mismatch')
        if old_spec['algorithm'] != algorithm or old_spec['seed'] != seed:
            raise ValueError('parent_algorithm_seed_mismatch')
        if any(old['contract'].get(key) != contract.get(key) for key in REPRESENTATION_KEYS):
            raise ValueError('parent_representation_mismatch')
        if cutoff < _time(old_spec['cutoff_timestamp']):
            raise ValueError('nonchronological_round_cutoff')
        cross_semester = term != old_spec['semester_id']
        if cross_semester:
            if term_order.index(term) != term_order.index(old_spec['semester_id']) + 1 or index != 1:
                raise ValueError('adjacent_semester_and_first_round_required')
        elif index != old_spec['round_index'] + 1 or old['memberships'] != memberships:
            raise ValueError('same_semester_cohort_and_consecutive_round_required')
        previous_ids = {r['signal_id'] for r in old_spec['signals']}
        if not set(signal_ids) - previous_ids and round_spec.get('control') != 'extra_steps_no_new_signal':
            raise ValueError('new_observed_signal_required')
        old_training_ids = set(old['memberships']['train']) | set(previous['report'].get('lineage_training_student_ids', []))
        if old_training_ids & set(memberships['validation']):
            raise ValueError('historical_replay_holdout_overlap')
        applied_signals = _validate_applied_feedback(previous, train_problems, contract, round_spec, snapshot)
    return {'ready': True, 'training_student_count': len(memberships['train']),
            'validation_student_count': len(memberships['validation']), 'memberships': memberships,
            'cross_semester': cross_semester, 'prediction_time_verified': not proxy,
            'availability_assumption': 'retrospective_event_time_proxy' if proxy else 'observed_at_or_before_cutoff',
            'thresholds': thresholds, 'scope': contract.get('scope', 'research_only'),
            'applied_signal_ids': applied_signals}


def _weights(model, algorithm):
    states = {'policy': model.model.policy.state_dict()} if algorithm == 'ppo' else {'online': model.online.state_dict(), 'target': model.target.state_dict()}
    value = hashlib.sha256()
    for network, state in states.items():
        for name, tensor in sorted(state.items()):
            value.update((network + ':' + name).encode())
            value.update(tensor.detach().cpu().numpy().tobytes())
    return value.hexdigest()


def _checkpoint_digest(directory):
    return record_hash({p.name: _digest(p) for p in sorted(Path(directory).iterdir()) if p.is_file()})


def _load_parent(previous):
    data = previous.get('weight_input', previous['input'])
    env = MatchingEnv([decode_problem(p) for p in data['train']], reward_weights=data['contract']['reward_weights'])
    checkpoint = previous['path'] / 'checkpoint'
    if data['round']['algorithm'] == 'ppo':
        model = MaskedPPOAgent.load(checkpoint, env, expected_contract=data['contract'])
        # Native inference checkpoint omits this logging counter; the surrounding
        # hashed training bundle preserves it in the training report.
        model.model._n_updates = previous['report']['training']['epochs_completed']
        return model
    return MaskedDQN.load(checkpoint, expected_contract=data['contract'])


def _replay_semantics(contract, spec):
    return record_hash({'reward_weights': contract['reward_weights'], 'reward_version': spec['reward_version'],
                        'quota_policy': contract['quota_policy_version'], 'constraint_version': spec['constraint_version'],
                        'signal_state_sha256': spec['signal_state_sha256'],
                        'signals': [{k: row[k] for k in ('signal_id', 'type', 'source_sha256')} for row in spec['signals']]})


def _safe(result):
    return (result.get('status') == 'feasible' and result['metrics']['coverage'] == 1.
            and result['metrics']['constraint_violations'] == 0 and result['invalid_action_count'] == 0)


def run_round(train_problems, validation_problem, contract, round_spec, output, *, parent=None,
              total_timesteps=256, model_config=None, historical_validation=None, eval_interval=None):
    source_root = Path(__file__).resolve().parents[2]
    code_sha256 = {name: _digest(source_root / name) for name in (
        'src/rl/nested_learning.py', 'src/rl/rebuild_ppo.py',
        'src/rl/rebuild_dqn.py', 'src/environment/rebuild_env.py', 'src/rl/model_retention.py')}
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('new_round_output_required')
    if parent and output.is_relative_to(Path(parent).resolve()):
        raise ValueError('round_output_must_not_modify_parent')
    if type(total_timesteps) is not int or total_timesteps < 1:
        raise ValueError('positive_timestep_budget_required')
    if eval_interval is not None and (type(eval_interval) is not int or eval_interval < 1):
        raise ValueError('positive_eval_interval_required')
    validation = validate_round(train_problems, validation_problem, contract, round_spec, parent=parent)
    previous = _parent(parent)
    if previous:
        protected = [previous['path']]
        if previous.get('retention'):
            protected.append(Path(previous['retention']['logical_context']['path']))
        if any(output.is_relative_to(path) for path in protected):
            raise ValueError('round_output_must_not_modify_parent')
    algorithm, seed = round_spec['algorithm'], round_spec['seed']
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    env = MatchingEnv(train_problems, shuffle_students=True, reward_weights=contract['reward_weights'])
    old_model = _load_parent(previous) if previous else None
    config = copy.deepcopy(model_config or {})
    if 'seed' in config or 'contract' in config:
        raise ValueError('model_config_cannot_override_identity')
    if previous and model_config is not None:
        raise ValueError('parent_model_configuration_is_inherited')
    retained = []
    if algorithm == 'ppo':
        config = {k: v for k, v in old_model.config.items() if k != 'seed'} if previous else config
        model = MaskedPPOAgent(env, seed=seed, contract=contract, **config)
        if previous:
            model.model.policy.load_state_dict(copy.deepcopy(old_model.model.policy.state_dict()))
            model.model.policy.optimizer.load_state_dict(copy.deepcopy(old_model.model.policy.optimizer.state_dict()))
            model.model.num_timesteps = old_model.model.num_timesteps
            model.model._n_updates = old_model.model._n_updates
        replay_policy = 'fresh_on_policy_rollouts'
    elif previous:
        model = old_model
        weight_input = previous.get('weight_input', previous['input'])
        same_semantics = _replay_semantics(weight_input['contract'], weight_input['round']) == _replay_semantics(contract, round_spec)
        old_ids = set(weight_input['memberships']['train'])
        if old_ids & set(validation['memberships']['train']):
            # Revisions to the same cohort may alter rewards or stored masks even
            # if a caller forgets to bump a semantic version.
            same_semantics &= record_hash(weight_input['train']) == record_hash([problem_payload(p) for p in train_problems])
        if same_semantics:
            retained = sorted({sid for cohort in model.training_provenance for sid in cohort['student_ids']})
            replay_policy = 'retain_compatible_bounded_replay'
        else:
            model.replay = ReplayBuffer(model.replay.capacity, model.observation_dim, model.action_count, seed=seed + 1)
            model.training_provenance = []
            replay_policy = 'discard_stale_keep_weights'
        # Keep an untouched parent for paired evaluations, including history.
        model.contract = copy.deepcopy(contract)
        model.contract_sha256 = record_hash(contract)
        old_model = _load_parent(previous)
    else:
        model = MaskedDQN(env.observation_space.shape[0], env.action_space.n, seed=seed, contract=contract, **config)
        replay_policy = 'bootstrap_empty_replay'
    start_signature = _weights(model, algorithm)
    starts_equal = start_signature == _weights(old_model, algorithm) if previous else None
    before_steps = int(model.model.num_timesteps if algorithm == 'ppo' else model.total_timesteps)
    historical_validation = historical_validation or {}
    if validation['cross_semester'] and not historical_validation:
        raise ValueError('cross_semester_historical_validation_required')
    known_history = ({record_hash(previous['input']['validation'])} |
                     {record_hash(p) for p in previous['input'].get('historical_validation', {}).values()}) if previous else set()
    learned_ids = set(validation['memberships']['train'])
    if previous:
        learned_ids.update(previous['report'].get('lineage_training_student_ids', previous['input']['memberships']['train']))
    for name, problem in historical_validation.items():
        if (problem.metadata.get('split') not in ('validation', 'historical_validation')
                or set(problem.student_ids) & learned_ids):
            raise ValueError('historical_validation_holdout_overlap_or_invalid_split')
        if not previous or record_hash(problem_payload(problem)) not in known_history:
            raise ValueError('historical_validation_must_match_parent_frozen_holdout')
    parent_result = evaluate_problem(validation_problem, algorithm, model=old_model, seed=seed) if previous else None
    before_history = {name: evaluate_problem(p, algorithm, model=old_model, seed=seed)
                      for name, p in historical_validation.items()} if previous else {}
    baselines = {name: evaluate_problem(validation_problem, name, seed=seed) for name in ('hungarian', 'greedy', 'random')}
    output.mkdir(parents=True)
    _write(output / 'input.json', {'schema_version': SCHEMA, 'contract': contract, 'round': round_spec,
            'memberships': validation['memberships'], 'train': [problem_payload(p) for p in train_problems],
            'validation': problem_payload(validation_problem),
            'historical_validation': {name: problem_payload(p) for name, p in historical_validation.items()},
            'requested_timesteps': total_timesteps, 'model_config': config,
            'eval_interval': eval_interval,
            'parent_retention': previous.get('retention') if previous else None,
            'scope': validation['scope'], 'prediction_time_verified': validation['prediction_time_verified']})
    curve_rows = []
    training_started = time.perf_counter()
    def capture_curve(progress, phase='interval'):
        step = int(progress['timesteps'])
        if eval_interval is None or (phase == 'interval' and (step-before_steps) % eval_interval):
            return
        # Evaluation uses independent environments and cannot change training
        # RNG streams or the policy train/eval mode during an active rollout.
        numpy_state, torch_state, python_state = np.random.get_state(), torch.get_rng_state(), random.getstate()
        networks = [model.model.policy] if algorithm == 'ppo' else [model.online, model.target]
        modes = [network.training for network in networks]
        try:
            result = evaluate_problem(validation_problem, algorithm, model=model, seed=seed)
            history = {name: evaluate_problem(p, algorithm, model=model, seed=seed)
                       for name, p in historical_validation.items()}
        finally:
            np.random.set_state(numpy_state); torch.set_rng_state(torch_state); random.setstate(python_state)
            for network, mode in zip(networks, modes):
                network.train(mode)
        elapsed = time.perf_counter() - training_started
        score = result['metrics']['objective'] / len(validation_problem.student_ids)
        baseline_scores = {name: value['metrics']['objective'] / len(validation_problem.student_ids)
                           for name, value in baselines.items()}
        row = {'relative_step': step-before_steps, 'cumulative_step': step, 'phase': phase,
               'elapsed_seconds': elapsed, 'steps_per_second': (step-before_steps) / max(elapsed, 1e-9),
               'validation_objective_per_student': score,
               'validation_mean_compatibility': result['metrics']['mean_compatibility'],
               'validation_coverage': result['metrics']['coverage'],
               'validation_constraint_violations': result['metrics']['constraint_violations'],
               'validation_invalid_action_count': result['invalid_action_count'],
               'parent_objective_per_student': parent_result['metrics']['objective'] / len(validation_problem.student_ids) if parent_result else None,
               **{name+'_objective_per_student': value for name, value in baseline_scores.items()},
               'hungarian_regret_per_student': baseline_scores['hungarian']-score,
               'train_loss': progress.get('loss'), 'train_mean_episode_reward': progress.get('mean_episode_reward'),
               'episodes': progress.get('episodes', 0), 'epsilon': progress.get('epsilon'),
               'historical_validation': {name: {
                    'objective_per_student': value['metrics']['objective'] / len(historical_validation[name].student_ids),
                    'mean_compatibility': value['metrics']['mean_compatibility'],
                    'coverage': value['metrics']['coverage'], 'constraint_violations': value['metrics']['constraint_violations'],
                    'drop_from_parent': (before_history[name]['metrics']['objective']-value['metrics']['objective']) / len(historical_validation[name].student_ids)}
                    for name, value in history.items()}}
        if curve_rows and curve_rows[-1]['cumulative_step'] == step:
            curve_rows[-1] = row
        else:
            curve_rows.append(row)
        (output / 'learning_curve.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False, allow_nan=False)+'\n' for r in curve_rows), encoding='utf-8')
    capture_curve({'timesteps':before_steps}, 'initial')
    progress_callback = capture_curve if eval_interval is not None else None
    training = (model.learn(total_timesteps, progress_callback=progress_callback) if algorithm == 'ppo' else
                model.learn(env, total_timesteps, epsilon_start=round_spec.get('epsilon_start', .2),
                            epsilon_end=round_spec.get('epsilon_end', .05), progress_callback=progress_callback))
    after_steps = int(model.model.num_timesteps if algorithm == 'ppo' else model.total_timesteps)
    episode_rewards = training.get('episode_rewards', [])
    last_loss = training['losses'][-1] if training.get('losses') else None
    capture_curve({'timesteps':after_steps, 'episodes':training['episodes'],
                   'loss':last_loss.get('loss') if isinstance(last_loss, dict) else last_loss,
                   'mean_episode_reward':float(np.mean([r['reward'] for r in episode_rewards[-100:]])) if episode_rewards else None,
                   'epsilon':training.get('epsilon_end')}, 'final')
    candidate = evaluate_problem(validation_problem, algorithm, model=model, seed=seed)
    after_history = {name: evaluate_problem(p, algorithm, model=model, seed=seed)
                     for name, p in historical_validation.items()}
    forgetting = {name: {'metric': 'objective_per_student',
                        'before': before_history[name]['metrics']['objective'] / len(historical_validation[name].student_ids),
                        'after': result['metrics']['objective'] / len(historical_validation[name].student_ids),
                        'signed_drop': (before_history[name]['metrics']['objective'] - result['metrics']['objective']) / len(historical_validation[name].student_ids),
                        'compatibility_signed_drop': before_history[name]['metrics']['mean_compatibility'] - result['metrics']['mean_compatibility']}
                  for name, result in after_history.items()} if previous else {}
    thresholds = validation['thresholds']
    learning_ran = bool(training.get('losses')) and after_steps > before_steps
    safe = _safe(candidate) and all(_safe(r) for r in after_history.values())
    parent_score = parent_result['metrics']['objective'] / len(validation_problem.student_ids) if parent_result else None
    candidate_score = candidate['metrics']['objective'] / len(validation_problem.student_ids)
    delta = candidate_score - parent_score if parent_score is not None else None
    old_pass = all(row['signed_drop'] <= thresholds['max_old_drop'] for row in forgetting.values())
    if not learning_ran or not safe or not old_pass or (delta is not None and delta < -thresholds['max_new_drop']):
        decision = 'rejected'
    elif delta is None or delta > thresholds['min_improvement'] or thresholds['accept_non_regression']:
        decision = 'accepted'
    else:
        decision = 'inconclusive'
    model.save(output / 'checkpoint')
    shutil.copytree(output / 'checkpoint', output / 'inference')
    if algorithm == 'dqn':
        # Inference needs weights/contract; preserve full native checkpoint for
        # current loaders, while the checkpoint copy remains training authority.
        loaded = MaskedDQN.load(output / 'checkpoint', expected_contract=contract)
        inference = MaskedDQN.load(output / 'inference', expected_contract=contract)
    else:
        loaded = MaskedPPOAgent.load(output / 'checkpoint', env, expected_contract=contract)
        inference = MaskedPPOAgent.load(output / 'inference', env, expected_contract=contract)
    reload_result = evaluate_problem(validation_problem, algorithm, model=loaded, seed=seed)
    inference_result = evaluate_problem(validation_problem, algorithm, model=inference, seed=seed)
    reload_parity = candidate['trace'] == reload_result['trace']
    inference_parity = candidate['trace'] == inference_result['trace']
    if not reload_parity or not inference_parity:
        raise RuntimeError('native_checkpoint_parity_failed')
    report = {'schema_version': SCHEMA, 'round_id': round_spec['round_id'], 'semester_id': round_spec['semester_id'],
              'round_index': round_spec['round_index'], 'algorithm': algorithm, 'seed': seed,
              'scope': validation['scope'], 'prediction_time_verified': validation['prediction_time_verified'],
              'availability_assumption': validation['availability_assumption'], 'cross_semester': validation['cross_semester'],
              'parent_round_id': previous['report']['round_id'] if previous else None,
              'logical_parent_round_id': previous['input']['round']['round_id'] if previous else None,
              'parent_retention': previous.get('retention') if previous else None,
              'parent_checkpoint_sha256': previous['report']['checkpoint_sha256'] if previous else None,
              'checkpoint_sha256': _checkpoint_digest(output / 'checkpoint'),
              'start_weights_equal_parent': starts_equal, 'weights_changed': _weights(model, algorithm) != start_signature,
              'steps_before': before_steps, 'steps_added': after_steps - before_steps, 'steps_after': after_steps,
              'replay_policy': replay_policy, 'retained_historical_training_student_ids': retained,
              'lineage_training_student_ids': sorted(learned_ids),
              'training': training, 'parent': parent_result, 'candidate': candidate, 'baselines': baselines,
              'training_elapsed_seconds': time.perf_counter()-training_started,
              'learning_curve': {'path':'learning_curve.jsonl', 'points':len(curve_rows), 'eval_interval':eval_interval,
                                 'selection_policy':'final_checkpoint_only', 'uses_final_test':False} if eval_interval is not None else None,
              'primary_metric': 'objective_per_student', 'candidate_score': candidate_score, 'parent_score': parent_score,
              'delta': delta, 'improvement_demonstrated': delta is not None and delta > thresholds['min_improvement'] and round_spec.get('control') != 'extra_steps_no_new_signal',
              'improvement_attribution': 'optimization_only_control' if round_spec.get('control') == 'extra_steps_no_new_signal' else 'causality_not_established',
              'signal_quality_effect_established': False,
              'applied_signal_ids': validation['applied_signal_ids'],
              'forgetting_status': 'measured' if forgetting else 'unavailable', 'forgetting': forgetting,
              'decision': decision, 'decision_thresholds': thresholds,
              'reload_parity': reload_parity, 'inference_parity': inference_parity,
              'production_promoted': False, 'convergence_established': False,
              'limitations': ['Acceptance is a research safety/validation decision, not institutional approval.',
                             'A single seed or reused validation does not establish generalization.',
                             'Native PPO restarts fresh rollout/RNG at round boundaries; uninterrupted equivalence is not claimed.']}
    _write(output / 'report.json', report)
    _write(output / 'decision.json', {'round_id': round_spec['round_id'], 'decision': decision,
            'accepted_checkpoint': 'checkpoint' if decision == 'accepted' else None,
            'retained_parent': str(previous['path']) if previous and decision != 'accepted' else None,
            'logical_parent_context': str(Path(parent).resolve()) if previous and previous.get('retention') else None,
            'production_promoted': False})
    _write(output / 'manifest.json', {'schema_version': SCHEMA, 'created_at': datetime.now(timezone.utc).isoformat(),
            'code_sha256': code_sha256,
            'artifacts': {p.relative_to(output).as_posix(): _digest(p) for p in sorted(output.rglob('*')) if p.is_file()}})
    verify_round(output)
    return report
