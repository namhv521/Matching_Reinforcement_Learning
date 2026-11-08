import importlib.util
import unicodedata
from pathlib import Path

import pytest


def module():
    path = Path(__file__).resolve().parents[2] / 'src/data_pipeline/normalization.py'
    assert path.exists(), 'Normalization implementation missing'
    spec = importlib.util.spec_from_file_location('normalization', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_taxonomy_is_draft_and_ids_come_from_defined_groups():
    helper = module()
    taxonomy = helper.load_taxonomy()
    assert taxonomy['status'] == 'draft_pending_owner_review'
    assert taxonomy['taxonomy_version'] == '1.0'
    ids = helper.taxonomy_ids(taxonomy)
    assert {'ai', 'machine_learning', 'cpp', 'csharp', 'sql', 'nlp', 'llm'} <= ids
    assert 'skills_tags' not in taxonomy['groups']


def test_aliases_preserve_original_offsets_and_do_not_assign_proficiency():
    helper = module()
    text = 'Nghiên cứu AI, ML, NLP, LLM; C++, C#, JS, SQL và học máy.'
    found = helper.normalize_mentions(text, helper.load_taxonomy())
    assert {'ai', 'machine_learning', 'nlp', 'llm', 'cpp', 'csharp', 'javascript', 'sql'} <= {m['tag'] for m in found}
    assert all(text[m['start']:m['end']] == m['matched_text'] for m in found)
    assert all(m['evidence_type'] == 'inferred_from_thesis' for m in found)
    assert all(set(m) == {'tag', 'group', 'matched_text', 'start', 'end', 'evidence_type'} for m in found)


def test_web_mobile_game_and_product_development_terms_are_taxonomy_mentions_only():
    helper = module()
    text = ('Xây dựng ứng dụng web full-stack và ứng dụng di động bằng React Native và Flutter; '
            'phát triển game với Unity, UI/UX, microservices, Docker và DevOps.')
    found = helper.normalize_mentions(text, helper.load_taxonomy())
    tags = {match['tag'] for match in found}
    assert {'web_development', 'full_stack_development', 'mobile_app_development',
            'game_development', 'ui_ux_design', 'microservices', 'react_native',
            'flutter', 'unity', 'docker', 'devops'} <= tags
    assert all(match['evidence_type'] == 'inferred_from_thesis' for match in found)


def test_nfd_unicode_matches_nfc_alias_with_exact_original_span():
    helper = module()
    phrase = unicodedata.normalize('NFD', 'thị giác máy tính')
    text = 'Đề tài: ' + phrase + ' trong y tế.'
    found = helper.normalize_mentions(text, helper.load_taxonomy())
    matches = [m for m in found if m['tag'] == 'computer_vision']
    assert matches
    assert all(m['matched_text'] == phrase and text[m['start']:m['end']] == phrase for m in matches)


def test_negative_word_boundaries_and_ambiguous_short_aliases():
    helper = module()
    text = 'JavaScript TypeScript MySQL PostgreSQL; ai cũng thấy 10 ml, r = 1. Flowers bloom in spring and react to sunlight.'
    found = helper.normalize_mentions(text, helper.load_taxonomy())
    tags = {m['tag'] for m in found}
    assert {'javascript', 'typescript', 'mysql', 'postgresql'} <= tags
    assert not {'java', 'sql', 'ai', 'machine_learning', 'r', 'spring', 'react'} & tags
    contextual = helper.normalize_mentions('Ngôn ngữ R, R programming, Spring Boot và ReactJS', helper.load_taxonomy())
    assert {'r', 'spring', 'react'} <= {m['tag'] for m in contextual}


def test_longest_alias_wins_within_group_and_output_is_deterministic():
    helper = module()
    text = 'Java Script và C++17, thư viện scikit-learn.'
    found = helper.normalize_mentions(text, helper.load_taxonomy())
    languages = [m for m in found if m['group'] == 'programming_languages']
    assert [(m['tag'], m['matched_text']) for m in languages] == [('javascript', 'Java Script'), ('cpp', 'C++17')]
    assert found == helper.normalize_mentions(text, helper.load_taxonomy())


def test_conflicting_aliases_and_unknown_groups_are_rejected(tmp_path):
    helper = module()
    path = tmp_path / 'bad.yaml'
    path.write_text("schema_version: '1.0'\ntaxonomy_version: '1.0'\nstatus: draft_pending_owner_review\ngroups:\n  programming_languages:\n    first: {aliases: [same]}\n    second: {aliases: [same]}\n", encoding='utf-8')
    with pytest.raises(ValueError, match='ambiguous_alias'):
        helper.load_taxonomy(path)
    path.write_text("schema_version: '1.0'\ntaxonomy_version: '1.0'\nstatus: draft_pending_owner_review\ngroups:\n  student_name:\n    person: {aliases: [name]}\n", encoding='utf-8')
    with pytest.raises(ValueError, match='unknown_taxonomy_group'):
        helper.load_taxonomy(path)
