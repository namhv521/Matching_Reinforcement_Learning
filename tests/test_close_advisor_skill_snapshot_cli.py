import json

from scripts.close_advisor_skill_snapshot import main


def test_partition_appends_into_existing_data_root(tmp_path):
    data_root = tmp_path / 'data'
    (data_root / '2025.1' / 'advisors' / 'faculty_corpus').mkdir(parents=True)
    candidates = tmp_path / 'candidates.jsonl'
    candidates.write_text(json.dumps({'artifact_id': 'p1', 'advisor_id': 'a', 'title': 'T',
                                      'event_date': '2025-03-04', 'available_at': None}) + '\n',
                          encoding='utf-8')

    assert main(['partition', '--candidates', str(candidates), '--data-root', str(data_root),
                 '--output', str(tmp_path / 'run')]) == 0

    written = list((data_root / '2025.1' / 'advisors' / 'faculty_corpus').glob('advisor_candidates.*.jsonl'))
    assert len(written) == 1
    row = json.loads(written[0].read_text(encoding='utf-8'))
    assert row['academic_term'] == '2024.2' and row['available_at'] is None
    assert row['dedup_status'] == 'singleton'
    manifest = json.loads((tmp_path / 'run' / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['counts'] == {'2025.1': 1}
