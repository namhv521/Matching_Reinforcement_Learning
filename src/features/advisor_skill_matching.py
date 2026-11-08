"""Convert reviewed per-skill snapshots into the native constrained matching problem."""
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from src.domain.rebuild_matching import AllocationProblem
from src.features.advisor_skill_scores import SCHEMA_VERSION


def _time(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timezone_timestamp_required')
    return result


def _ids(values):
    result = tuple(values)
    if not result or any(not isinstance(x, str) or not x or x != x.strip() for x in result) or len(set(result)) != len(result):
        raise ValueError('unique_nonempty_registry_required')
    return result


def build_skill_problem(score_rows, requirements, *, advisor_ids, student_ids,
                        capacities, eligible, present, cutoff, scope, coverage_floor):
    """Weights cover ALL requirements; unknown advisor scores never renormalize them.

    Requirements are reviewed pre-decision needs, never completed-thesis skills.
    Caller supplies operator capacities/eligibility; this function infers neither.
    A distinct feature contract requires new training or a verified migration.
    """
    deadline = _time(cutoff)
    if scope not in {'point_in_time_verified', 'retrospective_proxy'}:
        raise ValueError('explicit_supported_scope_required')
    if isinstance(coverage_floor, bool) or not isinstance(coverage_floor, (int, float)) or not math.isfinite(coverage_floor) or not 0 <= coverage_floor <= 1:
        raise ValueError('coverage_floor_0_1_required')
    advisors, students = _ids(advisor_ids), _ids(student_ids)
    final, seen = {}, set()
    for row in score_rows:
        advisor, skill = row['advisor_id'], row['skill_id']
        if advisor not in advisors:
            raise ValueError('advisor_outside_registry')
        if row.get('schema_version') != SCHEMA_VERSION:
            raise ValueError('scoring_contract_mismatch')
        if skill is None:  # Scorer's registry-only insufficient-data sentinel.
            continue
        key = advisor, skill
        if key in seen:
            raise ValueError('duplicate_advisor_skill')
        seen.add(key)
        if row['scope'] != scope or _time(row['cutoff']) != deadline:
            raise ValueError('snapshot_contract_mismatch')
        if row.get('known_mask') is True and row.get('status') == 'complete':
            value = row.get('final_score')
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100:
                raise ValueError('finite_final_score_0_100_required')
            final[key] = value / 100
    needs = {student: {} for student in students}
    for row in requirements:
        student, skill = row['student_id'], row['skill_id']
        if student not in needs or not isinstance(skill, str) or not skill:
            raise ValueError('invalid_student_requirement')
        if skill in needs[student]:
            raise ValueError('duplicate_student_requirement')
        if row.get('review_status') != 'approved' or row.get('training_eligibility') != scope:
            raise ValueError('reviewed_requirement_required')
        if row.get('evidence_scope') != 'predecision_requirement' or _time(row['available_at']) > deadline:
            raise ValueError('requirement_prediction_time_leakage')
        weight = row['requirement_weight']
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(weight) or weight <= 0:
            raise ValueError('positive_requirement_weight_required')
        if type(row.get('mandatory', False)) is not bool:
            raise ValueError('boolean_mandatory_required')
        needs[student][skill] = (weight, row.get('mandatory', False))
    skills = tuple(sorted({skill for student in needs.values() for skill in student}))
    scores = np.zeros((len(students), len(advisors)), dtype=float)
    coverage = np.zeros_like(scores)
    available = np.zeros_like(scores, dtype=bool)
    features = np.zeros((len(students), len(skills)), dtype=float)
    known = np.zeros_like(features, dtype=bool)
    review_reasons = []
    for i, student in enumerate(students):
        total = sum(weight for weight, _ in needs[student].values())
        if not total:
            review_reasons.append({'student_id': student, 'status': 'needs_review',
                                   'reason': 'no_reviewed_project_requirements'})
            continue
        for skill, (weight, mandatory) in needs[student].items():
            column = skills.index(skill)
            features[i, column], known[i, column] = weight / total, True
            for j, advisor in enumerate(advisors):
                if (advisor, skill) in final:
                    scores[i, j] += weight / total * final[advisor, skill]
                    coverage[i, j] += weight / total
        for j, advisor in enumerate(advisors):
            missing = [skill for skill, (_, mandatory) in needs[student].items()
                       if mandatory and (advisor, skill) not in final]
            if missing:
                review_reasons.append({'student_id': student, 'advisor_id': advisor,
                                       'status': 'needs_review', 'reason': 'mandatory_skill_evidence_unknown',
                                       'skill_ids': missing})
            required_known = all(not mandatory or (advisor, skill) in final
                                 for skill, (_, mandatory) in needs[student].items())
            available[i, j] = bool(coverage[i, j] > 0 and coverage[i, j] + 1e-12 >= coverage_floor and required_known)
            if not available[i, j] and not missing:
                review_reasons.append({'student_id': student, 'advisor_id': advisor,
                                       'status': 'needs_review', 'reason': 'insufficient_skill_coverage'})
    contract = {'schema_version': 'advisor-skill-matching/1', 'skills': skills,
                'advisor_ids': advisors, 'scoring_schema_version': SCHEMA_VERSION,
                'taxonomy_sha256': hashlib.sha256((Path(__file__).resolve().parents[2] /
                    'configs/data/taxonomy_v1.yaml').read_bytes()).hexdigest(),
                'score_channel': 'final_score', 'profile_weights': [.4, .6],
                'final_weights': [.5, .5], 'unknown_policy': 'zero_with_mask_no_renormalization',
                'scope': scope, 'coverage_floor': coverage_floor}
    contract_hash = hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()
    return AllocationProblem(scores=scores, available=available,
        student_ids=students, advisor_ids=advisors, capacities=capacities,
        eligible=eligible, present=present, student_features=features,
        student_feature_known=known, metadata={'feature_contract': contract,
            'feature_contract_sha256': contract_hash, 'cutoff': cutoff,
            'skill_coverage': coverage.tolist(), 'review_reasons': review_reasons,
            'review_status': 'needs_review' if review_reasons else 'ready',
            'requires_new_or_migrated_checkpoint': True})
