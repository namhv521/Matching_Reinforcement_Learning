"""Create immutable, review-gated advisor skill snapshot receipts.

This command does not crawl, approve identities, infer availability, or mutate
source data. It stages dated candidates and closes only reviewer-backed claims.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data_pipeline.advisor_skill_snapshot import (apply_review_decisions,
    close_snapshot, grouped_thesis_split, mark_duplicate_candidates, partition_advisor_candidates)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8-sig').splitlines() if line.strip()]


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def write_jsonl(path, rows):
    Path(path).write_text(''.join(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n' for row in rows), encoding='utf-8')


def read_registry(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    ids = [row.get('advisor_id') for row in rows]
    if not ids or any(not isinstance(value, str) or not value.strip() for value in ids) or len(set(ids)) != len(ids):
        raise ValueError('unique_nonempty_registry_required')
    return ids


def review_pack(rows):
    """Produce stable reviewer work items; no decision is populated automatically."""
    output, seen = [], set()
    for row in rows:
        evidence = row.get('evidence_id')
        if not isinstance(evidence, str) or not evidence or evidence in seen:
            raise ValueError('unique_evidence_id_required_for_review_pack')
        seen.add(evidence)
        output.append({'evidence_id': evidence, 'advisor_id': row.get('advisor_id'),
                       'artifact_id': row.get('artifact_id'), 'skill_id': row.get('skill_id'),
                       'channel': row.get('channel'), 'source_url': row.get('source_url'),
                       'available_at': row.get('available_at'), 'review_status': row.get('review_status'),
                       'required_decision_fields': ['review_status', 'reviewer', 'reviewed_at', 'reason'],
                       'note': 'Parser output is a candidate; approval must be entered by a reviewer.'})
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    partition = commands.add_parser('partition')
    partition.add_argument('--candidates', type=Path, required=True)
    partition.add_argument('--data-root', type=Path,
                           help='Optional data root to append run-specific advisor corpus files under <pool>/advisors/.')
    partition.add_argument('--output', type=Path, required=True)
    pack = commands.add_parser('review-pack')
    pack.add_argument('--claims', type=Path, nargs='+', required=True)
    pack.add_argument('--output', type=Path, required=True)
    close = commands.add_parser('close')
    close.add_argument('--profile-claims', type=Path, required=True)
    close.add_argument('--thesis-claims', type=Path, required=True)
    close.add_argument('--decisions', type=Path, required=True)
    close.add_argument('--registry', type=Path, required=True)
    close.add_argument('--semester', choices=['2024', '2025.1', '2025.2'], required=True)
    close.add_argument('--cutoff', required=True)
    close.add_argument('--scope', choices=['point_in_time_verified', 'retrospective_proxy'], required=True)
    close.add_argument('--requirements', type=Path)
    close.add_argument('--students', type=Path, help='JSONL rows with student_id and thesis_id')
    close.add_argument('--capacities', type=Path, help='JSON object keyed by advisor_id')
    close.add_argument('--eligible', type=Path, help='JSON object keyed by student_id then advisor_id')
    close.add_argument('--present', type=Path, help='JSON object keyed by advisor_id')
    close.add_argument('--split-seed', type=int, default=42)
    close.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise ValueError('immutable_output_directory_required')
    if args.command == 'partition':
        rows = partition_advisor_candidates(mark_duplicate_candidates(read_jsonl(args.candidates)))
        args.output.mkdir(parents=True)
        for pool, candidates in rows.items():
            target_root = args.data_root if args.data_root is not None else args.output
            target = target_root / pool / 'advisors' / 'faculty_corpus'
            target.mkdir(parents=True, exist_ok=True)
            name = 'advisor_candidates.' + digest(args.candidates)[:12] + '.jsonl'
            destination = target / name
            if destination.exists():
                raise ValueError('immutable_partition_destination_required')
            write_jsonl(destination, candidates)
        manifest = {'schema_version': 'advisor-calendar-partition/1',
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'input_sha256': digest(args.candidates),
                    'counts': {pool: len(value) for pool, value in rows.items()},
                    'duplicate_rows_pending_review': sum(row['dedup_status'] == 'pending_review'
                                                         for value in rows.values() for row in value),
                    'data_root': str(args.data_root.resolve()) if args.data_root is not None else None,
                    'note': 'Staging only; candidates retain original available_at and are not approved or scored.'}
        write_json(args.output / 'manifest.json', manifest)
        return 0
    if args.command == 'review-pack':
        rows = [row for path in args.claims for row in read_jsonl(path)]
        pack_rows = review_pack(rows)
        args.output.mkdir(parents=True)
        write_jsonl(args.output / 'review_candidates.jsonl', pack_rows)
        write_json(args.output / 'manifest.json', {'schema_version': 'advisor-skill-review-pack/1',
                   'created_at': datetime.now(timezone.utc).isoformat(),
                   'input_hashes': {str(path): digest(path) for path in args.claims},
                   'candidate_count': len(pack_rows), 'approvals_granted': 0})
        return 0
    profile = apply_review_decisions(read_jsonl(args.profile_claims), read_jsonl(args.decisions))
    theses = apply_review_decisions(read_jsonl(args.thesis_claims), read_jsonl(args.decisions))
    registry = read_registry(args.registry)
    kwargs = {}
    split = None
    operator_paths = [args.requirements, args.students, args.capacities, args.eligible, args.present]
    if any(operator_paths) and not all(operator_paths):
        raise ValueError('complete_matching_contract_required')
    if all(operator_paths):
        students = read_jsonl(args.students)
        split = grouped_thesis_split(students, seed=args.split_seed)
        assignments = split['assignments']
        for row in theses:
            student_ids = row.get('student_ids', [])
            observed = {assignments[student] for student in student_ids if student in assignments}
            if len(observed) > 1:
                raise ValueError('thesis_cross_split_leakage')
            if observed:
                row['split'] = observed.pop()
        capacity = json.loads(args.capacities.read_text(encoding='utf-8'))
        eligibility = json.loads(args.eligible.read_text(encoding='utf-8'))
        attendance = json.loads(args.present.read_text(encoding='utf-8'))
        student_ids = sorted(assignments)
        kwargs = {'requirements': read_jsonl(args.requirements), 'student_ids': student_ids,
                  'capacities': [capacity[advisor] for advisor in registry],
                  'eligible': [[eligibility[student][advisor] for advisor in registry] for student in student_ids],
                  'present': [attendance[advisor] for advisor in registry]}
    result = close_snapshot(profile_claims=profile, thesis_claims=theses, registry=registry,
                            semester=args.semester, cutoff=args.cutoff, scope=args.scope, **kwargs)
    args.output.mkdir(parents=True)
    write_jsonl(args.output / 'reviewed_profile_claims.jsonl', profile)
    write_jsonl(args.output / 'reviewed_thesis_claims.jsonl', theses)
    write_jsonl(args.output / 'advisor_skill_scores.jsonl', result['score_rows'])
    if split is not None:
        write_json(args.output / 'grouped_thesis_split.json', split)
    write_json(args.output / 'baseline_hungarian.json', result['baseline'])
    for name, value in result.get('baselines', {}).items():
        if name != 'hungarian':
            write_json(args.output / f'baseline_{name}.json', value)
    input_paths = [args.profile_claims, args.thesis_claims, args.decisions, args.registry, *operator_paths]
    write_json(args.output / 'snapshot_manifest.json', {
        'schema_version': 'advisor-skill-closed-snapshot/1', 'created_at': datetime.now(timezone.utc).isoformat(),
        'status': result['status'], 'semester': args.semester, 'cutoff': args.cutoff, 'scope': args.scope,
        'input_hashes': {str(path): digest(path) for path in input_paths if path is not None},
        'output_hashes': {path.name: digest(path) for path in args.output.iterdir() if path.is_file()},
        'feature_contract_sha256': result.get('feature_contract_sha256'),
        'blocking_reasons': result['blocking_reasons'], 'baseline_status': result['baseline']['status'],
        'production_promoted': False,
    })
    return 0


if __name__ == '__main__':
    raise SystemExit(main())