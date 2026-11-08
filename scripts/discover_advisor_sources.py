"""Index observed links and publication citations from a completed seed collection.

Discovery is not identity verification or full-text collection. No inferred URL,
historical availability, or reviewer approval is created.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup


def _rows(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def observed_links(body, source_url):
    """Return only actual HTTP(S) anchor destinations; drop tracking fragments."""
    links = {}
    for node in BeautifulSoup(body, 'html.parser').find_all('a', href=True):
        destination = urlsplit(urljoin(source_url, node['href']))
        if (destination.scheme not in {'http', 'https'} or not destination.hostname
                or destination.username or destination.password):
            continue
        url = urlunsplit((destination.scheme, destination.netloc, destination.path,
                          destination.query, ''))
        links.setdefault(url, node.get_text(' ', strip=True))
    return sorted(links.items())


def discover(collection, output):
    collection, output = Path(collection).resolve(), Path(output).resolve()
    receipts = _rows(collection / 'sources.jsonl')
    profiles = _rows(collection / 'profiles.jsonl')
    seen_links, seen_titles = {}, {}
    for receipt in receipts:
        if not receipt.get('raw_path'):
            continue
        path = (collection / receipt['raw_path']).resolve()
        if not path.is_relative_to(collection):
            raise ValueError('raw_path_outside_collection')
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != receipt['sha256']:
            raise ValueError('raw_hash_mismatch')
        for url, anchor in observed_links(body, receipt['source_url']):
            key = (receipt['advisor_id'], url)
            source = {'source_url': receipt['source_url'], 'source_sha256': receipt['sha256'],
                      'anchor_text': anchor, 'request_id': receipt['request_id']}
            row = seen_links.setdefault(key, {'advisor_id': key[0], 'candidate_url': url,
                'provenance': [], 'review_status': 'pending', 'available_at': None,
                'training_eligibility': 'unresolved'})
            row['provenance'].append(source)
    for profile in profiles:
        parsed = profile.get('parsed_official_profile', {})
        for citation in parsed.get('publications', []):
            key = (profile['advisor_id'], ' '.join(citation.split()))
            row = seen_titles.setdefault(key, {'advisor_id': key[0], 'citation_text': key[1],
                'content_scope': 'title_only', 'citation_requires_title_parsing': True,
                'provenance': [], 'review_status': 'pending', 'available_at': None,
                'training_eligibility': 'unresolved'})
            row['provenance'].append({'source_url': profile['source_url'],
                                     'source_sha256': profile['source_sha256']})
    output.mkdir(parents=True, exist_ok=False)
    for name, values in [('observed_links.jsonl', seen_links), ('publication_citations.jsonl', seen_titles)]:
        with (output / name).open('x', encoding='utf-8') as stream:
            for key in sorted(values):
                stream.write(json.dumps(values[key], ensure_ascii=False) + '\n')
    report = {'observed_link_count': len(seen_links), 'publication_citation_count': len(seen_titles),
              'discovery_only': True, 'historical_training_ready': False,
              'chrome_capture_discovery': 'text-only captures do not supply anchor destinations'}
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collection', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(discover(args.collection, args.output)))
