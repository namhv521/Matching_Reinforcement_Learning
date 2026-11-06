"""Recover one actually observed browser PDF redirect and audit fallback truth."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.data_pipeline.advisor_paper_fulltext import bounded_public_fetch, sha, MAX_BYTES, IMPLEMENTATION_HASHES
from src.data_pipeline.pdf_extract import iter_pdf_blocks


def recover_redirect(metadata, queue_path, chrome_dir, output, *, fetcher=None):
    metadata, queue_path, chrome_dir, output = map(Path, (metadata, queue_path, chrome_dir, output))
    source = json.loads(metadata.read_text(encoding='utf-8'))
    queue = [json.loads(line) for line in queue_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    task = next((row for row in queue if row['source_url'] == source['requested_url']), None)
    if not task:
        raise ValueError('observed_redirect_not_in_queue')
    output.mkdir(parents=True, exist_ok=False)
    receipt = {'request_id': task['request_id'], 'source_url': source['requested_url'],
               'observed_redirect_metadata_sha256': sha(metadata.read_bytes()),
               'observed_redirect_url_sha256': sha(source['final_url'].encode()),
               'observed_redirect_host': urlsplit(source['final_url']).hostname,
               'collected_at': datetime.now(timezone.utc).isoformat(),
               'collection_method': 'http_from_observed_chrome_redirect',
               'publications': task['publications'], 'review_status': 'pending',
               'article_identity_review_status': 'pending',
               'available_at': None, 'training_eligibility': 'unresolved',
               'full_text_scope': 'downloaded_document_only_not_verified_article',
               'status': 'download_failed'}
    try:
        result = (fetcher or bounded_public_fetch)(source['final_url'])
        body = result['body']
        receipt['http_status'] = result['status']
        receipt['final_url_sha256'] = sha(result['final_url'].encode())
        receipt['final_host'] = urlsplit(result['final_url']).hostname
        if not isinstance(body, bytes) or len(body) > MAX_BYTES:
            raise ValueError('bounded_bytes_required')
        (output / 'raw').mkdir()
        raw_hash = sha(body)
        is_pdf = body.startswith(b'%PDF-')
        raw = output / 'raw' / (raw_hash + ('.pdf' if is_pdf else '.bin'))
        raw.write_bytes(body)
        receipt.update(sha256=raw_hash, size_bytes=len(body), raw_path=raw.relative_to(output).as_posix())
        if result['status'] != 200 or not is_pdf:
            receipt.update(status='needs_chrome', reason='http_or_pdf_signature_failed')
        else:
            records = list(iter_pdf_blocks(raw, {'source_id': raw_hash,
                                'source_file': str(raw), 'source_sha256': raw_hash}))
            extracted = output / 'extracted.jsonl'
            extracted.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in records), encoding='utf-8')
            outcomes = [row for row in records if row['kind'] == 'page_outcome']
            complete = bool(outcomes) and all(row['page'] is not None and row['status'] in {'extracted', 'blank'} for row in outcomes)
            receipt.update(status='pdf_extracted' if complete else 'pdf_partial',
                           page_count=len(outcomes), content_scope='full_text_complete' if complete else 'partial_full_text',
                           extracted_sha256=sha(extracted.read_bytes()))
    except Exception as error:
        # Signed redirect URLs must not be echoed in exception messages/logs.
        receipt.update(status='download_failed', error_class=type(error).__name__)
    rows = []
    for queued in queue:
        path = chrome_dir / (queued['request_id'] + '.json')
        row = {'request_id': queued['request_id'], 'source_url': queued['source_url'],
               'chrome_attempted': path.exists()}
        if not path.exists():
            row['status'] = 'unattempted'
        else:
            capture = json.loads(path.read_text(encoding='utf-8'))
            row['capture_sha256'] = sha(path.read_bytes())
            if 'Debugger unattached' in capture.get('error', ''):
                row['status'] = 'debugger_unattached'
            elif capture.get('error'):
                row['status'] = 'browser_navigation_error'
            elif capture.get('text', '').strip():
                row['status'] = 'browser_text_captured_needs_review'
            else:
                row['status'] = 'browser_capture_empty'
        if queued['request_id'] == task['request_id']:
            row['redirect_recovery_status'] = receipt['status']
        rows.append(row)
    (output / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'chrome_truth.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')
    report = {'queue_count': len(rows), 'status_counts': dict(Counter(row['status'] for row in rows)),
              'chrome_attempted_count': sum(row['chrome_attempted'] for row in rows),
              'recovered_status': receipt['status'], 'recovered_pages': receipt.get('page_count', 0),
              'historical_training_ready': False, 'all_papers_fulltext_complete': False,
              'implementation_hashes': IMPLEMENTATION_HASHES,
              'recovery_code_sha256': sha(Path(__file__).read_bytes())}
    report['output_hashes'] = {str(path.relative_to(output)): sha(path.read_bytes()) for path in output.rglob('*') if path.is_file()}
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('metadata', 'queue', 'chrome-dir', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    report = recover_redirect(args.metadata, args.queue, args.chrome_dir, args.output)
    print(json.dumps({key: value for key, value in report.items() if key not in {'implementation_hashes', 'output_hashes'}}))
