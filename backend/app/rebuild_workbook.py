"""Normalize a student workbook into the existing Rebuild intake contract."""

import csv
import hashlib
import io
import unicodedata
import zipfile
from xml.etree.ElementTree import ParseError

from openpyxl import Workbook, load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from src.data_pipeline.csv_contracts import HEADERS
from src.serving.rebuild_service import MAX_IMPORT_ROWS

try:
    from lxml.etree import XMLSyntaxError
except ImportError:
    XMLSyntaxError = ParseError

ALIASES = {
    'student_name': ('student_name', 'họ và tên', 'họ tên', 'tên sinh viên', 'tên'),
    'student_id': ('student_id', 'mã sinh viên', 'mã sv', 'mssv'),
    'thesis_title': ('thesis_title', 'topic_title', 'đề tài', 'ý tưởng', 'tên đề tài'),
    'thesis_abstract': ('thesis_abstract', 'topic_description', 'mô tả', 'mô tả đề tài'),
}

WORKBOOK_COLUMNS = {
    'student_id': 'student_id',
    'student_name': 'student_name',
    'topic_title': 'thesis_title',
    'topic_description': 'thesis_abstract',
}


def export_workbook(students):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'SinhVien'
    sheet.append(list(WORKBOOK_COLUMNS))
    for student in students:
        sheet.append([student.get(field) or '' for field in WORKBOOK_COLUMNS.values()])
        for cell in sheet[sheet.max_row]:
            # Keep identifiers and formula-shaped input as literal strings.
            cell.data_type = 's'
            cell.number_format = '@'
    sheet.freeze_panes = 'C2'
    sheet.auto_filter.ref = sheet.dimensions
    for column, width in zip('ABCD', (34, 32, 44, 64)):
        sheet.column_dimensions[column].width = width
    metadata = workbook.create_sheet('ThongTin')
    metadata.append(['schema_version', 'unimatch-student-workbook/1'])
    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def normalize_workbook(content):
    errors = []

    def error(row, column, code):
        if len(errors) < 1000:
            errors.append({'row': row, 'column': column, 'code': code})

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if (len(entries) > 2048 or sum(entry.file_size for entry in entries) > 50 * 1024 * 1024
                    or any(entry.flag_bits & 1 for entry in entries)):
                raise ValueError('unsupported_workbook_archive')
            if any(name.lower().endswith('vbaproject.bin') or name.startswith('xl/externalLinks/')
                   for name in archive.namelist()):
                raise ValueError('unsupported_workbook_content')
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=False, keep_links=False)
    except (ValueError, OSError, KeyError, zipfile.BadZipFile, InvalidFileException, ParseError, XMLSyntaxError):
        error(0, '__file__', 'invalid_workbook')
        return None, errors

    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, HEADERS['students'])
    writer.writeheader()
    count = 0
    try:
        if not 1 <= len(workbook.worksheets) <= 20:
            error(0, '__file__', 'workbook_sheet_limit')
            return None, errors
        sheet = workbook['SinhVien'] if 'SinhVien' in workbook else workbook.worksheets[0]
        if (sheet.max_column or 0) > 64:
            error(1, '__header__', 'workbook_column_limit')
            return None, errors
        cells = sheet.iter_rows(max_col=65)
        headers = [' '.join(unicodedata.normalize('NFC', str(cell.value or '')).casefold().split())
                   for cell in next(cells, ())]
        columns = {}
        for key, aliases in ALIASES.items():
            matches = [i for i, header in enumerate(headers) if header in aliases]
            if len(matches) > 1:
                error(1, key, 'duplicate_workbook_column')
            if matches:
                columns[key] = matches[0]
        if 'student_name' not in columns:
            error(1, 'student_name', 'workbook_name_column_required')
        if errors:
            return None, errors
        fingerprint = hashlib.sha256(content).hexdigest()[:16]
        seen = set()
        for number, cells_in_row in enumerate(cells, 2):
            if number > MAX_IMPORT_ROWS + 1:
                error(number, '__file__', 'row_count_limit')
                break
            if not any(cell.value is not None for cell in cells_in_row):
                continue
            row = {}
            for key, index in columns.items():
                cell = cells_in_row[index]
                value = cell.value
                if cell.data_type in ('f', 'e'):
                    error(number, key, 'workbook_formula_or_error')
                elif value is not None and not isinstance(value, str):
                    error(number, key, 'workbook_text_required')
                row[key] = unicodedata.normalize('NFC', str(value or '')).strip()
            if not row['student_name']:
                error(number, 'student_name', 'workbook_name_required')
            student_id = row.get('student_id') or f'excel-{fingerprint}-{number}'
            if student_id in seen:
                error(number, 'student_id', 'duplicate_identity')
            seen.add(student_id)
            writer.writerow({**row, 'student_id': student_id})
            count += 1
    except (ValueError, OSError, zipfile.BadZipFile, ParseError, XMLSyntaxError):
        error(0, '__file__', 'invalid_workbook')
    finally:
        workbook.close()
    if count == 0 and not errors:
        error(1, '__file__', 'empty_dataset')
    return (None if errors else output.getvalue()), errors
