"""Resolve exact observed article links using publisher citation metadata only."""
import argparse
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.data_pipeline.advisor_paper_fulltext import bounded_public_fetch, detail_key, sha
from src.data_pipeline.pdf_extract import iter_pdf_blocks


def norm(value):
    value = unicodedata.normalize('NFKC', value).casefold()
    return re.sub(r'\W+', ' ', value).strip()


def citation_metadata(body, source_url):
    soup = BeautifulSoup(body, 'html.parser')
    values = {}
    for node in soup.find_all('meta'):
        name = (node.get('name') or node.get('property') or '').lower()
        if name in {'citation_title', 'dc.title', 'citation_author', 'citation_pdf_url', 'citation_doi'}:
            values.setdefault(name, []).append(node.get('content', ''))
    pdfs = [urljoin(source_url, value) for value in values.get('citation_pdf_url', [])
            if urlsplit(urljoin(source_url, value)).scheme in {'https', 'http'}]
    return {'titles': values.get('citation_title', []) + values.get('dc.title', []),
            'authors': values.get('citation_author', []), 'pdf_urls': list(dict.fromkeys(pdfs)),
            'dois': values.get('citation_doi', [])}


def resolve(captures, publication_index, output, *, max_landings=20):
    if isinstance(max_landings, bool) or not isinstance(max_landings, int) or max_landings < 0:
        raise ValueError('nonnegative_landing_budget_required')
    captures, publication_index, output = map(Path, (captures, publication_index, output))
    articles = [json.loads(line) for line in publication_index.read_text(encoding='utf-8').splitlines() if line.strip()]
    owners = {detail_key(url): row for row in articles for url in row['detail_urls']}
    candidates = {}
    for path in sorted(captures.glob('*.json')):
        capture = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(capture, dict):
            continue
        article = owners.get(detail_key(capture.get('source_url') or capture.get('url', '')))
        if not article or len(norm(article['title'])) < 12:
            continue
        for link in capture.get('links', []):
            url, text = link.get('url', ''), link.get('text', '')
            parsed = urlsplit(url)
            if (parsed.scheme not in {'https', 'http'} or not parsed.hostname
                    or 'scholar.google' in parsed.hostname or re.search(r'\.pdf(?:$|\?)', url, re.I)):
                continue
            # Require article title itself as anchor; this avoids reference/sidebar links.
            if SequenceMatcher(None, norm(text), norm(article['title'])).ratio() < .9:
                continue
            candidates.setdefault(url, {'source_url': url, 'article': article,
                'capture_path': str(path.resolve()), 'capture_sha256': sha(path.read_bytes())})
    output.mkdir(parents=True, exist_ok=False)
    (output / 'raw').mkdir()
    rows, downloaded = [], set()
    for url, candidate in list(candidates.items())[:max_landings]:
        row = {**candidate, 'status': 'unresolved', 'available_at': None,
               'review_status': 'pending', 'article_person_link_status': 'pending'}
        try:
            result = bounded_public_fetch(url, max_bytes=5*1024*1024, timeout=10)
            body = result['body']
            row.update(http_status=result['status'], final_url=result['final_url'], raw_sha256=sha(body))
            (output / 'raw' / (sha(body) + '.html')).write_bytes(body)
            metadata = citation_metadata(body, result['final_url'])
            row['citation_metadata'] = metadata
            match = max((SequenceMatcher(None, norm(title), norm(candidate['article']['title'])).ratio()
                         for title in metadata['titles']), default=0)
            row['title_similarity'] = match
            if result['status'] == 200 and match >= .8:
                row['status'] = 'metadata_title_candidate'
                row['pdf_results'] = []
                for pdf_url in metadata['pdf_urls'][:1]:
                    if pdf_url in downloaded:
                        continue
                    downloaded.add(pdf_url)
                    pdf = bounded_public_fetch(pdf_url, timeout=10)
                    data = pdf['body']
                    item = {'url': pdf_url, 'http_status': pdf['status'], 'sha256': sha(data), 'status': 'not_pdf'}
                    if pdf['status'] == 200 and data.startswith(b'%PDF-'):
                        target = output / 'raw' / (sha(data) + '.pdf')
                        target.write_bytes(data)
                        records = list(iter_pdf_blocks(target, {'source_id': sha(data), 'source_sha256': sha(data), 'source_file': str(target)}))
                        outcomes = [r for r in records if r['kind'] == 'page_outcome']
                        complete = bool(outcomes) and all(r['page'] is not None and r['status'] in {'extracted','blank'} for r in outcomes)
                        extracted = output / (sha(data) + '_extracted.jsonl')
                        extracted.write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in records), encoding='utf-8')
                        item.update(status='pdf_extracted' if complete else 'pdf_partial', page_count=len(outcomes),
                                    raw_path=str(target.resolve()), document_matches_article='pending')
                    row['pdf_results'].append(item)
        except Exception as error:
            row['error_class'] = type(error).__name__
        rows.append(row)
        (output / (sha(url.encode()) + '_receipt.json')).write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
    report = {'landing_candidates': len(candidates), 'attempted_landings': len(rows),
              'metadata_title_candidates': sum(r['status']=='metadata_title_candidate' for r in rows),
              'pdf_extracted': sum(p['status']=='pdf_extracted' for r in rows for p in r.get('pdf_results',[])),
              'identity_approvals_granted': 0, 'historical_training_ready': False}
    report['input_index_sha256'] = sha(publication_index.read_bytes())
    report['output_hashes'] = {str(path.relative_to(output)): sha(path.read_bytes())
                             for path in output.rglob('*') if path.is_file()}
    (output / 'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for arg in ('captures','publication-index','output'):
        parser.add_argument('--'+arg,required=True,type=Path)
    parser.add_argument('--max-landings',type=int,default=20)
    args=parser.parse_args()
    print(json.dumps(resolve(args.captures,args.publication_index,args.output,max_landings=args.max_landings)))
