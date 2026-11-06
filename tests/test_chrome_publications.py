import importlib.util
from pathlib import Path


def test_only_actual_publication_detail_links_are_kept():
    path = Path(__file__).parents[1] / 'scripts/prepare_chrome_publications.py'
    spec = importlib.util.spec_from_file_location('chrome_publications', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.publication_url('https://scholar.google.com/citations?view_op=view_citation&citation_for_view=abc:def&hl=vi')
    assert module.publication_url('https://www.researchgate.net/publication/123_Title')
    assert module.publication_url('https://www.researchgate.net/publication/123_Title/figures') is None
    assert module.publication_url('https://scholar.google.com/citations?user=abc') is None
    assert module.publication_url('javascript:alert(1)') is None
