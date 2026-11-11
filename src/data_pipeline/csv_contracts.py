"""Versioned CSV cells and generated Pydantic schemas; no approval or imputation."""
from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (AfterValidator, AwareDatetime, BaseModel, BeforeValidator,
                      ConfigDict, Field, HttpUrl, StrictBool, StrictInt,
                      TypeAdapter, ValidationError, ValidationInfo, create_model,
                      model_validator)

MAX_CSV_BYTES = 10 * 1024 * 1024
MAX_CSV_ROWS = 10_000
MAX_ERRORS = 1000
MAX_EVIDENCE_CHARS = 128 * 1024
TAG_ID_PATTERN = r'[a-z][a-z0-9]*(?:_[a-z0-9]+)*'
TAG_CELL_PATTERN = rf'^{TAG_ID_PATTERN}(?:;{TAG_ID_PATTERN})*$'
TECH_FIELDS = ('programming_languages', 'frameworks_libraries', 'databases', 'ml_ai_methods',
               'data_engineering_tools', 'cloud_devops_tools', 'security_network_tools',
               'software_engineering_methods', 'research_methods', 'math_statistics_topics')
TAG_FIELDS = {'students': ('research_domain_tags', 'topic_tags', 'skills_tags', *TECH_FIELDS),
              'advisors': ('research_domain_tags', 'expertise_topic_tags', *TECH_FIELDS)}
TAG_GROUP_PROJECTIONS = {'expertise_topic_tags': 'topic_tags'}
HEADERS = {
    'students': 'schema_version,semester_id,student_id,student_name,program_code,cohort_year,thesis_title,thesis_abstract,thesis_keywords,research_domain_tags,topic_tags,skills_tags,programming_languages,frameworks_libraries,databases,ml_ai_methods,data_engineering_tools,cloud_devops_tools,security_network_tools,software_engineering_methods,research_methods,math_statistics_topics,project_evidence_urls,skill_evidence_type,skill_evidence_refs,skill_confidence,skill_proficiency_json,preferred_advisor_ids,preferred_research_topics,availability_notes,eligibility_flags,consent_status,source_type,source_file,source_page,source_url,source_sha256,extracted_at,review_status,reviewer_notes'.split(','),
    'advisors': 'schema_version,semester_id,advisor_id,advisor_name,department,academic_title,degree,profile_url,research_description,research_domain_tags,expertise_topic_tags,programming_languages,frameworks_libraries,databases,ml_ai_methods,data_engineering_tools,cloud_devops_tools,security_network_tools,software_engineering_methods,research_methods,math_statistics_topics,publications_urls,expertise_evidence_type,expertise_evidence_refs,expertise_confidence,expertise_proficiency_json,eligible_program_codes,active_for_semester,capacity_max,capacity_min,target_load,existing_load,supervision_restrictions,public_contact_url,source_type,source_url,source_sha256,crawled_at,review_status,reviewer_notes'.split(','),
}
REQUIRED = {
    'students': {'schema_version', 'semester_id', 'student_id', 'thesis_title', 'source_type', 'source_file', 'source_sha256', 'review_status'},
    'advisors': {'schema_version', 'semester_id', 'advisor_id', 'advisor_name', 'source_type', 'source_url', 'source_sha256', 'review_status'},
}
EVIDENCE_TYPES = Literal['observed', 'self_reported', 'inferred_from_thesis', 'verified_web', 'missing']
REVIEW_STATUSES = Literal['pending', 'needs_review', 'approved', 'rejected']
URL_ADAPTER = TypeAdapter(HttpUrl)


