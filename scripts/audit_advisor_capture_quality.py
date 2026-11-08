"""Read-only quality audit of Chrome publication detail captures.

This reports access failures and review needs; it never verifies identities,
approves claims or treats a Scholar description as complete article text.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit


BLOCK_NOTICES = re.compile(
    r'security check required|unusual (?:activity|traffic)|verify (?:that )?you are human|'
    r'complete the security check|access denied|just a moment[.!]?|'
    r'lưu lượng truy cập bất thường|hoạt động bất thường|xác minh bạn là con người|'
    r'vérifiez que vous êtes humain|trafic inhabituel|ungewöhnlichen datenverkehr|'
    r'异常流量|人机验证', re.IGNORECASE)
GENERIC_TITLES = {'', 'view', 'read', 'download', 'full text', 'view full text',
                  'read full-text', 'download pdf', 'pdf', 'xem', 'tải xuống'}
KNOWN_REVIEWER_FLAGS = {
    '15': ('Eksplorasi dan Pemetaan Potensi Wisata Kampung Batu Busuk, Kecamatan Pauh, Kota Padang',
           'Capture profile header is Quan Dang Minh; displayed author list is '
           'PK Dewi Hayati, Yonariza Yonariza, Rudi Febriamansyah, Eri Besra, Virtuous Setyaka. '
           'The claimed advisor is absent; quarantine the article-person link pending review.'),
    '94': ('Discovery of giant, non-saturating thermopower in topological semimetal at quantum limit',
           'Capture profile header is Nguyễn Thanh Hương; displayed paper author list '
           'contains Thanh Nguyen and Quynh Nguyen, not Nguyễn Thanh Hương. '
           'Do not approve the article-person link from profile membership alone.'),
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def classify_capture(capture, capture_id):
    """Use visible access notices, never guess person identity from names."""
    text = capture.get('text', '')
    if not isinstance(text, str):
        raise ValueError('capture_text_must_be_string')
    source = capture.get('source_url', capture.get('url', ''))
    title = capture.get('source_title', '')
    if not isinstance(source, str) or not isinstance(title, str):
        raise ValueError('capture_source_and_title_must_be_strings')
    reasons = []
    final_url = capture.get('url', '')
    if not isinstance(final_url, str):
        raise ValueError('capture_url_must_be_string')
    for url in (source, final_url):
        path = urlsplit(url).path.casefold()
        if re.search(r'(?:^|/)(?:sorry|captcha)(?:/|$)', path):
            reasons.append('block_url')
    if BLOCK_NOTICES.search(text):
        reasons.append('block_notice')
    generic = title.strip().casefold() in GENERIC_TITLES
    blocked = bool(reasons)
    if blocked:
        access = 'blocked'
    elif not text.strip():
        access = 'empty'
    elif len(text.strip()) < 300:
        access = 'short_needs_review'
    else:
        access = 'captured_needs_review'
    return {
        'capture_id': capture_id, 'source_url': source, 'source_title': title,
        'characters': len(text), 'access_status': access,
        'block_reasons': sorted(set(reasons)), 'generic_title': generic,
        'title_status': 'needs_review' if generic else 'candidate_unverified',
        'article_person_status': 'needs_review',
        'content_scope': 'unavailable' if blocked or not text.strip() else 'captured_unverified',
        'full_text_verified': False, 'historical_training_ready': False,
        'available_at': capture.get('available_at'), 'review_status': 'pending',
    }


def audit(details, output):
    details, output = Path(details).resolve(), Path(output).resolve()
    if not details.is_dir():
        raise ValueError('details_directory_required')
    if output == details or output.is_relative_to(details):
        raise ValueError('output_must_be_outside_captures')
    records, reviewer_flags = [], []
    paths = sorted(details.glob('*.json'), key=lambda p: (not p.stem.isdigit(),
                                                        int(p.stem) if p.stem.isdigit() else p.stem))
    if not paths:
        raise ValueError('no_capture_files')
    for path in paths:
        capture = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(capture, dict):
            raise ValueError('capture_must_be_object')
        record = classify_capture(capture, path.stem)
        record.update({'capture_path': str(path), 'capture_sha256': digest(path)})
        records.append(record)
        expected = KNOWN_REVIEWER_FLAGS.get(path.stem)
        if expected is not None and capture.get('source_title') == expected[0]:
            reviewer_flags.append({
                'capture_id': path.stem, 'capture_path': str(path),
                'capture_sha256': record['capture_sha256'], 'source_title': expected[0],
                'reason': expected[1], 'classification': 'reviewer_identified_attribution_mismatch',
                'review_status': 'needs_review', 'identity_approved': False,
                'basis': 'manual inspection of displayed profile header and article authors',
            })
    # Build all data before allocating an immutable output directory.
    summary = {
        'schema_version': 'advisor-capture-quality/1', 'captures': len(records),
        'access_counts': dict(sorted(Counter(r['access_status'] for r in records).items())),
        'generic_titles': sum(r['generic_title'] for r in records),
        'known_reviewer_attribution_flags': len(reviewer_flags),
        'available_at_missing': sum(not r['available_at'] for r in records),
        'full_text_verified': False, 'historical_training_ready': False,
        'identity_approvals_granted': 0,
    }
    output.mkdir(parents=True, exist_ok=False)
    files = {'capture_quality.jsonl': records, 'reviewer_attribution_flags.jsonl': reviewer_flags}
    for name, rows in files.items():
        (output / name).write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n'
                                         for row in rows), encoding='utf-8')
    (output / 'report.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    manifest = {
        'schema_version': 'advisor-capture-quality/1',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'audit_code_sha256': digest(__file__),
        'input_hashes': {str(p): digest(p) for p in paths},
        'output_hashes': {p.name: digest(p) for p in output.iterdir() if p.is_file()},
        'source_captures_modified': False,
    }
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--details', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(audit(args.details, args.output), ensure_ascii=True))


if __name__ == '__main__':
    main()
