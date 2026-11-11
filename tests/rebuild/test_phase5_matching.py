"""Technical constrained allocations: global feasibility, fixed rows and registry order."""
import itertools

import numpy as np
import pytest

from src.domain.rebuild_matching import AllocationProblem, action_mask, equal_quotas, feasible, validate_assignments
from src.baselines.rebuild_baselines import solve


def problem(scores=None, **changes):
    scores = np.array([[.9, .8], [.7, .1]], dtype=np.float64) if scores is None else scores
    n, m = np.shape(scores)
    values = dict(scores=scores, available=np.ones((n, m), bool),
                  student_ids=tuple('s'+str(i) for i in range(n)), advisor_ids=tuple('a'+str(i) for i in range(m)),
                  capacities=np.array([1]*m, dtype=np.int64), eligible=np.ones((n, m), bool), present=np.ones(m, bool))
    values.update(changes)
    return AllocationProblem(**values)


def test_equal_quota_remainders_follow_selected_ids_not_input_positions():
    assert equal_quotas(8, ('z', 'a', 'b', 'x'), ('b', 'a', 'z')).tolist() == [2, 3, 3, 0]
    for selected in [(), ('a', 'a'), ('unknown',)]:
        with pytest.raises(ValueError):
            equal_quotas(4, ('a', 'b'), selected)


def test_global_hall_feasibility_and_safe_mask_preserve_future_fixed_assignments():
    p = problem(eligible=np.array([[True, True], [True, False]]))
    assert feasible(p)
    assert action_mask(p, [0, 1], p.capacities).tolist() == [False, True]
    fixed = problem(fixed_assignments={'s1': 'a0'})
    assert action_mask(fixed, ['s0', 's1'], fixed.capacities).tolist() == [False, True]
    hall = problem(np.ones((3, 3), np.float64), eligible=np.array([[True, False, False]]*3),
                   capacities=np.array([1, 1, 1], np.int64))
    assert not feasible(hall)
    assert not action_mask(hall, [0, 1, 2], hall.capacities).any()


@pytest.mark.parametrize('algorithm', ['hungarian', 'greedy', 'random'])
def test_quota_only_student_keeps_sole_eligible_slot(algorithm):
    from src.evaluation.rebuild_benchmark import evaluate_problem

    p = problem(available=np.array([[True, True], [False, False]]),
                eligible=np.array([[True, True], [True, False]]))
    result = evaluate_problem(p, algorithm, seed=42, quota_only=('s1',))
    assert [row['advisor_id'] for row in result['assignments']] == ['a1', 'a0']
    assert result['metrics']['scored_students'] == 1
    assert result['metrics']['mean_compatibility'] == pytest.approx(.8)
    assert result['trace'][-1]['score'] is None
    assert result['trace'][-1]['policy_output']['kind'] == 'quota_only_random'


@pytest.mark.parametrize('algorithm', ['hungarian', 'greedy', 'random'])
def test_every_baseline_completes_safe_masks_and_never_uses_unknown_or_absent_pairs(algorithm):
    p = problem(eligible=np.array([[True, True], [True, False]]))
    result = solve(p, algorithm=algorithm, seed=9)
    assert result['status'] == 'feasible'
    assert validate_assignments(p, result['assignments'])['valid']
    assert [(a['student_id'], a['advisor_id']) for a in result['assignments']] == [('s0', 'a1'), ('s1', 'a0')]
    assert result['metrics']['coverage'] == 1
    assert result['metrics']['constraint_violations'] == 0
    assert result['assignments'][0]['preference_known'] is False
    absent = problem(present=np.array([True, False]))
    blocked = solve(absent, algorithm=algorithm)
    assert blocked['status'] == 'infeasible' and blocked['assignments'] == []
    assert blocked['metrics']['coverage'] == 0


