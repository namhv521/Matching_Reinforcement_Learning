"""Supplement incomplete GitHub REST collection with public bare Git trees/root READMEs."""
import argparse
import json
from pathlib import Path

from collect_advisor_repositories import pin_head, sha
from read_advisor_repository_sources import collect_source_reading, write_json


def finish(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    manifest_bytes = (source / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    # Only read a verified upstream inventory; never edit the immutable API run.
    for relative, expected in manifest['artifacts'].items():
        path = (source / relative).resolve()
        if not path.is_relative_to(source) or path.is_symlink() or sha(path.read_bytes()) != expected:
            raise ValueError('upstream_artifact_hash_mismatch')
    repos = json.loads((source / 'repositories.json').read_bytes())
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for repo in repos:
        if repo['status'] in {'captured_inventory_and_readme', 'captured_inventory_and_root_readme', 'empty_repository'}:
            rows.append({'repository': repo['full_name'], 'status': repo['status'], 'source': 'upstream',
                         'commit_sha': repo.get('commit_sha')})
            continue
        name = repo['full_name']
        commit = repo.get('commit_sha')
        row = {'repository': name, 'source': 'git_supplement', 'previous_status': repo['status'],
               'evidence_eligibility': ('excluded_fork_without_verified_contribution' if repo.get('fork')
                                        else 'pending_attribution_review'), 'review_status': 'pending'}
        try:
            if not commit:
                commit, head = pin_head(name, repo['default_branch'])
                row['pin_method'] = 'new_git_ls_remote_default_branch'
                row['head_receipt_sha256'] = sha(head)
            else:
                row['pin_method'] = 'preserved_upstream_immutable_sha'
            row['commit_sha'] = commit
            if not commit:
                row['status'] = 'empty_repository'
            else:
                directory = name.replace('/', '_')
                result = collect_source_reading(name, commit, output / directory, root_readme_only=True)
                row.update(status=result.get('status', 'captured_inventory_and_root_readme'),
                           manifest_path=directory + '/manifest.json',
                           manifest_sha256=sha((output / directory / 'manifest.json').read_bytes()),
                           text_units=len(result.get('processed_units', [])),
                           missing_units=len(result.get('missing_units', [])),
                           bytes_read=result.get('bytes_read'))
                if row['missing_units']:
                    row['status'] = 'partial_root_readme'
        except Exception as error:
            row.update(status='git_collection_failed', error=type(error).__name__)
        rows.append(row)
        # Persist coherent progress at each repository, including failures.
        write_json(output / 'progress.json', rows)
    summary = {'upstream_path': str(source), 'upstream_manifest_sha256': sha(manifest_bytes),
               'repositories': rows, 'total_repositories': len(rows), 'review_status': 'pending',
               'scope': 'Supplemental whole tree and root README only; no full repository code audit',
               'status_counts': {s: sum(r['status'] == s for r in rows) for s in sorted({r['status'] for r in rows})}}
    write_json(output / 'manifest.json', summary)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = finish(args.source, args.output)
    print(json.dumps({k: v for k, v in result.items() if k != 'repositories'}, indent=2))
