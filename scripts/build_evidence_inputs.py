"""Build a matching input package from a rebuilt evidence snapshot.

Copies the reference package (same split, roster, exclusions, advisor files and
taxonomy) and replaces only evidence-derived student columns, joined on
student_id + source_sha256. Nothing else in the package changes, so before/after
comparisons isolate the effect of the extractor fix.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

EVIDENCE_COLUMNS = ('research_domain_tags', 'topic_tags', 'skills_tags', 'programming_languages',
                    'frameworks_libraries', 'databases', 'ml_ai_methods', 'data_engineering_tools',
                    'cloud_devops_tools', 'security_network_tools', 'software_engineering_methods',
                    'research_methods', 'math_statistics_topics', 'skill_evidence_refs',
                    'skill_evidence_type', 'reviewer_notes')
SPLIT_FILES = ('students_train.csv', 'students_validation.csv', 'students_external_test.csv')


def digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_csv(path: Path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or ()), list(reader)


def write_csv(path: Path, header, rows) -> None:
    with Path(path).open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


def build(base: Path, snapshot: Path, variant: str, destination: Path) -> dict:
    base, snapshot, destination = Path(base).resolve(), Path(snapshot).resolve(), Path(destination).resolve()
    if destination.exists():
        raise FileExistsError('fresh_destination_required')
    shutil.copytree(base, destination)
    report = {'schema_version': 'evidence-input-package/1', 'created_at': datetime.now(timezone.utc).isoformat(),
              'base_package': str(base), 'base_checksums_sha256': digest(base / 'checksums.json'),
              'evidence_snapshot': str(snapshot),
              'evidence_manifest_sha256': digest(snapshot / 'manifest.json'),
              'variant': variant, 'replaced_columns': list(EVIDENCE_COLUMNS), 'terms': {}}
    for term_dir in sorted(p for p in destination.iterdir() if p.is_dir()):
        term = term_dir.name
        source = snapshot / variant / term / 'students_processed.csv'
        if not source.is_file():
            continue
        _, rebuilt = read_csv(source)
        by_key = {(r['student_id'], r['source_sha256']): r for r in rebuilt}
        term_report = {}
        for name in SPLIT_FILES:
            path = term_dir / name
            if not path.is_file():
                continue
            header, rows = read_csv(path)
            missing = 0
            for row in rows:
                match = by_key.get((row['student_id'], row['source_sha256']))
                if match is None:
                    missing += 1
                    continue
                for column in EVIDENCE_COLUMNS:
                    if column in header:
                        row[column] = match[column]
            if missing:
                raise ValueError(f'unmatched_rows:{term}/{name}:{missing}')
            write_csv(path, header, rows)
            term_report[name] = len(rows)
        report['terms'][term] = term_report
    (destination / 'evidence_package.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                                                        encoding='utf-8')
    checksums = {p.relative_to(destination).as_posix(): digest(p)
                 for p in sorted(destination.rglob('*')) if p.is_file() and p.name != 'checksums.json'}
    (destination / 'checksums.json').write_text(json.dumps(checksums, ensure_ascii=False, indent=2) + '\n',
                                                encoding='utf-8')
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--variant', choices=('strict', 'topic'), required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(build(args.base, args.snapshot, args.variant, args.destination), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
