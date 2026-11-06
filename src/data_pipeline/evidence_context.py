"""Context gating for taxonomy mentions before they become matching features.

A taxonomy alias match proves a term appears in a document. It does not prove the
student used the technology. This module classifies every mention by the context
it was found in, so that only evidence-backed mentions reach the feature path.

Policy, applied uniformly to every taxonomy group:

- ``direct_evidence``   implementation, configuration, experiment or result text.
                        Full weight. Eligible as a skill feature.
- ``research_topic``    the thesis subject itself (title, abstract, keywords,
                        chapter heading). Kept in the topic columns. Weight is
                        configurable and defaults to 0 for skill features.
- ``audit_only``        table of contents, abbreviation tables, references, tool
                        listings, theoretical comparison, background knowledge,
                        future work. Weight 0, retained only for audit.
- ``needs_review``      context not clear enough to decide. Weight 0 by default.

Classification never inspects the tag identity, so AI, web, mobile, research and
every other group are held to the same standard.
"""
from __future__ import annotations

import re
import unicodedata

CONTEXT_VERSION = 'evidence-context/1.1'

DIRECT_EVIDENCE = 'direct_evidence'
RESEARCH_TOPIC = 'research_topic'
AUDIT_ONLY = 'audit_only'
NEEDS_REVIEW = 'needs_review'

CONTEXT_CLASSES = (DIRECT_EVIDENCE, RESEARCH_TOPIC, AUDIT_ONLY, NEEDS_REVIEW)

#: Weight profiles. ``binary`` keeps the existing binary feature schema: only
#: direct evidence becomes a feature. ``topic_quarter`` is the experimental
#: configuration that also admits research topics at a reduced weight.
WEIGHT_PROFILES = {
    'binary': {DIRECT_EVIDENCE: 1.0, RESEARCH_TOPIC: 0.0, AUDIT_ONLY: 0.0, NEEDS_REVIEW: 0.0},
    'topic_quarter': {DIRECT_EVIDENCE: 1.0, RESEARCH_TOPIC: 0.25, AUDIT_ONLY: 0.0, NEEDS_REVIEW: 0.0},
}
DEFAULT_PROFILE = 'binary'

# ---------------------------------------------------------------------------
# Section headings. A heading switches the section state; the state carries
# forward to later pages until another heading replaces it, subject to
# ``section_continues``.
# ---------------------------------------------------------------------------
SECTION_HEADINGS = (
    ('references', r'(?:TÀI\s+LIỆU\s+THAM\s+KHẢO|REFERENCES|BIBLIOGRAPHY|DANH\s+MỤC\s+TÀI\s+LIỆU)'),
    ('abbreviations', r'(?:DANH\s+MỤC\s+(?:CÁC\s+)?(?:TỪ|CHỮ|KÝ\s+HIỆU|THUẬT\s+NGỮ)[^\n]{0,40}VIẾT\s+TẮT'
                      r'|BẢNG\s+(?:CÁC\s+)?(?:TỪ|CHỮ)\s+VIẾT\s+TẮT'
                      r'|DANH\s+MỤC\s+THUẬT\s+NGỮ|ABBREVIATIONS?|LIST\s+OF\s+ABBREVIATIONS|GLOSSARY)'),
    ('contents', r'(?:MỤC\s+LỤC|TABLE\s+OF\s+CONTENTS'
                 r'|DANH\s+MỤC\s+(?:CÁC\s+)?(?:HÌNH|BẢNG|BIỂU|SƠ\s+ĐỒ|ẢNH)[^\n]{0,30}'
                 r'|LIST\s+OF\s+(?:FIGURES|TABLES))'),
    ('future_work', r'(?:HƯỚNG\s+PHÁT\s+TRIỂN|ĐỊNH\s+HƯỚNG\s+PHÁT\s+TRIỂN|HƯỚNG\s+NGHIÊN\s+CỨU\s+TIẾP\s+THEO'
                    r'|PHÁT\s+TRIỂN\s+TRONG\s+TƯƠNG\s+LAI|FUTURE\s+WORKS?|FUTURE\s+DEVELOPMENT)'),
)
SECTION_HEADING_RE = [(name, re.compile(r'(?im)^\s*(?:\d+(?:\.\d+)*\.?\s*)?' + pattern + r'\s*:?\s*$'))
                      for name, pattern in SECTION_HEADINGS]

