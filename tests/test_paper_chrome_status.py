import importlib.util
from pathlib import Path


def test_local_failures_are_not_source_visits():
    path = Path(__file__).parents[1] / 'scripts/audit_paper_chrome_status.py'
    spec = importlib.util.spec_from_file_location('paper_chrome_status', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.classify({'error': 'ReferenceError: bt is not defined', 'chrome_attempted': True}) == ('orchestration_not_attempted', False)
    assert module.classify({'error': 'Error: Debugger unattached', 'chrome_attempted': True}) == ('transport_unavailable_not_attempted', False)
    assert module.classify({'error': 'Timed out Page.navigate'}) == ('navigation_error_source_visit_unconfirmed', True)
    assert module.classify({'text': 'Thực hiện xác minh bảo mật'}) == ('browser_access_challenge', True)
