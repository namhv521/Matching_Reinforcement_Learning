"""Additive local API entrypoint; incumbent app is never imported or switched."""
import hashlib
import hmac
import json
import os
import threading
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from src.serving.rebuild_service import MAX_CSV_BYTES, RebuildService


MAX_REQUEST_BYTES = 2 * MAX_CSV_BYTES + 65536
ROOT = Path(__file__).resolve().parents[2]


def create_app(*, service=None, token=None, output=None, selection_manifest=None,
               frontend_dir=None, allow_origins=None):
    app = FastAPI(title='UniMatch local rebuild proposals', docs_url=None, redoc_url=None, openapi_url=None)
    production = os.environ.get('UNIMATCH_DEPLOYMENT') == 'production'
    if production:
        from .portal_database import database_location
        if not database_location().startswith(('postgres://', 'postgresql://')):
            raise ValueError('production_postgresql_required')
        if urlparse(os.environ.get('UNIMATCH_PUBLIC_ORIGIN', '')).scheme != 'https':
            raise ValueError('production_https_origin_required')
    configured_token = os.environ.get('UNIMATCH_REBUILD_TOKEN', '') if token is None else token
    output = Path(output or ROOT/'data_rebuild/v1')
    selection = selection_manifest or os.environ.get('UNIMATCH_REBUILD_SELECTION')
    origins = list(allow_origins or [])
    if any(urlparse(origin).hostname not in {'127.0.0.1', 'localhost', '::1'} or urlparse(origin).scheme not in {'http', 'https'} for origin in origins):
        raise ValueError('only_explicit_local_origins_allowed')
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=['GET', 'POST'],
                           allow_headers=['Authorization', 'Content-Type'], allow_credentials=False)
    app.state.rebuild_service = service
    semester_run=os.environ.get('UNIMATCH_SEMESTER_RUN')
    app.state.semester_run=Path(semester_run).resolve() if semester_run else None
    app.state.rebuild_initialization_lock = threading.Lock()

    def authorize(request: Request):
        if not production and request.client and request.client.host not in {'127.0.0.1', '::1', 'testclient'}:
            raise HTTPException(403, detail='local_access_only')
        if request.cookies.get('unimatch_session') and hasattr(app.state, 'portal_authenticated'):
            if request.method != 'GET' and request.headers.get('sec-fetch-site') == 'cross-site':
                raise HTTPException(403, detail='origin_not_allowed')
            origin = request.headers.get('origin')
            expected_origin = os.environ.get('UNIMATCH_PUBLIC_ORIGIN', '').rstrip('/') if production else str(request.base_url).rstrip('/')
            if origin and origin != expected_origin and origin not in origins:
                raise HTTPException(403, detail='origin_not_allowed')
            return app.state.portal_authenticated(request)['id']
        if production:
            raise HTTPException(401, detail='login_required')
        if not isinstance(configured_token, str) or len(configured_token) < 16 or not configured_token.strip():
            raise HTTPException(503, detail='local_auth_not_configured')
        header = request.headers.get('authorization', '')
        if not header.startswith('Bearer ') or not hmac.compare_digest(header[7:].encode(), configured_token.encode()):
            raise HTTPException(401, detail='bearer_token_required')
        origin = request.headers.get('origin')
        same_origin = str(request.base_url).rstrip('/')
        if origin and origin != same_origin and origin not in origins:
            raise HTTPException(403, detail='origin_not_allowed')
        return hashlib.sha256(configured_token.encode()).hexdigest()

    def get_service(scope=Depends(authorize)):
        if app.state.rebuild_service is None:
            with app.state.rebuild_initialization_lock:
                if app.state.rebuild_service is None:
                    try:
                        if app.state.semester_run is not None:
                            from src.serving.semester_service import load_semester_service
                            app.state.rebuild_service=load_semester_service(app.state.semester_run,inputs=os.environ.get('UNIMATCH_SEMESTER_INPUTS'))
                        else:
                            app.state.rebuild_service = RebuildService.from_artifacts(output, selection_manifest=selection)
                    except Exception:
                        # Source/checkpoint paths, names, tokens and tracebacks never enter HTTP errors.
                        raise HTTPException(503, detail='verified_artifacts_not_ready') from None
        return app.state.rebuild_service

    app.state.rebuild_authorize = authorize
    app.state.rebuild_get_service = get_service

    async def body(request):
        try:
            declared = int(request.headers.get('content-length', '0'))
        except ValueError:
            raise HTTPException(400, detail='invalid_content_length') from None
        if declared < 0 or declared > MAX_REQUEST_BYTES:
            raise HTTPException(413, detail='request_size_limit')
        chunks, length = [], 0
        async for chunk in request.stream():
            length += len(chunk)
            if length > MAX_REQUEST_BYTES:
                raise HTTPException(413, detail='request_size_limit')
            chunks.append(chunk)
        try:
            value = json.loads(b''.join(chunks).decode('utf-8'))
        except (ValueError, UnicodeError):
            raise HTTPException(400, detail='invalid_json') from None
        if not isinstance(value, dict):
            raise HTTPException(400, detail='json_object_required')
        return value

    @app.exception_handler(ValueError)
    async def value_error(request, error):
        # Only module-owned constant error codes are returned; no input text or paths.
        message = str(error)
        safe = message if message.replace('_', '').isalnum() and len(message) < 100 else 'invalid_inference_request'
        return JSONResponse({'detail': safe}, status_code=400)

    @app.exception_handler(Exception)
    async def bounded_failure(request, error):
        return JSONResponse({'detail': 'local_inference_failed'}, status_code=500)

    @app.middleware('http')
    async def privacy_headers(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.get('/health')
    def health():
        return {'status': 'ready' if app.state.rebuild_service is not None else 'degraded',
                'mode': 'local_inference_only', 'training_in_handler': False}

    @app.get('/api/rebuild/bootstrap')
    def bootstrap(active=Depends(get_service)):
        return active.bootstrap()

    @app.get('/api/rebuild/templates/{entity}.csv')
    def template(entity: str, active=Depends(get_service)):
        return Response(active.template(entity), media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition': f'attachment; filename="{entity}_import.csv"'})

    @app.post('/api/rebuild/students/validate')
    async def validate_students(request: Request, scope=Depends(authorize), active=Depends(get_service)):
        payload = await body(request)
        return await run_in_threadpool(active.validate_students, payload.get('csv_text'), scope=scope)

    @app.post('/api/rebuild/quotas')
    async def quotas(request: Request, active=Depends(get_service)):
        payload = await body(request)
        return active.quotas(payload.get('student_count'), payload.get('advisor_ids', []))

    @app.post('/api/rebuild/advisors/validate')
    async def validate_advisors(request: Request, scope=Depends(authorize), active=Depends(get_service)):
        payload = await body(request)
        return await run_in_threadpool(active.validate_advisors, payload.get('csv_text'), scope=scope)

    @app.post('/api/rebuild/recommend')
    async def recommend(request: Request, scope=Depends(authorize), active=Depends(get_service)):
        payload = await body(request)
        return await run_in_threadpool(active.recommend, payload.get('cohort_id'), payload.get('advisor_ids', []),
                                       top_k=payload.get('top_k', 5), scope=scope)

    @app.post('/api/rebuild/compare')
    async def compare(request: Request, scope=Depends(authorize), active=Depends(get_service)):
        payload = await body(request)
        return await run_in_threadpool(active.compare, payload.get('cohort_id'), payload.get('advisor_ids', []),
                                       coordinator_confirmed=payload.get('coordinator_confirmed', False), scope=scope)

    @app.get('/api/rebuild/runs/{run_id}/{algorithm}.csv')
    def export(run_id: str, algorithm: str, scope=Depends(authorize), active=Depends(get_service)):
        return Response(active.export(run_id, algorithm, scope=scope), media_type='text/csv; charset=utf-8',
                        headers={'Content-Disposition': 'attachment; filename="allocation_proposals.csv"'})

    @app.get('/api/rebuild/runs/{run_id}')
    def run(run_id: str, scope=Depends(authorize), active=Depends(get_service)):
        return active._get('runs', run_id, scope)

    frontend = Path(frontend_dir or (ROOT/'frontend/dist' if (ROOT/'frontend/dist').is_dir() else ROOT/'frontend'))
    if frontend.is_dir():
        app.mount('/', StaticFiles(directory=frontend, html=True), name='existing_frontend')
    from backend.app.portal import install_portal
    install_portal(app)
    return app


app = create_app()
