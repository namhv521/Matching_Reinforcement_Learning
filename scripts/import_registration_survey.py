"""Read the supplied XLSX survey into a minimal, source-bound JSON receipt."""
import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def normalize(value):
    return ' '.join(unicodedata.normalize('NFC', str(value or '')).split()).casefold()


def export_survey(source, output):
    from openpyxl import load_workbook
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError('new_survey_export_required')
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    allowed = {normalize('Đăng ký làm Đề án, Đăng ký Khoá luận tốt nghiệp'), normalize('Đăng ký Khoá luận tốt nghiệp')}
    workbook = load_workbook(source, read_only=True, data_only=True)
    rows, seen, statuses, issues = [], Counter(), Counter(), []
    for sheet in workbook:
        iterator = iter(sheet.values)
        header = next(iterator)
        if len(header) < 19 or normalize(header[3]) != normalize('Mã sinh viên'):
            raise ValueError('expected_survey_column_layout_required')
        for number, record in enumerate(iterator, 2):
            seen[normalize(record[1])] += 1
            if normalize(record[1]) not in allowed:
                continue
            raw_id = record[3]
            sid = str(int(raw_id)) if isinstance(raw_id, (int, float)) else re.sub(r'\.0$', '', str(raw_id or '').strip())
            if not re.fullmatch(r'\d{8}', sid):
                issues.append({'source_sheet': sheet.title, 'source_row': number,
                               'student_id': sid, 'reason': 'invalid_student_id_no_automatic_correction'})
            timestamp = record[0].isoformat() if isinstance(record[0], datetime) else str(record[0] or '')
            rows.append({'source_sheet': sheet.title, 'source_row': number, 'timestamp': timestamp,
                         'registration_type': str(record[1]), 'assigned_advisor': record[2] or '',
                         'student_id': sid, 'student_name': record[4] or '', 'priority_1': record[6] or '',
                         'registration_status': record[8] or '', 'priority_2': record[9] or '',
                         'priority_3': record[10] or '', 'declared_term': record[18] or ''})
            statuses[str(record[8])] += 1
    workbook.close()
    if hashlib.sha256(source.read_bytes()).hexdigest() != source_sha:
        raise ValueError('survey_source_changed_during_read')
    payload = {'schema_version': 'registration-survey/1', 'source_path': str(source), 'source_sha256': source_sha,
               'exported_at': datetime.now(timezone.utc).isoformat(), 'filter_column': 'B',
               'allowed_normalized_values': sorted(allowed), 'timestamp_timezone_assumption': 'Asia/Saigon for naive form timestamps',
               'status_semantics': 'self_reported_registration_not_independent_advisor_acceptance',
               'filtered_rows': len(rows), 'unique_student_ids': len({r['student_id'] for r in rows}),
               'status_counts': dict(statuses), 'issues': issues, 'rows': rows}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return {k: payload[k] for k in ('filtered_rows', 'unique_student_ids', 'status_counts', 'source_sha256')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export_survey(args.source, args.output), ensure_ascii=True, indent=2))
