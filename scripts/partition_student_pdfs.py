"""Re-extract local theses, partition by centred cover dates, then verify moves.

The 40-column import template is preserved. Skill tags are document mentions,
not measured proficiency. Run without --apply first to produce a review plan.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.data_pipeline.normalization import load_taxonomy, normalize_mentions
from src.data_pipeline.student_candidates import extract_candidates

TERMS = ('2024', '2025.1', '2025.2', '2025.3')
TECH_GROUPS = ('programming_languages', 'frameworks_libraries', 'databases',
               'ml_ai_methods', 'data_engineering_tools', 'cloud_devops_tools',
               'security_network_tools', 'software_engineering_methods',
               'research_methods', 'math_statistics_topics')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def clean(text):
    return unicodedata.normalize('NFC', text).replace('\u200b', '').replace('\ufeff', '')


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def partition_for(value):
    year, month = map(int, value[:7].split('-'))
    if not 1 <= month <= 12:
        raise ValueError('invalid_month')
    term = f'{year}.1' if month >= 9 else f'{year - 1}.{2 if month <= 5 else 3}'
    partition = '2024' if (year, month) <= (2025, 8) else term
    return (partition if partition in TERMS else None), term


def page_lines(page, textpage=None):
    if isinstance(textpage, list):
        return textpage
    lines = []
    flags = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES
    for block in page.get_text('dict', flags=flags, textpage=textpage)['blocks']:
        for line in block.get('lines', []):
            text = clean(''.join(span['text'] for span in line['spans'])).strip()
            if text:
                lines.append({'text': text, 'bbox': list(line['bbox']), 'dir': list(line['dir'])})
    return lines


def cover_date(document, textpages=None):
    """Only horizontal, bottom-centre text on the first two cover pages counts."""
    seen = []
    for index in range(min(2, len(document))):
        page = document[index]
        lines = page_lines(page, (textpages or {}).get(index))
        frame = page.rect
        # Similarity reports embed a reduced thesis cover within a larger page.
        # Its footer is relative to that image, not to the enclosing report page.
        if len(page.get_text().strip()) < 50:
            images = page.get_image_info()
            if images:
                image_frame = max((pymupdf.Rect(image['bbox']) for image in images), key=lambda rect: rect.get_area())
                if image_frame.get_area() > .3 * page.rect.get_area():
                    frame = image_frame
        body = '\n'.join(line['text'] for line in lines)
        if index and not re.search(r'(?:khóa|khoá)\s+luận|chuyên\s+đề\s+tốt\s+nghiệp|khoa\s+luan\s+tot\s+nghiep|đề\s+án\s+công\s+nghệ\s+thông\s+tin', body, re.I):
            continue
        candidates = []
        for line in lines:
            box = line['bbox']
            if abs(line['dir'][1]) > .15 or box[1] < frame.y0 + .65 * frame.height:
                continue
            if not frame.x0 + .28 * frame.width < (box[0] + box[2]) / 2 < frame.x0 + .72 * frame.width:
                continue
            text = line['text']
            seen.append({'page': index + 1, 'text': text, 'bbox': box})
            if re.search(r'ngày\s*nộp|submission|turnitin|https?://|\.docx?\b|\.pdf\b', text, re.I):
                continue
            # Year.first-semester notation (2025.1) never matches month/year.
            match = re.search(r'tháng\s*(\d{1,2})\s*(?:năm|[/,.-])?\s*((?:19|20)\d{2})(?!\d)', text, re.I)
            if not match:
                match = re.search(r'(?<![\d/.])(\d{1,2})\s*[/.-]\s*((?:19|20)\d{2})(?![\d.])', text)
            if match and 1 <= int(match[1]) <= 12:
                value = f'{match[2]}-{int(match[1]):02d}'
                partition, term = partition_for(value)
                candidates.append({'date': value, 'page': index + 1, 'quote': text,
                                   'bbox': box, 'partition': partition, 'academic_term': term})
        if candidates:
            if len({item['date'] for item in candidates}) != 1:
                return {'status': 'unresolved', 'reason': 'conflicting_centre_cover_dates', 'candidates': candidates}
            return {**candidates[0], 'status': 'resolved' if candidates[0]['partition'] else 'outside_requested_periods'}
    return {'status': 'unresolved', 'reason': 'month_year_missing_from_centre_cover', 'centre_text': seen}


def grouped_cover(page, textpage=None):
    horizontal = [line for line in page_lines(page, textpage) if abs(line['dir'][1]) < .15
                  and (line['bbox'][0] + line['bbox'][2]) / 2 > .12 * page.rect.width]
    groups = []
    for line in sorted(horizontal, key=lambda item: (round(item['bbox'][1] / 3), item['bbox'][0])):
        if groups and abs(groups[-1][0] - line['bbox'][1]) < 3:
            groups[-1][1].append(line)
        else:
            groups.append((line['bbox'][1], [line]))
    return [' '.join(item['text'] for item in sorted(group, key=lambda item: item['bbox'][0]))
            for _, group in groups]


def title_from_cover_lines(pages):
    marker = re.compile(r'^(?:tên\s+)?đề\s+tài\s*[:：]?\s*(.*)$', re.I)
    heading = re.compile(r'(?:khóa|khoá)\s+luận\s+tốt\s+nghiệp|khoa\s+luan\s+tot\s+nghiep|chuyên\s+đề\s+(?:thực\s+tập|tốt\s+nghiệp)|đề\s+án\s+công\s+nghệ\s+thông\s+tin', re.I)
    stop = re.compile(r'^(?:tên\s+sinh\s+viên|họ\s+(?:và\s+)?tên|sinh\s+viên\s+thực\s+hiện|giảng\s+viên|giáo\s+viên|mã\s+(?:số\s+)?sinh\s+viên|mssv|lớp\b|ngành\b|khoa\b|hệ\s+đào\s+tạo|hà\s+nội|đại\s+học|trường\b)', re.I)
    for lines in pages:
        explicit = [(i, marker.match(line)) for i, line in enumerate(lines) if marker.match(line)]
        starts = [(i, match[1]) for i, match in explicit]
        if not starts:
            starts = [(i, '') for i, line in enumerate(lines) if heading.search(line)]
        for index, initial in starts:
            parts = [initial] if initial else []
            for line in lines[index + 1:]:
                if stop.search(line) or marker.match(line) or heading.search(line):
                    break
                if re.search(r'\w', line):
                    parts.append(line)
            title = ' '.join(' '.join(parts).split()).strip(' :')
            if (title.startswith('“') and title.endswith('”')) or (title.startswith('"') and title.endswith('"')):
                title = title[1:-1].strip()
            if len(title) >= 8 and not marker.fullmatch(title):
                return title
    return None


def metadata(document, sha, filename, textpages=None):
    blocks = []
    for index in range(min(2, len(document))):
        for i, text in enumerate(grouped_cover(document[index], (textpages or {}).get(index))):
            blocks.append({'text': text, 'page': index + 1, 'kind': 'block',
                           'source_sha256': sha, 'source_file': filename,
                           'block_id': f'cover-{index + 1}-{i}', 'locator': f'page:{index + 1}'})
    candidates = extract_candidates(blocks)
    fields = candidates[0]['fields'] if len(candidates) == 1 else {}
    result = {name: field['value'] for name, field in fields.items()}
    text = '\n'.join(block['text'] for block in blocks)
    if not result.get('student_id'):
        # Spine text may corroborate identity, but never determines the date.
        native_cover = '\n'.join(document[i].get_text() for i in range(min(2, len(document))))
        ids = set(re.findall(r'(?<!\d)\d{8}(?!\d)', native_cover))
        if len(ids) == 1:
            result['student_id'] = next(iter(ids))
    if not result.get('student_name'):
        match = re.search(r'(?:tên\s+sinh\s+viên|họ\s+(?:và\s+)?tên(?:\s+sinh\s+viên)?|sinh\s+viên\s+thực\s+hiện)\s*[:：]?\s*([^\n]+)', text, re.I)
        if match:
            result['student_name'] = match[1].strip(' :')
    if not result.get('thesis_title'):
        match = re.search(r'(?:(?:khóa|khoá)\s+luận\s+tốt\s+nghiệp|khoa\s+luan\s+tot\s+nghiep|đề\s+án\s+công\s+nghệ\s+thông\s+tin)[”"»]?\s*\n+(.*?)(?=\n\s*(?:tên\s+sinh\s+viên|họ\s+(?:và\s+)?tên|sinh\s+viên\s+thực\s+hiện|mã\s+sinh\s+viên))', text, re.I | re.S)
        if match:
            title = re.sub(r'^\s*(?:đề\s+tài|tên\s+đề\s+tài)\s*[:：]?\s*', '', match[1], flags=re.I)
            result['thesis_title'] = ' '.join(title.split()).strip(' :“”"')
    title = title_from_cover_lines([grouped_cover(document[i], (textpages or {}).get(i))
                                   for i in range(min(2, len(document)))])
    if title:
        result['thesis_title'] = title
    return result, blocks


def skill_evidence(pages, taxonomy=None):
    taxonomy = taxonomy or load_taxonomy()
    result = {name: set() for name in ('research_domain_tags', 'topic_tags', *TECH_GROUPS)}
    evidence, seen = [], Counter()
    for index, text in enumerate(pages):
        # A full bibliography heading, not a TOC entry with a page number.
        if index >= len(pages) / 2:
            heading = re.search(r'(?im)^\s*(?:TÀI\s+LIỆU\s+THAM\s+KHẢO|REFERENCES|BIBLIOGRAPHY)\s*$', text)
            if heading:
                text = text[:heading.start()]
                stop = True
            else:
                stop = False
        else:
            stop = False
        for mention in normalize_mentions(text, taxonomy):
            group, tag = mention['group'], mention['tag']
            result[group].add(tag)
            key = (group, tag)
            if seen[key] < 2:
                start, end = mention['start'], mention['end']
                left, right = max(0, start - 90), min(len(text), end + 130)
                evidence.append({'group': group, 'tag': tag, 'page': index + 1,
                                 'start': start, 'end': end, 'matched_text': mention['matched_text'],
                                 'snippet': text[left:right], 'evidence_type': 'inferred_from_thesis'})
                seen[key] += 1
        if stop:
            break
    return {**{name: sorted(tags) for name, tags in result.items()}, 'evidence': evidence}


def move_verified(source, destination, expected_hash):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if digest(source) != expected_hash:
        raise ValueError('source_hash_changed')
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Copy + hash + unlink also works across volumes and preserves originals on failure.
    shutil.copy2(source, destination)
    if digest(destination) != expected_hash:
        raise ValueError('destination_hash_mismatch_source_not_removed')
    source.unlink()


def extract(source, report, template, *, tessdata=None, only=None, ocr_all=False, cached_from=None):
    source, report = Path(source).resolve(), Path(report).resolve()
    if (report / 'plan.json').exists():
        raise FileExistsError('Use --apply on the existing plan or choose a fresh report directory.')
    report.mkdir(parents=True, exist_ok=True)
    (report / 'extracted').mkdir(exist_ok=True)
    with Path(template).open(encoding='utf-8-sig', newline='') as stream:
        header = next(csv.reader(stream))
    taxonomy = load_taxonomy()
    plans, rows = [], []
    now = datetime.now(timezone.utc).isoformat()
    paths = sorted(p for p in source.iterdir() if p.is_file() and p.suffix.lower() == '.pdf'
                   and (only is None or p.name == only))
    for count, path in enumerate(paths, 1):
        sha = digest(path)
        plan = {'original': str(path), 'sha256': sha, 'bytes': path.stat().st_size}
        try:
            with pymupdf.open(path) as document:
                textpages, pages, ocr_pages = {}, [], []
                # OCR TextPage.parent is weak: keep its Page alive through metadata extraction.
                document_pages = list(document)
                cached_text = Path(cached_from) / 'extracted' / f'{sha}.jsonl' if cached_from else None
                cached_evidence = Path(cached_from) / 'extracted' / f'{sha}.evidence.json' if cached_from else None
                use_cache = cached_text and cached_text.is_file() and cached_evidence.is_file() and not tessdata
                for index, page in enumerate(document_pages) if not use_cache else []:
                    text = clean(page.get_text())
                    if tessdata and (ocr_all or (len(text.strip()) < 40 and page.get_images())):
                        from src.data_pipeline.pdf_extract import _image_coverage
                        if ocr_all or _image_coverage(page) > .3:
                            tp = page.get_textpage_ocr(language='vie+eng', dpi=260, full=True, tessdata=str(Path(tessdata).resolve()))
                            text = clean(page.get_text(sort=True, textpage=tp))
                            if index < 2:
                                textpages[index] = page_lines(page, tp)
                            ocr_pages.append(index + 1)
                    pages.append(text)
                if use_cache:
                    pages = [json.loads(line)['text'] for line in cached_text.read_text(encoding='utf-8').splitlines()]
                date = cover_date(document, textpages)
                fields, cover_blocks = metadata(document, sha, path.name, textpages)
                # Parse complete text once; source cover metadata remains authoritative.
                if use_cache:
                    evidence = json.loads(cached_evidence.read_text(encoding='utf-8'))['skills']
                    tags = {group: sorted({item['tag'] for item in evidence if item['group'] == group})
                            for group in ('research_domain_tags', 'topic_tags', *TECH_GROUPS)}
                    tags['evidence'] = evidence
                else:
                    tags = skill_evidence(pages, taxonomy)
                plan.update(date=date, fields=fields, pages=len(pages),
                            empty_pages=[i + 1 for i, text in enumerate(pages) if len(text.strip()) < 30], ocr_pages=ocr_pages)
                with (report / 'extracted' / f'{sha}.jsonl').open('w', encoding='utf-8') as stream:
                    for index, text in enumerate(pages):
                        stream.write(json.dumps({'page': index + 1, 'text': text}, ensure_ascii=False) + '\n')
                dump(report / 'extracted' / f'{sha}.evidence.json', {'cover': cover_blocks, 'skills': tags['evidence']})
                row = dict.fromkeys(header, '')
                partition = date.get('partition')
                row.update(schema_version='1.0', semester_id=partition or '', cohort_year=partition or '',
                           student_id=fields.get('student_id', ''), student_name=fields.get('student_name', ''),
                           thesis_title=fields.get('thesis_title', ''), source_type='pdf', source_file=path.name,
                           source_page=str(date.get('page', '')), source_sha256=sha, extracted_at=now,
                           review_status='needs_review', skill_evidence_type='inferred_from_thesis')
                for name in ('research_domain_tags', 'topic_tags', *TECH_GROUPS):
                    row[name] = ';'.join(tags[name])
                row['skills_tags'] = ';'.join(sorted({tag for group in TECH_GROUPS for tag in tags[group]}))
                # Extract actual abstract/keywords if present; never synthesize them.
                all_text = '\n'.join(pages)
                abstract = re.search(r'(?im)^\s*(?:TÓM\s+TẮT|ABSTRACT)\s*\n(.{40,6000}?)(?=\n\s*(?:TỪ\s+KHÓA|TỪ\s+KHOÁ|KEYWORDS|CHƯƠNG\s+\d)|\Z)', all_text, re.S)
                if abstract:
                    row['thesis_abstract'] = ' '.join(abstract[1].split())
                keywords = re.search(r'(?im)^\s*(?:Từ\s+khóa|Từ\s+khoá|Keywords)\s*[:：]\s*([^\n]{3,500})', all_text)
                if keywords:
                    row['thesis_keywords'] = keywords[1].strip()
                row['skill_evidence_refs'] = json.dumps(tags['evidence'], ensure_ascii=False, separators=(',', ':'))
                row['reviewer_notes'] = json.dumps({'cover_date': date, 'evidence_scope': 'retrospective_document_proxy',
                    'prediction_time_verified': False, 'skill_semantics': 'source_mentions_not_proficiency',
                    'skill_confidence': 'unknown', 'empty_pages': plan['empty_pages'], 'ocr_pages': ocr_pages,
                    'missing_identity_fields': [key for key in ('student_id', 'student_name', 'thesis_title') if not row[key]]},
                    ensure_ascii=False, separators=(',', ':'))
                if partition:
                    plan['destination'] = str(source.parent / partition / 'student' / 'KLTN' / path.name)
                rows.append(row)
        except Exception as exc:
            plan['error'] = f'{type(exc).__name__}: {exc}'
        plans.append(plan)
        print(f'[{count}/{len(paths)}] {path.name[:24]}: {plan.get("date", {}).get("partition") or plan.get("error") or "unresolved"}', flush=True)
    dump(report / 'plan.json', {'source': str(source), 'created_at': now, 'header': header, 'files': plans, 'rows': rows})
    dump(report / 'summary.json', {'pdf_files': len(plans), 'partitions': dict(Counter(p.get('date', {}).get('partition') or 'unresolved' for p in plans)),
                                 'errors': [p for p in plans if p.get('error')]})


def apply(report):
    report = Path(report).resolve()
    plan = json.loads((report / 'plan.json').read_text(encoding='utf-8'))
    data_root = Path(plan['source']).parent.resolve()
    rows_by_hash = {row['source_sha256']: row for row in plan['rows']}
    grouped = {term: [] for term in TERMS}
    ledger_path = report / 'moves.jsonl'
    for term in TERMS:
        target = data_root / term / 'student' / 'students_processed' / 'students_processed.csv'
        expected = {item['sha256'] for item in plan['files']
                    if item.get('date', {}).get('status') == 'resolved'
                    and item['date'].get('partition') == term}
        if target.exists():
            with target.open(encoding='utf-8-sig', newline='') as stream:
                existing = {row['source_sha256'] for row in csv.DictReader(stream)}
            if not existing <= expected:
                raise ValueError('existing_student_rows_outside_current_plan')
    # Validate the whole move set before making the first filesystem change.
    for item in plan['files']:
        if item.get('error') or item.get('date', {}).get('status') != 'resolved':
            continue
        source, destination = Path(item['original']).resolve(), Path(item['destination']).resolve()
        expected_parent = data_root / item['date']['partition'] / 'student' / 'KLTN'
        if source.parent != Path(plan['source']).resolve() or destination.parent != expected_parent:
            raise ValueError('unexpected_source_or_destination')
        if source.exists() and (digest(source) != item['sha256'] or destination.exists()):
            raise ValueError('move_preflight_hash_or_destination_conflict')
        if not source.exists() and (not destination.is_file() or digest(destination) != item['sha256']):
            raise ValueError('move_preflight_missing_source_and_destination')
        if item['sha256'] not in rows_by_hash:
            raise ValueError('move_preflight_missing_extracted_row')
    moved = []
    for item in plan['files']:
        if item.get('error') or item.get('date', {}).get('status') != 'resolved':
            continue
        source = Path(item['original']).resolve()
        destination = Path(item['destination']).resolve()
        partition = item['date']['partition']
        if source.parent != Path(plan['source']).resolve() or destination.parent != data_root / partition / 'student' / 'KLTN':
            raise ValueError('unexpected_source_or_destination')
        if source.exists():
            move_verified(source, destination, item['sha256'])
        elif not destination.is_file() or digest(destination) != item['sha256']:
            raise ValueError('source_and_verified_destination_missing')
        moved.append(item)
        with ledger_path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'source': str(source), 'destination': str(destination), 'sha256': item['sha256']}, ensure_ascii=False) + '\n')
        row = dict(rows_by_hash[item['sha256']])
        row['source_file'] = destination.relative_to(data_root).as_posix()
        previous = next((r for r in grouped[partition] if r['source_sha256'] == item['sha256']), None)
        if not previous:
            grouped[partition].append(row)
    for partition, rows in grouped.items():
        target = data_root / partition / 'student' / 'students_processed' / 'students_processed.csv'
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.copy2(target, report / f'{partition}.previous.csv')
        with target.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=plan['header'])
            writer.writeheader()
            writer.writerows(rows)
    unresolved = [item for item in plan['files'] if item.get('error') or item.get('date', {}).get('status') != 'resolved']
    dump(report / 'unresolved.json', unresolved)
    summary = {'moved_pdfs': len(moved), 'student_rows': {term: len(rows) for term, rows in grouped.items()},
               'unresolved_pdfs': len(unresolved), 'all_moved_hashes_verified': True}
    dump(report / 'applied_summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'data/1.pdfs')
    parser.add_argument('--template', type=Path, default=ROOT / 'data/2024/student/students_processed/students_processed.csv')
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--tessdata', type=Path)
    parser.add_argument('--only', help='Re-extract one exact source filename for review.')
    parser.add_argument('--ocr-all', action='store_true', help='OCR every page of a document with broken font encoding.')
    parser.add_argument('--cached-from', type=Path, help='Reuse exact-hash text/evidence from the same fresh extraction.')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    apply(args.report) if args.apply else extract(args.source, args.report, args.template, tessdata=args.tessdata, only=args.only, ocr_all=args.ocr_all, cached_from=args.cached_from)
