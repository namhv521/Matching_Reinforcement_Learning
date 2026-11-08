"""Batch pinned first-party source reading with pending, conservative skill claims."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from read_advisor_repository_sources import collect_source_reading, write_json, digest
from src.data_pipeline.advisor_skill_extraction import extract_skill_claims
from src.data_pipeline.normalization import load_taxonomy, taxonomy_ids


IMPORT_SKILLS = {'torch': 'pytorch', 'tensorflow': 'tensorflow', 'sklearn': 'scikit_learn',
                 'fastapi': 'fastapi', 'django': 'django', 'pyspark': 'spark',
                 'airflow': 'airflow', 'redis': 'redis', 'pymongo': 'mongodb'}


def code_claims(unit, *, artifact_id, advisor_id, taxonomy):
    """Imports are not scored; framework call syntax is implementation evidence pending review."""
    if not unit['unit_id'].lower().endswith('.py'):
        return []
    text = unit['text']
    try:
        tree = ast.parse(text)
    except (ValueError, SyntaxError, RecursionError):
        return []
    valid = taxonomy_ids(taxonomy)
    aliases, imports = {}, {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                root = name.name.split('.')[0]
                skill = IMPORT_SKILLS.get(root)
                if skill in valid:
                    aliases[name.asname or root] = skill
                    imports[skill] = node
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            root = (node.module or '').split('.')[0]
            skill = IMPORT_SKILLS.get(root)
            if skill in valid:
                for name in node.names:
                    if name.name != '*':
                        aliases[name.asname or name.name] = skill
                imports[skill] = node
    usages = {}
    rebound = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}
    rebound.update(node.arg for node in ast.walk(tree) if isinstance(node, ast.arg))
    rebound.update(node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        while isinstance(target, ast.Attribute):
            target = target.value
        if isinstance(target, ast.Name) and target.id in aliases and target.id not in rebound:
            usages.setdefault(aliases[target.id], node)
    claims = []
    for skill, node in imports.items():
        used = skill in usages
        node = usages.get(skill, node)
        quote = ast.get_source_segment(text, node)
        if not quote:
            continue
        claim = {'advisor_id': advisor_id, 'artifact_id': artifact_id, 'skill_id': skill,
                 'channel': 'evidence', 'score': 80 if used else None,
                 'usage_status': 'used' if used else 'unknown', 'review_status': 'pending',
                 'evidence_status': 'extracted_from_full_text',
                 'evidence_class': 'framework_call_syntax' if used else 'code_import_only',
                 'level': 'Implemented' if used else 'Mention', 'quote': quote,
                 'locator': {'unit_id': unit['unit_id'], 'line': node.lineno, 'end_line': node.end_lineno},
                 'raw_sha256': unit['sha256'], 'content_completeness': 'complete',
                 'contribution_status': 'unverified', 'inference_version': 'python-call-rules/1.0'}
        claim['evidence_id'] = digest(json.dumps(claim, sort_keys=True, ensure_ascii=False).encode())
        claims.append(claim)
    return claims


def merge_claims(claims):
    merged = {}
    for claim in claims:
        claim = dict(claim)
        key = (claim['artifact_id'], claim['skill_id'], claim['channel'])
        old = merged.get(key)
        if old is None:
            claim['evidence_refs'] = [claim['evidence_id']]
            merged[key] = claim
        else:
            refs = list(dict.fromkeys(old['evidence_refs'] + [claim['evidence_id']]))
            if (claim.get('score') or 0) > (old.get('score') or 0):
                merged[key] = claim
            merged[key]['evidence_refs'] = refs
    return list(merged.values())


def verified_manifest(path):
    body = path.read_bytes()
    value = json.loads(body)
    for relative, expected in value.get('artifacts', {}).items():
        child = (path.parent / relative).resolve()
        if not child.is_relative_to(path.parent.resolve()) or child.is_symlink() or digest(child.read_bytes()) != expected:
            raise ValueError('upstream_hash_mismatch')
    return value, digest(body)


def extract_job(job):
    """Isolated CPU stage: caller enforces wall-clock timeout and preserves source."""
    path = Path(job['source_path'])
    reading, reading_hash = verified_manifest(path / 'manifest.json')
    if reading_hash != job['source_manifest_sha256']:
        raise ValueError('extract_job_source_mismatch')
    units = [json.loads(line) for line in (path / 'text_units.jsonl').read_text(encoding='utf-8').splitlines()]
    blanks = [u['unit_id'] for u in units if not u['text'].strip()]
    units = [u for u in units if u['text'].strip()]
    expected = [u['unit_id'] for u in units] + [n['path'] for n in reading.get('missing_units', [])]
    taxonomy = load_taxonomy()
    extracted = extract_skill_claims(units, content_scope='partial_full_text',
        artifact_id=job['artifact_id'], advisor_id=job['advisor_id'], taxonomy=taxonomy, expected_units=expected)
    claims = extracted['claims']
    for unit in units:
        claims.extend(code_claims(unit, artifact_id=job['artifact_id'], advisor_id=job['advisor_id'], taxonomy=taxonomy))
    for claim in claims:
        claim.update(source_manifest_path=str(path / 'manifest.json'), source_manifest_sha256=reading_hash,
                     training_eligibility='unresolved', available_at=None, identity_review_status='pending',
                     content_completeness='partial', candidate_text_scope=reading.get('content_scope'))
    claims = merge_claims(claims)
    claims_path = Path(job['claims_path'])
    claims_path.write_text(''.join(json.dumps(c, ensure_ascii=False, sort_keys=True) + '\n' for c in claims), encoding='utf-8')
    write_json(Path(job['result_path']), {'claims': len(claims), 'claims_sha256': digest(claims_path.read_bytes()),
               'blank_units': list(dict.fromkeys(reading.get('blank_units', []) + blanks))})


def batch(source, supplement, output, *, pilot_root=None, stop_file=None, resume_from=None):
    source, supplement, output = Path(source).resolve(), Path(supplement).resolve(), Path(output).resolve()
    source_manifest, source_hash = verified_manifest(source / 'manifest.json')
    supplement_manifest = json.loads((supplement / 'manifest.json').read_bytes())
    if supplement_manifest['upstream_manifest_sha256'] != source_hash:
        raise ValueError('supplement_upstream_mismatch')
    updates = {r['repository']: r for r in supplement_manifest['repositories']}
    repos = json.loads((source / 'repositories.json').read_bytes())
    output.mkdir(parents=True, exist_ok=False)
    previous = {}
    previous_hash = None
    if resume_from:
        previous_manifest, previous_hash = verified_manifest(Path(resume_from).resolve() / 'manifest.json')
        previous = {r['repository']: r for r in previous_manifest.get('repositories', [])}
    taxonomy = load_taxonomy()
    results = []
    for repo in repos:
        name = repo['full_name']
        update = updates[name]
        row = {'repository': name, 'advisor_id': repo['advisor_id'], 'review_status': 'pending'}
        if repo.get('fork') or update['status'] == 'empty_repository':
            row['status'] = 'excluded_fork' if repo.get('fork') else 'empty_repository'
        elif stop_file and Path(stop_file).exists():
            row['status'] = 'stopped_before_collection'
        elif previous.get(name, {}).get('status') == 'read_pending_review':
            old = previous[name]
            reading, reading_hash = verified_manifest(Path(old['source_manifest_path']))
            if reading_hash != old['source_manifest_sha256'] or old.get('commit_sha') != (update.get('commit_sha') or repo.get('commit_sha')):
                raise ValueError('resume_source_or_pin_mismatch')
            old_claims = Path(resume_from).resolve() / old['claims_path']
            if digest(old_claims.read_bytes()) != old['claims_sha256']:
                raise ValueError('resume_claims_hash_mismatch')
            row = {**old, 'claims_path': str(old_claims), 'reused_previous_batch': True}
        else:
            commit = update.get('commit_sha') or repo.get('commit_sha')
            row['commit_sha'] = commit
            write_json(output / 'running.json', row)
            print(json.dumps({'running': name, 'commit_sha': commit}), flush=True)
            directory = name.replace('/', '_')
            path = output / directory
            pilot = Path(pilot_root) / directory if pilot_root else None
            cached = previous.get(name, {})
            if cached.get('source_manifest_path') and cached.get('status') in {'source_read_pending_extraction', 'extraction_timeout'}:
                cached_path = Path(cached['source_manifest_path'])
                if digest(cached_path.read_bytes()) != cached['source_manifest_sha256']:
                    raise ValueError('cached_source_hash_mismatch')
                pilot = cached_path.parent
            try:
                if pilot and (pilot / 'manifest.json').is_file():
                    reading, reading_hash = verified_manifest(pilot / 'manifest.json')
                    if reading.get('commit_sha') != commit or reading.get('collection_scope') == 'root_readme_and_tree_only':
                        raise ValueError('pilot_reference_or_scope_mismatch')
                    path = pilot
                    row['reused_pilot'] = True
                else:
                    sizes = {n['path']: n.get('size') for n in repo.get('first_party_inventory', [])}
                    reading = collect_source_reading(name, commit, path, inventory_sizes=sizes)
                    reading_hash = digest((path / 'manifest.json').read_bytes())
                row.update(source_manifest_path=str(path / 'manifest.json'), source_manifest_sha256=reading_hash,
                           processed_units=len(reading.get('processed_units', [])),
                           missing_units=len(reading.get('missing_units', [])), bytes_read=reading.get('bytes_read'))
                if reading.get('status') == 'source_reading_failed':
                    row['status'] = reading['status']
                else:
                    artifact = 'github:' + name + '@' + commit
                    claims_path = output / (directory + '_claims.jsonl')
                    job_path, result_path = output / (directory + '_extract_job.json'), output / (directory + '_extract_result.json')
                    write_json(job_path, {'source_path': str(path.resolve()), 'source_manifest_sha256': reading_hash,
                        'artifact_id': artifact, 'advisor_id': repo['advisor_id'],
                        'claims_path': str(claims_path), 'result_path': str(result_path)})
                    row.update(extraction_job_path=job_path.name, claims_complete=False)
                    try:
                        subprocess.run([sys.executable, str(Path(__file__).resolve()), '--extract-job', str(job_path)],
                            timeout=60, check=True, capture_output=True)
                    except subprocess.TimeoutExpired:
                        row['status'] = 'extraction_timeout'
                    else:
                        result = json.loads(result_path.read_bytes())
                        row.update(status='read_pending_review', claims_complete=True,
                            claims=result['claims'], claims_path=claims_path.name,
                            claims_sha256=result['claims_sha256'], blank_units=result['blank_units'])
            except Exception as error:
                row.update(status='batch_failed', error=type(error).__name__)
        results.append(row)
        write_json(output / 'progress.json', results)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    summary = {'repositories': results, 'upstream_manifest_sha256': source_hash,
               'supplement_manifest_sha256': digest((supplement / 'manifest.json').read_bytes()),
               'review_status': 'pending', 'whole_repository_audit': False,
               'previous_batch_manifest_sha256': previous_hash,
               'status_counts': {s: sum(r['status'] == s for r in results) for s in sorted({r['status'] for r in results})}}
    write_json(output / 'manifest.json', summary)
    return summary


if __name__ == '__main__':
    if sys.argv[1:2] == ['--extract-job']:
        extract_job(json.loads(Path(sys.argv[2]).read_bytes()))
        raise SystemExit(0)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--supplement', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--pilot-root')
    parser.add_argument('--stop-file')
    parser.add_argument('--resume-from')
    args = parser.parse_args()
    batch(args.source, args.supplement, args.output, pilot_root=args.pilot_root, stop_file=args.stop_file,
          resume_from=args.resume_from)
