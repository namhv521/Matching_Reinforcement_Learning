"""Debug: show retained direct-evidence snippets for a tag in a rebuilt snapshot."""
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
TECH = GROUPS[2:]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--term', default='2025.1')
    parser.add_argument('--variant', default='strict')
    parser.add_argument('--tag', default='ai')
    parser.add_argument('--limit', type=int, default=40)
    args = parser.parse_args()

    path = args.snapshot / args.variant / args.term / 'students_processed.csv'
    rows = list(csv.DictReader(path.open(encoding='utf-8-sig')))
    lines, reasons = [], Counter()
    hits = 0
    for row in rows:
        for item in json.loads(row['skill_evidence_refs'] or '[]'):
            reasons[item['reason']] += 1
        direct = [i for i in json.loads(row['skill_evidence_refs'] or '[]')
                  if i['tag'] == args.tag and i['context_class'] == 'direct_evidence']
        if not direct:
            continue
        hits += 1
        for item in direct[:1]:
            lines.append(f"== {row['student_id']} p{item['page']} {item['reason']}")
            lines.append(f"   {item['snippet'][:230]}")
    out = ROOT / 'outputs/_debug_direct.txt'
    out.write_text('\n'.join([f'hits={hits}', ''] + lines[:args.limit * 2] + ['', 'reasons:'] +
                             [f'  {k}: {v}' for k, v in reasons.most_common()]), encoding='utf-8')
    print(f'hits={hits} wrote {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
