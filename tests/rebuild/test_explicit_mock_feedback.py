import copy
import numpy as np

from scripts.prepare_explicit_mock_feedback import choices, respond
from src.domain.rebuild_matching import AllocationProblem, feasible
from src.evaluation.rebuild_benchmark import problem_payload
from src.rl.nested_learning import decode_problem


def problem():
    return problem_payload(AllocationProblem(
        scores=np.array([[.9, .3], [.8, .2]]), available=np.ones((2, 2), bool),
        student_ids=('s1', 's2'), advisor_ids=('a', 'b'), capacities=np.array([1, 1]),
        eligible=np.ones((2, 2), bool), present=np.ones(2, bool),
        student_features=np.ones((2, 1)), student_feature_known=np.ones((2, 1), bool)))


def test_each_named_choice_has_explicit_capacity_limited_response():
    p = problem()
    rows = choices(p, 'V1', {'s1': 'Mock Student A', 's2': 'Mock Student B'}, {'a': 'Mock Advisor A'}, choice_fraction=1)
    assert [r['advisor_id'] for r in rows] == ['a', 'a']
    assert all(r['student_name'] and r['advisor_name'] and r['choice_rank'] == 1 for r in rows)
    r2 = copy.deepcopy(p)
    changes = respond(p, rows)
    assert sum(r['advisor_response'] == 'accepted' for r in rows) == 1
    assert sum(r['advisor_response'] == 'rejected' for r in rows) == 1
    assert len(changes) == 1 and changes[0]['field'] == 'eligible'
    assert all(r['response_is_simulated'] and not r['student_excluded_from_cohort'] for r in rows)
    assert p['capacities'] == r2['capacities']
    assert p['scores'] == r2['scores']
    assert feasible(decode_problem(p))
    rejected = next(r for r in rows if r['advisor_response'] == 'rejected')
    i = p['student_ids'].index(rejected['student_id'])
    assert not p['eligible'][i][0] and p['eligible'][i][1]


def test_missing_names_stay_blank_and_flagged():
    rows = choices(problem(), 'V1', {}, {})
    assert all(r['student_name'] == '' and r['advisor_name'] == '' and r['name_note'] for r in rows)


def test_mock_lottery_and_responses_are_reproducible():
    results = []
    for _ in range(2):
        p = problem()
        rows = choices(p, 'V1', {}, {})
        changes = respond(p, rows)
        results.append((rows, changes))
    assert results[0] == results[1]


def test_unchosen_students_have_no_preference_or_advisor_response():
    p = problem()
    rows = choices(p, 'V1', {}, {}, choice_fraction=.5)
    respond(p, rows)
    assert sum(r['choice_status'] == 'chosen' for r in rows) == 1
    row = next(r for r in rows if r['choice_status'] == 'not_chosen')
    i = p['student_ids'].index(row['student_id'])
    assert row['advisor_id'] == '' and row['advisor_name'] == ''
    assert row['advisor_response'] == 'not_applicable_no_choice'
    assert p['preferences'][i] == [0., 0.] and p['preference_known'][i] == [False, False]