#: Sections whose mentions can never become features.
AUDIT_SECTIONS = frozenset({'references', 'abbreviations', 'contents', 'future_work'})

# ---------------------------------------------------------------------------
# Line-level signals
# ---------------------------------------------------------------------------
#: A contents entry: dotted leader followed by a page number, or heavy dot
#: padding. Matches "Ứng dụng AI trong phân tích tài chính ......... 14".
TOC_LINE_RE = re.compile(r'\.{4,}\s*\d{1,4}\s*$|\.{6,}')

#: An abbreviation row maps a short token to its expansion: "ML Machine Learning".
ABBREVIATION_ROW_RE = re.compile(
    r'^\s*(?:[A-Z][A-Za-z0-9/+.\-]{0,11})\s+'
    r'(?:[A-Z][\w/+.\-]*|[A-ZĐ][a-zà-ỹ]+|Trí|Mạng|Diện|Giao|Phần|Dự|Bộ|Học|Mô|Thư)'
    r'[^\n]{0,120}$')

#: Cover and administrative metadata lines.
COVER_METADATA_RE = re.compile(
    r'(?i)(?:^|\s)(?:lớp|ngành|chuyên\s+ngành|khoa|viện|trường|hệ\s+đào\s+tạo|khóa|khoá'
    r'|mã\s+(?:số\s+)?sinh\s+viên|mssv|msv|sinh\s+viên\s+thực\s+hiện|họ\s+(?:và\s+)?tên'
    r'|tên\s+sinh\s+viên|giảng\s+viên|giáo\s+viên|người\s+hướng\s+dẫn|hà\s+nội)\s*[:：]')
MAJOR_NAME_RE = re.compile(r'(?i)(?:khoa|ngành|chuyên\s+ngành|lớp)\s*[:：]?\s*(?:học\s+)?'
                           r'(?:khoa\s+học\s+máy\s+tính|công\s+nghệ\s+thông\s+tin|hệ\s+thống\s+thông\s+tin)')
#: "Khoa học máy tính" is the degree programme, not the machine-learning method.
#: This is the largest single false-positive source for the machine_learning tag.
COMPUTER_SCIENCE_MAJOR_RE = re.compile(r'(?i)khoa\s+học\s+máy\s+tính')

# ---------------------------------------------------------------------------
# Sentence-level signals
# ---------------------------------------------------------------------------
#: Implementation verbs that need a complement to mean "used". A bare "phát triển"
#: describes a research field ("sự phát triển mạnh mẽ của AI"), so it only counts
#: when it takes an object the author actually built.
DIRECT_VERB_PATTERNS = (
    r'(?i)\b(?:sử\s+dụng|dùng|áp\s+dụng)\b',
    r'(?i)\b(?:triển\s+khai|cài\s+đặt|xây\s+dựng|hiện\s+thực|thực\s+thi|thực\s+hiện)\b',
    r'(?i)\b(?:tích\s+hợp|nhúng|viết\s+bằng|được\s+viết)\b',
    r'(?i)\bphát\s+triển\s+(?:mô\s+hình|hệ\s+thống|module|api|dịch\s+vụ|chức\s+năng'
    r'|tính\s+năng|ứng\s+dụng|website|giao\s+diện|thuật\s+toán)\b',
    r'(?i)\blập\s+trình\s+(?:bằng|với|trên|cho\s+hệ)\b',
)
DIRECT_VERB_RE = [re.compile(pattern) for pattern in DIRECT_VERB_PATTERNS]

#: Experimental and configuration evidence, which stands on its own.
DIRECT_RESULT_PATTERNS = (
    r'(?i)\b(?:huấn\s+luyện|đào\s+tạo\s+mô\s+hình|tinh\s+chỉnh|fine[\s-]?tun\w*|train\w*)\b',
    r'(?i)\b(?:thực\s+nghiệm|thí\s+nghiệm|đánh\s+giá\s+mô\s+hình|kiểm\s+thử'
    r'|kết\s+quả\s+(?:thực\s+nghiệm|đánh\s+giá|huấn\s+luyện))\b',
    r'(?i)\b(?:độ\s+chính\s+xác|accuracy|precision|recall|f1[\s-]?score|rmse|mae|auc)\b',
    r'(?i)\b(?:cấu\s+hình|khởi\s+tạo|deploy\w*|docker[\s-]?compose|pip\s+install'
    r'|npm\s+install|requirements\.txt)\b',
    r'(?i)\b(?:import|from)\s+[\w.]+',
)
DIRECT_RESULT_RE = [re.compile(pattern) for pattern in DIRECT_RESULT_PATTERNS]

