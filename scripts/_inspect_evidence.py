"""Temporary inspection helper: print evidence snippets per tag for calibration."""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--term', default='2025.1')
    parser.add_argument('--tags', default='ai,cpp,machine_learning')
    parser.add_argument('--limit', type=int, default=30)
    parser.add_argument('--out', type=Path, default=ROOT / 'outputs/_inspect_evidence.txt')
    args = parser.parse_args()

    wanted = {t.strip() for t in args.tags.split(',') if t.strip()}
    path = ROOT / 'data' / args.term / 'student/students_processed/students_processed.csv'
    rows = list(csv.DictReader(path.open(encoding='utf-8-sig')))
    lines = [f'rows={len(rows)} file={path}']
    shown = Counter()
    for row in rows:
        for item in json.loads(row['skill_evidence_refs'] or '[]'):
            tag = item['tag']
            if tag not in wanted or shown[tag] >= args.limit:
                continue
            shown[tag] += 1
            snippet = ' '.join(item['snippet'].split())
            lines.append(f"\n[{tag}] sv={row['student_id']} page={item['page']} matched={item['matched_text']!r}")
            lines.append(f'    {snippet[:300]}')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'wrote {args.out} ({len(lines)} lines)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
