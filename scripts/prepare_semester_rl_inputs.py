"""Create a fresh supervisor-resolved input package for nested semester RL."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


TERMS = ('2024', '2025.1', '2025.2', '2025.3')
TRAIN_SPLITS = {'2024': ('students_train.csv', 'students_validation.csv'),
                '2025.1': ('students_train.csv', 'students_validation.csv'),
                '2025.2': ('students_train.csv', 'students_validation.csv'),
                '2025.3': ('students_external_test.csv',)}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or ()), list(reader)


def write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def prepare_inputs(source: Path, destination: Path, data_root: Path) -> dict:
    source, destination, data_root = source.resolve(), destination.resolve(), data_root.resolve()
    if destination.exists() or not (source / 'checksums.json').is_file():
        raise ValueError('fresh_prepared_input_destination_required')
    destination.mkdir(parents=True)
    retained_by_term, exclusions = {}, {}
    for term in TERMS:
        source_term, target_term = source / term, destination / term
        target_term.mkdir()
        link_headers, links = read_csv(source_term / 'student_advisor_links.csv')
        resolved = {row['student_id']: row for row in links
                    if row.get('status') == 'matched_needs_review' and row.get('advisor_id')}
        retained_by_term[term] = set(resolved)
        exclusions[term] = [{'student_id': row['student_id'], 'reason': row.get('status', 'missing_supervisor_link'),
                             'source_quote': row.get('source_quote', '')}
                            for row in links if row['student_id'] not in resolved]
        write_csv(target_term / 'student_advisor_links.csv', link_headers,
                  [row for row in links if row['student_id'] in resolved])
        for filename in TRAIN_SPLITS[term]:
            headers, rows = read_csv(source_term / filename)
            write_csv(target_term / filename, headers, [row for row in rows if row['student_id'] in resolved])
        for filename in ('advisors_profile.csv', 'advisors_processed.csv'):
            shutil.copy2(source_term / filename, target_term / filename)

    # Canonical corpora changed after the old package. Rebuild V1 IDs from 2024;
    # V2/V3 intentionally use the cumulative 2024+2025.1 advisor snapshot.
    corpora = {}
    for pool in ('2024', '2025.1'):
        _, rows = read_csv(data_root / pool / 'advisors/faculty_corpus/advisors_corpus.csv')
        corpora[pool] = {row['record_id']: row for row in rows}
    for term, pools in {'2024': ('2024',), '2025.1': ('2024', '2025.1'),
                        '2025.2': ('2024', '2025.1'), '2025.3': ('2024', '2025.1')}.items():
        path = destination / term / 'advisors_processed.csv'
        headers, rows = read_csv(path)
        available = {key for pool in pools for key in corpora[pool]}
        for row in rows:
            record_ids = [item for item in json.loads(row['source_record_ids']) if item in available]
            row['source_record_ids'] = json.dumps(record_ids, ensure_ascii=False)
            row['record_count'] = str(len(record_ids))
            row['snapshot_cutoff'] = '2025-12-31' if term in {'2025.1', '2025.2', '2025.3'} else '2025-08-31'
        write_csv(path, headers, rows)
    shutil.copy2(source / 'split_manifest.csv', destination / 'split_manifest.csv')
    taxonomy = data_root.parent / 'configs/data/taxonomy_v1.yaml'
    shutil.copy2(taxonomy, destination / 'taxonomy_v1.yaml')
    report = {'schema_version': 'semester-rl-prepared-inputs/2', 'created_at': datetime.now(timezone.utc).isoformat(),
              'source_package': str(source), 'data_root': str(data_root),
              'taxonomy_sha256': digest(destination / 'taxonomy_v1.yaml'),
              'advisor_source_policy': {'2024': ['2024'], '2025.1': ['2024', '2025.1'],
                                        '2025.2': ['2024', '2025.1'], '2025.3': ['2024', '2025.1']},
              'student_counts': {term: {filename.removesuffix('.csv'): sum(1 for _ in csv.DictReader(
                  (destination / term / filename).open(encoding='utf-8-sig', newline='')))
                  for filename in TRAIN_SPLITS[term]} for term in TERMS},
              'excluded_students': {term: len(rows) for term, rows in exclusions.items()},
              'v3_semantics': 'student_theses_only_with_v2_frozen_advisor_representation_no_2025_2_advisor_corpus'}
    for term, rows in exclusions.items():
        (destination / term / 'excluded_students.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (destination / 'manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    checksums = {path.relative_to(destination).as_posix(): digest(path)
                 for path in sorted(destination.rglob('*')) if path.is_file() and path.name != 'checksums.json'}
    (destination / 'checksums.json').write_text(json.dumps(checksums, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, default=Path(__file__).resolve().parents[1] / 'data')
    args = parser.parse_args(argv)
    print(json.dumps(prepare_inputs(args.source, args.destination, args.data_root), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())