"""Separate app: fail-closed local auth, bounded CSV and private cohort access."""
import hashlib
import sys

from fastapi.testclient import TestClient

from test_phase7_service import service, csv_text
from backend.app.rebuild_api import create_app


TOKEN = 'technical-token-with-enough-length'


def test_workbook_preview_requires_confirmation_and_preserves_text_ids(service):
    from io import BytesIO
    from openpyxl import Workbook, load_workbook

    workbook = Workbook()
    workbook.active.append(['Họ và tên', 'Mã sinh viên', 'Ý tưởng', 'Mô tả'])
    workbook.active.append(['Sinh viên A', '00123', 'Nhận diện ảnh', 'Mô tả đề tài'])
    workbook.active.append(['Sinh viên B', None, None])
    stream = BytesIO()
    workbook.save(stream)
    path = '/api/rebuild/students/workbook'
    client = TestClient(create_app(service=service, token=TOKEN))
    content = stream.getvalue()
    assert client.post(path, content=content).status_code == 401
    headers = {'Authorization': 'Bearer ' + TOKEN}
    preview = client.post(path, content=content, headers=headers).json()
    assert preview['valid'] and 'cohort_id' not in preview
    assert preview['students'][0]['student_id'] == '00123'
    assert preview['students'][1]['student_id'].startswith('excel-')
    saved = client.post(path + '?confirm=true', content=content, headers=headers).json()
    assert saved['cohort_id'] and saved['students'] == preview['students']

    export = f"/api/rebuild/cohorts/{saved['cohort_id']}/students.xlsx"
    assert client.get(export).status_code == 401
    other_token = 'other-technical-token-long'
    other = TestClient(create_app(service=service, token=other_token))
    assert other.get(export, headers={'Authorization': 'Bearer ' + other_token}).json() == {
        'detail': 'cohort_not_found'
    }
    exported = client.get(export, headers=headers)
    assert exported.status_code == 200 and exported.headers['Cache-Control'] == 'no-store'
    assert 'attachment' in exported.headers['Content-Disposition']
    exported_book = load_workbook(BytesIO(exported.content))
    sheet = exported_book['SinhVien']
    assert sheet['A2'].value == '00123' and sheet['A2'].data_type == 's'
    assert sheet['D2'].value == 'Mô tả đề tài' and sheet['D2'].data_type == 's'
    sheet.move_range('A2:D2', rows=2)
    reordered = BytesIO()
    exported_book.save(reordered)
    exported_book.close()
    imported = client.post(path, content=reordered.getvalue(), headers=headers).json()
    assert imported['valid']
    assert imported['students'] == list(reversed(saved['students']))
    resaved = client.post(path + '?confirm=true', content=reordered.getvalue(), headers=headers).json()
    assert service.get_students(resaved['cohort_id'], scope=hashlib.sha256(TOKEN.encode()).hexdigest())[1][
        'thesis_abstract'
    ] == 'Mô tả đề tài'


def test_workbook_reports_formula_with_original_row_number(service):
    from io import BytesIO
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.active.append(['Họ và tên', 'Ý tưởng'])
    workbook.active.append([None, None])
    workbook.active.append(['Sinh viên A', '=1+2'])
    stream = BytesIO()
    workbook.save(stream)
    client = TestClient(create_app(service=service, token=TOKEN))
    response = client.post('/api/rebuild/students/workbook?confirm=true', content=stream.getvalue(),
                           headers={'Authorization': 'Bearer ' + TOKEN})
    assert response.json()['errors'] == [
        {'row': 3, 'column': 'thesis_title', 'code': 'workbook_formula_or_error'}
    ]


def test_separate_backend_import_does_not_import_broken_legacy_main():
    assert 'backend.app.main' not in sys.modules


