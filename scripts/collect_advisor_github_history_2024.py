"""Collect event-dated GitHub snapshots through calendar2024; public availability remains unknown.

Commit API: https://docs.github.com/en/rest/commits/commits#list-commits
"""
import argparse
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from read_advisor_repository_sources import collect_source_reading, digest, write_json
from src.data_pipeline.github_advisors import public_fetch


CUTOFF = datetime.fromisoformat('2025-01-01T00:00:00+07:00')
UNTIL = (CUTOFF.astimezone(timezone.utc)-timedelta(seconds=1)).strftime('%Y-%m-%dT%H:%M:%SZ')


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('timestamp_required')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timestamp_timezone_required')
    return result


def classify_repository(entry):
    if entry.get('private'):
        return 'excluded_private'
    try:
        created = timestamp(entry.get('created_at'))
    except ValueError:
        return 'unresolved_creation_date'
    if created >= CUTOFF:
        return 'excluded_created_2025_or_later'
    if entry.get('fork'):
        return 'excluded_fork_without_verified_contribution'
    return 'eligible_event_date'


def select_commit(payload):
    if not isinstance(payload, list):
        raise ValueError('commit_list_required')
    if not payload:
        return None
    commit = payload[0]
    if not re.fullmatch('[0-9a-f]{40}', commit.get('sha', '')):
        raise ValueError('invalid_commit_sha')
    metadata = commit.get('commit', {})
    author = metadata.get('author', {}).get('date')
    committer = metadata.get('committer', {}).get('date')
    if timestamp(author) >= CUTOFF or timestamp(committer) >= CUTOFF:
        raise ValueError('commit_event_after_2024')
    return {'sha': commit['sha'], 'author_date': author, 'committer_date': committer,
            'event_time_verified': True, 'historical_public_availability_verified': False}


def resume_selected(source_progress, output, *, stop_file=None):
    """Resume only exact, hash-verified historical selections; never consult HEAD."""
    source_progress, output = Path(source_progress).resolve(), Path(output).resolve()
    snapshot = source_progress.read_bytes()
    rows = json.loads(snapshot)
    output.mkdir(parents=True, exist_ok=False)
    (output/'source_progress_snapshot.json').write_bytes(snapshot)
    for row in rows:
        if row['status'] == 'historical_source_captured':
            row['source_manifest_path'] = str((source_progress.parent/row['source_manifest_path']).resolve())
        if row['status'] != 'historical_commit_selected':
            continue
        if stop_file and Path(stop_file).exists():
            row['status'] = 'historical_source_deferred_checkpoint'
        else:
            try:
                witness = row['commit_date_witness']
                body = (source_progress.parent/witness['raw_path']).read_bytes()
                if digest(body) != witness['sha256']:
                    raise ValueError('historical_commit_witness_hash_mismatch')
                selected = select_commit(json.loads(body))
                if selected != row['selected_commit']:
                    raise ValueError('historical_selection_mismatch')
                directory = row['repository'].replace('/', '_')
                result = collect_source_reading(row['repository'], selected['sha'], output/directory,
                                                 root_readme_only=True)
                row.update(status='historical_source_failed' if result.get('status') == 'source_reading_failed' else 'historical_source_captured',
                    source_manifest_path=directory+'/manifest.json',
                    source_manifest_sha256=digest((output/directory/'manifest.json').read_bytes()),
                    processed_units=len(result.get('processed_units', [])),
                    missing_units=len(result.get('missing_units', [])), source_scope='root')
            except Exception as error:
                row.update(status='unresolved_historical_source', error=type(error).__name__)
        write_json(output/'progress.json', rows)
        print(json.dumps({'repository':row['repository'],'status':row['status']}), flush=True)
    manifest={'cutoff_exclusive':CUTOFF.isoformat(), 'upstream_source_progress_path':str(source_progress),
              'upstream_source_progress_sha256':digest(snapshot),'repositories':rows,
              'historical_public_availability_verified':False,
              'status_counts':{s:sum(r['status']==s for r in rows) for s in sorted({r['status'] for r in rows})}}
    write_json(output/'manifest.json',manifest)
    return manifest


