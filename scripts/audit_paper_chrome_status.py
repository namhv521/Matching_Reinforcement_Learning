"""Classify browser records without equating local errors with source visits."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re


def classify(capture):
    error = capture.get('error', '')
    if re.search(r'\b(?:ReferenceError|SyntaxError|TypeError)\b', error):
        return 'orchestration_not_attempted', False
    if 'Debugger unattached' in error:
        return 'transport_unavailable_not_attempted', False
    if error:
        return 'navigation_error_source_visit_unconfirmed', True
    text = capture.get('text', '').strip()
    if not text:
        return 'browser_capture_empty', True
    if re.search(r'captcha|verify you are human|access denied|xác minh bảo mật|checking your browser', text, re.I):
        return 'browser_access_challenge', True
    if re.search(r'\b(?:Error 404|404 Not Found|ERR_[A-Z_]+)\b', text):
        return 'browser_error_page', True
    return 'browser_text_needs_review', True


def audit(queue_path, chrome_dir, output):
    queue_path, chrome_dir, output = map(Path, (queue_path, chrome_dir, output))
    queue = [json.loads(line) for line in queue_path.read_text(encoding='utf-8').splitlines() if line.strip()]
    rows = []
    for task in queue:
        path = chrome_dir / (task['request_id'] + '.json')
        row = {'request_id': task['request_id'], 'source_url': task['source_url'],
               'source_record_exists': path.exists(), 'source_navigation_attempted': False,
               'status': 'unattempted', 'review_status': 'pending', 'full_text_verified': False}
        if path.exists():
            raw = path.read_bytes()
            capture = json.loads(raw)
            row['status'], row['source_navigation_attempted'] = classify(capture)
            row.update(capture_sha256=hashlib.sha256(raw).hexdigest(),
                       capture_path=str(path.resolve()), captured_text_length=len(capture.get('text', '')))
        rows.append(row)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'status.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')
    counts = dict(Counter(row['status'] for row in rows))
    report = {'created_at': datetime.now(timezone.utc).isoformat(), 'queue_count': len(rows),
              'source_records': sum(row['source_record_exists'] for row in rows),
              'source_navigation_attempted': sum(row['source_navigation_attempted'] for row in rows),
              'status_counts': counts, 'all_sources_visited': False,
              'historical_training_ready': False,
              'queue_sha256': hashlib.sha256(queue_path.read_bytes()).hexdigest(),
              'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'status_sha256': hashlib.sha256((output / 'status.jsonl').read_bytes()).hexdigest()}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('queue', 'chrome-dir', 'output'):
        parser.add_argument('--' + arg, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.queue, args.chrome_dir, args.output)))
