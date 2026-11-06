"""Batch collection, extraction and reviewed per-skill snapshots (PRD v1.3)."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_rows(path):
    with Path(path).open(encoding='utf-8-sig') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def write_rows(path, rows):
    Path(path).write_text(''.join(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n' for row in rows), encoding='utf-8')


def extract_jobs(jobs):
    """Jobs contain text units, inventory and explicit provenance; never approve."""
    from src.data_pipeline.advisor_skill_extraction import extract_skill_claims
    claims, reports = [], []
    for job in jobs:
        result = extract_skill_claims(
            job['text_units'], content_scope=job['content_scope'],
            artifact_id=job['artifact_id'], advisor_id=job['advisor_id'],
            expected_units=job.get('expected_units'))
        for claim in result['claims']:
            # Metadata is supplied by the caller, never inferred from crawl time.
            row = {**claim, 'available_at': job.get('available_at'),
                   'split': job.get('split'),
                   'training_eligibility': job.get('training_eligibility', 'unresolved'),
                   'source_url': job.get('source_url'),
                   'content_completeness': claim['content_completeness']}
            for field in ('article_person_link_status', 'downloaded_document_matches_article',
                          'identity_review_status', 'article_identity_review_status',
                          'document_sha256', 'candidate_publication', 'candidate_publications',
                           'source_pool', 'academic_term', 'supervision_review_status',
                           'supervision_id', 'student_ids', 'thesis_id'):
                if field in job:
                    row[field] = job[field]
            if job.get('channel') == 'thesis':
                if job['content_scope'] == 'title_only':
                    raise ValueError('thesis_scoring_requires_content_not_title')
                row['channel'] = 'thesis'
                row['supervision_review_status'] = 'pending'
            claims.append(row)
        reports.append({k: v for k, v in result.items() if k != 'claims'} | {
            'artifact_id': job['artifact_id'], 'advisor_id': job['advisor_id']})
    return claims, reports


def build_scores(profile, theses, *, registry, cutoff, scope, excluded_thesis_ids=()):
    from src.features.advisor_skill_scores import score_advisor_skills
    from src.data_pipeline.normalization import load_taxonomy, taxonomy_ids
    allowed_skills = taxonomy_ids(load_taxonomy())
    for row in [*profile, *theses]:
        if row.get('source_pool') == '2025.3' or row.get('academic_term') == '2025.3':
            raise ValueError('external_test_source_forbidden')
        if row.get('advisor_id') not in registry:
            raise ValueError('advisor_outside_registry')
        if row.get('skill_id') not in allowed_skills:
            raise ValueError('skill_outside_taxonomy')
    return score_advisor_skills(profile, theses, cutoff=cutoff, scope=scope,
                               excluded_thesis_ids=excluded_thesis_ids, advisor_ids=registry)


def validate_snapshot_cutoff(semester, cutoff):
    deadline = datetime.fromisoformat(cutoff.replace('Z', '+00:00'))
    if deadline.tzinfo is None:
        raise ValueError('timezone_timestamp_required')
    # Exclusive semester end in Asia/Saigon. A decision may precede semester start.
    ends = {'2024': '2025-09-01T00:00:00+07:00',
            '2025.1': '2026-01-01T00:00:00+07:00',
            '2025.2': '2026-06-01T00:00:00+07:00'}
    if deadline >= datetime.fromisoformat(ends[semester]):
        raise ValueError('cutoff_outside_semester_protocol')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    collect = commands.add_parser('collect', help='Collect exact seeds; failures require Chrome UI')
    collect.add_argument('--seed-csv', type=Path, required=True)
    collect.add_argument('--max-urls', type=int, default=68)
    collect.add_argument('--output', type=Path, required=True)
    extract = commands.add_parser('extract', help='Extract pending claims from JSONL text-unit jobs')
    extract.add_argument('--jobs', type=Path, required=True)
    extract.add_argument('--output', type=Path, required=True)
    score = commands.add_parser('score', help='Score explicitly reviewed JSONL claims')
    score.add_argument('--profile-claims', type=Path, required=True)
    score.add_argument('--thesis-claims', type=Path, required=True)
    score.add_argument('--registry', type=Path, required=True)
    score.add_argument('--cutoff', required=True, help='Decision timestamp with timezone')
    score.add_argument('--semester', choices=['2024', '2025.1', '2025.2'], required=True)
    score.add_argument('--scope', choices=['point_in_time_verified', 'retrospective_proxy'], required=True)
    score.add_argument('--exclude-thesis-id', action='append', default=[])
    score.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == 'collect':
        from src.data_pipeline.advisor_skill_collection import collect_seed_profiles
        report = collect_seed_profiles(args.seed_csv, args.output, max_urls=args.max_urls)
        print(json.dumps(report, ensure_ascii=True))
        return 0
    # Compute and validate before creating a new immutable output namespace.
    if args.command == 'extract':
        rows, report = extract_jobs(read_rows(args.jobs))
        inputs = {'jobs': digest(args.jobs)}
    else:
        validate_snapshot_cutoff(args.semester, args.cutoff)
        with args.registry.open(encoding='utf-8-sig', newline='') as stream:
            registry_rows = list(csv.DictReader(stream))
        registry = [row['advisor_id'] for row in registry_rows]
        if len(set(registry)) != len(registry) or not registry:
            raise ValueError('unique_nonempty_registry_required')
        rows = build_scores(read_rows(args.profile_claims), read_rows(args.thesis_claims),
                            registry=registry, cutoff=args.cutoff, scope=args.scope,
                            excluded_thesis_ids=args.exclude_thesis_id)
        report = {'score_rows': len(rows), 'complete': sum(r['known_mask'] for r in rows),
                  'scope': args.scope, 'cutoff': args.cutoff, 'semester': args.semester,
                  'excluded_thesis_ids': args.exclude_thesis_id, 'allowed_splits': ['train']}
        inputs = {'profile_claims': digest(args.profile_claims),
                  'thesis_claims': digest(args.thesis_claims), 'registry': digest(args.registry)}
    args.output.mkdir(parents=True, exist_ok=False)
    target = args.output / ('skill_evidence.jsonl' if args.command == 'extract' else 'advisor_skill_scores.jsonl')
    write_rows(target, rows)
    write_json(args.output / 'report.json', report)
    if args.command == 'score':
        with (args.output / 'advisor_skill_scores.csv').open('w', encoding='utf-8-sig', newline='') as stream:
            fields = list(rows[0]) if rows else ['advisor_id', 'skill_id', 'final_score']
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                             for k, v in row.items()} for row in rows)
    hashes = {path.name: digest(path) for path in args.output.iterdir() if path.is_file()}
    write_json(args.output / 'snapshot_manifest.json', {
        'schema_version': 'advisor-skill-batch/1.3', 'command': args.command,
        'created_at': datetime.now(timezone.utc).isoformat(), 'input_hashes': inputs,
        'output_hashes': hashes, 'taxonomy_sha256': digest(ROOT / 'configs/data/taxonomy_v1.yaml'),
        'spec_sha256': digest(ROOT / 'docs/advisor_skill_semester_prd_spec.md'),
        'scoring_code_sha256': digest(ROOT / 'src/features/advisor_skill_scores.py'),
        'extraction_code_sha256': digest(ROOT / 'src/data_pipeline/advisor_skill_extraction.py'),
        'normalization_code_sha256': digest(ROOT / 'src/data_pipeline/normalization.py'),
        'pipeline_code_sha256': digest(Path(__file__)),
        'weights': {'prediction': .4, 'evidence': .6, 'profile': .5, 'gvhd': .5},
        'production_promoted': False})
    print(json.dumps({'output': str(args.output), 'rows': len(rows)}, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
