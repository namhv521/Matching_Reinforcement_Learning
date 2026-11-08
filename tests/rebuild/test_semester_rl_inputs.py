import csv
import json
from pathlib import Path

from scripts.prepare_semester_rl_inputs import prepare_inputs


def write_csv(path, headers, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def test_prepare_inputs_excludes_students_without_exact_roster_supervisor(tmp_path):
    source, destination, data = tmp_path / 'source', tmp_path / 'destination', tmp_path / 'data'
    for term in ('2024', '2025.1', '2025.2', '2025.3'):
        links = [
            {'semester_id': term, 'student_id': 'kept', 'advisor_id': 'advisor-1', 'status': 'matched_needs_review', 'source_quote': 'exact'},
            {'semester_id': term, 'student_id': 'removed', 'advisor_id': '', 'status': 'supervisor_not_in_confirmed_roster', 'source_quote': 'unknown'},
        ]
        write_csv(source / term / 'student_advisor_links.csv', list(links[0]), links)
        for name in (('students_external_test.csv',) if term == '2025.3' else ('students_train.csv', 'students_validation.csv')):
            write_csv(source / term / name, ['student_id', 'thesis_title'],
                      [{'student_id': 'kept', 'thesis_title': 'kept'}, {'student_id': 'removed', 'thesis_title': 'removed'}])
        write_csv(source / term / 'advisors_profile.csv', ['advisor_id', 'name'], [{'advisor_id': 'advisor-1', 'name': 'Advisor'}])
        write_csv(source / term / 'advisors_processed.csv', ['advisor_id', 'source_record_ids', 'record_count', 'snapshot_cutoff'],
                  [{'advisor_id': 'advisor-1', 'source_record_ids': '["record-1"]', 'record_count': '1', 'snapshot_cutoff': ''}])
    (source / 'checksums.json').write_text('{}')
    (source / 'split_manifest.csv').write_text('student_id,split\nkept,train\n')
    (tmp_path / 'configs' / 'data').mkdir(parents=True)
    (tmp_path / 'configs' / 'data' / 'taxonomy_v1.yaml').write_text('schema_version: \'1.0\'\ntaxonomy_version: \'1.0\'\ngroups: {}\n')
    for pool in ('2024', '2025.1'):
        write_csv(data / pool / 'advisors/faculty_corpus/advisors_corpus.csv', ['record_id'], [{'record_id': 'record-1'}])
    report = prepare_inputs(source, destination, data)
    assert report['excluded_students']['2025.2'] == 1
    with (destination / '2025.2/students_train.csv').open(encoding='utf-8-sig', newline='') as stream:
        assert [row['student_id'] for row in csv.DictReader(stream)] == ['kept']
    excluded = json.loads((destination / '2025.2/excluded_students.json').read_text())
    assert excluded == [{'student_id': 'removed', 'reason': 'supervisor_not_in_confirmed_roster', 'source_quote': 'unknown'}]