#: Impersonal modality and field description. "AI có thể tự động xử lý thông tin"
#: describes what a technology can do, not what the student built.
FIELD_MODAL_PATTERNS = (
    r'(?i)\b(?:có\s+thể|được\s+sử\s+dụng\s+để|được\s+ứng\s+dụng|được\s+dùng\s+để)\b',
    r'(?i)\b(?:giúp|hỗ\s+trợ|cho\s+phép)\b',
    r'(?i)\b(?:các\s+hướng\s+(?:nghiên\s+cứu|phát\s+triển)|lĩnh\s+vực)\b',
)
FIELD_MODAL_RE = [re.compile(pattern) for pattern in FIELD_MODAL_PATTERNS]

#: Parenthetical gloss and citation framing: definitional, not evidential.
CITATION_GLOSS_RE = [re.compile(pattern) for pattern in (
    r'\(\s*(?:AI|ML|NLP|IoT|LLM)\s*\)',
    r'(?i)\btheo\s+(?:định\s+nghĩa|tác\s+giả|nghiên\s+cứu|công\s+trình)\b',
    r'\b\d{4}\s*\)',
)]

#: A line dominated by commas, slashes and pluses is a listing, not a claim.
LISTING_PUNCT_RE = re.compile(r'[,/+;]')

#: Third-party subjects using a technology: a company, a sector, a class of
#: system, or a body of professionals. "Amazon sử dụng AI", "các hệ thống camera
#: giám sát sử dụng AI" and "chuyên gia nhân sự sử dụng AI" describe the world,
#: not work the author did.
THIRD_PARTY_SUBJECT_PATTERNS = (
    r'(?i)\b(?:các\s+)?(?:công\s+ty|doanh\s+nghiệp|tổ\s+chức|ngân\s+hàng|trường|đại\s+học'
    r'|chính\s+phủ|quốc\s+gia|tập\s+đoàn|thương\s+hiệu|startup|studio|hãng)\b',
    r'(?i)\b(?:các\s+)?(?:hệ\s+thống|ứng\s+dụng|nền\s+tảng|sản\s+phẩm|dịch\s+vụ|trang\s+web'
    r'|website|mô\s+hình|camera|thiết\s+bị)\b',
    r'(?i)\b(?:chuyên\s+gia|kỹ\s+sư|người\s+dùng|người\s+tiêu\s+dùng|lập\s+trình\s+viên'
    r'|nhà\s+phát\s+triển|nhiều\s+(?:trường|đơn\s+vị|tổ\s+chức))\b',
    r'(?i)\b(?:nhiều\s+người|mọi\s+người|bất\s+kỳ\s+ai)\b',
    # Nominalised or exemplary framing: "hình mẫu điển hình về việc sử dụng AI".
    r'(?i)\b(?:về\s+việc|hình\s+mẫu|ví\s+dụ\s+điển\s+hình|xu\s+hướng|tỷ\s+lệ)\b',
)
THIRD_PARTY_SUBJECT_RE = [re.compile(pattern) for pattern in THIRD_PARTY_SUBJECT_PATTERNS]


#: Future work, intent and unrealised plans. Never evidence of a used skill.
FUTURE_PATTERNS = (
    r'(?i)\b(?:hướng\s+phát\s+triển|trong\s+tương\s+lai|tương\s+lai\s+(?:gần|xa)|sắp\s+tới'
    r'|dự\s+(?:kiến|định)|kế\s+hoạch\s+(?:phát\s+triển|tới))\b',
    r'(?i)\b(?:sẽ\s+(?:thêm|bổ\s+sung|tích\s+hợp|phát\s+triển|nghiên\s+cứu|áp\s+dụng)'
    r'|có\s+thể\s+(?:được\s+)?(?:thêm|bổ\s+sung|tích\s+hợp|mở\s+rộng|cân\s+nhắc)'
    r'|cần\s+(?:thêm|bổ\s+sung))\b',
    r'(?i)\b(?:chưa\s+(?:được\s+)?(?:tích\s+hợp|triển\s+khai|áp\s+dụng|hoàn\s+thiện|thực\s+hiện)'
    r'|còn\s+hạn\s+chế)\b',
    r'(?i)\b(?:hứa\s+hẹn|tiềm\s+năng)\b',
    # "Tìm hiểu và áp dụng những công nghệ mới ... như AI chatbot" states an
    # intention to adopt a technology, so it is not evidence of use.
    r'(?i)\btìm\s+hiểu\s+(?:thêm\s+)?(?:và\s+)?(?:áp\s+dụng|tích\s+hợp|phát\s+triển|bổ\s+sung)\b',
    r'(?i)\bcông\s+nghệ\s+mới\b',
    r'(?i)\b(?:future\s+works?|will\s+be\s+(?:added|integrated|implemented)|planned\s+(?:feature|work))\b',
)
FUTURE_RE = [re.compile(pattern) for pattern in FUTURE_PATTERNS]

