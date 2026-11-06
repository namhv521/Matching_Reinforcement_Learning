"""Bounded seed collection with explicit, auditable Chrome fallback receipts.

This collector does not claim title lists are paper full text or establish
historical availability, identity approval, or browser execution.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

from .lecturer_crawl import parse_profile

MAX_BYTES = 5 * 1024 * 1024
HOSTS = {'fit.neu.edu.vn', 'scholar.google.com', 'scholar.google.com.vn',
         'www.researchgate.net', 'researchgate.net', 'github.com', 'www.github.com'}
URL_FIELDS = ('university_url', 'scholar_url', 'researchgate_url', 'github_url')


def _url(url):
    value = urlsplit(url)
    if (value.scheme != 'https' or value.hostname not in HOSTS or value.username
            or value.password or value.port not in (None, 443) or '\\' in url):
        raise ValueError('public_seed_https_url_required')
    return value


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def _write(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def _lines(path, rows):
    with path.open('x', encoding='utf-8') as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')


def _fetch(url):
    _url(url)
    # Deliberately do not follow redirects: every redirect is a browser-review task.
    with requests.get(url, timeout=(10, 25), allow_redirects=False, stream=True,
                      headers={'User-Agent': 'UniMatchSkillEvidence/1.0'}) as response:
        data = bytearray()
        for chunk in response.iter_content(65536):
            data.extend(chunk)
            if len(data) > MAX_BYTES:
                raise ValueError('response_size_limit')
        return bytes(data), response.status_code, response.url


def collect_seed_profiles(seed_csv, output, *, max_urls=68, fetcher=None):
    """Collect exact listed seeds once; queue every incomplete direct retrieval."""
    if isinstance(max_urls, bool) or not isinstance(max_urls, int) or max_urls < 1:
        raise ValueError('positive_max_urls_required')
    seed_csv, output = Path(seed_csv), Path(output)
    with seed_csv.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not {'advisor_id', 'name', *URL_FIELDS}.issubset(reader.fieldnames or ()):
            raise ValueError('seed_schema_missing')
        advisors = list(reader)
    ids = [row['advisor_id'] for row in advisors]
    if any(not item for item in ids) or len(set(ids)) != len(ids):
        raise ValueError('unique_advisor_ids_required')
    seeds = []
    for person in advisors:
        for field in URL_FIELDS:
            url = person[field].strip()
            if url:
                _url(url)
                seeds.append((person, field, url))
    output.mkdir(parents=True, exist_ok=False)
    (output / 'raw').mkdir()
    receipts, profiles, queue = [], [], []
    fetcher = fetcher or _fetch
    for index, (person, field, url) in enumerate(seeds):
        request_id = _hash((person['advisor_id'] + '\n' + field + '\n' + url).encode())
        receipt = {'request_id': request_id, 'advisor_id': person['advisor_id'],
                   'source_field': field, 'source_url': url, 'collection_method': 'http',
                   'collected_at': datetime.now(timezone.utc).isoformat(),
                   'status': 'needs_chrome', 'reason': '', 'available_at': None,
                   'review_status': 'pending', 'training_eligibility': 'unresolved'}
        if index >= max_urls:
            receipt.update(status='budget_exceeded', reason='direct_url_budget_exceeded')
        else:
            try:
                body, code, final_url = fetcher(url)
                _url(final_url)
                if final_url != url:
                    raise ValueError('redirect_requires_browser_review')
                if not isinstance(body, bytes) or len(body) > MAX_BYTES:
                    raise ValueError('bounded_response_bytes_required')
                sha = _hash(body)
                raw = output / 'raw' / (sha + '.html')
                if not raw.exists():
                    raw.write_bytes(body)
                receipt.update(http_status=code, final_url=final_url, sha256=sha,
                               raw_path=raw.relative_to(output).as_posix())
                soup = BeautifulSoup(body, 'html.parser')
                for node in soup(['script', 'style', 'noscript']):
                    node.decompose()
                text = soup.get_text('\n', strip=True)
                if code != 200:
                    receipt['reason'] = f'http_{code}'
                elif re.search(r'captcha|unusual traffic|access denied|verify you are human', text, re.I):
                    receipt['reason'] = 'browser_challenge'
                elif len(text) < 80:
                    receipt['reason'] = 'empty_or_incomplete_render'
                else:
                    profile = {'request_id': request_id, 'advisor_id': person['advisor_id'],
                               'source_url': url, 'text': text, 'content_scope': 'partial_full_text',
                               'pagination_complete': False, 'review_status': 'pending',
                               'source_sha256': sha}
                    if field == 'university_url':
                        parsed = parse_profile(body, url, receipt['collected_at'], sha)
                        profile['parsed_official_profile'] = parsed
                        if parsed['status'] == 'extracted' and parsed['profile_text']:
                            receipt.update(status='success', reason='official_profile_parsed')
                        else:
                            receipt['reason'] = 'official_markup_incomplete'
                    else:
                        receipt['reason'] = 'external_pagination_and_content_review_required'
                    profiles.append(profile)
            except (requests.RequestException, ValueError, OSError) as error:
                receipt['reason'] = type(error).__name__ + ':' + str(error)
        if receipt['status'] == 'needs_chrome':
            queue.append({'request_id': request_id, 'advisor_id': person['advisor_id'],
                          'source_url': url, 'reason': receipt['reason'],
                          'status': 'pending_chrome', 'chrome_attempted': False})
        receipts.append(receipt)
    _lines(output / 'registry.jsonl', advisors)
    _lines(output / 'sources.jsonl', receipts)
    _lines(output / 'profiles.jsonl', profiles)
    _lines(output / 'chrome_queue.jsonl', queue)
    report = {'schema_version': 'advisor-skill-seeds/1', 'advisor_count': len(advisors),
              'seed_url_count': len(seeds), 'attempted_urls': min(len(seeds), max_urls),
              'status_counts': dict(Counter(row['status'] for row in receipts)),
              'chrome_pending': len(queue), 'chrome_attempted': False,
              'seed_sha256': _hash(seed_csv.read_bytes()), 'historical_training_ready': False}
    _write(output / 'collection_report.json', report)
    return report


def record_chrome_capture(run_dir, request_id, *, text, final_url, status='success', captured_at):
    """Import actual browser text; caller must perform and attest browser retrieval."""
    run_dir = Path(run_dir)
    queue = [json.loads(line) for line in (run_dir / 'chrome_queue.jsonl').read_text(encoding='utf-8').splitlines()]
    task = next((row for row in queue if row['request_id'] == request_id), None)
    if task is None:
        raise ValueError('unknown_chrome_request')
    if not re.fullmatch('[a-f0-9]{64}', request_id):
        raise ValueError('invalid_request_id')
    if _url(final_url).hostname != _url(task['source_url']).hostname:
        raise ValueError('chrome_final_host_mismatch')
    timestamp = datetime.fromisoformat(captured_at.replace('Z', '+00:00'))
    if timestamp.tzinfo is None:
        raise ValueError('timezone_timestamp_required')
    if status not in {'success', 'blocked', 'requires_user_action', 'partial'}:
        raise ValueError('invalid_chrome_status')
    if not isinstance(text, str) or len(text.encode()) > MAX_BYTES or (status == 'success' and not text.strip()):
        raise ValueError('bounded_nonempty_capture_required')
    captures = run_dir / 'chrome_captures'
    captures.mkdir(exist_ok=True)
    target = captures / request_id
    target.mkdir(exist_ok=False)
    encoded = text.encode('utf-8')
    (target / 'text.txt').write_bytes(encoded)
    receipt = {**task, 'status': status, 'chrome_attempted': True,
               'collection_method': 'chrome_ui', 'captured_at': captured_at,
               'final_url': final_url, 'sha256': _hash(encoded),
               'text_path': (target / 'text.txt').relative_to(run_dir).as_posix(),
               'content_scope': 'partial_full_text', 'pagination_complete': False,
               'review_status': 'pending', 'available_at': None,
               'training_eligibility': 'unresolved'}
    _write(target / 'receipt.json', receipt)
    return receipt
