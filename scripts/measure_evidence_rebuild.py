"""Before/after measurement for the student evidence rebuild.

Deterministic part only (no RL training): tag frequencies, cosine score
statistics, Hungarian/Greedy baselines on each validation split, the AI-advisor
exposure check and the V1 2025.1 preference test with a cosine ranker.

Every variant uses the same split, roster, quota policy and advisor corpus; only
student evidence columns differ, so differences are attributable to the data.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.baselines.rebuild_baselines import solve
from src.features.fresh_suite import restore_encoder
from src.features.semester_suite import student_text
from src.features.survey_feedback import declared_term, name_key
from src.features.rebuild_features import preprocess_text
from src.rl.nested_learning import decode_problem

GROUPS = ('research_domain_tags', 'topic_tags', 'programming_languages', 'frameworks_libraries',
          'databases', 'ml_ai_methods', 'data_engineering_tools', 'cloud_devops_tools',
          'security_network_tools', 'software_engineering_methods', 'research_methods',
          'math_statistics_topics')
AI_TAGS = {('research_domain_tags', 'ai'), ('topic_tags', 'machine_learning'), ('topic_tags', 'nlp'),
           ('topic_tags', 'llm'), ('topic_tags', 'computer_vision'), ('topic_tags', 'reinforcement_learning'),
           ('ml_ai_methods', 'deep_learning'), ('ml_ai_methods', 'classification'), ('ml_ai_methods', 'nlp'),
           ('ml_ai_methods', 'computer_vision'), ('frameworks_libraries', 'pytorch'),
           ('frameworks_libraries', 'tensorflow'), ('frameworks_libraries', 'scikit_learn')}
STRICT_AI_TAGS = {('research_domain_tags', 'ai'), ('topic_tags', 'machine_learning'), ('topic_tags', 'nlp'),
                  ('topic_tags', 'llm'), ('topic_tags', 'computer_vision'), ('frameworks_libraries', 'pytorch'),
                  ('frameworks_libraries', 'tensorflow'), ('ml_ai_methods', 'deep_learning')}
HEADLINE = [('research_domain_tags', 'ai'), ('topic_tags', 'machine_learning'), ('programming_languages', 'cpp'),
            ('programming_languages', 'python'), ('programming_languages', 'javascript'),
            ('programming_languages', 'java'), ('topic_tags', 'optimization'), ('math_statistics_topics', 'statistics')]


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def tags(row):
    return {(g, t) for g in GROUPS for t in filter(None, (row.get(g) or '').split(';'))}


def has_ai(row, strict=True):
    return bool(tags(row) & (STRICT_AI_TAGS if strict else AI_TAGS))
