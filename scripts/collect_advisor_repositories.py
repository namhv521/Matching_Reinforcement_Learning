"""Capture public GitHub inventories and pinned README files, not full code audits."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.data_pipeline.github_advisors import EXCLUDED, public_fetch, safe_source_path


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(body):
    return hashlib.sha256(body).hexdigest()


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode('utf-8')


def github_accounts(registry):
    with Path(registry).open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    accounts, seen = [], set()
    for row in rows:
        if not row.get('github_url'):
            continue
        parsed = urlparse(row['github_url'])
        username = parsed.path.strip('/')
        if (parsed.scheme != 'https' or parsed.hostname != 'github.com' or parsed.port not in (None, 443)
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}', username)):
            raise ValueError('invalid_github_profile_url')
        if username.casefold() in seen:
            raise ValueError('duplicate_github_account')
        seen.add(username.casefold())
        accounts.append({'advisor_id': row['advisor_id'], 'github_username': username,
                         'source_url': row['github_url'], 'identity_status': 'pending',
                         'review_status': 'pending'})
    return accounts


class RateLimitStop(Exception):
    pass


def pin_head(full_name, branch):
    if not isinstance(branch, str) or not branch or re.search(r'[\x00-\x20\x7f]', branch):
        raise ValueError('invalid_default_branch')
    result = subprocess.run(
        ['git', '-c', 'credential.helper=', 'ls-remote',
         'https://github.com/' + full_name + '.git', 'refs/heads/' + branch],
        capture_output=True, timeout=45, check=False,
        env={**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GIT_ASKPASS': ''})
    if result.returncode or len(result.stdout) > 65536:
        raise ValueError('default_branch_pin_failed')
    lines = result.stdout.decode('utf-8').strip().splitlines()
    if not lines:
        return None, result.stdout
    parts = lines[0].split()
    if len(lines) != 1 or len(parts) != 2 or not re.fullmatch('[0-9a-f]{40}', parts[0]):
        raise ValueError('invalid_pinned_sha')
    if parts[1] != 'refs/heads/' + branch:
        raise ValueError('default_branch_ref_mismatch')
    return parts[0], result.stdout


def harvest(registry, output, *, fetch=public_fetch, pin=pin_head, max_requests=100,
            max_pages=20, resume_from=None, readme_scope='root'):
    """Write receipts as requests finish; immutable output must not exist.

    No source is marked historically available or personally attributable.
    All discovered repos remain in the ledger even when rate/budget stops detail.
    """
    if max_requests < 1 or max_pages < 1:
        raise ValueError('positive_collection_bounds_required')
    if readme_scope not in {'root', 'all'}:
        raise ValueError('invalid_readme_scope')
    accounts = github_accounts(registry)
    upstream = None
    inherited_repositories = []
    inherited_raw = {}
    inherited_sources = b''
    if resume_from is not None:
        previous = Path(resume_from).resolve()
        manifest_bytes = (previous / 'manifest.json').read_bytes()
        upstream = {'path': str(previous), 'manifest_sha256': sha(manifest_bytes)}
        prior = json.loads(manifest_bytes)
        if prior.get('registry_sha256') != sha(Path(registry).read_bytes()):
            raise ValueError('resume_registry_mismatch')
        for relative, expected in prior['artifacts'].items():
            safe_source_path(relative)
            file = previous / relative
            if file.is_symlink() or not file.resolve().is_relative_to(previous):
                raise ValueError('unsafe_resume_artifact')
            body = file.read_bytes()
            if sha(body) != expected:
                raise ValueError('resume_artifact_hash_mismatch')
            if relative.startswith('raw/'):
                inherited_raw[relative] = body
        accounts = json.loads((previous / 'accounts.json').read_bytes())
        if not all(a.get('enumeration_complete') for a in accounts):
            raise ValueError('resume_requires_complete_account_listing')
        inherited_repositories = json.loads((previous / 'repositories.json').read_bytes())
        for repo in inherited_repositories:
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]+', repo['full_name']):
                raise ValueError('unsafe_resume_repository')
        inherited_sources = (previous / 'sources.jsonl').read_bytes() if (previous / 'sources.jsonl').exists() else b''
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / 'raw').mkdir()
    for relative, body in inherited_raw.items():
        (output / relative).write_bytes(body)
    if upstream:
        (output / 'upstream_sources.jsonl').write_bytes(inherited_sources)
    receipts, repositories = [], inherited_repositories
    completed_statuses = {'captured_inventory_and_readme', 'empty_repository'}
    if readme_scope == 'root':
        completed_statuses.add('captured_inventory_and_root_readme')
    reused_repositories = sum(r.get('status') in completed_statuses
                              for r in repositories) if upstream else 0
    stop_reason = None

    def save_body(body):
        digest = sha(body)
        path = output / 'raw' / (digest + '.bin')
        if not path.exists():
            path.write_bytes(body)
        return digest, path.relative_to(output).as_posix()

    def capture(url, kind):
        nonlocal stop_reason
        if stop_reason:
            raise RateLimitStop(stop_reason)
        if len(receipts) >= max_requests:
            stop_reason = 'request_budget_exceeded'
            raise RateLimitStop(stop_reason)
        receipt = {'url': url, 'kind': kind, 'collected_at': now(), 'collection_method': 'http',
                   'review_status': 'pending', 'available_at': None,
                   'training_eligibility': 'unresolved'}
        try:
            status, body, headers = fetch(url)
            digest, path = save_body(body)
            receipt.update(http_status=status, sha256=digest, raw_path=path, size_bytes=len(body))
            # Keep only rate/pagination headers. Never persist arbitrary credentials.
            safe_headers = {k.lower(): str(v) for k, v in headers.items()
                            if k.lower() in {'link', 'x-ratelimit-remaining', 'x-ratelimit-reset', 'retry-after'}}
            receipt['headers'] = safe_headers
            receipts.append(receipt)
            with (output / 'sources.jsonl').open('ab') as stream:
                stream.write(json_bytes(receipt).replace(b'\n', b' ') + b'\n')
            if status == 429 or (status == 403 and (
                    safe_headers.get('x-ratelimit-remaining') == '0'
                    or 'retry-after' in safe_headers or b'rate limit' in body.lower())):
                stop_reason = 'github_rate_limited'
                raise RateLimitStop(stop_reason)
            if safe_headers.get('x-ratelimit-remaining') == '0':
                # Current successful response remains usable; no later request is sent.
                stop_reason = 'github_rate_limit_exhausted'
            return status, body, safe_headers, receipt
        except RateLimitStop:
            raise
        except Exception as error:
            receipt.update(http_status=None, error=type(error).__name__)
            receipts.append(receipt)
            with (output / 'sources.jsonl').open('ab') as stream:
                stream.write(json_bytes(receipt).replace(b'\n', b' ') + b'\n')
            return None, b'', {}, receipt

    # Listing all seed accounts comes before detail collection to preserve coverage.
    for account in ([] if upstream else accounts):
        username = account['github_username']
        account.update(status='pending', enumeration_complete=False, repository_count=0)
        seen = set()
        try:
            for page in range(1, max_pages + 1):
                url = f'https://api.github.com/users/{username}/repos?per_page=100&page={page}&type=owner&sort=full_name'
                status, body, headers, source = capture(url, 'repository_listing')
                if status != 200:
                    account.update(status='listing_failed', http_status=status)
                    break
                data = json.loads(body)
                if not isinstance(data, list):
                    raise ValueError('repository_listing_not_list')
                for entry in data:
                    owner = entry.get('owner', {}).get('login', '')
                    name = entry.get('name', '')
                    if (entry.get('private') or owner.casefold() != username.casefold()
                            or not re.fullmatch(r'[A-Za-z0-9_.-]+', name)
                            or entry.get('full_name', '').casefold() != f'{owner}/{name}'.casefold()):
                        continue
                    if entry.get('id') in seen:
                        raise ValueError('duplicate_repository_listing')
                    seen.add(entry.get('id'))
                    repositories.append({**account, 'repository_id': entry['id'],
                        'full_name': entry['full_name'], 'default_branch': entry.get('default_branch'),
                        'fork': bool(entry.get('fork')), 'archived': bool(entry.get('archived')),
                        'status': 'not_collected', 'listing_source_sha256': source['sha256'],
                        'content_scope': 'repository_metadata_only', 'commit_sha': None,
                        'first_party_inventory': [], 'readme_files': [], 'code_files_read': 0,
                        'available_at': None, 'training_eligibility': 'unresolved'})
                account['repository_count'] = len(seen)
                if not re.search(r';\s*rel="next"', headers.get('link', '')):
                    account.update(status='listed', enumeration_complete=True)
                    break
            else:
                account['status'] = 'pagination_budget_exceeded'
        except RateLimitStop as error:
            account['status'] = str(error)
        except (ValueError, KeyError, TypeError) as error:
            account.update(status='listing_parse_error', error=type(error).__name__)

    for repo in repositories:
        repo['evidence_eligibility'] = ('excluded_fork_without_verified_contribution' if repo.get('fork')
                                        else 'pending_attribution_review')
        if upstream and repo['status'] in completed_statuses:
            continue
        if stop_reason:
            repo['status'] = stop_reason
            continue
        try:
            earlier_readmes = {f['path']: f for f in repo.get('readme_files', []) if f.get('http_status') == 200}
            repo['first_party_inventory'] = []
            repo['readme_files'] = []
            commit = repo.get('commit_sha')
            if not commit:
                commit, body = pin(repo['full_name'], repo['default_branch'])
                digest, path = save_body(body)
                repo.update(commit_sha=commit, head_receipt={'sha256': digest, 'raw_path': path,
                            'collected_at': now(), 'collection_method': 'git_ls_remote'})
            elif not re.fullmatch('[0-9a-f]{40}', commit):
                raise ValueError('invalid_resume_commit_sha')
            if not commit:
                repo['status'] = 'empty_repository'
                continue
            url = f'https://api.github.com/repos/{repo["full_name"]}/git/trees/{commit}?recursive=1'
            tree_hash = repo.get('tree_sha256')
            cached_tree = output / 'raw' / (str(tree_hash) + '.bin')
            if tree_hash and cached_tree.is_file():
                status, body, source = 200, cached_tree.read_bytes(), {'sha256': tree_hash}
            else:
                status, body, _, source = capture(url, 'repository_tree')
            if status != 200:
                repo.update(status='tree_failed', http_status=status)
                continue
            tree = json.loads(body)
            if not isinstance(tree.get('tree'), list):
                raise ValueError('invalid_repository_tree')
            repo.update(tree_sha256=source['sha256'], tree_truncated=bool(tree.get('truncated')))
            excluded = []
            for node in tree['tree']:
                if node.get('type') != 'blob':
                    continue
                file_path = safe_source_path(node['path'])
                item = {'path': file_path, 'sha': node.get('sha'), 'size': node.get('size')}
                if any(part.lower() in EXCLUDED for part in PurePosixPath(file_path).parts):
                    excluded.append(item)
                else:
                    repo['first_party_inventory'].append(item)
            repo['excluded_inventory'] = excluded
            # Inventory is first-party candidate paths, not verified authorship.
            # Only README content is fetched in this stage, never repo source code.
            for item in repo['first_party_inventory']:
                if not PurePosixPath(item['path']).name.lower().startswith('readme'):
                    continue
                if readme_scope == 'root' and len(PurePosixPath(item['path']).parts) != 1:
                    continue
                if item['path'] in earlier_readmes:
                    repo['readme_files'].append(earlier_readmes[item['path']])
                    continue
                if item.get('size', 0) > 512 * 1024:
                    repo['readme_files'].append({**item, 'status': 'size_bound'})
                    continue
                url = f'https://raw.githubusercontent.com/{repo["full_name"]}/{commit}/' + quote(item['path'], safe='/')
                status, _, _, source = capture(url, 'pinned_readme')
                repo['readme_files'].append({**item, 'http_status': status, 'sha256': source.get('sha256'),
                                            'raw_path': source.get('raw_path')})
            repo['content_scope'] = 'readme_and_tree_only'
            repo['readme_scope'] = readme_scope
            repo['status'] = ('tree_truncated' if tree.get('truncated') else 'captured_inventory_and_root_readme'
                              if readme_scope == 'root' else 'captured_inventory_and_readme')
        except RateLimitStop as error:
            repo['status'] = str(error)
        except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError) as error:
            repo.update(status='detail_failed', error=type(error).__name__)

    for name, rows in [('accounts', accounts), ('repositories', repositories)]:
        (output / (name + '.json')).write_bytes(json_bytes(rows))
    summary = {'schema_version': 'advisor-github-collection/1.0', 'collected_at': now(),
               'accounts': len(accounts), 'repositories': len(repositories), 'requests': len(receipts),
               'stop_reason': stop_reason, 'review_status': 'pending',
               'identity_status': 'seed_mapping_unverified', 'historical_training_eligible': False,
               'scope': 'Public owned repo listing, pinned tree inventory and README; no full code audit.',
               'account_statuses': {a['github_username']: a['status'] for a in accounts},
               'repository_statuses': {s: sum(r['status'] == s for r in repositories)
                                       for s in sorted({r['status'] for r in repositories})},
               'registry_sha256': sha(Path(registry).read_bytes()),
               'code_sha256': sha(Path(__file__).read_bytes())}
    summary['upstream'] = upstream
    summary['readme_scope'] = readme_scope
    summary['reused_repositories'] = reused_repositories
    summary['artifacts'] = {p.relative_to(output).as_posix(): sha(p.read_bytes())
                            for p in output.rglob('*') if p.is_file()}
    (output / 'manifest.json').write_bytes(json_bytes(summary))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--max-requests', type=int, default=100)
    parser.add_argument('--max-pages', type=int, default=20)
    parser.add_argument('--resume-from')
    parser.add_argument('--readme-scope', choices=['root', 'all'], default='root')
    args = parser.parse_args()
    print(json.dumps(harvest(args.registry, args.output, max_requests=args.max_requests,
                             max_pages=args.max_pages, resume_from=args.resume_from,
                             readme_scope=args.readme_scope), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
