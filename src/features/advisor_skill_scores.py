"""Deterministic per-skill scores for advisor-skill-semester PRD v1.3.

Input rows are reviewed claims, not raw keyword hits. ``review_status=approved``
attests that the advisor/artifact link was verified upstream. Canonical
``artifact_id`` must already group PDF/DOCX aliases and publication mirrors.
No missing channel is imputed and no weights are renormalized.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from math import isfinite
from statistics import fmean


SCHEMA_VERSION = 'advisor-skill-scores/1.3'
SCOPES = {'point_in_time_verified', 'retrospective_proxy', 'retrospective_document_proxy'}


def _text(value, field):
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f'nonempty_text_required: {field}')
    return value


def _time(value):
    if not isinstance(value, str):
        raise ValueError('timezone_timestamp_required')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise ValueError('timezone_timestamp_required') from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('timezone_timestamp_required')
    return result


def score_advisor_skills(profile_claims, thesis_claims, *, cutoff,
                         allowed_splits=('train',), excluded_thesis_ids=(),
                         scope='point_in_time_verified', advisor_ids=()):
    """Return sorted sparse advisor/skill rows plus registry-only no-data rows.

    Every claim requires advisor_id, skill_id, artifact_id, channel, score,
    usage_status, review_status, available_at, split, training_eligibility.
    Non-used/unknown claims carry score=None. A genuinely scored zero with
    usage_status='used' remains in the denominator. Optional content_completeness
    is 'complete' or 'partial'; approved claims default to complete. Optional
    Identity, supervision and article-link review flags, when supplied, must
    all be approved. A supplied document/article match must be exactly True.
    Partial/unreviewed eligible input prevents final publication for that skill.
    Future, excluded, other-split and other-scope claims never contribute.
    """
    deadline = _time(cutoff)
    if scope not in SCOPES:
        raise ValueError('unsupported_scope')
    allowed = set(allowed_splits)
    if not allowed or not allowed <= {'train', 'validation', 'test'}:
        raise ValueError('explicit_valid_splits_required')
    excluded = {_text(item, 'excluded_thesis_id') for item in excluded_thesis_ids}
    registry = {_text(item, 'advisor_id') for item in advisor_ids}
    grouped = defaultdict(dict)
    incomplete = set()
    evidence_refs = defaultdict(set)
    for rows, channels in ((profile_claims, {'prediction', 'evidence'}),
                           (thesis_claims, {'thesis'})):
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('claim_must_be_object')
            advisor = _text(row.get('advisor_id'), 'advisor_id')
            skill = _text(row.get('skill_id'), 'skill_id')
            artifact = _text(row.get('artifact_id'), 'artifact_id')
            channel = row.get('channel')
            if channel not in channels:
                raise ValueError('invalid_claim_channel')
            usage = row.get('usage_status')
            if usage not in {'used', 'not_used', 'unknown'}:
                raise ValueError('explicit_usage_status_required')
            review = row.get('review_status')
            if review not in {'pending', 'needs_review', 'approved', 'rejected'}:
                raise ValueError('explicit_review_status_required')
            value = row.get('score')
            if usage == 'used':
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not isfinite(value) or not 0 <= value <= 100):
                    raise ValueError('finite_score_0_100_required')
                value = float(value)
            elif value is not None:
                raise ValueError('unscored_usage_requires_null_score')
            available = _time(row.get('available_at'))
            split = row.get('split')
            if split not in {'train', 'validation', 'test'}:
                raise ValueError('explicit_valid_split_required')
            eligibility = row.get('training_eligibility')
            if eligibility not in SCOPES | {'unresolved', 'excluded'}:
                raise ValueError('explicit_training_eligibility_required')
            completeness = row.get('content_completeness', 'complete')
            if completeness not in {'complete', 'partial'}:
                raise ValueError('invalid_content_completeness')
            if (available > deadline or split not in allowed or eligibility != scope
                    or (channel == 'thesis' and artifact in excluded)):
                continue
            key = (advisor, skill)
            grouped[key]  # Retain known skill rows even when no score is usable.
            registry.add(advisor)
            verified = review == 'approved' and all(
                row.get(field, 'approved') == 'approved'
                for field in ('identity_review_status', 'supervision_review_status',
                              'article_person_link_status', 'article_identity_review_status'))
            if 'downloaded_document_matches_article' in row:
                verified = verified and row['downloaded_document_matches_article'] is True
            if not verified or completeness != 'complete' or usage == 'unknown':
                if review != 'rejected':
                    incomplete.add(key)
                continue
            dedup_key = (channel, artifact)
            signature = (usage, value)
            existing = grouped[key].get(dedup_key)
            if existing is not None and existing != signature:
                raise ValueError(f'conflicting_duplicate_claim: {advisor}/{skill}/{artifact}')
            grouped[key][dedup_key] = signature
            refs = row.get('evidence_ids', [])
            if not isinstance(refs, list):
                raise ValueError('evidence_ids_must_be_list')
            if row.get('evidence_id') is not None:
                refs = [*refs, row['evidence_id']]
            evidence_refs[key].update(_text(ref, 'evidence_id') for ref in refs)

    output = []
    for (advisor, skill), artifacts in sorted(grouped.items()):
        values = {channel: [score for (kind, _), (usage, score) in artifacts.items()
                            if kind == channel and usage == 'used']
                  for channel in ('prediction', 'evidence', 'thesis')}
        means = {channel: fmean(scores) if scores else None
                 for channel, scores in values.items()}
        prediction, evidence, gvhd = (means[channel]
                                     for channel in ('prediction', 'evidence', 'thesis'))
        profile = (.4 * prediction + .6 * evidence
                   if prediction is not None and evidence is not None else None)
        partial = (advisor, skill) in incomplete
        final = (.5 * profile + .5 * gvhd
                 if profile is not None and gvhd is not None and not partial else None)
        output.append({
            'schema_version': SCHEMA_VERSION, 'advisor_id': advisor, 'skill_id': skill,
            'prediction_score': prediction, 'evidence_score': evidence,
            'profile_score': profile, 'gvhd_score': gvhd, 'final_score': final,
            'prediction_count': len(values['prediction']),
            'evidence_count': len(values['evidence']), 'thesis_count': len(values['thesis']),
            'component_masks': {'prediction': prediction is not None,
                                'evidence': evidence is not None, 'profile': profile is not None,
                                'gvhd': gvhd is not None, 'final': final is not None},
            'known_mask': final is not None,
            'status': 'partial' if partial else ('complete' if final is not None else 'insufficient_data'),
            'evidence_ids': sorted(evidence_refs[(advisor, skill)]),
            'cutoff': cutoff, 'scope': scope,
        })
    represented = {row['advisor_id'] for row in output}
    for advisor in sorted(registry - represented):
        output.append({'schema_version': SCHEMA_VERSION, 'advisor_id': advisor, 'skill_id': None,
                       'prediction_score': None, 'evidence_score': None, 'profile_score': None,
                       'gvhd_score': None, 'final_score': None, 'prediction_count': 0,
                       'evidence_count': 0, 'thesis_count': 0, 'component_masks': dict.fromkeys(
                           ('prediction', 'evidence', 'profile', 'gvhd', 'final'), False),
                       'known_mask': False, 'status': 'insufficient_data', 'evidence_ids': [],
                       'cutoff': cutoff, 'scope': scope})
    return sorted(output, key=lambda row: (row['advisor_id'], row['skill_id'] or ''))