def test_hungarian_optimizes_common_objective_and_recomputes_assignment_scores():
    p = problem(preferences=np.array([[1., 0.], [0., 1.]]), preference_known=np.ones((2, 2), bool), preference_weight=.8)
    result = solve(p)
    optimum = max(sum(p.scores[i, j] + .8*p.preferences[i, j] for i, j in enumerate(perm))
                  for perm in itertools.permutations(range(2)))
    assert result['metrics']['objective'] == pytest.approx(optimum)
    forged = [dict(a, score=999) for a in result['assignments']]
    assert not validate_assignments(p, forged)['valid']
    assert solve(p, algorithm='random', seed=3)['assignments'] == solve(p, algorithm='random', seed=3)['assignments']


def test_registry_permutation_preserves_optimal_identity_pairs():
    p = problem()
    original = solve(p)['assignments']
    q = problem(p.scores[:, ::-1], advisor_ids=p.advisor_ids[::-1])
    reordered = solve(q)['assignments']
    assert {(x['student_id'], x['advisor_id']) for x in original} == {(x['student_id'], x['advisor_id']) for x in reordered}


def test_unknown_fields_remain_masked_and_arrays_cannot_be_mutated():
    p = problem(available=np.array([[False, True], [True, True]]),
                preferences=np.ones((2, 2), np.float64), preference_known=np.zeros((2, 2), bool),
                student_features=np.ones((2, 3), np.float32), student_feature_known=np.zeros((2, 3), bool))
    assert p.scores[0, 0] == 0 and not p.allowed[0, 0]
    assert not p.preferences.any() and not p.student_features.any()
    with pytest.raises(ValueError):
        p.scores[0, 0] = 1


@pytest.mark.parametrize('change', [dict(capacities=np.array([1., 1.])), dict(capacities=np.array([True, True])),
                                  dict(capacities=np.array([-1, 3])), dict(available=np.ones((2, 2), int)),
                                  dict(student_ids=('s0', 's0')), dict(advisor_ids=('a0', 'a0')),
                                  dict(fixed_assignments={'unknown': 'a0'}), dict(fixed_assignments={'s0': 'unknown'}),
                                  dict(scores=np.full((2, 2), np.nan)), dict(scores=np.ones((2, 2), bool)),
                                  dict(preference_weight=float('inf'))])
def test_invalid_contracts_are_rejected(change):
    with pytest.raises(ValueError):
        problem(**change)


def test_validation_rejects_duplicates_unknown_ids_and_over_capacity():
    p = problem()
    for rows in [[{'student_id': 's0', 'advisor_id': 'a0'}]*2,
                 [{'student_id': 'unknown', 'advisor_id': 'a0'}],
                 [{'student_id': 's0', 'advisor_id': 'a0'}, {'student_id': 's1', 'advisor_id': 'a0'}]]:
        assert not validate_assignments(p, rows)['valid']


def test_residual_state_validation_and_empty_completion():
    p = problem()
    assert feasible(p, remaining_students=[], remaining_capacities=np.zeros(2, np.int64))
    assert not action_mask(p, [], np.zeros(2, np.int64)).any()
    for students, caps in [([0, 0], p.capacities), ([99], p.capacities), ([0], np.array([2, 1]))]:
        with pytest.raises(ValueError):
            feasible(p, remaining_students=students, remaining_capacities=caps)


def test_hall_and_safe_masks_match_exhaustive_small_bipartite_graphs():
    for bits in itertools.product((False, True), repeat=6):
        eligible = np.array(bits, bool).reshape(3, 2)
        p = problem(np.ones((3, 2), np.float64), eligible=eligible, capacities=np.array([2, 1], np.int64))
        valid = [choices for choices in itertools.product(range(2), repeat=3)
                 if all(eligible[i, j] for i, j in enumerate(choices))
                 and all(choices.count(j) <= p.capacities[j] for j in range(2))]
        assert feasible(p) == bool(valid)
        assert action_mask(p, [0, 1, 2], p.capacities).tolist() == [
            any(choices[0] == j for choices in valid) for j in range(2)]


def test_normalized_fairness_handles_unequal_capacities_without_penalizing_equal_utilization():
    p = problem(np.ones((3, 2), np.float64), capacities=np.array([2, 1], np.int64))
    result = solve(p)
    assert result['metrics']['normalized_load_imbalance'] == 0
    assert result['metrics']['objective'] == 3
