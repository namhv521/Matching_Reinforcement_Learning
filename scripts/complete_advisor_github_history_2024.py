"""Native public Git fallback for API-unresolved historical commits; no REST retries."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from datetime import datetime, timezone

from collect_advisor_github_history_2024 import CUTOFF, timestamp
from read_advisor_repository_sources import collect_source_reading, digest, write_json


def select_git_log(body):
    eligible = []
    for line in body.decode('utf-8').splitlines():
        fields = line.split('\t')
        if len(fields) != 3 or not re.fullmatch('[0-9a-f]{40}', fields[0]):
            raise ValueError('invalid_git_date_witness')
        sha, author, committer = fields
        if timestamp(author) < CUTOFF and timestamp(committer) < CUTOFF:
            eligible.append({'sha': sha, 'author_date': author, 'committer_date': committer})
    return max(eligible, key=lambda r: (timestamp(r['committer_date']), r['sha'])) if eligible else None


def historical_git_commit(repository, branch):
    if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]+', repository)
            or repository.split('/')[1] in {'.', '..'} or not isinstance(branch, str)
            or not branch or re.search(r'[\x00-\x20\x7f]', branch)):
        raise ValueError('invalid_public_git_ref')
    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GIT_ASKPASS': '', 'GIT_CONFIG_NOSYSTEM': '1',
           'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_COUNT': '0'}
    with tempfile.TemporaryDirectory(prefix='unimatch-history-date-') as temp:
        temp = Path(temp)
        hooks, bare = temp/'empty-hooks', temp/'history.git'
        hooks.mkdir()
        base = ['git', '-c', 'credential.helper=', '-c', 'core.hooksPath='+str(hooks),
                '-c', 'protocol.file.allow=never', '-c', 'submodule.recurse=false']
        def run(args, timeout=90):
            return subprocess.run(base+args, env=env, capture_output=True, check=True, timeout=timeout).stdout
        run(['init', '--bare', '--template='+str(hooks), str(bare)])
        run(['-C', str(bare), 'fetch', '--no-tags', '--no-recurse-submodules', '--filter=blob:none',
             'https://github.com/'+repository+'.git', 'refs/heads/'+branch])
        body = run(['-C', str(bare), 'log', '--format=%H%x09%aI%x09%cI', 'FETCH_HEAD'], timeout=30)
    return select_git_log(body), body


def complete(source_progress, output, *, stop_file=None):
    source_progress, output = Path(source_progress).resolve(), Path(output).resolve()
    snapshot = source_progress.read_bytes()
    rows = json.loads(snapshot)
    unresolved = [r for r in rows if r['status'] in {'github_rate_limit_exhausted', 'github_rate_limited',
                                                   'unresolved_commit', 'commit_lookup_failed'}]
    output.mkdir(parents=True, exist_ok=False)
    (output/'raw').mkdir()
    (output/'upstream_source_progress.json').write_bytes(snapshot)
    results = []
    for original in unresolved:
        row = dict(original)
        row.update(previous_status=row['status'], collection_method='public_bare_git', available_at=None,
                   historical_public_availability_verified=False)
        if stop_file and Path(stop_file).exists():
            row['status'] = 'deferred_checkpoint'
        else:
            try:
                selected, body = historical_git_commit(row['repository'], row['default_branch'])
                sha = digest(body)
                (output/'raw'/(sha+'.bin')).write_bytes(body)
                row.update(commit_log_sha256=sha, commit_log_raw_path='raw/'+sha+'.bin',
                           collected_at=datetime.now(timezone.utc).isoformat(), selected_commit=selected,
                           commit_scope='current_default_branch_reachable_history_only')
                if selected is None:
                    row['status'] = 'no_commit_before_2025'
                else:
                    directory = row['repository'].replace('/', '_')
                    reading = collect_source_reading(row['repository'], selected['sha'], output/directory,
                                                      root_readme_only=True)
                    row.update(status='historical_source_failed' if reading.get('status') == 'source_reading_failed' else 'historical_source_captured',
                        source_manifest_path=directory+'/manifest.json',
                        source_manifest_sha256=digest((output/directory/'manifest.json').read_bytes()),
                        processed_units=len(reading.get('processed_units', [])), missing_units=len(reading.get('missing_units', [])))
            except Exception as error:
                row.update(status='unresolved_native_git', error=type(error).__name__)
        results.append(row)
        write_json(output/'progress.json', results)
        print(json.dumps({'repository':row['repository'],'status':row['status']}), flush=True)
    manifest = {'cutoff_exclusive': CUTOFF.isoformat(), 'source_progress_path':str(source_progress),
                'source_progress_snapshot_sha256':digest(snapshot), 'repositories':results,
                'historical_public_availability_verified':False,
                'status_counts':{s:sum(r['status']==s for r in results) for s in sorted({r['status'] for r in results})}}
    write_json(output/'manifest.json', manifest)
    return manifest


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-progress', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--stop-file')
    args=parser.parse_args()
    complete(args.source_progress,args.output,stop_file=args.stop_file)
