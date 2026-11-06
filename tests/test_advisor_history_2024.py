import importlib.util
import json
from pathlib import Path
import pytest


def module():
    path=Path(__file__).parents[1]/'scripts/collect_advisor_history_2024.py'
    spec=importlib.util.spec_from_file_location('history_2024',path)
    result=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_citation_chart_and_references_do_not_date_paper():
    m=module()
    assert m.browser_date({'text':'Paper\nCitations\n2024\nReferences\n2020'}) is None
    d=m.browser_date({'text':'Ngày xuất bản\n2023/5/8\nTổng trích dẫn\n2026'})
    assert d['event_year']==2023 and d['date_precision']=='day'
    assert m.browser_date({'url':'https://www.researchgate.net/publication/123','text':'Article\nOwn title\nMay 2024Journal of Science\nAuthors:\nA\nReferences\n2026'})['event_year']==2024


def test_year_only_and_field_conflict():
    m=module()
    assert m.date_field('2024')=={'event_year':2024,'date_precision':'year','date_witness':'2024'}
    assert m.date_field('2024/13/2') is None
    assert m.corpus_date({'published_at':'2025','publication_year':'2024','date_evidence':'(2024)'}) is None
    assert m.corpus_date({'published_at':'2024','publication_year':'2024','date_evidence':'(2024)'})['event_year']==2024


def test_partial_resume_checks_indexes_and_completed_run_is_immutable(tmp_path,monkeypatch):
    m=module()
    roster=[{'advisor_id':'a'}]
    monkeypatch.setattr(m,'build_index',lambda root:(roster,[]))
    monkeypatch.setattr(m,'cache_index',lambda root:[])
    output=tmp_path/'run'
    output.mkdir()
    for name,rows in [('registry.jsonl',roster),('eligible_works.jsonl',[]),('excluded_after_2024.jsonl',[]),('unresolved_dates.jsonl',[])]:
        (output/name).write_text(''.join(json.dumps(row)+'\n'for row in rows),encoding='utf-8')
    report=m.collect(tmp_path,output,max_requests=0,resume=True)
    assert report['resumed_partial_run'] and report['http_requests']==0
    with pytest.raises(ValueError,match='completed_run_is_immutable'):
        m.collect(tmp_path,output,max_requests=0,resume=True)


def test_all_eligible_rows_have_status_and_prior_requests_are_not_repeated(tmp_path,monkeypatch):
    m=module()
    roster=[{'advisor_id':'a'}]
    work={'work_id':'paper','advisor_id':'a','title':'A sufficiently long article title','event_year':2024,
          'timing':{'event_year':2024},'content_type':'publication','source_url':'https://example.org/article',
          'candidate_urls':[{'url':'https://example.org/paper.pdf','kind':'pdf'}]}
    award={**work,'work_id':'award','content_type':'award','candidate_urls':[]}
    monkeypatch.setattr(m,'build_index',lambda root:(roster,[work,award]))
    monkeypatch.setattr(m,'cache_index',lambda root:[])
    first=tmp_path/'first'
    m.collect(tmp_path,first,max_requests=1,fetcher=lambda url:{'body':b'Forbidden','status':403,'final_url':url})
    second=m.collect(tmp_path,tmp_path/'second',max_requests=1,prior_runs=[first],
                     fetcher=lambda url:pytest.fail('duplicate request'))
    assert second['new_http_requests']==0 and second['prior_request_count']==1
    results=m.read_jsonl(tmp_path/'second/work_results.jsonl')
    assert len(results)==2 and next(r for r in results if r['work_id']=='award')['status']=='metadata_indexed_nonpaper'


def test_known_identity_mismatch_never_downloads_or_links_pdf(tmp_path,monkeypatch):
    m=module()
    work={'work_id':'bad','advisor_id':'a','title':'Wrong author article','event_year':2024,
          'timing':{'event_year':2024},'content_type':'publication','source_url':'https://example.org/article',
          'candidate_urls':[{'url':'https://example.org/paper.pdf','kind':'pdf'}]}
    monkeypatch.setattr(m,'build_index',lambda root:([{'advisor_id':'a'}],[work]))
    monkeypatch.setattr(m,'cache_index',lambda root:[])
    monkeypatch.setattr(m,'identity_flags',lambda root:{('a',m.norm(work['title'])):'exclude_wrong_author_candidate'})
    report=m.collect(tmp_path,tmp_path/'run',fetcher=lambda url:pytest.fail('quarantined fetch'))
    row=m.read_jsonl(tmp_path/'run/work_results.jsonl')[0]
    assert row['status']=='quarantined_identity' and 'pdf_sha256'not in row
    assert report['calendar_2024']['unique_pdfs_pending_review']==0


def test_calendar_year_mode_crawls_only_2025(tmp_path, monkeypatch):
    m=module()
    roster=[{'advisor_id':'a'}]
    work=lambda key, year: {'work_id':key,'advisor_id':'a','title':'A sufficiently long article title '+key,
        'event_year':year,'timing':{'event_year':year},'content_type':'award',
        'source_url':'https://example.org/'+key,'candidate_urls':[]}
    monkeypatch.setattr(m,'build_index',lambda root:(roster,[work('old',2024),work('current',2025),work('future',2026)]))
    monkeypatch.setattr(m,'cache_index',lambda root:[])
    report=m.collect(tmp_path,tmp_path/'run',max_requests=0,calendar_year=2025)
    assert report['scope']=='event_calendar_year_2025_only'
    assert report['eligible_works']==1
    assert m.read_jsonl(tmp_path/'run/eligible_works.jsonl')[0]['work_id']=='current'
