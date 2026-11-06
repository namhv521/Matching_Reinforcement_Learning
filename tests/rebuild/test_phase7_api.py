"""Separate app: fail-closed local auth, bounded CSV and private cohort access."""
import sys

from fastapi.testclient import TestClient

from test_phase7_service import service, csv_text
from backend.app.rebuild_api import create_app


TOKEN = 'technical-token-with-enough-length'


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