#: Tool/platform capability listings: "VS Code hỗ trợ JavaScript, Python, C++".
ENUMERATION_PATTERNS = (
    r'(?i)\b(?:hỗ\s+trợ|tích\s+hợp)\s+(?:sẵn\s+)?(?:các\s+|nhiều\s+|đa\s+)?'
    r'(?:ngôn\s+ngữ|nền\s+tảng|framework|công\s+cụ|thư\s+viện|hệ\s+quản\s+trị)',
    r'(?i)\b(?:các\s+)?ngôn\s+ngữ\s*(?:lập\s+trình)?\s*(?:được\s+)?(?:tích\s+hợp|hỗ\s+trợ|phổ\s+biến)',
    r'(?i)\b(?:bao\s+gồm|gồm\s+có|chẳng\s+hạn\s+như|ví\s+dụ\s+như|v\.v\.|vân\s+vân)\b',
    r'(?i)\b(?:supports?|supported\s+languages?|such\s+as|including)\b',
    r'(?i)\b(?:extensions?|tiện\s+ích|plugin)\b',
)
ENUMERATION_RE = [re.compile(pattern) for pattern in ENUMERATION_PATTERNS]

#: Theoretical comparison and background knowledge, with no use by the student.
COMPARISON_PATTERNS = (
    r'(?i)\b(?:so\s+(?:với|sánh\s+với)|tương\s+tự\s+(?:với|như)|khác\s+(?:với|so\s+với)'
    r'|nhanh\s+hơn|chậm\s+hơn|tốt\s+hơn|kém\s+hơn|thay\s+(?:vì|cho))\b',
    r'(?i)\b(?:tổng\s+quan\s+về|khái\s+niệm|định\s+nghĩa|giới\s+thiệu\s+(?:về|chung)'
    r'|lý\s+thuyết|cơ\s+sở\s+lý\s+thuyết|kiến\s+thức\s+nền|lịch\s+sử\s+phát\s+triển)\b',
    r'(?i)\b(?:mối\s+quan\s+hệ\s+giữa|phân\s+biệt\s+giữa|ưu\s+(?:điểm|nhược)|nhược\s+điểm)\b',
    r'(?i)\blà\s+(?:một\s+)?(?:nền\s+tảng|công\s+cụ|thư\s+viện|framework|ngôn\s+ngữ'
    r'|hệ\s+quản\s+trị|phương\s+pháp|kỹ\s+thuật|mô\s+hình|khái\s+niệm)\b',
    r'(?i)\bđược\s+giới\s+thiệu\b',
    r'(?i)\b(?:overview\s+of|introduction\s+to|comparison\s+(?:of|with)|compared\s+(?:to|with))\b',
)
COMPARISON_RE = [re.compile(pattern) for pattern in COMPARISON_PATTERNS]

#: Numbered chapter/section headings mark the thesis subject, not implementation.
HEADING_LINE_RE = re.compile(r'^\s*(?:CHƯƠNG|CHAPTER|PHẦN)\s+[\dIVXLC]+|^\s*\d+(?:\.\d+)*\.?\s+\S')

SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?;])\s+|\n')


def _normalize(text: str) -> str:
    return unicodedata.normalize('NFC', text or '')


def resolve_profile(profile: str | dict | None = None) -> dict:
    """Return a context-class weight mapping for a profile name or custom dict."""
    if profile is None:
        profile = DEFAULT_PROFILE
    if isinstance(profile, str):
        if profile not in WEIGHT_PROFILES:
            raise ValueError('unknown_weight_profile')
        return dict(WEIGHT_PROFILES[profile])
    if not isinstance(profile, dict) or set(profile) != set(CONTEXT_CLASSES):
        raise ValueError('invalid_weight_profile')
    for value in profile.values():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0:
            raise ValueError('invalid_weight_profile')
    return {key: float(value) for key, value in profile.items()}


