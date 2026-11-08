import hashlib
import json

import pymupdf
import pytest

from scripts.partition_student_pdfs import cover_date, partition_for, move_verified, skill_evidence


def test_cover_date_ignores_spine_term_and_prefers_first_cover():
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=840)
    page.insert_text((24, 740), '11/2025', rotate=90)
    page.insert_text((260, 710), '2025.1')
    page.insert_text((245, 760), 'Ha Noi, 5/2024')
    second = doc.new_page(width=600, height=840)
    second.insert_text((245, 760), 'Ha Noi, 11/2025')
    result = cover_date(doc)
    assert result['date'] == '2024-05'
    assert result['page'] == 1
    assert result['partition'] == '2024'


@pytest.mark.parametrize('date,partition,term', [
    ('2025-08', '2024', '2024.3'),
    ('2025-09', '2025.1', '2025.1'),
    ('2026-05', '2025.2', '2025.2'),
    ('2026-06', '2025.3', '2025.3'),
])
def test_partition_boundaries(date, partition, term):
    assert partition_for(date) == (partition, term)


def test_year_only_and_unrelated_numbers_are_unresolved():
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=840)
    page.insert_text((245, 760), 'Ha Noi, 2025')
    assert cover_date(doc)['status'] == 'unresolved'


def test_submission_report_footer_is_not_a_thesis_cover_date():
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=840)
    page.insert_text((200, 760), 'Submission Date: 12/2024')
    assert cover_date(doc)['status'] == 'unresolved'
    page.insert_text((245, 720), '2025.2')
    assert cover_date(doc)['status'] == 'unresolved'


def test_inner_cover_date_is_used_only_when_outer_cover_has_no_month():
    doc = pymupdf.open()
    outer = doc.new_page(width=600, height=840)
    outer.insert_text((245, 760), 'Ha Noi, 2025')
    inner = doc.new_page(width=600, height=840)
    # The Vietnamese heading is supplied as the native Unicode extraction.
    inner.insert_text((245, 760), 'Ha Noi, 5/2025')
    from scripts import partition_student_pdfs as module
    original = module.page_lines
    def lines(page, textpage=None):
        result = original(page, textpage)
        if page.number == 1:
            result.append({'text': 'KHÓA LUẬN TỐT NGHIỆP', 'bbox': [100, 300, 500, 330], 'dir': [1, 0]})
        return result
    from unittest.mock import patch
    with patch.object(module, 'page_lines', lines):
        assert cover_date(doc)['date'] == '2025-05'


def test_skill_evidence_excludes_references_and_does_not_assign_levels():
    result = skill_evidence(['We implement the server using Python.',
                             'REFERENCES\nTensorFlow documentation'])
    assert 'python' in result['programming_languages']
    assert 'tensorflow' not in result['frameworks_libraries']
    assert result['evidence'][0]['page'] == 1
    assert 'Python' in result['evidence'][0]['snippet']


def test_move_verifies_bytes_and_never_overwrites(tmp_path):
    source = tmp_path / 'source.pdf'
    source.write_bytes(b'original bytes')
    destination = tmp_path / 'KLTN' / 'source.pdf'
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    move_verified(source, destination, digest)
    assert destination.read_bytes() == b'original bytes'
    assert not source.exists()
    source.write_bytes(b'other bytes')
    with pytest.raises(FileExistsError):
        move_verified(source, destination, hashlib.sha256(source.read_bytes()).hexdigest())
    assert source.exists()


def test_title_stops_before_student_label_and_date_and_skips_placeholder():
    from scripts.partition_student_pdfs import title_from_cover_lines
    assert title_from_cover_lines([
        ['KHÓA LUẬN TỐT NGHIỆP', 'ĐỀ TÀI: Xây dựng', 'hệ thống quản lý',
         'Họ tên sinh viên: Nguyễn Văn A', 'Hà Nội, 5/2025'],
    ]) == 'Xây dựng hệ thống quản lý'
    assert title_from_cover_lines([
        ['KHÓA LUẬN TỐT NGHIỆP', 'Tên đề tài', 'Tên sinh viên: A'],
        ['KHÓA LUẬN TỐT NGHIỆP', 'Thiết kế game nhập vai hành động 2D',
         'Unity Engine', 'Tên sinh viên: A'],
    ]) == 'Thiết kế game nhập vai hành động 2D Unity Engine'
    assert title_from_cover_lines([
        ['BÁO CÁO', 'CHUYÊN ĐỀ THỰC TẬP', 'Đề tài:', 'Xây dựng website',
         'quản lý trung tâm tiếng Anh', 'Hà Nội, 9/2025'],
    ]) == 'Xây dựng website quản lý trung tâm tiếng Anh'


def test_new_run_cannot_erase_previously_processed_students(tmp_path):
    from scripts.partition_student_pdfs import apply
    source = tmp_path / 'data/1.pdfs'
    source.mkdir(parents=True)
    report = tmp_path / 'report'
    report.mkdir()
    target = source.parent / '2024/student/students_processed/students_processed.csv'
    target.parent.mkdir(parents=True)
    target.write_text('source_sha256\nexisting-student-hash\n', encoding='utf-8')
    original = target.read_bytes()
    (report / 'plan.json').write_text(json.dumps({'source': str(source),
        'files': [], 'rows': [], 'header': ['source_sha256']}), encoding='utf-8')
    with pytest.raises(ValueError, match='existing_student_rows_outside_current_plan'):
        apply(report)
    assert target.read_bytes() == original
