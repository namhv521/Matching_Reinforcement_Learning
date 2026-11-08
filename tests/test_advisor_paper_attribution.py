import importlib.util
from pathlib import Path


def test_vietnamese_d_stroke_preserved_for_attribution():
    path = Path(__file__).parents[1] / 'scripts/audit_advisor_paper_attribution.py'
    spec = importlib.util.spec_from_file_location('paper_attribution', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.normalized('ĐẶNG MINH QUÂN') == 'dang minh quan'
