"""Index real browser-captured publication links and prepare pending title jobs."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit


def digest(data):
    return hashlib.sha256(data).hexdigest()


def identity(url):
    value = urlsplit(url)
    query = parse_qs(value.query)
    if value.hostname in {'scholar.google.com', 'scholar.google.com.vn'}:
        return ('scholar', query.get('user', [''])[0])
    return ((value.hostname or '').removeprefix('www.'), value.path.rstrip('/'))


def publication_url(url):
    value = urlsplit(url)
    if value.scheme not in {'http', 'https'} or value.username or value.password:
        return None
    query = parse_qs(value.query)
    if value.hostname in {'scholar.google.com', 'scholar.google.com.vn'}:
        citation = query.get('citation_for_view', [''])[0]
        if query.get('view_op') == ['view_citation'] and re.fullmatch(r'[A-Za-z0-9_-]+:[A-Za-z0-9_-]+', citation):
            return 'https://scholar.google.com/citations?' + urlencode({'view_op': 'view_citation', 'citation_for_view': citation})
    if value.hostname in {'researchgate.net', 'www.researchgate.net'} and re.fullmatch(r'/publication/\d+(?:_[^/]+)?/?', value.path):
        return 'https://www.researchgate.net' + value.path.rstrip('/')
    if value.hostname in {'doi.org', 'dx.doi.org'} or value.path.lower().endswith('.pdf'):
        return urlunsplit((value.scheme, value.netloc, value.path, value.query, ''))
    return None


def prepare(captures, registry, queue, output):
    captures, registry, queue, output = map(Path, (captures, registry, queue, output))
    with registry.open(encoding='utf-8-sig', newline='') as stream:
        advisors = list(csv.DictReader(stream))
    owners = {}
    for row in advisors:
        for field in ('scholar_url', 'researchgate_url', 'github_url', 'university_url'):
            if row.get(field):
                owners.setdefault(identity(row[field]), []).append(row['advisor_id'])
    hashes, records, covered, rejected = [], {}, set(), []
    for path in sorted(captures.glob('*.json')):
        raw = path.read_bytes()
        capture = json.loads(raw)
        if not isinstance(capture, dict):
            hashes.append({'path': str(path.resolve()), 'sha256': digest(raw),
                           'capture_type': 'auxiliary_non_capture'})
            rejected.append({'path': str(path), 'reason': 'not_capture_object'})
            continue
        source_url = capture.get('url', '')
        source_identity = identity(source_url)
        hashes.append({'path': str(path.resolve()), 'sha256': digest(raw),
                       'source_url': source_url, 'collected_at': capture.get('collected_at'),
                       'pagination_complete': capture.get('pagination_complete', False)})
        matched = owners.get(source_identity, [])
        if len(matched) != 1:
            rejected.append({'path': str(path), 'reason': 'missing_or_ambiguous_registry_link'})
            continue
        advisor = matched[0]
        covered.add((advisor, source_identity))
        for link in capture.get('links', []):
            url = publication_url(link.get('url', ''))
            title = ' '.join(link.get('text', '').split())
            if not url or len(title) < 8 or title.casefold() in {'view article', 'view publication', 'download pdf', 'full text', 'view full-text'}:
                continue
            normalized = unicodedata.normalize('NFC', title).casefold()
            key = (advisor, normalized)
            row = records.setdefault(key, {'advisor_id': advisor, 'title': title,
                'artifact_id': 'title_' + digest((advisor + '\n' + normalized).encode()),
                'detail_urls': [], 'provenance': [], 'review_status': 'pending',
                'available_at': None, 'training_eligibility': 'unresolved',
                'content_scope': 'title_only'})
            if url not in row['detail_urls']:
                row['detail_urls'].append(url)
            row['provenance'].append({'capture_path': str(path.resolve()), 'capture_sha256': digest(raw),
                                      'source_url': source_url, 'actual_href': link['url']})
    tasks = [json.loads(line) for line in queue.read_text(encoding='utf-8').splitlines() if line.strip()]
    statuses = [{**task, 'chrome_capture_found': (task['advisor_id'], identity(task['source_url'])) in covered,
                 'pagination_complete': False} for task in tasks]
    jobs = [{'artifact_id': row['artifact_id'], 'advisor_id': row['advisor_id'],
             'content_scope': 'title_only', 'text_units': [{'unit_id': 'title', 'text': row['title']}],
             'expected_units': ['title'], 'available_at': None, 'split': None,
             'training_eligibility': 'unresolved', 'source_url': row['detail_urls'][0]}
            for _, row in sorted(records.items())]
    output.mkdir(parents=True, exist_ok=False)
    for name, rows in [('publications.jsonl', [row for _, row in sorted(records.items())]),
                       ('title_jobs.jsonl', jobs), ('capture_manifest.jsonl', hashes),
                       ('chrome_status.jsonl', statuses), ('unresolved_captures.jsonl', rejected)]:
        (output / name).write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')
    report = {'capture_count': len(hashes), 'publication_count': len(records),
              'chrome_queue_count': len(tasks), 'queue_items_with_capture': sum(row['chrome_capture_found'] for row in statuses),
              'queue_items_without_capture': sum(not row['chrome_capture_found'] for row in statuses),
              'pagination_complete': False, 'historical_training_ready': False,
              'dedup_policy': 'advisor plus exact normalized title; retain all actual detail URLs'}
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('captures', 'registry', 'queue', 'output'):
        parser.add_argument('--' + arg, required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.captures, args.registry, args.queue, args.output)))
