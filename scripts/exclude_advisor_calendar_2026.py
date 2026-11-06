"""Exclude calendar-year 2026+ advisor corpus records from canonical pools.

Raw crawl assets remain untouched for provenance. The removed index records are
not approved, scored, or eligible for matching/training.
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


def is_2026_or_later(row: dict[str, str]) -> bool:
    for field in ('event_date', 'published_at', 'publication_year'):
        value = str(row.get(field, '')).strip()[:4]
        if value.isdigit() and int(value) >= 2026:
            return True
    return False


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or ()), list(reader)


def write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def exclude(data_root: Path, receipt: Path) -> dict:
    if receipt.exists():
        raise ValueError('immutable_receipt_path_required')
    report = {'schema_version': 'advisor-calendar-exclusion/1',
              'created_at': datetime.now(timezone.utc).isoformat(),
              'operation': 'exclude_calendar_year_2026_or_later_from_canonical_advisor_corpus',
              'pools': {}, 'not_changed': ['raw crawl assets', 'identity approval', 'availability',
                                            'skill evidence', 'training eligibility', 'score']}
    for pool in ('2025.2', '2025.3'):
        path = data_root / pool / 'advisors/faculty_corpus/advisors_corpus.csv'
        headers, rows = read_csv(path)
        if 'record_id' not in headers:
            raise ValueError('record_id_required')
        removed = [row for row in rows if is_2026_or_later(row)]
        retained = [row for row in rows if not is_2026_or_later(row)]
        ids = [row['record_id'] for row in removed]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate_record_id')
        before = {'sha256': digest(path), 'rows': len(rows)}
        write_csv(path, headers, retained)
        _, verified = read_csv(path)
        if len(verified) != len(retained) or any(is_2026_or_later(row) for row in verified):
            raise ValueError('post_exclusion_verification_failed')
        report['pools'][pool] = {'path': str(path), 'before': before,
                                 'after': {'sha256': digest(path), 'rows': len(verified)},
                                 'excluded_record_ids': ids, 'excluded_count': len(ids)}
    receipt.mkdir(parents=True, exist_ok=False)
    (receipt / 'exclusion_receipt.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, default=Path(__file__).resolve().parents[1] / 'data')
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(exclude(args.data_root.resolve(), args.receipt.resolve()), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())