"""Re-derive student skill evidence in place with context-gated extraction.

This never moves or rewrites source documents and never re-runs cover-date
partitioning: the existing ``students_processed.csv`` rows carry the identity,
hash and semester decisions that were already reviewed. Only the skill/topic
evidence is rebuilt, because that is what the broken rule produced.

Two snapshot variants are written from the same reading pass:

``strict``  every taxonomy column holds direct implementation evidence only.
``topic``   technology columns stay direct-evidence only, while the research
            domain and topic columns also admit the thesis subject.

The pipeline consumes tags as a binary presence schema, so an experimental
"lower weight for indirect topic signal" is expressed as membership of the
topic variant rather than a 0.25 written into a cell that nothing reads.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data_pipeline.evidence_context import (AUDIT_ONLY, CONTEXT_VERSION, DIRECT_EVIDENCE,
                                                NEEDS_REVIEW, RESEARCH_TOPIC, classify_mention,
                                                page_sections, resolve_profile, section_continues)
from src.data_pipeline.normalization import load_taxonomy, normalize_mentions

TERMS = ('2024', '2025.1', '2025.2', '2025.3')
TECH_GROUPS = ('programming_languages', 'frameworks_libraries', 'databases',
               'ml_ai_methods', 'data_engineering_tools', 'cloud_devops_tools',
               'security_network_tools', 'software_engineering_methods',
               'research_methods', 'math_statistics_topics')
TOPIC_GROUPS = ('research_domain_tags', 'topic_tags')
ALL_GROUPS = (*TOPIC_GROUPS, *TECH_GROUPS)

#: Class priority when the same tag appears in several contexts in one document.
CLASS_PRIORITY = {DIRECT_EVIDENCE: 3, RESEARCH_TOPIC: 2, NEEDS_REVIEW: 1, AUDIT_ONLY: 0}

#: Evidence snippets retained per tag per document.
MAX_EVIDENCE_PER_TAG = 3

VARIANTS = {
    # variant -> (profile name, groups that may carry research_topic)
    'strict': ('binary', ()),
    'topic': ('topic_quarter', TOPIC_GROUPS),
}


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_file(path: Path) -> str:
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def clean(text: str) -> str:
    return unicodedata.normalize('NFC', text).replace('\u200b', '').replace('\ufeff', '')


def dump(path: Path, value) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def read_csv(path: Path) -> tuple[list[str], list[dict]]:
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or ()), list(reader)


def write_csv(path: Path, header: list[str], rows: list[dict]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


def resolve_document(term: str, row: dict, data_root: Path) -> dict:
    """Locate the readable document for a processed row and verify its bytes.

    DOCX rows keep DOCX identity: ``source_sha256`` must still match the DOCX
    bytes, while page text is read from the rendered PDF stored beside it, which
    is the only artifact with real page numbers.
    """
    kltn = data_root / term / 'student/KLTN'
    name = Path(row['source_file']).name
    source = kltn / name
    result = {'student_id': row['student_id'], 'term': term, 'source_file': name,
              'source_type': row['source_type'], 'expected_sha256': row['source_sha256']}
    if not source.is_file():
        return {**result, 'status': 'missing_source_document'}
    actual = digest_file(source)
    if actual != row['source_sha256']:
        return {**result, 'status': 'source_hash_mismatch', 'actual_sha256': actual}
    if row['source_type'] == 'pdf':
        return {**result, 'status': 'ok', 'read_path': source, 'read_sha256': actual}
    rendered = source.with_suffix('.pdf')
    if not rendered.is_file():
        return {**result, 'status': 'missing_rendered_pdf_for_docx'}
    return {**result, 'status': 'ok', 'read_path': rendered,
            'read_sha256': digest_file(rendered), 'render_of_docx': True}


def page_texts(path: Path, cache_dir: Path, read_sha: str) -> tuple[list[str], str]:
    """Page text for a document, reusing cache only on an exact byte match."""
    cached = cache_dir / f'{read_sha}.pages.json'
    if cached.is_file():
        payload = json.loads(cached.read_text(encoding='utf-8'))
        if payload.get('read_sha256') == read_sha:
            return payload['pages'], 'cache'
    with pymupdf.open(path) as document:
        pages = [clean(page.get_text()) for page in document]
    dump(cached, {'read_sha256': read_sha, 'pages': pages})
    return pages, 'extracted'


def topic_field_spans(row: dict) -> str:
    """Thesis subject fields, used to mark research-topic context."""
    return '\n'.join(filter(None, (row.get('thesis_title', ''), row.get('thesis_abstract', ''),
                                   row.get('thesis_keywords', ''))))


def classify_document(pages: list[str], topic_text: str, taxonomy: dict) -> dict:
    """Classify every taxonomy mention in a document.

    Returns the best context class per (group, tag) plus retained evidence rows.
    The section state carries across pages so a references or abbreviation list
    spanning a page break stays classified. Retained snippets prefer the
    strongest class found, so a tag's audit row does not crowd out the
    implementation snippet that justified it.
    """
    best: dict[tuple[str, str], dict] = {}
    pool: dict[tuple[str, str], list[dict]] = {}
    counts = Counter()
    section = None

    def record(key, item, verdict) -> None:
        counts[verdict['context_class']] += 1
        entry = {'group': key[0], 'tag': key[1], 'page': item['page'],
                 'locator': item['locator'], 'matched_text': item['matched_text'],
                 'start': item['start'], 'end': item['end'],
                 'context_class': verdict['context_class'], 'reason': verdict['reason'],
                 'section': verdict['section'], 'snippet': verdict['sentence'],
                 'evidence_type': 'inferred_from_thesis'}
        if (key not in best
                or CLASS_PRIORITY[verdict['context_class']] > CLASS_PRIORITY[best[key]['context_class']]):
            best[key] = entry
        bucket = pool.setdefault(key, [])
        if len(bucket) < MAX_EVIDENCE_PER_TAG:
            bucket.append(entry)
        else:
            weakest = min(range(len(bucket)),
                          key=lambda i: CLASS_PRIORITY[bucket[i]['context_class']])
            if CLASS_PRIORITY[verdict['context_class']] > CLASS_PRIORITY[bucket[weakest]['context_class']]:
                bucket[weakest] = entry

    # The thesis subject fields are read first so topic context is available even
    # when the body text never restates the title.
    if topic_text.strip():
        for mention in normalize_mentions(topic_text, taxonomy):
            key = (mention['group'], mention['tag'])
            item = {**mention, 'page': 0, 'locator': 'thesis_subject_fields'}
            record(key, item, classify_mention(topic_text, item, in_topic_field=True))

    for index, text in enumerate(pages):
        if not text.strip():
            continue
        for mention in normalize_mentions(text, taxonomy):
            key = (mention['group'], mention['tag'])
            item = {**mention, 'page': index + 1, 'locator': f'page:{index + 1}'}
            record(key, item, classify_mention(text, item, section=section))
        # Section state for the next page comes from this page's last heading,
        # but front-matter lists only carry while the next page still looks like
        # the same kind of list.
        starts = page_sections(text)
        if starts:
            section = max(starts.items(), key=lambda item: item[1])[0]
        elif not section_continues(section, pages[index + 1] if index + 1 < len(pages) else ''):
            section = None
    evidence = [entry for key in sorted(pool) for entry in pool[key]]
    return {'best': best, 'evidence': evidence, 'mention_counts': dict(counts)}



def variant_tags(best: dict, variant: str) -> dict[str, list[str]]:
    """Tag columns for a snapshot variant from per-tag context classes."""
    profile_name, topic_groups = VARIANTS[variant]
    profile = resolve_profile(profile_name)
    columns = {group: set() for group in ALL_GROUPS}
    for (group, tag), record in best.items():
        context_class = record['context_class']
        if group not in columns:
            continue
        if context_class == DIRECT_EVIDENCE:
            columns[group].add(tag)
        elif (context_class == RESEARCH_TOPIC and group in topic_groups
              and profile[RESEARCH_TOPIC] > 0.0):
            columns[group].add(tag)
    return {group: sorted(tags) for group, tags in columns.items()}


def build_row(row: dict, classified: dict, variant: str) -> dict:
    """Copy the processed row, replacing only evidence-derived fields."""
    output = dict(row)
    tags = variant_tags(classified['best'], variant)
    for group in ALL_GROUPS:
        output[group] = ';'.join(tags[group])
    output['skills_tags'] = ';'.join(sorted({tag for group in TECH_GROUPS for tag in tags[group]}))
    output['skill_evidence_refs'] = json.dumps(classified['evidence'], ensure_ascii=False,
                                              separators=(',', ':'))
    direct = sorted({record['tag'] for (group, _tag), record in classified['best'].items()
                     if group in ALL_GROUPS and record['context_class'] == DIRECT_EVIDENCE})
    output['skill_evidence_type'] = 'inferred_from_thesis'
    try:
        notes = json.loads(row.get('reviewer_notes') or '{}')
    except json.JSONDecodeError:
        notes = {}
    notes.update({
        'evidence_scope': 'retrospective_document_proxy',
        'prediction_time_verified': False,
        'skill_semantics': 'source_mentions_not_proficiency',
        'skill_confidence': 'unknown',
        'context_gating': {'version': CONTEXT_VERSION, 'variant': variant,
                           'profile': VARIANTS[variant][0],
                           'topic_groups': list(VARIANTS[variant][1])},
        'mention_counts_by_context': classified['mention_counts'],
        'direct_evidence_tag_count': len(direct),
    })
    output['reviewer_notes'] = json.dumps(notes, ensure_ascii=False, separators=(',', ':'))
    output['review_status'] = 'needs_review'
    return output


def rebuild(terms, source_root: Path, output: Path, *, cache: Path | None = None) -> dict:
    source_root, output = Path(source_root).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError('immutable_snapshot_destination_required')
    cache = Path(cache).resolve() if cache else output / '_page_cache'
    cache.mkdir(parents=True, exist_ok=True)
    taxonomy = load_taxonomy(ROOT / 'configs/data/taxonomy_v1.yaml')
    created = datetime.now(timezone.utc).isoformat()

    manifest = {'schema': 'student-evidence-rebuild/1', 'created_at': created,
                'context_version': CONTEXT_VERSION,
                'taxonomy_source_sha256': digest_file(ROOT / 'configs/data/taxonomy_v1.yaml'),
                'variants': {name: {'profile': VARIANTS[name][0],
                                    'topic_groups': list(VARIANTS[name][1])}
                             for name in VARIANTS},
                'semantics': 'tags_are_source_evidence_not_proficiency',
                'source_documents_moved': False,
                'terms': {}}
    audit_rows, unexpected = [], []

    for term in terms:
        csv_path = source_root / term / 'student/students_processed/students_processed.csv'
        header, rows = read_csv(csv_path)
        variants = {name: [] for name in VARIANTS}
        term_audit = {'source_csv': str(csv_path), 'source_csv_sha256': digest_file(csv_path),
                      'rows_in': len(rows), 'rows_out': {}, 'columns': len(header)}

        for row in rows:
            resolved = resolve_document(term, row, source_root)
            base = {'term': term, 'student_id': row['student_id'],
                    'source_file': resolved['source_file'],
                    'source_type': row['source_type'], 'status': resolved['status']}
            if resolved['status'] != 'ok':
                # Unreadable bytes keep the previous tags and are flagged, never
                # silently emptied.
                unexpected.append(base)
                for name in VARIANTS:
                    variants[name].append(dict(row, review_status='needs_review'))
                continue
            pages, origin = page_texts(resolved['read_path'], cache, resolved['read_sha256'])
            classified = classify_document(pages, topic_field_spans(row), taxonomy)
            for name in VARIANTS:
                variants[name].append(build_row(row, classified, name))
            audit_rows.append({**base, 'pages': len(pages), 'text_origin': origin,
                               'read_path': str(resolved['read_path']),
                               'read_sha256': resolved['read_sha256'],
                               'render_of_docx': resolved.get('render_of_docx', False),
                               'distinct_tags': len(classified['best']),
                               'mention_counts': classified['mention_counts']})

        for name, variant_rows in variants.items():
            target = output / name / term / 'students_processed.csv'
            write_csv(target, header, variant_rows)
            term_audit['rows_out'][name] = len(variant_rows)
            term_audit[name] = {'path': str(target), 'sha256': digest_file(target)}
        manifest['terms'][term] = term_audit

    dump(output / 'evidence_audit.json',
         {'schema': 'student-evidence-audit/1', 'created_at': created, 'documents': audit_rows})
    dump(output / 'unexpected_documents.json', unexpected)
    manifest['documents_read'] = len(audit_rows)
    manifest['documents_unexpected'] = len(unexpected)
    dump(output / 'manifest.json', manifest)
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT / 'data')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--terms', nargs='+', default=list(TERMS), choices=TERMS)
    args = parser.parse_args(argv)
    manifest = rebuild(args.terms, args.source_root, args.output, cache=args.cache)
    summary = {'output': str(args.output), 'documents_read': manifest['documents_read'],
               'documents_unexpected': manifest['documents_unexpected'],
               'rows': {term: value['rows_out'] for term, value in manifest['terms'].items()}}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
