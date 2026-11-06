"""Measure page-text extraction and mention-classification cost on a sample."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data_pipeline.evidence_context import classify_mention
from src.data_pipeline.normalization import load_taxonomy, normalize_mentions

paths = sorted((ROOT / 'data/2025.1/student/KLTN').glob('*.pdf'))[:3]
taxonomy = load_taxonomy()
for path in paths:
    start = time.perf_counter()
    with pymupdf.open(path) as document:
        pages = [page.get_text() for page in document]
    read = time.perf_counter() - start

    start = time.perf_counter()
    total = 0
    for text in pages:
        mentions = normalize_mentions(text, taxonomy)
        for mention in mentions:
            classify_mention(text, mention)
        total += len(mentions)
    tag = time.perf_counter() - start
    print(f'{path.name[:28]:30s} pages={len(pages):4d} read={read:6.2f}s tag={tag:7.2f}s mentions={total}')