def page_sections(text: str) -> dict[str, int]:
    """First offset of every section heading found on a page."""
    text = _normalize(text)
    starts: dict[str, int] = {}
    for name, pattern in SECTION_HEADING_RE:
        for match in pattern.finditer(text):
            starts[name] = min(starts.get(name, match.start()), match.start())
    return starts


def section_at(offset: int, text: str, carried: str | None = None) -> str | None:
    """Section governing a character offset inside a page.

    A heading only governs text after it; text above the first heading keeps the
    section carried in from the previous page, so a references list that runs
    over a page break stays classified.
    """
    before = [(start, name) for name, start in page_sections(text).items() if start <= offset]
    return max(before)[1] if before else carried


def section_continues(section: str | None, page_text: str) -> bool:
    """Whether a section heading still governs the next page.

    A references list runs to the end of the document, so it always carries.
    Table-of-contents and abbreviation pages are short front matter: they only
    carry while the next page still looks like the same kind of list. Without
    this check a single ``MỤC LỤC`` heading classifies the whole thesis as audit
    material.
    """
    if section is None:
        return False
    if section == 'references':
        return True
    text = _normalize(page_text)
    if not text.strip():
        return True
    lines = [line for line in text.split('\n') if line.strip()]
    if section == 'contents':
        listy = sum(1 for line in lines if TOC_LINE_RE.search(line))
        return listy >= 2 and listy >= 0.15 * len(lines)
    if section == 'abbreviations':
        rows = sum(1 for line in lines if ABBREVIATION_ROW_RE.match(line))
        return rows >= 3 and rows >= 0.3 * len(lines)
    return True


def _line_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    left = text.rfind('\n', 0, start) + 1
    right = text.find('\n', end)
    return left, len(text) if right == -1 else right


def _sentence_bounds(text: str, start: int, end: int) -> tuple[int, int, int, int]:
    """Absolute bounds of the mention's line and of its sentence inside it.

    Restricting the window to its own line and sentence stops an implementation
    verb in an unrelated clause from upgrading an enumeration match.
    """
    line_left, line_right = _line_bounds(text, start, end)
    line = text[line_left:line_right]
    offset = start - line_left
    best, cursor = (0, len(line)), 0
    for piece in SENTENCE_SPLIT_RE.split(line):
        index = line.find(piece, cursor)
        if index == -1:
            index = cursor
        if index <= offset <= index + len(piece) and len(piece) > best[1] - best[0]:
            best = (index, index + len(piece))
        cursor = index + len(piece)
    return line_left, line_right, line_left + best[0], line_left + best[1]


def _any(patterns, value: str) -> bool:
    return any(pattern.search(value) for pattern in patterns)


def _verb_applies(sentence: str, start: int, end: int) -> bool:
    """Whether an implementation verb governs the mention, with the author as subject.

    Vietnamese either puts the verb before the object ("sử dụng Python để ...")
    or the object before a passive construction ("hệ thống được xây dựng bằng
    Python"). The mention-relative window keeps a verb attached to a different
    noun in the same sentence from counting.

    Two exclusions keep third-party description out of a student's skill tags:

    - a verb introduced by impersonal modality ("AI có thể tự động xử lý ...",
      "giúp ...") describes a capability, not work the author did;
    - a verb whose subject is a company, sector body or class of system
      ("Amazon sử dụng AI", "các hệ thống camera sử dụng AI") is describing the
      world, not the thesis.
    """
    rejected_third_party = False
    for pattern in DIRECT_VERB_RE:
        for match in pattern.finditer(sentence):
            between = sentence[match.end():start] if match.start() < start else sentence[end:match.start()]
            if len(between) > 60 or ',' in between:
                continue
            # Text before the verb identifies its subject.
            subject = sentence[:match.start()]
            subject_tail = sentence[max(0, match.start() - 60):match.start()]
            if _any(FIELD_MODAL_RE, subject):
                continue
            # "hệ thống được xây dựng bằng Python" is the author's own passive
            # construction, so the passive marker overrides a system-noun subject.
            passive = re.search(r'(?i)\bđược\s*$', subject_tail) is not None
            if not passive and (_any(THIRD_PARTY_SUBJECT_RE, subject_tail)
                                or _any(THIRD_PARTY_SUBJECT_RE, between)):
                rejected_third_party = True
                continue
            return True
    return 'third_party' if rejected_third_party else False


