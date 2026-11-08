import json

import pymupdf
import pytest

from src.data_pipeline.advisor_paper_fulltext import collect_papers, observed_paper_link, validate_public_url
from src.data_pipeline import advisor_paper_fulltext as module


@pytest.mark.parametrize('address', ['127.0.0.1', '10.0.0.3', '169.254.169.254', '::1'])
def test_private_dns_rejected(address):
    with pytest.raises(ValueError, match='nonpublic_dns'):
        validate_public_url('https://example.org/paper.pdf', resolver=lambda *a, **k: [(None, None, None, None, (address, 443))])


def test_observed_pdf_and_doi():
    assert observed_paper_link('https://doi.org/10.1234/a') == 'doi'
    assert observed_paper_link('https://example.org/paper.pdf') == 'pdf'
    assert observed_paper_link('javascript:void(0)', '[PDF]') is None


def test_redirect_to_private_host_is_rejected_before_connect(monkeypatch):
    original = module.validate_public_url
    monkeypatch.setattr(module, 'validate_public_url', lambda url: original(url, resolver=lambda host, *a, **k:
        [(None, None, None, None, ('127.0.0.1' if host == 'localhost.example' else '93.184.216.34', 443))]))
    opened = []

    class Response:
        status = 302

        def getheaders(self):
            return [('Location', 'https://localhost.example/internal')]

        def getheader(self, key):
            return dict(self.getheaders()).get(key)

    class Connection:
        def __init__(self, host, *args, **kwargs):
            opened.append(host)

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(module.http.client, 'HTTPSConnection', Connection)
    with pytest.raises(ValueError, match='nonpublic_dns'):
        module.bounded_public_fetch('https://example.org/paper.pdf')
    assert opened == ['example.org']


def test_signature_all_pages_and_alias_dedup(tmp_path):
    captures = tmp_path / 'captures'
    captures.mkdir()
    article_url = 'https://scholar.google.com/citations?citation_for_view=abc:paper'
    pdf_url = 'https://example.org/paper.pdf'
    (captures / '1.json').write_text(json.dumps({'url': 'https://example.org/final', 'source_url': article_url, 'links': [{'url': pdf_url, 'text': '[PDF]'}]}))
    (captures / '2.json').write_text((captures / '1.json').read_text())
    index = tmp_path / 'index.jsonl'
    index.write_text(json.dumps({'advisor_id': 'a', 'artifact_id': 'paper', 'title': 'Paper', 'detail_urls': [article_url]}) + '\n')
    document = pymupdf.open()
    for number in range(2):
        page = document.new_page()
        page.insert_text((30, 30), f'We use Python for analysis on page {number}.')
    body = document.tobytes()
    document.close()
    report = collect_papers(captures, index, tmp_path / 'run', fetcher=lambda url: {'body': body, 'status': 200, 'final_url': url})
    assert report['pdf_candidate_count'] == 1
    assert report['status_counts'] == {'pdf_extracted': 1}
    receipt = json.loads((tmp_path / 'run/downloads.jsonl').read_text())
    assert receipt['page_count'] == 2 and receipt['available_at'] is None
    assert receipt['http_status'] == 200
    assert receipt['publications'][0]['artifact_id'] == 'paper'
    assert report['implementation_hashes']['downloader']
    assert len(receipt['provenance']) == 2
    bad = collect_papers(captures, index, tmp_path / 'bad', fetcher=lambda url: {'body': b'<html>captcha</html>', 'status': 200, 'final_url': url})
    assert bad['chrome_pending'] == 1


def test_blocked_capture_quality_excludes_links(tmp_path):
    captures = tmp_path / 'captures'
    captures.mkdir()
    capture = captures / 'blocked.json'
    capture.write_text(json.dumps({'url': 'https://example.org/article', 'links': [{'url': 'https://example.org/paper.pdf'}]}))
    quality = tmp_path / 'quality.jsonl'
    quality.write_text(json.dumps({'capture_path': str(capture.resolve()), 'capture_sha256': module.sha(capture.read_bytes()), 'access_status': 'blocked'}) + '\n')
    index = tmp_path / 'index.jsonl'
    index.write_text('')
    report = collect_papers(captures, index, tmp_path / 'run', capture_quality=quality,
                            fetcher=lambda url: pytest.fail('blocked source fetched'))
    assert report['blocked_captures_excluded'] == 1
    assert report['attempted_downloads'] == 0
