"""Audit actual calendar <=2024 inside the historical pool named 2024.

Dates come only from explicit metadata, never bibliography, title, collection
clock, file name or academic semester label. No source files are edited.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

ZONE = ZoneInfo('Asia/Saigon')
END = datetime(2025, 1, 1, tzinfo=ZONE)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def classify_date(value):
    """Classify event interval with an exclusive local 2025 boundary."""
    if value is None or value == '':
        return {'status': 'unknown', 'precision': None, 'year': None}
    if not isinstance(value, str):
        return {'status': 'invalid', 'precision': None, 'year': None}
    value = value.strip()
    try:
        if re.fullmatch(r'\d{4}', value):
            number = int(value)
            date(number, 1, 1)
            precision, local = 'year', None
        elif re.fullmatch(r'\d{4}-\d{2}', value):
            local = datetime.fromisoformat(value + '-01').replace(tzinfo=ZONE)
            number, precision = local.year, 'month'
        elif re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            local = datetime.fromisoformat(value).replace(tzinfo=ZONE)
            number, precision = local.year, 'day'
        else:
            local = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if local.tzinfo is None:
                raise ValueError('timezone_required')
            local = local.astimezone(ZONE)
            number, precision = local.year, 'timestamp'
    except (ValueError, OverflowError):
        return {'status': 'invalid', 'precision': None, 'year': None}
    eligible = number <= 2024 if precision == 'year' else local < END
    return {'status': 'calendar_eligible' if eligible else 'after_2024',
            'precision': precision, 'year': number,
            'local_value': local.isoformat() if local is not None else str(number),
            'academic_term': None if precision == 'year' else
                (f'{number}.1' if local.month >= 9 else f'{number-1}.{2 if local.month <= 5 else 3}')}


def classify_corpus(row):
    values = {field: classify_date(row.get(field))
              for field in ('published_at', 'event_date', 'publication_year')}
    known = [result for result in values.values() if result['status'] not in {'unknown', 'invalid'}]
    if any(result['status'] == 'invalid' for result in values.values()):
        status = 'date_needs_review'
    elif not known:
        status = 'unknown_date'
    elif len({result['year'] for result in known}) > 1:
        status = 'conflicting_dates'
    elif any(result['status'] == 'after_2024' for result in known):
        status = 'after_2024'
    else:
        status = 'calendar_eligible'
    return status, values


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def audit(data, output):
    data, output = Path(data).resolve(), Path(output).resolve()
    if output.is_relative_to(data):
        raise ValueError('output_must_be_outside_source_data')
    registry = data / '2024/advisors/faculty_profiles/advisors_profile.csv'
    corpus_path = data / '2024/advisors/faculty_corpus/advisors_corpus.csv'
    students_path = data / '2024/student/students_processed/students_processed.csv'
    paths = [registry, corpus_path, students_path]
    inputs = {str(path): sha(path) for path in paths}
    roster = read_csv(registry)
    ids = [r['advisor_id'] for r in roster]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('unique_advisor_registry_required')
    counts = {advisor: Counter() for advisor in ids}
    records, students = [], []
    corpus_rows = read_csv(corpus_path)
    for row in corpus_rows:
        status, dates = classify_corpus(row)
        if row['advisor_id'] not in counts:
            status = 'advisor_outside_registry'
        else:
            counts[row['advisor_id']][status] += 1
        selected = next((dates[k] for k in ('event_date', 'published_at', 'publication_year')
                         if dates[k]['status'] == 'calendar_eligible'), None)
        records.append({
            'record_id': row['record_id'], 'advisor_id': row['advisor_id'], 'content_type': row['content_type'],
            'title': row['title'], 'source_url': row['source_url'], 'status': status,
            'date_metadata': {k: row.get(k) for k in dates}, 'date_classification': dates,
            'date_evidence': row.get('date_evidence'), 'date_basis': row.get('date_basis'),
            'academic_term': selected.get('academic_term') if selected else None,
            'event_year': selected.get('year') if selected else None,
            'source_csv': str(corpus_path), 'source_csv_sha256': inputs[str(corpus_path)],
            'collected_at': row.get('collected_at'), 'available_at': row.get('available_at') or None,
            'collection_time_used_as_event_time': False,
            'source_review_status': row.get('review_status'), 'review_status': 'needs_review',
            'raw_path': row.get('raw_path'), 'source_sha256': row.get('sha256'),
            'calendar_eligible': status == 'calendar_eligible',
            'historical_training_eligible': False,
            'scope': 'retrospective_metadata_candidates_not_verified_person_or_skill',
        })
    for row in read_csv(students_path):
        try:
            notes = json.loads(row.get('reviewer_notes') or '{}')
        except ValueError:
            notes = {}
        cover = notes.get('cover_date', {})
        result = classify_date(cover.get('date'))
        status = result['status']
        if status == 'calendar_eligible' and (not cover.get('quote') or cover.get('status') != 'resolved'):
            status = 'cover_evidence_needs_review'
        record = {'student_id': row['student_id'], 'status': status, 'cover_date': cover,
                  'source_pool': '2024', 'calendar_eligible': status == 'calendar_eligible',
                  'source_opened': False, 'historical_training_eligible': False,
                  'available_at': None, 'supervision_review_status': 'pending'}
        # Later/unknown theses are not opened and their full text is not copied.
        if status == 'calendar_eligible':
            record.update(source_file=row['source_file'], source_sha256=row['source_sha256'],
                          academic_term=result.get('academic_term'),
                          reason='candidate_for_later_cover_advisor_review_only')
        students.append(record)
    report = {'schema_version': 'advisor-calendar-history/1', 'scope': 'calendar_through_2024_inclusive',
              'boundary_exclusive': END.isoformat(), 'roster_advisors': len(ids),
              'corpus_records': len(records), 'corpus_status_counts': dict(Counter(r['status'] for r in records)),
              'corpus_eligible_type_counts': dict(Counter(r['content_type'] for r in records if r['calendar_eligible'])),
              'eligible_missing_available_at': sum(r['calendar_eligible'] and not r['available_at'] for r in records),
              'student_metadata_rows': len(students), 'student_status_counts': dict(Counter(r['status'] for r in students)),
              'thesis_source_files_opened': 0, 'later_semester_directories_read': False,
              'historical_training_ready': False, 'identity_approvals_granted': 0, 'scores_published': 0}
    output.mkdir(parents=True, exist_ok=False)
    files = {'corpus_audit.jsonl': records,
             'eligible_corpus.jsonl': [r for r in records if r['calendar_eligible']],
             'eligible_source_records.jsonl': [dict(source, _audit=review)
                                              for source, review in zip(corpus_rows, records)
                                              if review['calendar_eligible']],
             'student_metadata_audit.jsonl': students,
             'eligible_student_candidates.jsonl': [r for r in students if r['calendar_eligible']],
             'advisor_counts.jsonl': [{'advisor_id': r['advisor_id'], 'name': r['name'],
                                      'counts': dict(counts[r['advisor_id']]),
                                      'eligible_records': counts[r['advisor_id']]['calendar_eligible'],
                                      'missing_or_conflicting_dates': sum(n for key,n in counts[r['advisor_id']].items()
                                                                         if key in {'unknown_date','date_needs_review','conflicting_dates'})}
                                     for r in roster]}
    for name, rows in files.items():
        (output / name).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if any(sha(path) != expected for path, expected in inputs.items()):
        raise ValueError('input_changed_during_audit')
    manifest = {'schema_version': report['schema_version'], 'input_hashes': inputs,
                'script_sha256': sha(__file__), 'source_files_modified': False,
                'output_hashes': {p.name: sha(p) for p in output.iterdir() if p.is_file()}}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=Path(__file__).resolve().parents[1] / 'data')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.data, args.output)))
