"""Temporary: inspect how docx rows reference their source and rendered PDF."""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for term in ('2024', '2025.1', '2025.2'):
    path = ROOT / 'data' / term / 'student/students_processed/students_processed.csv'
    rows = [r for r in csv.DictReader(path.open(encoding='utf-8-sig')) if r['source_type'] == 'docx']
    for row in rows[:4]:
        source = row['source_file']
        candidate = ROOT / 'data' / term / 'student/KLTN' / Path(source).name
        rendered = candidate.with_suffix('.pdf')
        print(f'{term} {Path(source).name[:40]:42s} docx={candidate.is_file()} pdf={rendered.is_file()}')
    kltn = ROOT / 'data' / term / 'student/KLTN'
    exts = {}
    for item in kltn.iterdir():
        exts[item.suffix.lower()] = exts.get(item.suffix.lower(), 0) + 1
    print(f'  {term} KLTN extensions: {exts}')