def test_auth_fail_closed_and_bootstrap_template_header_only(service):
    app = create_app(service=service, token=TOKEN)
    client = TestClient(app)
    assert client.get('/health').status_code == 200
    assert client.get('/api/rebuild/bootstrap').status_code == 401
    headers = {'Authorization': 'Bearer '+TOKEN}
    bootstrap = client.get('/api/rebuild/bootstrap', headers=headers)
    assert bootstrap.status_code == 200 and len(bootstrap.json()['advisors']) == 2
    template = client.get('/api/rebuild/templates/students.csv', headers=headers)
    assert template.status_code == 200 and len(template.text.lstrip('\ufeff').splitlines()) == 1
    assert TestClient(create_app(service=service, token='')).get('/api/rebuild/bootstrap', headers=headers).status_code == 503


def test_explicit_semester_run_uses_new_loader_and_keeps_auth(service, monkeypatch, tmp_path):
    from src.serving import semester_service
    monkeypatch.setenv('UNIMATCH_SEMESTER_RUN',str(tmp_path))
    monkeypatch.setattr(semester_service,'load_semester_service',lambda root,inputs=None:service)
    client=TestClient(create_app(token=TOKEN))
    assert client.get('/api/rebuild/bootstrap').status_code==401
    response=client.get('/api/rebuild/bootstrap',headers={'Authorization':'Bearer '+TOKEN})
    assert response.status_code==200 and len(response.json()['advisors'])==2


def test_csv_import_quota_compare_export_and_untrusted_origin(service):
    client = TestClient(create_app(service=service, token=TOKEN))
    headers = {'Authorization': 'Bearer '+TOKEN}
    text = csv_text([{'student_id': 's', 'thesis_title': 'Technical thesis'}])
    report = client.post('/api/rebuild/students/validate', headers=headers, json={'csv_text': text}).json()
    assert report['valid']
    quotas = client.post('/api/rebuild/quotas', headers=headers, json={'student_count': 1, 'advisor_ids': ['a']})
    assert quotas.status_code == 200 and quotas.json()['total_capacity'] == 1
    payload = {'cohort_id': report['cohort_id'], 'advisor_ids': ['a'], 'coordinator_confirmed': True}
    result = client.post('/api/rebuild/compare', headers=headers, json=payload)
    assert result.status_code == 200
    assert result.json()['results']['hungarian']['status'] == 'feasible'
    run_id = result.json()['run_id']
    assert client.get(f'/api/rebuild/runs/{run_id}/hungarian.csv', headers=headers).status_code == 200
    assert client.post('/api/rebuild/quotas', headers={**headers, 'Origin': 'https://untrusted.example'}, json={'student_count': 1, 'advisor_ids': ['a']}).status_code == 403
    bad = client.post('/api/rebuild/compare', headers=headers, json={**payload, 'cohort_id': '../other'})
    assert bad.status_code == 400 and 'Traceback' not in bad.text


def test_request_body_is_bounded_before_json_parsing(service, monkeypatch):
    import backend.app.rebuild_api as api
    monkeypatch.setattr(api, 'MAX_REQUEST_BYTES', 64)
    client = TestClient(create_app(service=service, token=TOKEN))
    result = client.post('/api/rebuild/students/validate', headers={'Authorization': 'Bearer '+TOKEN}, content=b'x'*65)
    assert result.status_code == 413


def test_bad_payload_types_are_bounded_and_external_clients_fail_closed(service):
    headers = {'Authorization': 'Bearer '+TOKEN}
    client = TestClient(create_app(service=service, token=TOKEN))
    assert client.post('/api/rebuild/quotas', headers=headers, json={'student_count': 1, 'advisor_ids': None}).status_code == 400
    external = TestClient(create_app(service=service, token=TOKEN), client=('203.0.113.1', 5000))
    assert external.get('/api/rebuild/bootstrap', headers=headers).status_code == 403


def test_faculty_intake_is_protected_and_does_not_change_catalog(service):
    from test_phase7_service import advisor_csv
    client = TestClient(create_app(service=service, token=TOKEN))
    payload = {'csv_text': advisor_csv([service.advisors[0]])}
    assert client.post('/api/rebuild/advisors/validate', json=payload).status_code == 401
    result = client.post('/api/rebuild/advisors/validate', headers={'Authorization': 'Bearer '+TOKEN}, json=payload)
    assert result.status_code == 200 and result.json()['inference_compatible']
    assert result.json()['registry_mutated'] is False and service.advisor_ids == ('a', 'b')
