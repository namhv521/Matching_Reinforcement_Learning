"""Conservative, reviewable skill claims from complete text-unit inventories.

Rules detect source claims, not personal proficiency. They never grant approval.
"""
from __future__ import annotations

import hashlib
from bisect import bisect_left
import json
import re

from src.data_pipeline.normalization import load_taxonomy, normalize_mentions, taxonomy_ids


INFERENCE_VERSION = 'advisor-skill-rules/1.1'
SCOPES = {'title_only', 'abstract_only', 'partial_full_text', 'full_text_complete'}
EXCLUDED = re.compile(
    r'\b(related work|references|bibliography|future work|future research|'
    r'tài liệu tham khảo|nghiên cứu liên quan|hướng phát triển|công việc tương lai)\b', re.I)
NEGATIVE = re.compile(
    r'\b(not used|(?:do|does|did) not (?:use|employ|apply|implement)|'
    r'without (?:using|employing)|not implemented|'
    r'không sử dụng|không dùng|chưa sử dụng|chưa triển khai|dự kiến|sẽ sử dụng|'
    r'plan to|planned|will|would|may|might|could|propose to|proposed|'
    r'sẽ|dự định|có thể sử dụng)\b', re.I)
NON_USAGE_CONTEXT = re.compile(
    r'\b(survey|review of|overview of|compared? (?:with|to)|comparison|'
    r'baseline|versus|so sánh|khảo sát|tổng quan)\b', re.I)
APPLIED = re.compile(
    r'\b(we use|we used|using|we apply|we applied|employ|employed|'
    r'sử dụng|áp dụng|ứng dụng|chúng tôi dùng)\b', re.I)
IMPLEMENTED = re.compile(
    r'\b(we implemented|implemented using|implementation uses|built using|'
    r'we developed|trained using|triển khai|xây dựng bằng|cài đặt bằng|huấn luyện bằng)\b', re.I)
EVALUATED = re.compile(
    r'\b(evaluated|evaluation|tested|accuracy|f1|benchmark|đánh giá|kiểm thử|độ chính xác)\b', re.I)


def _required_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(name + '_required')
    return value


