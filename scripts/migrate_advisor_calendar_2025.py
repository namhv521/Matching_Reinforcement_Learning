"""Move canonical advisor-corpus records dated in calendar year 2025 to pool 2025.1.

The original event/publication fields and raw-source paths remain unchanged. This
is a storage-pool correction only: it never approves identity, availability,
skill claims, or training eligibility.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_calendar_year_2025(row: dict[str, str]) -> bool:
    return any(str(row.get(field, '')).strip().startswith('2025')
               for field in ('event_date', 'published_at', 'publication_year'))


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or ()), list(reader)


def write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def migrate(data_root: Path, receipt: Path) -> dict:
    source = data_root / '2024/advisors/faculty_corpus/advisors_corpus.csv'
    destination = data_root / '2025.1/advisors/faculty_corpus/advisors_corpus.csv'
    if not source.is_file() or not destination.is_file():
        raise ValueError('canonical_advisor_corpus_required')
    if receipt.exists():
        raise ValueError('immutable_receipt_path_required')

    source_headers, source_rows = read_csv(source)
    destination_headers, destination_rows = read_csv(destination)
    if source_headers != destination_headers or 'record_id' not in source_headers:
        raise ValueError('matching_corpus_headers_and_record_id_required')
    before = {'source_sha256': digest(source), 'destination_sha256': digest(destination),
              'source_rows': len(source_rows), 'destination_rows': len(destination_rows)}
    moving = [row for row in source_rows if is_calendar_year_2025(row)]
    retained = [row for row in source_rows if not is_calendar_year_2025(row)]
    moving_ids = [row['record_id'] for row in moving]
    if len(moving_ids) != len(set(moving_ids)):
        raise ValueError('duplicate_source_record_id')
    destination_ids = {row['record_id'] for row in destination_rows}
    overlap = destination_ids & set(moving_ids)
    if overlap:
        raise ValueError('destination_already_contains_moving_record:' + ','.join(sorted(overlap)))
    if not moving:
        raise ValueError('no_calendar_year_2025_records_to_migrate')

    write_csv(source, source_headers, retained)
    write_csv(destination, destination_headers, [*destination_rows, *moving])
    after_source_headers, after_source_rows = read_csv(source)
    after_destination_headers, after_destination_rows = read_csv(destination)
    if (after_source_headers != source_headers or after_destination_headers != destination_headers
            or len(after_source_rows) != len(retained) or len(after_destination_rows) != len(destination_rows) + len(moving)
            or any(is_calendar_year_2025(row) for row in after_source_rows)
            or {row['record_id'] for row in after_destination_rows} < set(moving_ids)):
        raise ValueError('post_migration_verification_failed')

    receipt.mkdir(parents=True, exist_ok=False)
    result = {
        'schema_version': 'advisor-calendar-pool-migration/1',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'operation': 'move_calendar_year_2025_records_from_2024_to_2025.1',
        'source': str(source), 'destination': str(destination), 'before': before,
        'after': {'source_sha256': digest(source), 'destination_sha256': digest(destination),
                  'source_rows': len(after_source_rows), 'destination_rows': len(after_destination_rows)},
        'moved_record_ids': moving_ids,
        'moved_count': len(moving_ids),
        'preserved_fields': ['event_date', 'published_at', 'publication_year', 'academic_term',
                             'source_url', 'raw_path', 'sha256', 'review_status'],
        'not_changed': ['identity approval', 'availability', 'skill evidence', 'training eligibility', 'score'],
    }
    (receipt / 'migration_receipt.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, default=Path(__file__).resolve().parents[1] / 'data')
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(migrate(args.data_root.resolve(), args.receipt.resolve()), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())