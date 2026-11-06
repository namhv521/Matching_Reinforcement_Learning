"""Review-gated advisor-skill snapshot assembly.

This module never promotes raw crawler output. It assembles a score snapshot only
from claims already approved upstream and returns an explicit ``not_evaluable``
receipt when the required point-in-time evidence or matching contract is absent.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

import numpy as np

from src.baselines.rebuild_baselines import solve
from src.features.advisor_skill_matching import build_skill_problem
from src.features.advisor_skill_scores import score_advisor_skills


def _event_date(value):
    if not isinstance(value, str):
        raise ValueError('event_date_required')
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError('event_date_required') from error


def academic_term_for_date(value):
    """Return the real academic term in Asia/Saigon calendar convention."""
    event = _event_date(value)
    if event.month >= 9:
        return f'{event.year}.1'
    return f'{event.year - 1}.{2 if event.month <= 5 else 3}'


def storage_pool_for_date(value):
    """Map a dated advisor artifact to its allowed storage pool, never a new term."""
    event = _event_date(value)
    if event.year <= 2024:
        return '2024'
    # Advisor corpus follows the updated calendar-year 2025 collection rule;
    # the academic term remains on every record and student cohorts are untouched.
    if event.year == 2025:
        return '2025.1'
    raise ValueError('calendar_year_2026_or_later_excluded_from_advisor_corpus')


def partition_advisor_candidates(candidates):
    """Return copies partitioned by event date while preserving availability evidence."""
    result = defaultdict(list)
    seen = set()
    for row in candidates:
        if not isinstance(row, dict):
            raise ValueError('candidate_must_be_object')
        artifact, advisor = row.get('artifact_id'), row.get('advisor_id')
        if not isinstance(artifact, str) or not artifact or not isinstance(advisor, str) or not advisor:
            raise ValueError('candidate_artifact_and_advisor_required')
        pool = storage_pool_for_date(row.get('event_date'))
        key = (advisor, artifact, pool)
        if key in seen:
            raise ValueError('duplicate_partitioned_candidate')
        seen.add(key)
        result[pool].append({**row, 'academic_term': academic_term_for_date(row['event_date']),
                             'storage_pool': pool})
    return {pool: sorted(rows, key=lambda r: (r['advisor_id'], r['artifact_id']))
            for pool, rows in sorted(result.items())}


def _normalized_title(value):
    import re
    import unicodedata
    text = unicodedata.normalize('NFD', (value or '').casefold().replace('đ', 'd'))
    text = ''.join(char for char in text if not unicodedata.combining(char))
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', text).split())


def mark_duplicate_candidates(rows):
    """Flag likely duplicates per advisor by DOI or normalized title.

    Rows are never merged or dropped. Groups with more than one row get
    ``dedup_status=pending_review`` so a reviewer picks the canonical artifact.
    """
    import hashlib
    parent = list(range(len(rows)))

    def root(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    first_seen = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError('candidate_must_be_object')
        keys = []
        doi = row.get('doi')
        if isinstance(doi, str) and doi.strip():
            keys.append(('doi', row.get('advisor_id'), doi.strip().casefold()))
        title = _normalized_title(row.get('title'))
        if title:
            keys.append(('title', row.get('advisor_id'), title))
        for key in keys:
            if key in first_seen:
                parent[root(index)] = root(first_seen[key])
            else:
                first_seen[key] = index
    members = defaultdict(list)
    for index in range(len(rows)):
        members[root(index)].append(index)
    output = []
    for index, row in enumerate(rows):
        group = members[root(index)]
        artifacts = sorted(str(rows[i].get('artifact_id')) for i in group)
        group_id = 'dup_' + hashlib.sha256('|'.join(artifacts).encode()).hexdigest()[:16]
        output.append({**row, 'duplicate_group_id': group_id,
                       'duplicate_group_size': len(group),
                       'dedup_status': 'pending_review' if len(group) > 1 else 'singleton'})
    return output


def apply_review_decisions(claims, decisions):
    """Apply externally supplied reviewer verdicts without manufacturing approvals."""
    indexed = {}
    for decision in decisions:
        if not isinstance(decision, dict):
            raise ValueError('review_decision_must_be_object')
        evidence = decision.get('evidence_id')
        if not isinstance(evidence, str) or not evidence or evidence in indexed:
            raise ValueError('unique_review_evidence_id_required')
        status = decision.get('review_status')
        if status not in {'approved', 'rejected', 'needs_review'}:
            raise ValueError('review_decision_status_required')
        if status == 'approved':
            reviewer, reviewed_at, reason = decision.get('reviewer'), decision.get('reviewed_at'), decision.get('reason')
            try:
                timestamp = datetime.fromisoformat(reviewed_at.replace('Z', '+00:00')) if isinstance(reviewed_at, str) else None
            except ValueError:
                timestamp = None
            if (not isinstance(reviewer, str) or not reviewer.strip() or not isinstance(reason, str)
                    or not reason.strip() or timestamp is None or timestamp.tzinfo is None
                    or timestamp.utcoffset() is None):
                raise ValueError('review_decision_provenance_required')
        indexed[evidence] = dict(decision)
    result = []
    for claim in claims:
        if not isinstance(claim, dict):
            raise ValueError('claim_must_be_object')
        evidence = claim.get('evidence_id')
        decision = indexed.get(evidence)
        review_fields = ('review_status', 'reviewer', 'reviewed_at', 'reason')
        result.append({**claim, **({key: decision[key] for key in review_fields if key in decision}
                                    if decision else {})})
    return result


def grouped_thesis_split(rows, *, seed=42):
    """Assign complete thesis groups to train/validation/test without cross-split leakage."""
    if type(seed) is not int:
        raise ValueError('integer_seed_required')
    groups, students = defaultdict(list), set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('student_thesis_row_required')
        if row.get('source_pool') == '2025.3' or row.get('academic_term') == '2025.3':
            raise ValueError('external_test_student_forbidden')
        student, thesis = row.get('student_id'), row.get('thesis_id')
        if (not isinstance(student, str) or not student.strip() or not isinstance(thesis, str)
                or not thesis.strip() or student in students):
            raise ValueError('unique_student_and_thesis_id_required')
        students.add(student)
        groups[thesis].append(student)
    if len(groups) < 3:
        raise ValueError('at_least_three_independent_theses_required')
    # The stable digest avoids dependence on input iteration order and keeps all
    # students attached to the same thesis group.
    import hashlib
    order = sorted(groups, key=lambda thesis: hashlib.sha256(f'{seed}:{thesis}'.encode()).hexdigest())
    # 70/15/15 by thesis group; every split keeps at least one group.
    validation_count = max(1, round(len(order) * .15))
    test_count = max(1, round(len(order) * .15))
    train_count = len(order) - validation_count - test_count
    assignments, membership = {}, {}
    for index, thesis in enumerate(order):
        split = ('train' if index < train_count else
                 'validation' if index < train_count + validation_count else 'test')
        group_id = 'thesis_' + hashlib.sha256(thesis.encode()).hexdigest()
        for student in sorted(groups[thesis]):
            assignments[student], membership[student] = split, group_id
    return {'assignments': dict(sorted(assignments.items())), 'groups': dict(sorted(membership.items())),
            'metadata': {'split_version': 'advisor-skill-thesis-groups-v1', 'seed': seed,
                         'thesis_count': len(groups), 'student_count': len(students),
                         'test_policy': '2025.1 internal grouped test only; 2025.3 remains external and unopened'}}


def _approved_claims(rows, scope):
    return [row for row in rows if row.get('review_status') == 'approved'
            and row.get('training_eligibility') == scope
            and isinstance(row.get('available_at'), str)]


def close_snapshot(*, profile_claims, thesis_claims, registry, semester, cutoff, scope,
                   requirements=None, student_ids=None, capacities=None, eligible=None, present=None,
                   coverage_floor=0.5):
    """Score a reviewed snapshot and run the mandatory Hungarian baseline if usable.

    A returned result is a gate receipt, not a training authorization or promotion.
    """
    if semester == '2025.3':
        raise ValueError('external_test_cannot_be_closed_for_training')
    if semester not in {'2024', '2025.1', '2025.2'}:
        raise ValueError('unsupported_training_semester')
    approved_profile = _approved_claims(profile_claims, scope)
    approved_theses = _approved_claims(thesis_claims, scope)
    if not approved_profile and not approved_theses:
        return {'status': 'not_evaluable', 'score_rows': [],
                'baseline': {'status': 'not_run'},
                'blocking_reasons': ['no_approved_point_in_time_claims'],
                'semester': semester, 'cutoff': cutoff, 'scope': scope,
                'production_promoted': False}
    # Raw candidates can legitimately lack timestamps/split while awaiting review.
    # They remain in their review pack but cannot be passed to the strict scorer.
    scores = score_advisor_skills(approved_profile, approved_theses, cutoff=cutoff, scope=scope,
                                  advisor_ids=registry)
    complete = [row for row in scores if row['known_mask']]
    if not complete:
        return {'status': 'not_evaluable', 'score_rows': scores,
                'baseline': {'status': 'not_run'},
                'blocking_reasons': ['no_complete_advisor_skill_scores'],
                'semester': semester, 'cutoff': cutoff, 'scope': scope,
                'production_promoted': False}
    required = (requirements, student_ids, capacities, eligible, present)
    if any(value is None for value in required):
        return {'status': 'not_evaluable', 'score_rows': scores,
                'baseline': {'status': 'not_run'},
                'blocking_reasons': ['matching_requirements_or_operator_constraints_missing'],
                'semester': semester, 'cutoff': cutoff, 'scope': scope,
                'production_promoted': False}
    problem = build_skill_problem(
        scores, requirements, advisor_ids=registry, student_ids=student_ids,
        capacities=np.asarray(capacities, dtype=np.int64), eligible=np.asarray(eligible, dtype=bool),
        present=np.asarray(present, dtype=bool), cutoff=cutoff, scope=scope,
        coverage_floor=coverage_floor)
    # Hungarian is the primary baseline; Greedy and Random use the same problem.
    baselines = {name: solve(problem, name) for name in ('hungarian', 'greedy', 'random')}
    baseline = baselines['hungarian']
    status = 'ready_for_training' if baseline['status'] == 'feasible' else 'not_evaluable'
    return {'status': status, 'score_rows': scores, 'baseline': baseline, 'baselines': baselines,
            'blocking_reasons': [] if status == 'ready_for_training' else ['hungarian_infeasible'],
            'semester': semester, 'cutoff': cutoff, 'scope': scope,
            'feature_contract': problem.metadata['feature_contract'],
            'feature_contract_sha256': problem.metadata['feature_contract_sha256'],
            'production_promoted': False}