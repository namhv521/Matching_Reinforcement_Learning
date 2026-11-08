import importlib.util
import json
from pathlib import Path

import pymupdf


def test_recovery_preserves_truth_and_redacts_signed_url(tmp_path):
    path = Path(__file__).parents[1] / 'scripts/recover_advisor_paper_chrome.py'
    spec = importlib.util.spec_from_file_location('recover_paper', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    metadata, queue = tmp_path / 'metadata.json', tmp_path / 'queue.jsonl'
    signed_url = 'https://example.org/paper.pdf?token=secret'
    metadata.write_text(json.dumps({'requested_url': 'https://example.org/original.pdf', 'final_url': signed_url}))
    tasks = [{'request_id': str(i), 'source_url': f'https://example.org/{name}.pdf', 'publications': []}
             for i, name in enumerate(('original', 'error', 'missing'))]
    queue.write_text(''.join(json.dumps(row) + '\n' for row in tasks))
    chrome = tmp_path / 'chrome'
    chrome.mkdir()
    (chrome / '0.json').write_text(json.dumps({'text': '', 'error': 'Timed out'}))
    (chrome / '1.json').write_text(json.dumps({'error': 'Debugger unattached'}))
    doc = pymupdf.open()
    doc.new_page().insert_text((40, 40), 'Public paper text for full page extraction.')
    body = doc.tobytes()
    doc.close()
    output = tmp_path / 'recovery'
    report = module.recover_redirect(metadata, queue, chrome, output,
        fetcher=lambda url: {'body': body, 'status': 200, 'final_url': url})
    assert report['recovered_pages'] == 1 and report['recovered_status'] == 'pdf_extracted'
    assert report['status_counts'] == {'browser_navigation_error': 1, 'debugger_unattached': 1, 'unattempted': 1}
    assert 'token=secret' not in (output / 'receipt.json').read_text()
    assert not report['historical_training_ready']
