"""Regression tests for context-gated skill evidence.

Each case is taken from a real thesis snippet or from an explicit rule in the
rebuild brief: a mention in a contents line, abbreviation table, tool listing,
future-work paragraph or cover metadata is not evidence that the student used
the technology.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.data_pipeline.evidence_context import (AUDIT_ONLY, DIRECT_EVIDENCE, NEEDS_REVIEW,
                                                RESEARCH_TOPIC, classify_mention,
                                                feature_eligible, resolve_profile, weigh)
from src.data_pipeline.normalization import load_taxonomy, normalize_mentions


def classify(text, tag, *, section=None, in_topic_field=False):
    """Classify the first mention of ``tag`` in ``text``."""
    mentions = [m for m in normalize_mentions(text, load_taxonomy()) if m['tag'] == tag]
    assert mentions, f'no mention of {tag!r} in text'
    return classify_mention(text, mentions[0], section=section, in_topic_field=in_topic_field)


# ---------------------------------------------------------------------------
# Cases named explicitly in the rebuild brief
# ---------------------------------------------------------------------------
def test_website_future_chatbot_plan_is_not_an_ai_skill():
    text = ('hống tài khoản - Tìm hiểu và áp dụng những công nghệ mới phổ biến cho trang web '
            'như AI chatbot tương tác với người sử dụng.')
    result = classify(text, 'ai')
    assert result['context_class'] == AUDIT_ONLY
    assert not feature_eligible(result['context_class'])


def test_abbreviation_table_does_not_grant_ai_or_machine_learning():
    text = ('DANH MỤC CÁC TỪ VIẾT TẮT API Application Programming Interface '
            'AI Artificial Intelligence BERT Bidirectional Encoder Representations from Transformers')
    assert classify(text, 'ai', section='abbreviations')['context_class'] == AUDIT_ONLY
    text_row = 'ML Machine Learning'
    assert classify(text_row, 'machine_learning')['context_class'] == AUDIT_ONLY


def test_vscode_supported_languages_do_not_grant_cpp():
    text = ('Visual Studio Code sở hữu sẵn các nhiều ngôn ngữ lập trình như '
            'JavaScript, Python, C/C++, Java')
    assert classify(text, 'cpp')['context_class'] == AUDIT_ONLY
    other = ('Các ngôn ngữ được tích hợp trong Visual Studio bao gồm C, C++, C++/CLI, '
             'Visual Basic .NET, C#, F#, JavaScript, TypeScript, XML, XSLT, HTML và CSS.')
    assert classify(other, 'cpp')['context_class'] == AUDIT_ONLY


def test_project_that_trains_and_evaluates_a_model_keeps_machine_learning():
    text = 'Chúng em huấn luyện mô hình machine learning và đánh giá mô hình bằng độ chính xác trên tập kiểm thử.'
    result = classify(text, 'machine_learning')
    assert result['context_class'] == DIRECT_EVIDENCE
    assert feature_eligible(result['context_class'])


def test_cpp_project_with_implementation_evidence_keeps_cpp():
    text = 'Module xử lý ảnh được viết bằng C++ và biên dịch với OpenCV 4.9 trước khi đóng gói.'
    result = classify(text, 'cpp')
    assert result['context_class'] == DIRECT_EVIDENCE


# ---------------------------------------------------------------------------
# The standard must be identical for web, mobile, research and AI groups
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('tag,text', [
    ('web_development', 'Nhóm triển khai web development bằng Next.js cho cổng thông tin sinh viên.'),
    ('flutter', 'Ứng dụng được xây dựng bằng Flutter và phát hành trên Google Play.'),
    ('docker', 'Hệ thống cấu hình Docker và docker compose để chạy ba service độc lập.'),
    ('pytorch', 'Mô hình được huấn luyện bằng PyTorch trên GPU và đánh giá bằng F1-score.'),
    ('literature_review', 'Nhóm thực hiện literature review trên 60 bài báo và ghi lại kết quả.'),
])
def test_direct_evidence_is_recognised_for_every_group(tag, text):
    result = classify(text, tag)
    assert result['context_class'] == DIRECT_EVIDENCE, result['reason']


@pytest.mark.parametrize('tag,text', [
    ('flutter', 'Một số framework phổ biến hiện nay bao gồm React Native, Flutter và Xamarin.'),
    ('docker', 'Docker là nền tảng được giới thiệu trong chương này.'),
    ('pytorch', 'TensorFlow và PyTorch có ưu điểm khác nhau về hiệu năng.'),
])
def test_audit_contexts_are_rejected_for_every_group(tag, text):
    assert classify(text, tag)['context_class'] == AUDIT_ONLY


def test_research_thesis_subject_is_topic_not_a_used_skill():
    text = 'Đề tài: Nghiên cứu ứng dụng học tăng cường trong bài toán gợi ý.'
    result = classify(text, 'reinforcement_learning', in_topic_field=True)
    assert result['context_class'] == RESEARCH_TOPIC
    assert not feature_eligible(result['context_class'], 'binary')
    assert weigh(result['context_class'], 'topic_quarter') == pytest.approx(0.25)


def test_unclear_context_defaults_to_needs_review_and_is_excluded():
    text = 'Chương 2 trình bày về machine learning trong thực tế.'
    result = classify(text, 'machine_learning')
    assert result['context_class'] == NEEDS_REVIEW
    assert not feature_eligible(result['context_class'])


def test_contents_entry_is_audit_only_even_with_a_verb():
    text = '2.1.3. Ứng dụng AI trong phân tích tài chính ............................. 14'
    assert classify(text, 'ai')['context_class'] == AUDIT_ONLY


def test_computer_science_major_name_never_grants_machine_learning():
    for text in ('Lớp chuyên ngành : Khoa học máy tính 64',
                 'Ngành : Khoa học máy tính',
                 'KHOA HỌC MÁY TÍNH'):
        assert classify(text, 'machine_learning')['context_class'] == AUDIT_ONLY, text


def test_references_section_carries_into_following_page():
    text = 'Tài liệu tham khảo của TensorFlow và PyTorch được liệt kê ở đây.'
    result = classify(text, 'tensorflow', section='references')
    assert result['context_class'] == AUDIT_ONLY
    assert result['section'] == 'references'


def test_third_party_subject_is_not_the_students_skill():
    for text in ('Amazon là hình mẫu điển hình về việc sử dụng AI để tối ưu hóa toàn bộ mạng lưới.',
                 'Trong an ninh, các hệ thống camera giám sát sử dụng AI để nhận dạng khuôn mặt.',
                 'Theo báo cáo HireVue năm 2025, tỷ lệ chuyên gia nhân sự sử dụng AI hằng ngày.',
                 'Nhiều trường đại học trên thế giới và Việt Nam đã áp dụng AI vào các hệ thống.'):
        assert classify(text, 'ai')['context_class'] == AUDIT_ONLY, text


def test_authorial_passive_construction_is_still_evidence():
    text = 'Hệ thống được xây dựng bằng Python và triển khai trên Docker.'
    assert classify(text, 'python')['context_class'] == DIRECT_EVIDENCE


def test_impersonal_capability_claim_is_not_evidence():
    text = 'Các hệ thống AI có thể tự động xử lý thông tin và thực hiện nhiệm vụ phức tạp.'
    assert classify(text, 'ai')['context_class'] == AUDIT_ONLY


def test_definitional_framing_is_not_evidence():
    text = 'Chatbot là một chương trình máy tính sử dụng trí tuệ nhân tạo (AI) để mô phỏng hội thoại.'
    assert classify(text, 'ai')['context_class'] == AUDIT_ONLY


def test_weight_profiles_are_validated():
    assert resolve_profile('binary')['direct_evidence'] == 1.0
    assert resolve_profile('topic_quarter')['research_topic'] == 0.25
    with pytest.raises(ValueError, match='unknown_weight_profile'):
        resolve_profile('invented')
    with pytest.raises(ValueError, match='invalid_weight_profile'):
        resolve_profile({'direct_evidence': 1.0})
    with pytest.raises(ValueError, match='invalid_weight_profile'):
        resolve_profile({'direct_evidence': 1.0, 'research_topic': 2.0,
                         'audit_only': 0.0, 'needs_review': 0.0})
