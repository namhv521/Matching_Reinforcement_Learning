"""Prepare first-page attribution evidence for existing downloaded PDFs."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import unicodedata

import pymupdf


def normalized(value):
    plain = unicodedata.normalize('NFKD', value.replace('Đ', 'D').replace('đ', 'd')).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', ' ', plain).strip()


def audit(collection, recovered, registry, output):
    collection, recovered, registry, output = map(Path, (collection, recovered, registry, output))
    with registry.open(encoding='utf-8-sig', newline='') as stream:
        people = {row['advisor_id']: row for row in csv.DictReader(stream)}
    receipts = [json.loads(line) for line in (collection / 'downloads.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    pairs = [(collection, row) for row in receipts if row['status'] == 'pdf_extracted']
    receipt = json.loads((recovered / 'receipt.json').read_text(encoding='utf-8'))
    if receipt['status'] == 'pdf_extracted':
        pairs.append((recovered, receipt))
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for base, receipt in pairs:
        path = base / receipt['raw_path']
        if hashlib.sha256(path.read_bytes()).hexdigest() != receipt['sha256']:
            raise ValueError('pdf_hash_mismatch')
        with pymupdf.open(path) as document:
            text = document[0].get_text(sort=True)
            pdf_metadata = document.metadata
        name = receipt['sha256'] + '_first_page.txt'
        (output / name).write_text(text, encoding='utf-8')
        folded = normalized(text)
        for item in receipt['publications']:
            person = people[item['advisor_id']]
            tokens = normalized(re.sub(r'^(?:TS|ThS|PGS|GS)[.\s]+', '', person['name'], flags=re.I)).split()
            title = normalized(item['title'])
            generic = title in {'view', 'view article', 'download', 'view full text'} or len(title) < 10
            # Diagnostic token/substring tests propose review only, never approve identity.
            rows.append({'advisor_id': person['advisor_id'], 'advisor_name': person['name'],
                'artifact_id': item['artifact_id'], 'source_title': item['title'],
                'source_url': receipt.get('url') or receipt.get('source_url'),
                'pdf_path': str(path.resolve()), 'pdf_sha256': receipt['sha256'],
                'page_count': receipt['page_count'], 'pdf_metadata': pdf_metadata,
                'first_page_text_path': str((output / name).resolve()),
                'title_phrase_present': bool(title and not generic and title in folded),
                'advisor_name_tokens_present': bool(tokens) and all(token in folded.split() for token in tokens),
                'generic_source_title': generic,
                'article_person_link_status': 'pending', 'downloaded_document_matches_article': None,
                'available_at': None, 'review_status': 'pending', 'historical_training_ready': False})
    (output / 'attribution_candidates.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')
    report = {'unique_pdf_count': len({row['pdf_sha256'] for row in rows}),
              'association_count': len(rows), 'title_phrase_present': sum(row['title_phrase_present'] for row in rows),
              'advisor_name_tokens_present': sum(row['advisor_name_tokens_present'] for row in rows),
              'generic_source_titles': sum(row['generic_source_title'] for row in rows),
              'identity_approvals_granted': 0, 'historical_training_ready': False}
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('collection', 'recovered', 'registry', 'output'):
        parser.add_argument('--' + arg, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.collection, args.recovered, args.registry, args.output)))
