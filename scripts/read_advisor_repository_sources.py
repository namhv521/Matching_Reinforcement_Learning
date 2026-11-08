"""Read complete bounded text blobs at immutable public GitHub commits, without checkout."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone


TEXT_SUFFIXES = {'.py', '.js', '.ts', '.tsx', '.jsx', '.java', '.c', '.cpp', '.h', '.sql',
                 '.yaml', '.yml', '.json', '.toml', '.ini', '.cfg', '.md', '.txt', '.ipynb',
                 '.rs', '.go', '.sh', '.ps1', '.css', '.html', '.r', '.rmd', '.vue', '.svelte',
                 '.xml', '.properties', '.gradle', '.kt', '.swift', '.scala'}
EXCLUDE_DIRS = {'vendor', 'vendors', 'node_modules', 'third_party', 'third-party', 'venv', '.venv',
                '.git', 'dist', 'build', '.next', '__pycache__', 'generated'}


def digest(body):
    return hashlib.sha256(body).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True,
                                    allow_nan=False), encoding='utf-8')


def path_exclusion(path, mode):
    parts = PurePosixPath(path).parts
    name = parts[-1].lower()
    if mode != '100644' and mode != '100755':
        return 'symlink_or_submodule_not_followed'
    if any(p.lower() in EXCLUDE_DIRS for p in parts):
        return 'vendor_or_generated_directory'
    if name.endswith(('.min.js', '.map', '.lock')) or name in {'package-lock.json', 'yarn.lock'}:
        return 'generated_file'
    if name in {'.env', 'credentials.json', 'id_rsa'} or name.endswith(('.pem', '.key', '.p12')):
        return 'credential_filename_not_read'
    if PurePosixPath(name).suffix not in TEXT_SUFFIXES and name not in {'dockerfile', 'makefile', 'readme'}:
        return 'not_candidate_text'
    return None


def read_tree(tree, read_blob, output, *, max_file_bytes=512*1024, max_repo_bytes=20*1024*1024,
              max_files=500, root_readme_only=False):
    """Read whole candidate blobs, never prefixes; expose every skip in the manifest."""
    if min(max_file_bytes, max_repo_bytes, max_files) < 1:
        raise ValueError('positive_reading_bounds_required')
    output = Path(output)
    (output / 'raw').mkdir(parents=True, exist_ok=False)
    units, skipped, missing, total = [], [], [], 0
    seen = {}
    units_file = output / 'text_units.jsonl'
    units_file.touch(exist_ok=False)
    for node in tree:
        path, size = node['path'], node['size']
        if root_readme_only and (len(PurePosixPath(path).parts) != 1
                                 or not PurePosixPath(path).name.lower().startswith('readme')):
            skipped.append({**node, 'reason': 'outside_root_readme_collection_scope'})
            continue
        excluded = path_exclusion(path, node['mode'])
        if excluded:
            skipped.append({**node, 'reason': excluded})
            continue
        if size > max_file_bytes or total + size > max_repo_bytes or len(units) >= max_files:
            missing.append({**node, 'reason': 'file_or_repo_budget_exceeded'})
            continue
        try:
            body = seen.get(node['oid'])
            if body is None:
                body = read_blob(node['oid'])
                seen[node['oid']] = body
            if len(body) != size:
                raise ValueError('blob_size_mismatch')
            if b'\0' in body:
                skipped.append({**node, 'reason': 'binary_content'})
                continue
            text = body.decode('utf-8-sig')
            if not text.strip():
                skipped.append({**node, 'reason': 'blank_unit'})
                continue
            sha = digest(body)
            raw = output / 'raw' / (sha + '.bin')
            if not raw.exists():
                raw.write_bytes(body)
            units.append({**node, 'unit_id': path, 'text': text, 'sha256': sha,
                          'raw_path': raw.relative_to(output).as_posix(), 'read_status': 'whole_blob_read'})
            with units_file.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(units[-1], ensure_ascii=False, sort_keys=True) + '\n')
            total += len(body)
        except (UnicodeDecodeError, ValueError, subprocess.SubprocessError) as error:
            missing.append({**node, 'reason': type(error).__name__})
        write_json(output / 'reading_progress.json', {'last_unit': path,
                   'processed_units': len(units), 'missing_units': len(missing),
                   'skipped_units': len(skipped), 'bytes_read': total})
    # Text-bearing notebooks stay whole JSON; later extraction may inspect all cells.
    result = {'processed_units': [{k: v for k, v in u.items() if k != 'text'} for u in units],
              'skipped_units': skipped, 'missing_units': missing, 'bytes_read': total,
              'blank_units': [n['path'] for n in skipped if n['reason'] == 'blank_unit'],
              'content_scope': 'partial_full_text' if missing else 'candidate_text_complete',
              'whole_repository_audit': False, 'review_status': 'pending',
              'collection_scope': 'root_readme_and_tree_only' if root_readme_only else 'candidate_text',
              'exclusion_policy': 'candidate text only; no vendor/generated/binary/submodule/credential files',
              'bounds': {'max_file_bytes': max_file_bytes, 'max_repo_bytes': max_repo_bytes,
                         'max_files': max_files}}
    write_json(output / 'reading.json', result)
    return result


def collect_source_reading(full_name, commit_sha, output, *, max_file_bytes=512*1024,
                           max_repo_bytes=20*1024*1024, max_files=500, root_readme_only=False,
                           inventory_sizes=None):
    if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]+', full_name)
            or full_name.split('/')[1] in {'.', '..'}
            or not re.fullmatch(r'[0-9a-f]{40}', commit_sha)):
        raise ValueError('immutable_public_github_reference_required')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc).isoformat()
    deadline = time.monotonic() + 120
    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GIT_ASKPASS': '',
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
           'GIT_CONFIG_COUNT': '0'}
    with tempfile.TemporaryDirectory(prefix='unimatch-git-source-') as temp:
        temp = Path(temp)
        hooks, bare = temp / 'empty-hooks', temp / 'objects.git'
        hooks.mkdir()
        base = ['git', '-c', 'credential.helper=', '-c', 'core.hooksPath=' + str(hooks),
                '-c', 'protocol.file.allow=never', '-c', 'submodule.recurse=false']
        def run(args, timeout=90):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired('repository_reading_deadline', 120)
            return subprocess.run(base + args, capture_output=True, check=True, timeout=min(timeout, remaining),
                                  env=env).stdout
        try:
            run(['init', '--bare', '--template=' + str(hooks), str(bare)])
            fetch_receipt = run(['-C', str(bare), 'fetch', '--no-tags', '--depth=1',
                                 '--filter=blob:limit=524288', '--no-recurse-submodules', 'https://github.com/' + full_name + '.git',
                                 commit_sha], timeout=90)
            resolved = run(['-C', str(bare), 'rev-parse', 'FETCH_HEAD']).decode().strip()
            if resolved != commit_sha:
                raise ValueError('fetched_commit_mismatch')
            tree_bytes = run(['-C', str(bare), 'ls-tree', '-r', '-z', commit_sha])
            tree = []
            for entry in tree_bytes.split(b'\0'):
                if not entry:
                    continue
                metadata, raw_path = entry.split(b'\t', 1)
                fields = metadata.decode('ascii').split()
                mode, kind, oid = fields[:3]
                path = raw_path.decode('utf-8')
                known_size = (inventory_sizes or {}).get(path)
                is_candidate = kind == 'blob' and path_exclusion(path, mode) is None
                if root_readme_only:
                    is_candidate = is_candidate and len(PurePosixPath(path).parts) == 1 and PurePosixPath(path).name.lower().startswith('readme')
                size = known_size if isinstance(known_size, int) and known_size >= 0 else 0
                if is_candidate and known_size is None:
                    size = int(run(['-C', str(bare), 'cat-file', '-s', oid]).strip())
                tree.append({'path': path, 'mode': mode, 'kind': kind,
                             'oid': oid, 'size': size, 'size_known': known_size is not None or is_candidate})
            (output / 'tree.bin').write_bytes(tree_bytes)
            (output / 'fetch_stdout.bin').write_bytes(fetch_receipt)
            result = read_tree(tree, lambda oid: run(['-C', str(bare), 'cat-file', 'blob', oid]),
                               output, max_file_bytes=max_file_bytes,
                               max_repo_bytes=max_repo_bytes, max_files=max_files,
                               root_readme_only=root_readme_only)
            result.update(repository=full_name, commit_sha=commit_sha,
                          collected_at=started, collection_method='bare_git_no_checkout',
                          available_at=None, training_eligibility='unresolved',
                          identity_status='pending')
        except (ValueError, OSError, UnicodeError, subprocess.SubprocessError) as error:
            result = {'repository': full_name, 'commit_sha': commit_sha, 'collected_at': started,
                      'status': 'source_reading_failed', 'error': type(error).__name__,
                      'content_scope': 'partial_full_text', 'whole_repository_audit': False,
                      'review_status': 'pending'}
    result['artifacts'] = {p.relative_to(output).as_posix(): digest(p.read_bytes())
                            for p in output.rglob('*') if p.is_file()}
    write_json(output / 'manifest.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--max-files', type=int, default=500)
    parser.add_argument('--max-file-bytes', type=int, default=512*1024)
    parser.add_argument('--max-repo-bytes', type=int, default=20*1024*1024)
    parser.add_argument('--root-readme-only', action='store_true')
    args = parser.parse_args()
    result = collect_source_reading(args.repository, args.commit, args.output,
        max_files=args.max_files, max_file_bytes=args.max_file_bytes, max_repo_bytes=args.max_repo_bytes,
        root_readme_only=args.root_readme_only)
    print(json.dumps({k: v for k, v in result.items()
                     if k not in {'processed_units', 'skipped_units', 'missing_units', 'artifacts'}}, indent=2))
