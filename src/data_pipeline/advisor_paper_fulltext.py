"""Public paper-link discovery and bounded PDF retrieval from browser captures."""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlsplit, urlunsplit

from .pdf_extract import iter_pdf_blocks
from . import pdf_extract as pdf_module

MAX_BYTES = 25 * 1024 * 1024
TIMEOUT = 15
IMPLEMENTATION_HASHES = {
    'downloader': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'pdf_extract': hashlib.sha256(Path(pdf_module.__file__).read_bytes()).hexdigest(),
}


def sha(body):
    return hashlib.sha256(body).hexdigest()


def validate_public_url(url, *, resolver=socket.getaddrinfo):
    """Resolve once and reject every nonpublic result before opening a socket."""
    if not isinstance(url, str) or re.search(r'[\x00-\x20\\]', url):
        raise ValueError('invalid_public_url')
    parsed = urlsplit(url)
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname
            or parsed.username or parsed.password or parsed.port not in (None, 80, 443)
            or (parsed.port is not None and parsed.port != (443 if parsed.scheme == 'https' else 80))):
        raise ValueError('public_http_url_required')
    host = parsed.hostname.encode('idna').decode('ascii')
    if host.lower() in {'localhost', 'metadata.google.internal'} or host.endswith('.local'):
        raise ValueError('nonpublic_host')
    port = 443 if parsed.scheme == 'https' else 80
    records = resolver(host, port, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(record[4][0] for record in records))
    if not addresses or any(not ipaddress.ip_address(addr).is_global for addr in addresses):
        raise ValueError('nonpublic_dns_address')
    return parsed, host, addresses[0], port


def bounded_public_fetch(url, *, max_bytes=MAX_BYTES, timeout=TIMEOUT, max_redirects=5):
    """Pin the vetted IP while preserving TLS hostname/certificate checks."""
    visited, trail = set(), []
    for _ in range(max_redirects + 1):
        if url in visited:
            raise ValueError('redirect_cycle')
        visited.add(url)
        parsed, host, address, port = validate_public_url(url)
        connection = (http.client.HTTPSConnection(host, port, timeout=timeout, context=ssl.create_default_context())
                      if parsed.scheme == 'https' else http.client.HTTPConnection(host, port, timeout=timeout))
        # Pin DNS output; HTTPSConnection still wraps with server_hostname=host.
        connection._create_connection = lambda _, timeout, source_address=None: socket.create_connection(
            (address, port), timeout, source_address)
        try:
            path = urlunsplit(('', '', parsed.path or '/', parsed.query, ''))
            connection.request('GET', path, headers={'User-Agent': 'UniMatchPaperEvidence/1.0',
                               'Accept': 'application/pdf,text/html;q=0.8', 'Accept-Encoding': 'identity'})
            response = connection.getresponse()
            headers = dict(response.getheaders())
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader('Location')
                if not location:
                    raise ValueError('redirect_without_location')
                destination = urljoin(url, location)
                if parsed.scheme == 'https' and urlsplit(destination).scheme != 'https':
                    raise ValueError('https_downgrade_redirect')
                trail.append({'url': url, 'status': response.status, 'destination': destination})
                url = destination
                continue
            length = response.getheader('Content-Length')
            if length and int(length) > max_bytes:
                raise ValueError('paper_response_size_limit')
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise ValueError('paper_response_size_limit')
            return {'body': body, 'status': response.status, 'final_url': url,
                    'headers': headers, 'redirects': trail}
        finally:
            connection.close()
    raise ValueError('redirect_limit')


def detail_key(url):
    parsed = urlsplit(url)
    citation = parse_qs(parsed.query).get('citation_for_view', [''])[0]
    if citation:
        return ('scholar', citation)
    match = re.search(r'/publication/(\d+)', parsed.path)
    return ('researchgate', match[1]) if match else ('url', urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, '')))


