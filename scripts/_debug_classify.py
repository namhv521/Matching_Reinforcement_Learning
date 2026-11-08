"""Debug: show why a specific tag is classified as it is for one document."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data_pipeline.evidence_context import classify_mention, page_sections
from src.data_pipeline.normalization import load_taxonomy, normalize_mentions

cache = ROOT / 'data_rebuild/_smoke_2025_1/_page_cache'
tag = sys.argv[1] if len(sys.argv) > 1 else 'python'
term = sys.argv[2] if len(sys.argv) > 2 else '2025.1'
limit = int(sys.argv[3]) if len(sys.argv) > 3 else 3

taxonomy = load_taxonomy()
out = open(ROOT / 'outputs/_debug_classify.txt', 'w', encoding='utf-8')
seen = 0
for path in sorted(cache.glob('*.pages.json')):
    pages = json.loads(path.read_text(encoding='utf-8'))['pages']
    section = None
    for index, text in enumerate(pages):
        for mention in normalize_mentions(text, taxonomy):
            if mention['tag'] != tag:
                continue
            verdict = classify_mention(text, mention, section=section)
            print(f'{path.name[:16]} p{index+1} section={section} -> {verdict["context_class"]} '
                  f'({verdict["reason"]})', file=out)
            print(f'   sentence: {verdict["sentence"][:200]}', file=out)
            seen += 1
            if seen >= limit:
                raise SystemExit(0)
        starts = page_sections(text)
        if starts:
            section = max(starts.items(), key=lambda item: item[1])[0]
