"""Prepare pending supervision links and full-document thesis skill jobs.

Never edits source CSVs, moves theses, approves identities, or supplies outcomes.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.data_pipeline.pdf_extract import iter_pdf_blocks

POOLS = {'2024': '2025-08-31', '2025.1': '2025-12-31', '2025.2': '2026-05-31'}
LABEL = re.compile(r'giảng\s*viên\s*hướng\s*dẫn|người\s*hướng\s*dẫn(?:\s*khoa\s*học)?|'
                   r'cán\s*bộ\s*hướng\s*dẫn|\bGVHD\b', re.I)
BIBLIOGRAPHY = re.compile(r'^\s*(?:\d+[.)]?\s*)?(?:TÀI LIỆU THAM KHẢO|REFERENCES|BIBLIOGRAPHY)\s*$', re.I)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def normalize_name(text):
    text = text.casefold().replace('đ', 'd')
    return ' '.join(re.sub(r'[^a-z\s]', ' ', ''.join(c for c in unicodedata.normalize('NFD', text)
                                                  if not unicodedata.combining(c))).split())


def roster_name(text):
    text = re.sub(r'^(?:(?:PGS|GS|TS|ThS|Th\.S|Thạc sĩ|Tiến sĩ)[ .]+)+', '', text, flags=re.I)
    return normalize_name(text)


def advisor_candidates(pages, roster):
    candidates = {}
    for page in pages[:2]:
        text = page['text']
        for match in LABEL.finditer(text):
            # Cover label plus at most four following lines, not arbitrary mentions.
            after = text[match.end():].splitlines()[:4]
            quote = text[match.start():match.end()] + '\n'.join(after)
            folded = ' ' + normalize_name('\n'.join(after)) + ' '
            for row in roster:
                name = roster_name(row['name'])
                if name and (' ' + name + ' ') in folded:
                    candidates.setdefault(row['advisor_id'], []).append({
                        'page': page['page'], 'start': match.start(), 'quote': quote,
                        'match_method': 'exact_normalized_roster_name_in_cover_advisor_label_span'})
    return candidates


def month_partition(month):
    if not isinstance(month, str) or not re.fullmatch(r'\d{4}-\d{2}', month):
        raise ValueError('cover_month_required')
    year, number = map(int, month.split('-'))
    if not 1 <= number <= 12:
        raise ValueError('invalid_cover_month')
    term = f'{year}.1' if number >= 9 else f'{year-1}.{2 if number <= 5 else 3}'
    return ('2024' if month <= '2025-08' else term), term


def contained(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('source_path_outside_data_or_missing')
    return path


def read_pdf_pages(pdf, pdf_hash, cache_roots, cache_output):
    import pymupdf
    with pymupdf.open(pdf) as document:
        count = document.page_count
    for root in cache_roots:
        cache = root / (pdf_hash + '.jsonl')
        if cache.is_file():
            records = [json.loads(line) for line in cache.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
            # Historic cache is page-text format, distinct from parser block output.
            if (all(isinstance(r.get('page'), int) and isinstance(r.get('text'), str) for r in records)
                    and sorted(r['page'] for r in records) == list(range(1, count+1))):
                return records, {'path': str(cache), 'sha256': digest(cache), 'method': 'existing_page_text_cache',
                                 'cache_content_independently_verified': False}
    # Read every page's embedded text once. Image-heavy pages remain explicitly
    # pending OCR/review, avoiding expensive automatic OCR in a preparation job.
    result = []
    with pymupdf.open(pdf) as document:
        for page in document:
            try:
                text = page.get_text()
                images = page.get_image_info()
                area = page.rect.get_area()
                image_area = sum((pymupdf.Rect(image['bbox']) & page.rect).get_area() for image in images)
                needs_review = len(text.strip()) < 50 or (area > 0 and image_area / area >= .30)
                result.append({'page': page.number + 1, 'text': text, 'status': 'partial' if needs_review else 'extracted',
                               'reason': 'image_or_low_text_requires_review' if needs_review else ''})
            except Exception as error:
                result.append({'page': page.number + 1, 'text': '', 'status': 'failed', 'reason': type(error).__name__})
    path = cache_output / (pdf_hash + '.jsonl')
    path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in result), encoding='utf-8')
    return result, {'path': str(path), 'sha256': digest(path), 'method': 'pymupdf_all_pages_embedded_text',
                    'ocr_performed': False}


def thesis_units(pages):
    units, in_bibliography = [], False
    for page in pages:
        text = page['text']
        lines = text.splitlines()
        start = next((i for i, line in enumerate(lines) if BIBLIOGRAPHY.fullmatch(line)), None)
        if not in_bibliography and start is not None:
            # Keep method text preceding a bibliography heading on the same page.
            prefix = '\n'.join(lines[:start])
            suffix = '\n'.join(lines[start:])
            units.append({'unit_id': f"page:{page['page']}:body", 'text': prefix})
            units.append({'unit_id': f"page:{page['page']}:references", 'text': suffix, 'section': 'references'})
            in_bibliography = True
        else:
            units.append({'unit_id': f"page:{page['page']}", 'text': text,
                          'section': 'references' if in_bibliography else ''})
    return units


def prepare(data, registry, output, *, stop_file=None):
    data, registry, output = Path(data).resolve(), Path(registry).resolve(), Path(output).resolve()
    if output.is_relative_to(data):
        raise ValueError('output_must_be_outside_source_data')
    with registry.open(encoding='utf-8-sig', newline='') as stream:
        roster = list(csv.DictReader(stream))
    ids = [row['advisor_id'] for row in roster]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('unique_nonempty_registry_required')
    output.mkdir(parents=True, exist_ok=False)
    cache_output = output / 'extracted_pages'
    cache_output.mkdir()
    caches = [data / '_student_processing_20261101' / name / 'extracted'
              for name in ('pdf_extraction', 'docx_extraction')]
    # Reuse complete page caches from interrupted preparation runs as candidates.
    caches += sorted(output.parent.glob('supervision_preparation*/extracted_pages'))
    jobs, links, unresolved, excluded = [], [], [], []
    inputs = {str(registry): digest(registry)}
    seen, members = set(), {}
    persisted = {'links': 0, 'jobs': 0, 'unresolved': 0}
    source_counts = Counter()
    def checkpoint(pool):
        for key, records in (('links', links), ('jobs', jobs), ('unresolved', unresolved)):
            with (output / ('partial_' + key + '.jsonl')).open('a', encoding='utf-8') as stream:
                for record in records[persisted[key]:]:
                    stream.write(json.dumps(record, ensure_ascii=False) + '\n')
            persisted[key] = len(records)
        (output / 'progress.json').write_text(json.dumps({'current_pool': pool, 'links': len(links),
            'jobs': len(jobs), 'unresolved': len(unresolved), 'unique_theses_read': len(seen),
            'source_coverage_counts': dict(source_counts),
            'stop_requested': bool(stop_file and Path(stop_file).exists())}, indent=2), encoding='utf-8')
    for pool in (*POOLS, '2025.3'):
        csv_path = data / pool / 'student/students_processed/students_processed.csv'
        inputs[str(csv_path)] = digest(csv_path)
        with csv_path.open(encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream)
            if len(reader.fieldnames or []) != 40:
                raise ValueError('student_csv_40_columns_required')
            rows = list(reader)
        if pool == '2025.3':
            excluded.extend({'student_id': row['student_id'], 'source_pool': pool, 'reason': 'external_test_not_opened'} for row in rows)
            continue
        for row in rows:
            base = {'student_id': row['student_id'], 'source_pool': pool, 'source_file': row['source_file']}
            if stop_file and Path(stop_file).exists():
                unresolved.append({**base, 'reason': 'pending_stop_requested_source_not_opened'})
                source_counts['pending_stop_requested'] += 1
                checkpoint(pool)
                continue
            try:
                notes = json.loads(row['reviewer_notes'])
                cover = notes.get('cover_date', {})
                partition, term = month_partition(cover.get('date'))
                if partition != pool or cover.get('status') != 'resolved' or not cover.get('quote'):
                    raise ValueError('cover_partition_or_evidence_mismatch')
                source = contained(data, row['source_file'])
                source_hash = digest(source)
                if source_hash != row['source_sha256']:
                    raise ValueError('source_hash_mismatch')
                if row['source_type'] == 'docx':
                    pdf = contained(data, notes.get('rendered_pdf', ''))
                    pdf_hash = digest(pdf)
                    if pdf_hash != notes.get('rendered_pdf_sha256'):
                        raise ValueError('rendered_pdf_hash_mismatch')
                else:
                    pdf, pdf_hash = source, source_hash
                members.setdefault(pdf_hash, set()).add(row['student_id'])
                if pdf_hash in seen:
                    unresolved.append({**base, 'reason': 'duplicate_thesis_hash_not_scored_twice', 'pdf_sha256': pdf_hash})
                    continue
                seen.add(pdf_hash)
                pages, extraction = read_pdf_pages(pdf, pdf_hash, caches, cache_output)
                source_counts[extraction['method']] += 1
                inputs.update({str(source): source_hash, str(pdf): pdf_hash, extraction['path']: extraction['sha256']})
                matches = advisor_candidates(pages, roster)
                thesis_id = 'thesis_' + pdf_hash
                units = thesis_units(pages)
                shared = {**base, 'thesis_id': thesis_id, 'academic_term': term,
                          'cover_date': cover, 'source_cutoff': POOLS[pool],
                          'source_sha256': source_hash, 'document_sha256': pdf_hash,
                          'pdf_path': str(pdf), 'extraction': extraction,
                          'available_at': None, 'prediction_time_verified': False,
                          'evidence_scope': 'retrospective_document_proxy', 'training_eligibility': 'unresolved',
                          'split': None, 'review_status': 'pending', 'supervision_review_status': 'pending',
                          'identity_review_status': 'pending'}
                if not matches:
                    unresolved.append({**shared, 'reason': 'no_roster_advisor_in_cover_label_span',
                                       'cover_text': '\n'.join(p['text'] for p in pages[:2])})
                for advisor, proof in matches.items():
                    link_id = hashlib.sha256((thesis_id + ':' + advisor).encode()).hexdigest()
                    links.append({**shared, 'supervision_id': link_id, 'advisor_id': advisor,
                                  'student_ids': [row['student_id']], 'role': 'candidate_supervisor',
                                  'proof_refs': proof, 'match_status': 'candidate_needs_review'})
                    jobs.append({**shared, 'advisor_id': advisor, 'artifact_id': thesis_id,
                                 'supervision_id': link_id, 'channel': 'thesis',
                                 'content_scope': 'full_text_complete' if all(p['text'].strip() and p.get('status', 'extracted') == 'extracted' for p in pages) else 'partial_full_text',
                                 'text_units': units, 'expected_units': [u['unit_id'] for u in units],
                                 'bibliography_exclusion': 'references_and_subsequent_pages_conservatively_excluded'})
            except (ValueError, OSError, KeyError, TypeError) as error:
                unresolved.append({**base, 'reason': type(error).__name__ + ':' + str(error)})
                source_counts['source_unresolved'] += 1
            finally:
                checkpoint(pool)
    for record in links + jobs:
        record['student_ids'] = sorted(members[record['document_sha256']])
    for name, records in (('supervision_links.jsonl', links), ('thesis_jobs.jsonl', jobs),
                          ('unresolved.jsonl', unresolved), ('excluded_external.jsonl', excluded)):
        (output / name).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in records), encoding='utf-8')
    report = {'candidate_links': len(links), 'thesis_jobs': len(jobs), 'unique_theses_read': len(seen),
              'jobs_per_pool': dict(Counter(j['source_pool'] for j in jobs)), 'unresolved': len(unresolved),
              'source_coverage_counts': dict(source_counts),
              'stop_requested': bool(stop_file and Path(stop_file).exists()),
              'excluded_external_students': len(excluded), 'identity_approvals_granted': 0,
              'historical_training_ready': False, 'scores_published': 0}
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    manifest = {'schema_version': 'advisor-supervision-preparation/1', 'created_at': datetime.now(timezone.utc).isoformat(),
                'script_sha256': digest(__file__), 'parser_sha256': digest(ROOT / 'src/data_pipeline/pdf_extract.py'),
                'input_hashes': inputs, 'output_hashes': {str(p.relative_to(output)): digest(p) for p in output.rglob('*') if p.is_file()},
                'source_csvs_modified': False}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=ROOT / 'data')
    parser.add_argument('--registry', type=Path, default=ROOT / 'data/2024/advisors/faculty_profiles/advisors_profile.csv')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stop-file', type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.data, args.registry, args.output, stop_file=args.stop_file)))