def _text(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError('text_cell_required')
    if not value.strip():
        return None
    # Inspect before stripping: a tab/CR can hide an Excel formula prefix.
    probe = value.lstrip().lstrip('\ufeff').lstrip()
    if probe.startswith(('=', '+', '-', '@')) or value.lstrip(' \ufeff').startswith(('\t', '\r', '\n')):
        raise ValueError('spreadsheet_formula_not_allowed')
    return value.strip() or None


def _integer(value):
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        raise ValueError('integer_not_boolean')
    if isinstance(value, int):
        return value
    text = _text(value)
    if text is None:
        return None
    if not re.fullmatch(r'\d+', text):
        raise ValueError('nonnegative_integer_required')
    return int(text)


def _boolean(value):
    if value is None or isinstance(value, bool):
        return value
    text = _text(value)
    if text is None:
        return None
    if text.lower() not in {'true', 'false'}:
        raise ValueError('boolean_true_or_false_required')
    return text.lower() == 'true'


def _confidence(value):
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        raise ValueError('confidence_not_boolean')
    if isinstance(value, str):
        value = _text(value)
        if value is None:
            return None
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise ValueError('confidence_number_required') from None
    if not math.isfinite(result):
        raise ValueError('finite_confidence_required')
    return result


def _timestamp(value):
    if isinstance(value, datetime) or value is None:
        return value
    text = _text(value)
    if text is None:
        return None
    if 'T' not in text:
        raise ValueError('iso_datetime_required')
    return text


def _unique_tags(value):
    tags = value.split(';')
    if len(tags) != len(set(tags)):
        raise ValueError('duplicate_taxonomy_tag')
    return value


def _url_list(value):
    if value is None:
        return None
    for url in value.split(';'):
        URL_ADAPTER.validate_python(url)
    return value


def _no_duplicate_json_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_proficiency_key')
        result[key] = value
    return result


def _proficiency(value):
    if value is None or isinstance(value, dict):
        return value
    text = _text(value)
    if text is None:
        return None
    def bad_constant(_):
        raise ValueError('nonfinite_json_number')
    try:
        return json.loads(text, object_pairs_hook=_no_duplicate_json_keys, parse_constant=bad_constant)
    except (ValueError, TypeError):
        raise ValueError('invalid_proficiency_json') from None


Text = Annotated[str, Field(min_length=1, max_length=20000), BeforeValidator(_text)]
OptionalText = Annotated[Text | None, BeforeValidator(_text)]
EvidenceText = Annotated[str, Field(min_length=1, max_length=MAX_EVIDENCE_CHARS), BeforeValidator(_text)]
OptionalEvidence = Annotated[EvidenceText | None, BeforeValidator(_text)]
TagCell = Annotated[str, Field(pattern=TAG_CELL_PATTERN, max_length=20000), AfterValidator(_unique_tags)]
OptionalTags = Annotated[TagCell | None, BeforeValidator(_text)]
Confidence = Annotated[float | None, Field(ge=0, le=1), BeforeValidator(_confidence)]
Integer = Annotated[StrictInt | None, Field(ge=0), BeforeValidator(_integer)]
Boolean = Annotated[StrictBool | None, BeforeValidator(_boolean)]
Timestamp = Annotated[AwareDatetime | None, BeforeValidator(_timestamp)]
URL = Annotated[HttpUrl | None, BeforeValidator(_text)]
URLList = Annotated[OptionalText, AfterValidator(_url_list)]
TagID = Annotated[str, Field(pattern=rf'^{TAG_ID_PATTERN}$')]
Level = Annotated[StrictInt, Field(ge=1, le=5)]
Proficiency = Annotated[dict[TagID, Level] | None, BeforeValidator(_proficiency)]


class CSVRecord(BaseModel):
    model_config = ConfigDict(extra='forbid', validate_default=True)

    @model_validator(mode='after')
    def cross_fields(self, info: ValidationInfo):
        context = info.context or {}
        mode = context.get('mode', 'staging')
        entity = 'students' if 'student_id' in type(self).model_fields else 'advisors'
        prefix = 'skill' if entity == 'students' else 'expertise'
        errors = []
        def error(field, code):
            errors.append({'type': 'value_error', 'loc': (field,),
                           'input': None, 'ctx': {'error': ValueError(code)}})
        tags = set()
        taxonomy_groups = context.get('taxonomy_groups')
        for field in TAG_FIELDS[entity]:
            cell = getattr(self, field)
            values = cell.split(';') if cell else []
            tags.update(values)
            if context.get('taxonomy_ids') is not None and any(v not in context['taxonomy_ids'] for v in values):
                error(field, 'unknown_taxonomy_tag')
            if taxonomy_groups is not None and values:
                group = TAG_GROUP_PROJECTIONS.get(field, field)
                if field == 'skills_tags' and field not in taxonomy_groups:
                    allowed = {tag for technical_group in TECH_FIELDS for tag in taxonomy_groups.get(technical_group, set())}
                else:
                    allowed = taxonomy_groups.get(group, set())
                if any(tag not in allowed for tag in values):
                    error(field, 'taxonomy_group_mismatch')
        proficiency = getattr(self, f'{prefix}_proficiency_json')
        if tags or proficiency:
            for suffix in ('evidence_type', 'evidence_refs', 'confidence'):
                field = f'{prefix}_{suffix}'
                if (suffix == 'confidence' and context.get('allow_unknown_document_confidence')
                        and getattr(self, f'{prefix}_evidence_type') == 'inferred_from_thesis'):
                    continue
                if getattr(self, field) is None or (suffix == 'evidence_type' and getattr(self, field) == 'missing'):
                    error(field, 'tag_evidence_required')
        if proficiency:
            if getattr(self, f'{prefix}_evidence_type') == 'inferred_from_thesis':
                error(f'{prefix}_proficiency_json', 'thesis_terms_do_not_prove_proficiency')
            if any(key not in tags for key in proficiency):
                error(f'{prefix}_proficiency_json', 'undeclared_proficiency_tag')
            if context.get('taxonomy_ids') is not None and any(key not in context['taxonomy_ids'] for key in proficiency):
                error(f'{prefix}_proficiency_json', 'unknown_taxonomy_tag')
        if mode in {'gold', 'allocation'} and self.review_status != 'approved':
            error('review_status', 'approved_review_required')
        if entity == 'advisors':
            maximum = self.capacity_max
            if maximum is not None:
                for field in ('capacity_min', 'target_load', 'existing_load'):
                    value = getattr(self, field)
                    if value is not None and value > maximum:
                        error(field, 'exceeds_capacity_max')
            if mode == 'allocation':
                if self.active_for_semester is not True:
                    error('active_for_semester', 'active_participation_required')
                for field in ('capacity_max', 'existing_load'):
                    if getattr(self, field) is None:
                        error(field, 'allocation_capacity_required')
        if errors:
            raise ValidationError.from_exception_data(type(self).__name__, errors)
        return self


def _model(entity, *, allow_blank_thesis_title=False):
    fields = {}
    for name in HEADERS[entity]:
        required = name in REQUIRED[entity] and not (allow_blank_thesis_title and name == 'thesis_title')
        annotation = Text if required else OptionalText
        if name == 'schema_version':
            annotation = Annotated[Literal['1.0'], BeforeValidator(_text)]
        elif name == 'review_status':
            annotation = Annotated[REVIEW_STATUSES, BeforeValidator(_text)]
        elif name == 'source_sha256':
            annotation = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$'), BeforeValidator(_text)]
        elif name in TAG_FIELDS[entity]:
            annotation = OptionalTags
        elif name.endswith('_confidence'):
            annotation = Confidence
        elif name.endswith('_evidence_type'):
            annotation = Annotated[EVIDENCE_TYPES | None, BeforeValidator(_text)]
        elif name.endswith('_evidence_refs'):
            annotation = OptionalEvidence
        elif name.endswith('_proficiency_json'):
            annotation = Proficiency
        elif name in {'source_url', 'profile_url', 'public_contact_url'}:
            annotation = Annotated[HttpUrl, BeforeValidator(_text)] if name in REQUIRED[entity] else URL
        elif name in {'project_evidence_urls', 'publications_urls'}:
            annotation = URLList
        elif name in {'extracted_at', 'crawled_at'}:
            annotation = Timestamp
        elif name in {'capacity_max', 'capacity_min', 'target_load', 'existing_load'}:
            annotation = Integer
        elif name == 'active_for_semester':
            annotation = Boolean
        fields[name] = (annotation, ... if required else None)
    name = 'StudentWorkbookIntakeV1' if allow_blank_thesis_title else entity.title() + 'ImportV1'
    return create_model(name, __base__=CSVRecord, **fields)


MODELS = {entity: _model(entity) for entity in HEADERS}
STUDENT_WORKBOOK_MODEL = _model('students', allow_blank_thesis_title=True)


def _check_options(entity, mode):
    if entity not in MODELS:
        raise ValueError('entity must be students or advisors')
    if mode not in {'staging', 'gold', 'allocation'}:
        raise ValueError('mode must be staging, gold or allocation')


def _validate(row, entity, mode, taxonomy_ids, taxonomy_groups=None, allow_unknown_document_confidence=False,
              *, student_workbook=False):
    try:
        schema = STUDENT_WORKBOOK_MODEL if student_workbook else MODELS[entity]
        model = schema.model_validate(row, context={
            'mode': mode, 'taxonomy_ids': taxonomy_ids, 'taxonomy_groups': taxonomy_groups,
            'allow_unknown_document_confidence': allow_unknown_document_confidence})
        return model, []
    except ValidationError as exc:
        errors = []
        for error in exc.errors(include_input=False, include_url=False):
            message = error['msg']
            code = str(error.get('ctx', {}).get('error', error['type']))
            errors.append({'field': '.'.join(str(x) for x in error['loc']) or '__row__',
                           'code': code, 'message': message})
        return None, errors


def validate_row(row: dict, entity: str, *, mode='staging', taxonomy_ids: set[str] | None = None,
                 taxonomy_groups: dict[str, set[str]] | None = None,
                 allow_unknown_document_confidence=False, student_workbook=False) -> list[dict]:
    """Validate one candidate; no mutation, missing-to-zero fill, or approval."""
    _check_options(entity, mode)
    if student_workbook and (entity != 'students' or mode != 'staging'):
        raise ValueError('student_workbook_requires_staging')
    return _validate(row, entity, mode, taxonomy_ids, taxonomy_groups, allow_unknown_document_confidence,
                     student_workbook=student_workbook)[1]


def export_json_schema(entity: str) -> dict:
    """Generate cell schema from the same model used for row/CSV validation."""
    _check_options(entity, 'staging')
    schema = MODELS[entity].model_json_schema()
    schema['x-csv-headers'] = list(HEADERS[entity])
    schema['x-csv-encoding'] = 'UTF-8; optional BOM; comma dialect'
    schema['x-csv-json-cell-fields'] = ['skill_proficiency_json' if entity == 'students' else 'expertise_proficiency_json']
    prefix = 'skill' if entity == 'students' else 'expertise'
    evidence_fields = [f'{prefix}_{suffix}' for suffix in ('evidence_type', 'evidence_refs', 'confidence')]
    tagged = [{'required': [name], 'properties': {name: {'type': 'string', 'minLength': 1}}}
              for name in TAG_FIELDS[entity]]
    proficiency_field = f'{prefix}_proficiency_json'
    proficiency_present = {'required': [proficiency_field],
                           'properties': {proficiency_field: {'type': 'object', 'minProperties': 1}}}
    schema['allOf'] = [
        {'if': {'anyOf': [*tagged, proficiency_present]},
         'then': {'required': evidence_fields, 'properties': {
             evidence_fields[0]: {'not': {'enum': [None, 'missing']}},
             evidence_fields[1]: {'type': 'string', 'minLength': 1},
             evidence_fields[2]: {'type': 'number', 'minimum': 0, 'maximum': 1}}}},
        {'if': proficiency_present,
         'then': {'properties': {evidence_fields[0]: {'not': {'const': 'inferred_from_thesis'}}}}},
    ]
    schema['x-context-validation'] = {
        'tag_fields': list(TAG_FIELDS[entity]),
        'evidence_required_with_tags': ['evidence_type', 'evidence_refs', 'confidence'],
        'gold_review_status': 'approved', 'taxonomy_membership': 'taxonomy_ids context when supplied',
        'taxonomy_groups': 'Optional strict per-field tag sets; missing groups reject nonempty fields',
        'taxonomy_group_projections': dict(TAG_GROUP_PROJECTIONS),
        'skills_tags_fallback_groups': list(TECH_FIELDS),
        'allocation_advisors_required': ['active_for_semester=true', 'capacity_max', 'existing_load'],
        'uniqueness': ['semester_id', 'student_id' if entity == 'students' else 'advisor_id'],
    }
    return schema


def validate_csv(path: Path, entity: str, *, mode='staging', taxonomy_ids=None,
                 taxonomy_groups: dict[str, set[str]] | None = None) -> dict:
    """Validate bounded CSV imports without returning private row contents."""
    _check_options(entity, mode)
    report = {'entity': entity, 'mode': mode, 'valid': False, 'status': 'invalid',
              'rows': 0, 'valid_rows': 0, 'errors': []}
    def error(line, field, code):
        report['errors'].append({'row': line, 'field': field, 'code': code, 'message': code})
    try:
        if Path(path).stat().st_size > MAX_CSV_BYTES:
            error(0, '__file__', 'file_size_limit')
            return report
        with Path(path).open(encoding='utf-8-sig', newline='') as stream:
            reader = csv.reader(stream, strict=True)
            headers = next(reader, None)
            if headers is None:
                error(1, '__header__', 'missing_headers')
                return report
            if any(count > 1 for count in Counter(headers).values()):
                error(1, '__header__', 'duplicate_headers')
                return report
            if set(headers) != set(HEADERS[entity]):
                error(1, '__header__', 'header_contract')
                return report
            seen = set()
            for values in reader:
                if not values:
                    continue
                report['rows'] += 1
                if report['rows'] > MAX_CSV_ROWS:
                    error(reader.line_num, '__file__', 'row_count_limit')
                    break
                if len(values) != len(headers):
                    error(reader.line_num, '__row__', 'row_width')
                    continue
                if not any(value.strip() for value in values):
                    report['rows'] -= 1
                    continue
                model, errors = _validate(dict(zip(headers, values)), entity, mode, taxonomy_ids, taxonomy_groups)
                for item in errors:
                    report['errors'].append({'row': reader.line_num, **item})
                if model is not None:
                    key = (model.semester_id, getattr(model, 'student_id' if entity == 'students' else 'advisor_id'))
                    if key in seen:
                        error(reader.line_num, '__row__', 'duplicate_identity')
                    else:
                        seen.add(key)
                        report['valid_rows'] += 1
                if len(report['errors']) >= MAX_ERRORS:
                    error(reader.line_num, '__file__', 'error_limit')
                    break
    except UnicodeError:
        error(0, '__file__', 'invalid_utf8')
    except csv.Error:
        error(0, '__file__', 'malformed_csv')
    except OSError:
        error(0, '__file__', 'file_unreadable')
    if mode in {'gold', 'allocation'} and report['rows'] == 0:
        error(0, '__file__', 'empty_dataset')
    report['valid'] = not report['errors']
    report['status'] = 'valid' if report['valid'] else 'invalid'
    return report
