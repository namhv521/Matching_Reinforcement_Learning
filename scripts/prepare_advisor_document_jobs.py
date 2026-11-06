"""Build pending evidence jobs for actual downloaded PDF documents, not title matches."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8-sig').splitlines() if line.strip()]


def source_file(root, relative, expected_hash):
    if not isinstance(relative, str) or not relative or not isinstance(expected_hash, str):
        raise ValueError('artifact_path_and_hash_required')
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file() or digest(path) != expected_hash:
        raise ValueError('artifact_path_or_hash_mismatch')
    return path


def text_inventory(records, page_count):
    if isinstance(page_count, bool) or not isinstance(page_count, int) or page_count < 1:
        raise ValueError('positive_page_count_required')
    outcomes, blocks = {}, defaultdict(list)
    document_failure = False
    for record in records:
        page = record.get('page')
        if page is None and record.get('kind') == 'page_outcome':
            document_failure = True
            continue
        if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= page_count:
            raise ValueError('record_page_outside_inventory')
        if record.get('kind') == 'page_outcome':
            if page in outcomes:
                raise ValueError('duplicate_page_outcome')
            outcomes[page] = record
        elif record.get('kind') == 'block':
            if not isinstance(record.get('text'), str):
                raise ValueError('block_text_required')
            blocks[page].append(record['text'])
    expected = [f'page:{page}' for page in range(1, page_count + 1)]
    units = []
    unresolved = []
    for page in range(1, page_count + 1):
        outcome = outcomes.get(page, {})
        status = outcome.get('status', 'missing_outcome')
        text = '\n'.join(blocks[page]) if status == 'extracted' and not document_failure else ''
        # Blank pages stay empty; downstream completeness is conservative.
        if not text.strip():
            unresolved.append({'unit_id': f'page:{page}', 'status': status,
                               'reason': outcome.get('reason', 'document_failure' if document_failure else '')})
        units.append({'unit_id': f'page:{page}', 'text': text})
    complete = not unresolved and not document_failure
    return units, expected, complete, unresolved


def prepare(collection, output):
    root, output = Path(collection).resolve(), Path(output).resolve()
    downloads = root / 'downloads.jsonl'
    if not downloads.is_file():
        raise ValueError('completed_downloads_manifest_required')
    if output == root or output.is_relative_to(root):
        raise ValueError('output_must_be_outside_collection')
    jobs, unresolved, source_hashes, seen = [], [], {str(downloads): digest(downloads)}, set()
    for receipt in read_rows(downloads):
        if receipt.get('status') not in {'pdf_extracted', 'pdf_partial'}:
            unresolved.append({'request_id': receipt.get('request_id'), 'reason': 'document_not_extracted',
                               'download_status': receipt.get('status'), 'source_url': receipt.get('url')})
            continue
        raw = source_file(root, receipt.get('raw_path'), receipt.get('sha256'))
        extracted = source_file(root, receipt.get('extraction_path'), receipt.get('extracted_sha256'))
        source_hashes.update({str(raw): digest(raw), str(extracted): digest(extracted)})
        records = read_rows(extracted)
        if any(r.get('source_sha256') != receipt['sha256'] for r in records):
            raise ValueError('extracted_records_source_hash_mismatch')
        units, expected, complete, unread = text_inventory(records, receipt.get('page_count'))
        associations = receipt.get('publications', [])
        if not associations:
            unresolved.append({'request_id': receipt.get('request_id'), 'reason': 'no_publication_association',
                               'document_sha256': receipt['sha256'], 'source_url': receipt.get('url')})
        for association in associations:
            advisor = association.get('advisor_id')
            if not isinstance(advisor, str) or not advisor.strip():
                raise ValueError('association_advisor_id_required')
            key = (advisor, receipt['sha256'], association.get('artifact_id'))
            if key in seen:
                continue
            seen.add(key)
            jobs.append({
                'artifact_id': 'document_' + receipt['sha256'], 'advisor_id': advisor,
                'candidate_publication_artifact_id': association.get('artifact_id'),
                'candidate_publication_title': association.get('title'),
                'candidate_publication': dict(association),
                'document_sha256': receipt['sha256'],
                'downloaded_document_matches_article': None,
                'article_person_link_status': 'pending', 'identity_review_status': 'pending',
                'review_status': 'pending', 'available_at': None, 'split': None,
                'training_eligibility': 'unresolved',
                'content_scope': 'full_text_complete' if complete else 'partial_full_text',
                'text_units': units, 'expected_units': expected, 'unread_units': unread,
                'full_text_scope': 'downloaded_document_only_not_verified_article',
                'source_url': receipt.get('final_url', receipt.get('url')),
                'raw_path': str(raw), 'raw_sha256': receipt['sha256'],
                'extraction_path': str(extracted), 'extraction_sha256': receipt['extracted_sha256'],
                'collection_method': receipt.get('collection_method'),
            })
    output.mkdir(parents=True, exist_ok=False)
    for name, rows in (('document_jobs.jsonl', jobs), ('unresolved.jsonl', unresolved)):
        (output / name).write_text(''.join(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n'
                                         for row in rows), encoding='utf-8')
    report = {'jobs': len(jobs), 'unique_documents': len({j['raw_sha256'] for j in jobs}),
              'content_scope_counts': dict(Counter(j['content_scope'] for j in jobs)),
              'unresolved': len(unresolved), 'identity_approvals_granted': 0,
              'historical_training_ready': False, 'manual_fulltext_review_complete': False}
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    manifest = {'schema_version': 'advisor-document-jobs/1',
                'created_at': datetime.now(timezone.utc).isoformat(),
                'bridge_code_sha256': digest(__file__), 'input_hashes': source_hashes,
                'output_hashes': {p.name: digest(p) for p in output.iterdir() if p.is_file()}}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collection', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(prepare(args.collection, args.output)))


if __name__ == '__main__':
    main()
