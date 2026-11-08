import importlib.util
from pathlib import Path


def test_observed_links_only_and_exact_dedup():
    path = Path(__file__).parents[1] / 'scripts/discover_advisor_sources.py'
    spec = importlib.util.spec_from_file_location('discovery', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.observed_links(
        '<a href="/paper#abstract">Paper</a><a href="/paper#full">Copy</a>'
        '<a href="mailto:a@example.org">email</a><a href="javascript:alert(1)">bad</a>'
        '<a href="https://doi.org/10.example/x">DOI</a>', 'https://fit.neu.edu.vn/profile')
    assert result == [('https://doi.org/10.example/x', 'DOI'),
                      ('https://fit.neu.edu.vn/paper', 'Paper')]
