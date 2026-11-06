"""Collect bibliographically dated advisor works through calendar 2024 only.

The legacy data/2024 pool is not a calendar filter. Current crawl availability
and author identity remain unknown/pending, even for older publication events.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import date
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import sys
import unicodedata
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.data_pipeline.advisor_paper_fulltext import bounded_public_fetch, detail_key, observed_paper_link, sha
from src.data_pipeline.pdf_extract import iter_pdf_blocks

MONTHS = 'January February March April May June July August September October November December'.split()


def norm(text):
    text = unicodedata.normalize('NFKC', text).casefold()
    return re.sub(r'\W+', '', text)


def date_field(value):
    """Parse a dedicated publication-date field, preserving year-only precision."""
    value = str(value or '').strip()
    match = re.fullmatch(r'((?:19|20)\d{2})(?:[-/](\d{1,2})(?:[-/](\d{1,2}))?)?', value)
    if not match:
        return None
    year, month, day = match.groups()
    try:
        date(int(year), int(month or 1), int(day or 1))
    except ValueError:
        return None
    return {'event_year': int(year), 'date_precision': 'day' if day else 'month' if month else 'year',
            'date_witness': value}


def browser_date(capture):
    text = capture.get('text', '')
    match = re.search(r'(?:^|\n)(?:Ngày xuất bản|Publication date|Published date)\s*\n\s*([^\n]+)', text, re.I)
    if match:
        result = date_field(match[1])
        return {**result, 'date_basis': 'dedicated_publication_field'} if result else None
    if 'researchgate.net' in capture.get('url', ''):
        header = text.split('Authors:')[0].split('Citations')[0]
        # Only a month/year line in the main bibliographic header, never title or refs.
        for line in header.splitlines():
            match = re.match(r'^(' + '|'.join(MONTHS) + r')\s*((?:19|20)\d{2})(?:\D|$)', line, re.I)
            if match:
                return {'event_year': int(match[2]), 'date_precision': 'month',
                        'date_witness': line, 'date_basis': 'main_bibliographic_header'}
    return None


def corpus_date(row):
    # A title's incidental dataset year is not a publication-date field.
    field = date_field(row.get('published_at'))
    declared = date_field(row.get('publication_year'))
    witnesses = row.get('date_evidence', '')
    if field and declared and field['event_year'] != declared['event_year']:
        return None
    result = field or declared
    if result and re.search(r'(?<!\d)' + str(result['event_year']) + r'(?!\d)', witnesses):
        return {**result, 'date_basis': 'corpus_publication_field_with_witness', 'date_witness': witnesses}
    return None


def read_jsonl(path):
    path = Path(path)
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()] if path.exists() else []


def write_jsonl(path, rows):
    with Path(path).open('x', encoding='utf-8') as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')


def build_index(root):
    root = Path(root)
    with (root/'data/2024/advisors/faculty_profiles/advisors_profile.csv').open(encoding='utf-8-sig') as stream:
        roster = list(csv.DictReader(stream))
    ids = {row['advisor_id'] for row in roster}
    works, seen = [], set()
    for path in sorted((root/'data').glob('*/advisors/faculty_corpus/advisors_corpus.csv')):
        with path.open(encoding='utf-8-sig') as stream:
            for row in csv.DictReader(stream):
                if row['advisor_id'] not in ids:
                    continue
                key = (row['advisor_id'], norm(row['title']), row['content_type'])
                if key in seen:
                    continue
                seen.add(key)
                timing = corpus_date(row)
                works.append({'work_id': sha('|'.join(key).encode()), 'advisor_id': row['advisor_id'],
                    'title': row['title'], 'content_type': row['content_type'], 'timing': timing,
                    'content':row.get('content',''), 'published_at':row.get('published_at') or row.get('publication_year'),
                    'raw_path':str((root/'data'/row['raw_path']).resolve()) if row.get('raw_path') else None,
                    'source_url': row['source_url'], 'source_sha256': row['sha256'],
                    'source_record_id': row['record_id'], 'index_source': str(path.resolve()),
                    'candidate_urls': [], 'review_status': 'pending', 'available_at': None})
    index = read_jsonl(root/'outputs/advisor_skill_20261102/chrome_index/publications.jsonl')
    owners = {detail_key(url): row for row in index for url in row['detail_urls']}
    for path in sorted((root/'outputs/advisor_skill_20261102/chrome_full/details').glob('*.json')):
        capture = json.loads(path.read_text(encoding='utf-8'))
        source_url = capture.get('source_url') or capture.get('url', '')
        article = owners.get(detail_key(source_url))
        if not article:
            continue
        title = article['title']
        key = (article['advisor_id'], norm(title), 'publication')
        if key in seen:
            continue
        seen.add(key)
        candidates = []
        for link in capture.get('links', []):
            kind = observed_paper_link(link.get('url',''), link.get('text',''))
            # Only the title-linked publisher, DOI, or actual PDF download; no references/sidebar guesses.
            if kind in {'pdf','doi'} or (kind == 'publisher_candidate' and SequenceMatcher(None,norm(link.get('text','')),norm(title)).ratio() >= .9):
                candidates.append({'url': link['url'], 'kind': kind})
        works.append({'work_id': sha('|'.join(key).encode()), 'advisor_id': article['advisor_id'],
            'title': title, 'content_type': 'publication', 'timing': browser_date(capture),
            'content':capture.get('text',''), 'raw_path':str(path.resolve()),
            'published_at':None,
            'source_url': source_url, 'source_sha256': sha(path.read_bytes()),
            'index_source': str(path.resolve()), 'candidate_urls': candidates,
            'review_status': 'pending', 'available_at': None})
    for row in works:
        row['record_id']=row['work_id']
        row['sha256']=row['source_sha256']
        row['event_year']=row['timing']['event_year'] if row['timing'] else None
        row['date_precision']=row['timing']['date_precision'] if row['timing'] else 'unknown'
        if row['published_at'] is None and row['timing']:
            row['published_at']=row['timing']['date_witness'] if row['timing']['date_basis']=='dedicated_publication_field' else str(row['event_year'])
        row['evidence_scope']='current_capture_of_dated_work_not_historical_availability'
    return roster, works


def cache_index(root):
    root = Path(root)
    base = root/'outputs/advisor_skill_20261103'
    receipts = [(base/'paper_collection', row) for row in read_jsonl(base/'paper_collection/downloads.jsonl') if row['status']=='pdf_extracted']
    recovered = base/'paper_chrome_recovered'
    if (recovered/'receipt.json').exists():
        receipts.append((recovered,json.loads((recovered/'receipt.json').read_text(encoding='utf-8'))))
    readiness = {row['pdf_sha256']: row['readiness'] for row in read_jsonl(root/'outputs/advisor_skill_20261105/paper_attribution_v2/attribution_readiness.jsonl')}
    cache = []
    for parent, row in receipts:
        if readiness.get(row['sha256']) in {'exclude_wrong_author_candidate','needs_same_name_affiliation_review'}:
            continue
        path = parent/row['raw_path']
        if sha(path.read_bytes()) != row['sha256']:
            raise ValueError('cache_hash_mismatch')
        cache.append((path, row))
    return cache


def identity_flags(root):
    base=Path(root)/'outputs/advisor_skill_20261105/paper_attribution_v2'
    readiness={row['pdf_sha256']:row['readiness']for row in read_jsonl(base/'attribution_readiness.jsonl')}
    return {(row['advisor_id'],norm(row['source_title'])):readiness[row['pdf_sha256']]
            for row in read_jsonl(base/'attribution_candidates.jsonl')
            if readiness.get(row['pdf_sha256'])in {'exclude_wrong_author_candidate','needs_same_name_affiliation_review'}}


def document_matches(path, title):
    import pymupdf
    with pymupdf.open(path) as document:
        header = ' '.join(document[number].get_text(sort=True) for number in range(min(2,len(document))))
    return len(norm(title)) >= 12 and norm(title) in norm(header)


def collect(root, output, *, max_requests=100, fetcher=None, resume=False, prior_runs=(), calendar_year=None):
    if isinstance(max_requests,bool) or not isinstance(max_requests,int) or not 0<=max_requests<=100:
        raise ValueError('request_budget_0_100_required')
    if calendar_year is not None and (isinstance(calendar_year, bool) or not isinstance(calendar_year, int) or calendar_year < 1):
        raise ValueError('positive_calendar_year_required')
    root,output=Path(root),Path(output)
    roster, works = build_index(root)
    eligible=[row for row in works if row['timing'] and (row['timing']['event_year'] == calendar_year
              if calendar_year is not None else row['timing']['event_year']<=2024)]
    future=[row for row in works if row['timing'] and (row['timing']['event_year'] != calendar_year
            if calendar_year is not None else row['timing']['event_year']>2024)]
    unresolved=[row for row in works if not row['timing']]
    continuing=output.exists() and resume
    if continuing and (output/'report.json').exists():
        raise ValueError('completed_run_is_immutable')
    output.mkdir(parents=True,exist_ok=continuing)
    for name in ('raw','extracted','receipts'):
        (output/name).mkdir(exist_ok=continuing)
    for name,rows in [('registry.jsonl',roster),('eligible_works.jsonl',eligible),('excluded_after_2024.jsonl',future),('unresolved_dates.jsonl',unresolved)]:
        if continuing:
            if read_jsonl(output/name)!=rows:
                raise ValueError('resume_source_index_changed')
        else:
            write_jsonl(output/name,rows)
    fetcher=fetcher or bounded_public_fetch
    requests, processed, queue = {},[],[]
    for prior_path in prior_runs:
        prior=Path(prior_path)
        manifest=json.loads((prior/'report.json').read_text(encoding='utf-8'))
        if read_jsonl(prior/'registry.jsonl')!=roster or read_jsonl(prior/'eligible_works.jsonl')!=eligible:
            raise ValueError('prior_source_index_changed')
        for relative,expected in manifest['output_hashes'].items():
            if sha((prior/relative).read_bytes())!=expected:
                raise ValueError('prior_manifest_hash_mismatch')
        for receipt in read_jsonl(prior/'requests.jsonl'):
            requests[receipt['url']]=receipt
    previous_request_count=len(requests)
    if continuing:
        for path in (output/'receipts').glob('*.json'):
            prior=json.loads(path.read_text(encoding='utf-8'))
            if prior.get('raw_path') and sha(Path(prior['raw_path']).read_bytes())!=prior['sha256']:
                raise ValueError('resume_raw_hash_mismatch')
            requests[prior['url']]=prior
    cache=cache_index(root)
    quarantined=identity_flags(root)
    processing_order=sorted(eligible,key=lambda row:(-row['event_year'],row['advisor_id'],row['work_id']))
    for work in processing_order:
        result={'work_id':work['work_id'],'advisor_id':work['advisor_id'],'title':work['title'],
                'event_year':work['timing']['event_year'],'status':'title_only','review_status':'pending',
                'article_person_link_status':'pending','available_at':None,'training_eligibility':'unresolved'}
        if (work['advisor_id'],norm(work['title']))in quarantined:
            result.update(status='quarantined_identity',quarantine_reason=quarantined[work['advisor_id'],norm(work['title'])])
            processed.append(result)
            continue
        if work['content_type'] not in {'publication','book','research_project'}:
            result['status']='metadata_indexed_nonpaper'
            processed.append(result)
            continue
        candidate_pdf=None
        for path,receipt in cache:
            if any(item['advisor_id']==work['advisor_id'] and norm(item['title'])==norm(work['title']) for item in receipt['publications']) and document_matches(path,work['title']):
                candidate_pdf=path
                result['collection_method']='verified_existing_bytes_cache'
                break
        urls=list(dict.fromkeys(item['url'] for item in sorted(work['candidate_urls'],key=lambda x: x['kind']!='pdf')))
        for position,url in enumerate(urls if candidate_pdf is None else []):
            if url not in requests:
                if len(requests)>=previous_request_count+max_requests:
                    result['status']='budget_exceeded'
                    break
                request={'url':url,'source_work_id':work['work_id'],'status':'failed'}
                try:
                    fetched=fetcher(url)
                    body=fetched['body']
                    raw=output/'raw'/(sha(body)+('.pdf' if body.startswith(b'%PDF-') else '.html'))
                    if not raw.exists(): raw.write_bytes(body)
                    request.update(http_status=fetched['status'],sha256=sha(body),raw_path=str(raw.resolve()),final_url=fetched['final_url'])
                    if fetched['status']==200 and body.startswith(b'%PDF-'):
                        request['status']='pdf_downloaded'
                    elif fetched['status']==200:
                        soup=BeautifulSoup(body,'html.parser')
                        titles=[m.get('content','') for m in soup.find_all('meta') if m.get('name','').lower()=='citation_title']
                        if any(SequenceMatcher(None,norm(t),norm(work['title'])).ratio()>=.85 for t in titles):
                            # Download only the publisher's own article PDF metadata, no generic .pdf references.
                            for node in soup.find_all('meta'):
                                if node.get('name','').lower()=='citation_pdf_url':
                                    from urllib.parse import urljoin
                                    target=urljoin(fetched['final_url'],node.get('content',''))
                                    if target not in urls: urls.append(target)
                        request['status']='publisher_html'
                except Exception as error:
                    request['error_class']=type(error).__name__
                requests[url]=request
                (output/'receipts'/(sha(url.encode())+'.json')).write_text(json.dumps(request,indent=2),encoding='utf-8')
            request=requests[url]
            if request['status']=='publisher_html':
                from urllib.parse import urljoin
                soup=BeautifulSoup(Path(request['raw_path']).read_bytes(),'html.parser')
                titles=[m.get('content','') for m in soup.find_all('meta') if m.get('name','').lower()=='citation_title']
                if any(SequenceMatcher(None,norm(t),norm(work['title'])).ratio()>=.85 for t in titles):
                    for node in soup.find_all('meta'):
                        if node.get('name','').lower()=='citation_pdf_url':
                            target=urljoin(request['final_url'],node.get('content',''))
                            if target not in urls: urls.append(target)
            if request['status']=='pdf_downloaded':
                path=Path(request['raw_path'])
                if document_matches(path,work['title']):
                    candidate_pdf=path
                    result['collection_method']='http_public_pdf'
                    break
                result.setdefault('rejected_pdf_title_mismatches',[]).append(request['sha256'])
        if candidate_pdf is not None:
            raw_hash=sha(candidate_pdf.read_bytes())
            destination=output/'raw'/(raw_hash+'.pdf')
            if not destination.exists(): destination.write_bytes(candidate_pdf.read_bytes())
            blocks=list(iter_pdf_blocks(destination,{'source_id':raw_hash,'source_sha256':raw_hash,'source_file':str(destination)}))
            pages=[row for row in blocks if row['kind']=='page_outcome']
            complete=bool(pages) and all(row['page'] is not None and row['status'] in {'extracted','blank'} for row in pages)
            extracted=output/'extracted'/(raw_hash+'.jsonl')
            if not extracted.exists(): write_jsonl(extracted,blocks)
            result.update(status='full_document_extracted' if complete else 'partial_document',pdf_sha256=raw_hash,
                raw_path=str(destination.resolve()),extracted_path=str(extracted.resolve()),page_count=len(pages),
                title_match_first_two_pages=True)
        elif work['candidate_urls']:
            queue.append({**result,'source_url':work['source_url'],'candidate_urls':work['candidate_urls'],
                          'chrome_attempted_this_run':False})
        processed.append(result)
    write_jsonl(output/'work_results.jsonl',processed)
    write_jsonl(output/'chrome_queue.jsonl',queue)
    write_jsonl(output/'requests.jsonl',list(requests.values()))
    report={'scope':f'event_calendar_year_{calendar_year}_only' if calendar_year is not None else 'event_calendar_year_through_2024_inclusive','advisor_count':len(roster),'indexed_works':len(works),
            'eligible_works':len(eligible),'excluded_after_2024':len(future),'unresolved_dates':len(unresolved),
            'http_requests':len(requests),'request_budget':max_requests,'status_counts':dict(Counter(row['status'] for row in processed)),
            'unique_pdfs':len({row['pdf_sha256'] for row in processed if 'pdf_sha256'in row}),
            'chrome_pending':len(queue),'identity_approvals_granted':0,'historical_training_ready':False}
    candidate_urls={item['url'] for work in eligible for item in work['candidate_urls']}
    report.update(prior_request_count=previous_request_count,new_http_requests=len(requests)-previous_request_count,
        known_candidate_urls=len(candidate_urls),known_candidate_urls_untried=len(candidate_urls-set(requests)),
        works_with_untried_candidate_urls=sum(any(item['url']not in requests for item in work['candidate_urls'])for work in eligible),
        year_processing_order=f'calendar_year_{calendar_year}_only' if calendar_year is not None else '2024_first_then_older_descending',
        prior_runs=[str(Path(path).resolve())for path in prior_runs])
    results_by_id={row['work_id']:row for row in processed}
    focus_year = calendar_year or 2024
    work_focus=[row for row in eligible if row['event_year']==focus_year]
    attempted_focus={item['url']for row in work_focus for item in row['candidate_urls']if item['url']in requests}
    report[f'calendar_{focus_year}']={'candidate_records':len(work_focus),
        'status_counts':dict(Counter(results_by_id[row['work_id']]['status']for row in work_focus)),
        'candidate_urls_attempted':len(attempted_focus),
        'unique_pdfs_pending_review':len({results_by_id[row['work_id']]['pdf_sha256']for row in work_focus if 'pdf_sha256'in results_by_id[row['work_id']]})}
    report['resumed_partial_run']=continuing
    report['implementation_sha256']=sha(Path(__file__).read_bytes())
    report['output_hashes']={str(path.relative_to(output)):sha(path.read_bytes()) for path in output.rglob('*') if path.is_file()}
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--max-requests',type=int,default=100)
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--prior-run',type=Path,action='append',default=[])
    parser.add_argument('--calendar-year',type=int, help='Collect one calendar year only; use 2025 for the separate advisor run.')
    args=parser.parse_args()
    report=collect(args.root,args.output,max_requests=args.max_requests,resume=args.resume,prior_runs=args.prior_run,
                   calendar_year=args.calendar_year)
    print(json.dumps({k:v for k,v in report.items() if k!='output_hashes'}))