def extract_skill_claims(text_units, *, content_scope, artifact_id, advisor_id,
                         taxonomy=None, expected_units=None):
    """Extract pending claims and explicitly report inventory completeness.

    text_units: list of {unit_id, text, section?}; each unit is a page/section/file.
    expected_units: complete list of IDs from the source inventory. Without this
    inventory, full_text_complete is downgraded: supplied text alone proves no
    document-wide completeness. Returned locators index the original unit text.
    """
    if content_scope not in SCOPES:
        raise ValueError('invalid_content_scope')
    _required_text(artifact_id, 'artifact_id')
    _required_text(advisor_id, 'advisor_id')
    if not isinstance(text_units, list):
        raise ValueError('text_units_must_be_list')
    units = {}
    for unit in text_units:
        if not isinstance(unit, dict):
            raise ValueError('invalid_text_unit')
        key = _required_text(unit.get('unit_id'), 'unit_id')
        if key in units or not isinstance(unit.get('text'), str):
            raise ValueError('duplicate_or_invalid_text_unit')
        if not isinstance(unit.get('section', ''), str):
            raise ValueError('invalid_section')
        units[key] = unit
    if expected_units is not None:
        if (not isinstance(expected_units, list)
                or any(not isinstance(k, str) or not k.strip() for k in expected_units)
                or len(set(expected_units)) != len(expected_units)
                or not set(units).issubset(expected_units)):
            raise ValueError('invalid_expected_units')
    processed = [key for key, unit in units.items() if unit['text'].strip()]
    missing = [key for key in (expected_units or list(units)) if key not in processed]
    complete = expected_units is not None and bool(expected_units) and not missing
    effective_scope = content_scope
    if content_scope == 'full_text_complete' and not complete:
        effective_scope = 'partial_full_text'
    taxonomy = load_taxonomy() if taxonomy is None else taxonomy
    candidates = {}
    for key in processed:
        unit = units[key]
        text = unit['text']
        unit_mentions = normalize_mentions(text, taxonomy)
        mention_starts = [m['start'] for m in unit_mentions]
        # ponytail: sentence-local rules favor precision; reviewer resolves
        # cross-sentence methods and contribution attribution in the next stage.
        excluded_section = bool(EXCLUDED.search(unit.get('section', '')))
        for sentence in re.finditer(r'[^\n.!?]+(?:[.!?]|\n|$)', text):
            quote = sentence.group()
            stripped = quote.strip()
            if not stripped:
                continue
            if EXCLUDED.search(stripped) and len(stripped) < 100:
                excluded_section = True
            elif re.fullmatch(r'(?:\d+[. ]*)?(?:methods?|methodology|results?|implementation|'
                              r'phương pháp|kết quả|triển khai)', stripped, re.I):
                excluded_section = False
            excluded = (excluded_section or bool(EXCLUDED.search(quote))
                        or bool(NON_USAGE_CONTEXT.search(quote)))
            negative = bool(NEGATIVE.search(quote))
            for original in unit_mentions[bisect_left(mention_starts, sentence.start()):
                                          bisect_left(mention_starts, sentence.end())]:
                mention = {**original, 'start': original['start'] - sentence.start(),
                           'end': original['end'] - sentence.start()}
                tag = mention['tag']
                level, score, usage = 'Mention', None, 'unknown'
                if excluded or negative:
                    usage = 'not_used' if negative else 'unknown'
                elif content_scope == 'title_only':
                    level, score, usage = 'Title prediction', 100, 'used'
                elif IMPLEMENTED.search(quote):
                    level, score, usage = 'Implemented', 80, 'used'
                    if EVALUATED.search(quote):
                        level, score = 'Evaluated', 100
                elif APPLIED.search(quote):
                    level, score, usage = 'Applied', 60, 'used'
                claim = {
                    'artifact_id': artifact_id, 'advisor_id': advisor_id,
                    'skill_id': tag, 'group': mention['group'],
                    'channel': 'prediction' if content_scope == 'title_only' else 'evidence',
                    'score': score, 'usage_status': usage, 'level': level,
                    'evidence_status': ('inferred_from_title' if content_scope == 'title_only'
                                        else 'extracted_from_abstract' if content_scope == 'abstract_only'
                                        else 'extracted_from_full_text'),
                    'quote': quote, 'matched_text': mention['matched_text'],
                    'locator': {'unit_id': key, 'start': sentence.start(), 'end': sentence.end(),
                                'mention_start': sentence.start() + mention['start'],
                                'mention_end': sentence.start() + mention['end']},
                    'review_status': 'pending', 'inference_version': INFERENCE_VERSION,
                    'content_scope': effective_scope,
                    'content_completeness': ('partial' if effective_scope == 'partial_full_text'
                                             or missing else 'complete'),
                    'prediction_reason': ('explicit_title_term' if content_scope == 'title_only' else None),
                }
                previous = candidates.get(tag)
                if previous is None or (score or 0) > (previous['score'] or 0):
                    candidates[tag] = claim
        if (content_scope == 'title_only' and 'nlp' in taxonomy_ids(taxonomy)
                and 'nlp' not in candidates and not EXCLUDED.search(text)
                and not NEGATIVE.search(text) and not NON_USAGE_CONTEXT.search(text)):
            match = re.search(r'\b(sentiment analysis|phân tích cảm xúc)\b', text, re.I)
            if match:
                candidates['nlp'] = {
                    'artifact_id': artifact_id, 'advisor_id': advisor_id, 'skill_id': 'nlp',
                    'group': 'topic_tags', 'channel': 'prediction', 'score': 50,
                    'usage_status': 'used', 'level': 'Title prediction',
                    'evidence_status': 'inferred_from_title', 'quote': text,
                    'matched_text': match.group(),
                    'locator': {'unit_id': key, 'start': 0, 'end': len(text),
                                'mention_start': match.start(), 'mention_end': match.end()},
                    'review_status': 'pending', 'inference_version': INFERENCE_VERSION,
                    'content_scope': effective_scope,
                    'content_completeness': 'partial' if missing else 'complete',
                    'prediction_reason': 'sentiment_analysis_is_nlp; no_framework_inferred',
                }
    claims = [candidates[tag] for tag in sorted(candidates)]
    for claim in claims:
        claim['evidence_id'] = hashlib.sha256(json.dumps(
            claim, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {
        'claims': claims, 'content_scope': effective_scope,
        'requested_content_scope': content_scope, 'processed_units': processed,
        'missing_units': missing,
        'content_completeness': (len(processed) / len(expected_units)
                                 if expected_units else None),
        'inventory_verified': complete, 'review_status': 'pending',
        'inference_version': INFERENCE_VERSION,
    }
