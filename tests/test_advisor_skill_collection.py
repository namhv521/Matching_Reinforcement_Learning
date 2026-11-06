import csv
import json

import pytest

from src.data_pipeline.advisor_skill_collection import collect_seed_profiles, record_chrome_capture


def seed(tmp_path, url='https://fit.neu.edu.vn/lecturer/sample'):
    path = tmp_path / 'seed.csv'
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=['advisor_id', 'name', 'university_url', 'scholar_url', 'researchgate_url', 'github_url'])
        writer.writeheader()
        writer.writerow({'advisor_id': 'a', 'name': 'Sample', 'university_url': url})
    return path


def test_failed_fetch_queues_chrome_and_capture_is_immutable(tmp_path):
    output = tmp_path / 'run'
    report = collect_seed_profiles(seed(tmp_path), output, fetcher=lambda url: (b'Forbidden', 403, url))
    assert report['chrome_pending'] == 1 and not report['chrome_attempted']
    task = json.loads((output / 'chrome_queue.jsonl').read_text())
    capture = record_chrome_capture(output, task['request_id'], text='Actual browser text',
                                    final_url=task['source_url'], captured_at='2026-11-02T10:00:00+07:00')
    assert capture['collection_method'] == 'chrome_ui' and capture['available_at'] is None
    with pytest.raises(FileExistsError):
        record_chrome_capture(output, task['request_id'], text='Changed', final_url=task['source_url'], captured_at='2026-11-02T10:00:00+07:00')
    with pytest.raises(FileExistsError):
        collect_seed_profiles(tmp_path / 'seed.csv', output)


def test_reject_private_seed_and_redirect(tmp_path):
    with pytest.raises(ValueError, match='public_seed'):
        collect_seed_profiles(seed(tmp_path, 'https://127.0.0.1/private'), tmp_path / 'bad')
    output = tmp_path / 'run'
    report = collect_seed_profiles(seed(tmp_path), output, fetcher=lambda url: (b'', 200, 'https://127.0.0.1/private'))
    assert report['chrome_pending'] == 1
    task = json.loads((output / 'chrome_queue.jsonl').read_text())
    with pytest.raises(ValueError, match='public_seed'):
        record_chrome_capture(output, task['request_id'], text='x', final_url='https://127.0.0.1/private', captured_at='2026-11-02T10:00:00Z')


def test_official_profile_parser_reused_without_approving(tmp_path):
    body = ('<div class="info-lecturer_name-content"><h1>Sample</h1></div>'
            '<div class="info-lecturer_content">Research about data analysis and natural language processing applications.</div>').encode()
    report = collect_seed_profiles(seed(tmp_path), tmp_path / 'run', fetcher=lambda url: (body, 200, url))
    assert report['status_counts'] == {'success': 1}
    profile = json.loads((tmp_path / 'run/profiles.jsonl').read_text())
    assert profile['review_status'] == 'pending'
    assert profile['parsed_official_profile']['advisor_name'] == 'Sample'


def test_budget_exhaustion_not_claimed_as_browser_attempt(tmp_path):
    path = seed(tmp_path)
    with path.open('a', encoding='utf-8') as stream:
        stream.write('b,Other,https://fit.neu.edu.vn/lecturer/other,,,\n')
    report = collect_seed_profiles(path, tmp_path / 'run', max_urls=1, fetcher=lambda url: (b'', 500, url))
    assert report['status_counts'] == {'needs_chrome': 1, 'budget_exceeded': 1}
    assert report['attempted_urls'] == 1 and not report['chrome_attempted']
