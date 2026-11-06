"""Temporary: source type and duplicate audit across the four terms."""
import csv
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for term in ('2024', '2025.1', '2025.2', '2025.3'):
    path = ROOT / 'data' / term / 'student/students_processed/students_processed.csv'
    rows = list(csv.DictReader(path.open(encoding='utf-8-sig')))
    types = Counter(row['source_type'] for row in rows)
    hashes = Counter(row['source_sha256'] for row in rows)
    ids = Counter(row['student_id'] for row in rows)
    dup_h = sum(count - 1 for count in hashes.values() if count > 1)
    dup_id = sum(count - 1 for count in ids.values() if count > 1)
    print(f'{term:8s} rows={len(rows):4d} types={dict(types)} dup_hash_rows={dup_h} dup_ids={dup_id}')
