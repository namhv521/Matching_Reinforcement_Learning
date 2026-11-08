"""Compare tag frequencies between the original CSV and a rebuilt snapshot.

Counts each student at most once per tag, matching how the report tables and the
concept-presence feature treat a tag.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GROUPS = ('research_domain_tags', 'topic_tags', 'programming_languages', 'frameworks_libraries',
          'databases', 'ml_ai_methods', 'data_engineering_tools', 'cloud_devops_tools',
          'security_network_tools', 'software_engineering_methods', 'research_methods',
          'math_statistics_topics')


def read(path: Path) -> list[dict]:
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def tag_counts(rows: list[dict]) -> Counter:
    counts = Counter()
    for row in rows:
        for group in GROUPS:
            for tag in filter(None, (row.get(group) or '').split(';')):
                counts[(group, tag)] += 1
    return counts


def tags_per_student(rows: list[dict]) -> list[int]:
    totals = []
    for row in rows:
        seen = {(g, t) for g in GROUPS for t in filter(None, (row.get(g) or '').split(';'))}
        totals.append(len(seen))
    return totals


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--term', default='2025.1')
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--variant', default='strict')
    parser.add_argument('--top', type=int, default=25)
    args = parser.parse_args()

    before = read(ROOT / 'data' / args.term / 'student/students_processed/students_processed.csv')
    after = read(args.snapshot / args.variant / args.term / 'students_processed.csv')
    assert len(before) == len(after), 'row count changed'

    old, new = tag_counts(before), tag_counts(after)
    lines = [f'term={args.term} variant={args.variant} students={len(before)}']
    old_per = tags_per_student(before)
    new_per = tags_per_student(after)
    lines.append(f'tags/student mean: {sum(old_per)/len(old_per):.2f} -> {sum(new_per)/len(new_per):.2f}')
    lines.append(f'students with zero tags: {old_per.count(0)} -> {new_per.count(0)}')
    lines.append('')
    lines.append(f'{"group":30s} {"tag":26s} {"before":>7s} {"after":>7s} {"delta":>7s}')
    for key, count in old.most_common(args.top):
        group, tag = key
        lines.append(f'{group:30s} {tag:26s} {count:7d} {new.get(key, 0):7d} {new.get(key, 0)-count:7d}')
    print('\n'.join(lines))

    watch = [('research_domain_tags', 'ai'), ('topic_tags', 'machine_learning'),
             ('programming_languages', 'cpp')]
    print('\nheadline tags (students, share):')
    for key in watch:
        o, n = old.get(key, 0), new.get(key, 0)
        print(f'  {key[1]:18s} {o:3d} ({o/len(before)*100:5.1f}%) -> {n:3d} ({n/len(before)*100:5.1f}%)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
