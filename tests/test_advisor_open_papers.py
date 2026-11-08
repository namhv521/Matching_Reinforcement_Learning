import importlib.util
from pathlib import Path


def test_pdf_discovery_uses_publisher_citation_metadata():
    path = Path(__file__).parents[1] / 'scripts/resolve_advisor_open_papers.py'
    spec = importlib.util.spec_from_file_location('open_papers', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    html = b'<meta name="citation_title" content="Own paper"><meta name="citation_author" content="A. Author"><meta name="citation_pdf_url" content="/own.pdf"><a href="/unrelated.pdf">Reference</a>'
    result = module.citation_metadata(html, 'https://example.org/article')
    assert result['pdf_urls'] == ['https://example.org/own.pdf']
    assert result['titles'] == ['Own paper']
    assert result['authors'] == ['A. Author']