def classify_mention(page_text: str, mention: dict, *, section: str | None = None,
                     in_topic_field: bool = False) -> dict:
    """Classify one taxonomy mention by the context surrounding it.

    ``page_text`` is the original page text and ``mention`` carries ``start`` and
    ``end`` offsets into it. ``section`` is the section carried in from earlier
    pages. ``in_topic_field`` marks mentions taken from the title, abstract or
    keyword fields, which describe the thesis subject rather than a used skill.

    Order matters: audit contexts are decided before implementation evidence, so
    a dotted contents line or an abbreviation row can never be promoted by a
    verb elsewhere on the same line.
    """
    page_text = _normalize(page_text)
    start, end = int(mention['start']), int(mention['end'])
    line_left, line_right, sen_left, sen_right = _sentence_bounds(page_text, start, end)
    full_line = page_text[line_left:line_right]
    sentence = page_text[sen_left:sen_right]
    # Offsets of the mention relative to the sentence window.
    rel_start, rel_end = start - sen_left, end - sen_left
    resolved = section_at(start, page_text, section)

    def result(context_class: str, reason: str) -> dict:
        return {'context_class': context_class, 'reason': reason, 'section': resolved,
                'line': ' '.join(full_line.split())[:400],
                'sentence': ' '.join(sentence.split())[:400],
                'context_version': CONTEXT_VERSION}

    if resolved in AUDIT_SECTIONS:
        return result(AUDIT_ONLY, f'section_{resolved}')
    if TOC_LINE_RE.search(full_line):
        return result(AUDIT_ONLY, 'contents_entry_dotted_leader')
    if COMPUTER_SCIENCE_MAJOR_RE.search(full_line) or MAJOR_NAME_RE.search(full_line):
        return result(AUDIT_ONLY, 'academic_program_name_not_a_method')
    if COVER_METADATA_RE.search(full_line):
        return result(AUDIT_ONLY, 'cover_or_administrative_metadata')
    if _any(FUTURE_RE, sentence):
        return result(AUDIT_ONLY, 'future_work_or_unrealised_plan')
    if ABBREVIATION_ROW_RE.match(full_line) and len(full_line) <= 140 and not _any(DIRECT_RESULT_RE, sentence):
        return result(AUDIT_ONLY, 'abbreviation_table_row')
    if _any(CITATION_GLOSS_RE, sentence) and not _any(DIRECT_RESULT_RE, sentence):
        return result(AUDIT_ONLY, 'definition_or_citation_framing')
    has_result = _any(DIRECT_RESULT_RE, sentence)
    verb = _verb_applies(sentence, rel_start, rel_end)
    has_verb = verb is True
    if not has_result and not has_verb:
        if verb == 'third_party':
            return result(AUDIT_ONLY, 'third_party_usage_description')
        if _any(ENUMERATION_RE, sentence):
            return result(AUDIT_ONLY, 'tool_capability_listing')
        if _any(COMPARISON_RE, sentence):
            return result(AUDIT_ONLY, 'theoretical_comparison_or_background')
        if _any(FIELD_MODAL_RE, sentence):
            return result(AUDIT_ONLY, 'impersonal_capability_description')
        commas = len(LISTING_PUNCT_RE.findall(sentence))
        words = max(1, len(sentence.split()))
        if commas >= 2 and commas / words >= 0.15:
            return result(AUDIT_ONLY, 'technology_listing_line')
    if has_result or has_verb:
        return result(DIRECT_EVIDENCE, 'implementation_or_experiment_evidence')
    if in_topic_field:
        return result(RESEARCH_TOPIC, 'thesis_subject_field')
    if HEADING_LINE_RE.match(full_line):
        return result(RESEARCH_TOPIC, 'chapter_or_section_heading')
    return result(NEEDS_REVIEW, 'context_not_decisive')


def weigh(context_class: str, profile: str | dict | None = None) -> float:
    """Weight for a context class under a profile."""
    return resolve_profile(profile)[context_class]


def feature_eligible(context_class: str, profile: str | dict | None = None) -> bool:
    """Whether a context class contributes to matching features under a profile."""
    return weigh(context_class, profile) > 0.0
