"""Public HTTPS entrypoint; PostgreSQL and the pinned model release are mandatory."""
import os
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse


def create_app():
    os.environ['UNIMATCH_DEPLOYMENT'] = 'production'
    os.environ.setdefault('OMP_NUM_THREADS', '1')
    os.environ.setdefault('MKL_NUM_THREADS', '1')
    os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
    from .portal_database import Database, RecordStore, database_location
    from .production_release import unpack_release, load_release
    location = database_location()
    if not location.startswith(('postgres://', 'postgresql://')):
        raise ValueError('production_postgresql_required')
    if not os.environ.get('UNIMATCH_PUBLIC_ORIGIN', '').startswith('https://'):
        raise ValueError('production_https_origin_required')
    database = Database(location)
    key = os.environ.get('UNIMATCH_MODEL_BUNDLE', '')
    expected = os.environ.get('UNIMATCH_MODEL_BUNDLE_SHA256', '')
    if not key or len(expected) != 64:
        raise ValueError('pinned_model_bundle_required')
    with database.connect() as db:
        row = db.execute('SELECT sha256,payload FROM model_bundles WHERE bundle_key=?', (key,)).fetchone()
    if not row or row['sha256'] != expected:
        raise ValueError('pinned_model_bundle_unavailable')
    runtime = Path(os.environ.get('UNIMATCH_RUNTIME', '/tmp/unimatch'))
    folder = unpack_release(bytes(row['payload']), expected, runtime/'releases')
    service, assistant = load_release(folder, runtime/'proposals')
    store = RecordStore(database)
    store.catalog(service.versions.get('github_bundle_sha256', expected), service.advisors, service.versions)
    service.record_store = store
    from .rebuild_assistant_api import create_app as create_api
    root = Path(__file__).resolve().parents[2]
    app = create_api(service=service, assistant=assistant, token='', frontend_dir=root/'frontend/dist')
    app.state.record_store = store
    app.state.training_report = folder/'training_report.json'

    @app.middleware('http')
    async def production_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        return response

    async def readiness(request):
        try:
            from starlette.concurrency import run_in_threadpool
            await run_in_threadpool(store.health)
        except Exception:
            return JSONResponse({'status': 'degraded', 'storage': 'unavailable'}, status_code=503)
        return JSONResponse({'status': 'ready', 'storage': 'postgresql', 'data_loaded': True,
            'advisors': len(service.advisors), 'algorithms': sorted(service.models),
            'training_in_handler': False, 'model_release_sha256': expected,
            'model_release': key, 'checkpoint_versions': list(service.checkpoint_versions),
            'checkpoint_count': sum(len(models) for models, _, _ in service.checkpoint_versions.values()) or len(service.models),
            'research_models': True, 'production_promoted': False})
    app.router.routes[:] = [route for route in app.router.routes if getattr(route, 'path', None) != '/health']
    from starlette.routing import Route
    app.router.routes.insert(0, Route('/health', readiness, methods=['GET']))
    return app