def observed_paper_link(url, text=''):
    """Classify only actual destinations, not fabricated publisher search URLs."""
    parsed = urlsplit(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
        return None
    path = unquote(parsed.path)
    if (parsed.hostname or '').lower() in {'doi.org', 'dx.doi.org'}:
        return 'doi'
    if (re.search(r'\.pdf(?:$|/)', path, re.I) or re.search(r'/(?:pdf|download)(?:/|$)', path, re.I)
            or re.search(r'(?:^|[?&])(?:format|type)=pdf(?:&|$)', parsed.query, re.I)
            or re.search(r'^\s*\[PDF\]', text, re.I)):
        return 'pdf'
    if parsed.hostname not in {'scholar.google.com', 'scholar.google.com.vn'} and text.strip():
        return 'publisher_candidate'
    return None


def _read(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def _jsonl(path, rows):
    with path.open('x', encoding='utf-8') as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')


def collect_papers(captures, publication_index, output, *, max_downloads=60, fetcher=None, capture_quality=None):
    if isinstance(max_downloads, bool) or not isinstance(max_downloads, int) or max_downloads < 0:
        raise ValueError('nonnegative_download_budget_required')
    captures, output = Path(captures), Path(output)
    quality = ({str(Path(row['capture_path']).resolve()): row for row in _read(capture_quality)}
               if capture_quality else {})
    owners = {}
    for article in _read(publication_index):
        for url in article['detail_urls']:
            owners.setdefault(detail_key(url), []).append(article)
    sources, links = [], {}
    for path in sorted(captures.glob('*.json')):
        raw = path.read_bytes()
        capture = json.loads(raw)
        if not isinstance(capture, dict):
            continue
        original_url = capture.get('source_url') or capture.get('url', '')
        source = {'capture_path': str(path.resolve()), 'capture_sha256': sha(raw),
                  'source_url': original_url, 'final_capture_url': capture.get('url'),
                  'collected_at': capture.get('collected_at'),
                  'matched_publications': len(owners.get(detail_key(original_url), []))}
        assessment = quality.get(str(path.resolve()))
        if assessment and assessment['capture_sha256'] != sha(raw):
            raise ValueError('capture_quality_hash_mismatch')
        source['quality_status'] = assessment.get('access_status') if assessment else 'not_assessed'
        sources.append(source)
        if assessment and assessment.get('access_status') == 'blocked':
            continue
        articles = owners.get(detail_key(original_url), [])
        for link in capture.get('links', []):
            url = link.get('url', '')
            kind = observed_paper_link(url, link.get('text', ''))
            if not kind:
                continue
            parsed = urlsplit(url)
            canonical = urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, parsed.query, ''))
            row = links.setdefault(canonical, {'url': canonical, 'kind': kind,
                'provenance': [], 'publications': [], 'review_status': 'pending',
                'available_at': None, 'training_eligibility': 'unresolved'})
            row['provenance'].append({**source, 'anchor_text': link.get('text'), 'actual_href': url})
            for article in articles:
                association = {'advisor_id': article['advisor_id'], 'artifact_id': article['artifact_id'], 'title': article['title'],
                               'article_person_link_status': 'pending',
                               'downloaded_document_matches_article': None}
                if association not in row['publications']:
                    row['publications'].append(association)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'raw').mkdir()
    (output / 'extracted').mkdir()
    _jsonl(output / 'capture_manifest.jsonl', sources)
    _jsonl(output / 'observed_links.jsonl', [links[key] for key in sorted(links)])
    receipts, queue = [], []
    fetcher = fetcher or bounded_public_fetch
    candidates = [links[key] for key in sorted(links) if links[key]['kind'] == 'pdf']
    for index, candidate in enumerate(candidates):
        url = candidate['url']
        receipt = {'request_id': sha(url.encode()), **candidate, 'status': 'budget_exceeded',
                   'collected_at': datetime.now(timezone.utc).isoformat(), 'collection_method': 'http',
                   'content_scope': 'unavailable', 'reason': 'download_budget_exceeded',
                   'article_identity_review_status': 'pending',
                   'full_text_scope': 'downloaded_document_only_not_verified_article'}
        if index < max_downloads:
            try:
                result = fetcher(url)
                body = result.pop('body')
                receipt.update(result)
                receipt['http_status'] = result['status']
                if not isinstance(body, bytes) or len(body) > MAX_BYTES:
                    raise ValueError('bounded_bytes_required')
                body_hash = sha(body)
                is_pdf = body.startswith(b'%PDF-')
                filename = body_hash + ('.pdf' if is_pdf else '.bin')
                target = output / 'raw' / filename
                if not target.exists():
                    target.write_bytes(body)
                receipt.update(sha256=body_hash, raw_path=target.relative_to(output).as_posix(), size_bytes=len(body))
                if result['status'] != 200 or not is_pdf:
                    receipt.update(status='needs_chrome', reason='http_or_pdf_signature_failed')
                else:
                    source_ref = {'source_id': body_hash, 'source_file': str(target), 'source_sha256': body_hash}
                    records = list(iter_pdf_blocks(target, source_ref))
                    pages = [row for row in records if row['kind'] == 'page_outcome']
                    complete = bool(pages) and all(row['page'] is not None and row['status'] in {'extracted', 'blank'} for row in pages)
                    extracted = output / 'extracted' / (body_hash + '.jsonl')
                    if not extracted.exists():
                        _jsonl(extracted, records)
                    receipt.update(status='pdf_extracted' if complete else 'pdf_partial',
                        reason='' if complete else 'page_review_or_ocr_required', page_count=len(pages),
                        content_scope='full_text_complete' if complete else 'partial_full_text',
                        extraction_path=extracted.relative_to(output).as_posix(),
                        extracted_sha256=sha(extracted.read_bytes()))
            except (OSError, ValueError, http.client.HTTPException, ssl.SSLError) as error:
                receipt.update(status='needs_chrome', reason=type(error).__name__ + ':' + str(error))
            if receipt['status'] == 'needs_chrome':
                queue.append({'request_id': receipt['request_id'], 'source_url': url,
                              'reason': receipt['reason'], 'chrome_attempted': False,
                              'publications': candidate['publications']})
        receipts.append(receipt)
        # Persist a per-request receipt before advancing so interruption is reviewable.
        (output / 'receipts').mkdir(exist_ok=True)
        (output / 'receipts' / (receipt['request_id'] + '.json')).write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    _jsonl(output / 'downloads.jsonl', receipts)
    _jsonl(output / 'chrome_queue.jsonl', queue)
    report = {'capture_count': len(sources), 'observed_links': len(links), 'pdf_candidate_count': len(candidates),
              'attempted_downloads': min(len(candidates), max_downloads),
              'status_counts': dict(Counter(row['status'] for row in receipts)),
              'chrome_pending': len(queue), 'historical_training_ready': False,
              'all_papers_fulltext_complete': False,
              'implementation_hashes': IMPLEMENTATION_HASHES,
              'capture_quality_sha256': sha(Path(capture_quality).read_bytes()) if capture_quality else None,
              'blocked_captures_excluded': sum(row['quality_status'] == 'blocked' for row in sources)}
    report['artifact_hashes'] = {str(path.relative_to(output)): sha(path.read_bytes())
                               for path in output.rglob('*') if path.is_file()}
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report