def collect(source, output, *, fetch=public_fetch, reader=collect_source_reading,
            source_mode='root', max_requests=70, stop_file=None):
    source, output = Path(source).resolve(), Path(output).resolve()
    if source_mode not in {'root', 'source', 'none'} or max_requests < 1:
        raise ValueError('invalid_collection_bounds')
    upstream_bytes = (source/'manifest.json').read_bytes()
    upstream = json.loads(upstream_bytes)
    repos_bytes = (source/'repositories.json').read_bytes()
    if digest(repos_bytes) != upstream['artifacts']['repositories.json']:
        raise ValueError('upstream_inventory_hash_mismatch')
    repos = json.loads(repos_bytes)
    rows = []
    witness_bytes = {}
    for repo in repos:
        name = repo['full_name']
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]+', name) or name.split('/')[1] in {'.', '..'}:
            raise ValueError('invalid_repository_name')
        listing_sha = repo['listing_source_sha256']
        if not re.fullmatch('[0-9a-f]{64}', listing_sha):
            raise ValueError('invalid_listing_sha')
        body = (source/'raw'/(listing_sha+'.bin')).read_bytes()
        if digest(body) != listing_sha:
            raise ValueError('metadata_date_witness_hash_mismatch')
        matches = [x for x in json.loads(body) if x.get('id') == repo['repository_id']]
        if len(matches) != 1 or matches[0].get('full_name', '').casefold() != name.casefold():
            raise ValueError('metadata_repository_mismatch')
        entry = matches[0]
        witness_bytes[listing_sha] = body
        rows.append({'repository': name, 'advisor_id': repo['advisor_id'],
                     'default_branch': entry.get('default_branch'), 'created_at': entry.get('created_at'),
                     'creation_date_witness_sha256': listing_sha, 'status': classify_repository(entry),
                     'review_status': 'pending', 'identity_review_status': 'pending', 'available_at': None,
                     'training_eligibility': 'unresolved', 'historical_public_availability_verified': False})
    output.mkdir(parents=True, exist_ok=False)
    (output/'raw').mkdir()
    for sha, body in witness_bytes.items():
        (output/'raw'/(sha+'.bin')).write_bytes(body)
    write_json(output/'creation_date_inventory.json', rows)
    requests, stop_reason = 0, None
    for row in rows:
        if row['status'] != 'eligible_event_date':
            continue
        if stop_file and Path(stop_file).exists():
            stop_reason = 'quota_checkpoint'
        if requests >= max_requests:
            stop_reason = 'request_budget_exceeded'
        if stop_reason:
            row['status'] = stop_reason
            continue
        url = 'https://api.github.com/repos/'+row['repository']+'/commits?'+urlencode(
            {'sha': row['default_branch'], 'until': UNTIL, 'per_page': 1})
        receipt = {'url': url, 'collected_at': datetime.now(timezone.utc).isoformat()}
        try:
            requests += 1
            status, body, headers = fetch(url)
            sha = digest(body)
            (output/'raw'/(sha+'.bin')).write_bytes(body)
            receipt.update(http_status=status, sha256=sha, raw_path='raw/'+sha+'.bin')
            limits = {k.lower(): v for k, v in headers.items() if k.lower() in {'x-ratelimit-remaining', 'x-ratelimit-reset', 'retry-after'}}
            receipt['rate_headers'] = limits
            if status in {403, 429} and (limits.get('x-ratelimit-remaining') == '0' or status == 429 or b'rate limit' in body.lower()):
                row['status'] = stop_reason = 'github_rate_limited'
            elif status in {404, 409}:
                row['status'] = 'no_accessible_historical_commit'
            elif status != 200:
                row['status'] = 'commit_lookup_failed'
            else:
                selected = select_commit(json.loads(body))
                row.update(status='historical_commit_selected' if selected else 'no_commit_before_2025', selected_commit=selected)
            if limits.get('x-ratelimit-remaining') == '0':
                stop_reason = 'github_rate_limit_exhausted'
        except Exception as error:
            row.update(status='unresolved_commit', error=type(error).__name__)
        row['commit_date_witness'] = receipt
        write_json(output/'selection_progress.json', rows)
    # Select all dates first; root/source reads never use the previous2026 HEAD SHA.
    for row in rows:
        if row['status'] != 'historical_commit_selected' or source_mode == 'none':
            continue
        if stop_file and Path(stop_file).exists():
            row['status'] = 'historical_source_deferred_checkpoint'
        else:
            directory = row['repository'].replace('/', '_')
            result = reader(row['repository'], row['selected_commit']['sha'], output/directory,
                            root_readme_only=source_mode == 'root')
            row.update(status='historical_source_failed' if result.get('status') == 'source_reading_failed' else 'historical_source_captured',
                       source_manifest_path=directory+'/manifest.json',
                       source_manifest_sha256=digest((output/directory/'manifest.json').read_bytes()),
                       processed_units=len(result.get('processed_units', [])),
                       missing_units=len(result.get('missing_units', [])), source_scope=source_mode)
        write_json(output/'source_progress.json', rows)
        print(json.dumps({'repository': row['repository'], 'status': row['status']}), flush=True)
    manifest = {'schema_version': 'advisor-history-through2024/1', 'cutoff_exclusive': CUTOFF.isoformat(),
        'until_api_utc': UNTIL, 'upstream_manifest_sha256': digest(upstream_bytes),
        'upstream_path': str(source), 'requests': requests, 'stop_reason': stop_reason,
        'repositories': rows, 'historical_public_availability_verified': False,
        'status_counts': {s: sum(r['status'] == s for r in rows) for s in sorted({r['status'] for r in rows})}}
    write_json(output/'manifest.json', manifest)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--source-mode', choices=['root', 'source', 'none'], default='root')
    parser.add_argument('--max-requests', type=int, default=70)
    parser.add_argument('--stop-file')
    parser.add_argument('--resume-selected', action='store_true')
    args = parser.parse_args()
    result = (resume_selected(args.source, args.output, stop_file=args.stop_file) if args.resume_selected else
              collect(args.source, args.output, source_mode=args.source_mode,
                      max_requests=args.max_requests, stop_file=args.stop_file))
    print(json.dumps(result['status_counts'], indent=2))
