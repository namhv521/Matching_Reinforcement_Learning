"""Browser authentication and bounded, read-only experiment telemetry."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlencode, urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

ROOT = Path(__file__).resolve().parents[2]
COOKIE = 'unimatch_session'
PROVIDERS = {
    'google': ('https://accounts.google.com/o/oauth2/v2/auth', 'https://oauth2.googleapis.com/token',
               'https://openidconnect.googleapis.com/v1/userinfo', 'openid profile email'),
    'github': ('https://github.com/login/oauth/authorize', 'https://github.com/login/oauth/access_token',
               'https://api.github.com/user', 'read:user'),
    'facebook': ('https://www.facebook.com/v23.0/dialog/oauth', 'https://graph.facebook.com/v23.0/oauth/access_token',
                 'https://graph.facebook.com/v23.0/me?fields=id,name', 'public_profile'),
}


def hashed(value):
    return hashlib.sha256(value.encode()).hexdigest()


class AuthStartRateLimiter:
    """Bound OAuth-start requests per direct client IP in a sliding window."""
    def __init__(self, limit, window_seconds):
        self.limit = limit
        self.window_seconds = window_seconds
        self.requests = {}
        self.lock = threading.Lock()

    def allow(self, client_ip):
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self.lock:
            for key, timestamps in list(self.requests.items()):
                while timestamps and timestamps[0] <= cutoff:
                    timestamps.popleft()
                if not timestamps:
                    del self.requests[key]
            timestamps = self.requests.setdefault(client_ip, deque())
            if len(timestamps) >= self.limit:
                return False
            timestamps.append(now)
            return True


def auth_start_rate_limiter():
    try:
        limit = int(os.environ.get('UNIMATCH_AUTH_START_RATE_LIMIT', '10'))
        window_seconds = int(os.environ.get('UNIMATCH_AUTH_START_RATE_WINDOW_SECONDS', '60'))
    except ValueError:
        raise ValueError('invalid_auth_start_rate_limit') from None
    if not 1 <= limit <= 1000 or not 1 <= window_seconds <= 3600:
        raise ValueError('invalid_auth_start_rate_limit')
    return AuthStartRateLimiter(limit, window_seconds)


class PortalStore:
    def __init__(self, path):
        from .portal_database import Database
        self.database = path if isinstance(path, Database) else Database(path)

    def connect(self):
        return self.database.connect()

    def create_session(self, provider, subject, name):
        identity = hashed(provider + ':' + subject)
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute('INSERT INTO users VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name',
                       (identity, provider, subject, name[:160]))
            db.execute('DELETE FROM sessions WHERE expires < ?', (time.time(),))
            db.execute('INSERT INTO sessions VALUES (?,?,?)', (hashed(token), identity, time.time() + 28800))
        return token

    def session(self, token):
        if not token or len(token) > 200:
            return None
        with self.connect() as db:
            row = db.execute('SELECT u.id,u.name,u.provider FROM users u JOIN sessions s ON s.user_id=u.id '
                             'WHERE s.token=? AND s.expires>?', (hashed(token), time.time())).fetchone()
        return dict(row) if row else None

    def create_pending(self, provider, verifier):
        state = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute('DELETE FROM pending WHERE expires < ?', (time.time(),))
            db.execute('INSERT INTO pending VALUES (?,?,?,?)', (hashed(state), provider, verifier, time.time() + 300))
        return state

    def consume_pending(self, state):
        with self.connect() as db:
            row = db.execute('DELETE FROM pending WHERE state=? AND expires>? RETURNING provider,verifier',
                             (hashed(state), time.time())).fetchone()
        return dict(row) if row else None


def install_portal(app):
    from .portal_database import database_location
    store = PortalStore(database_location())
    app.state.portal_store = store
    app.state.portal_auth_start_rate_limiter = auth_start_rate_limiter()
    router = APIRouter()
    origin = os.environ.get('UNIMATCH_PUBLIC_ORIGIN', 'http://127.0.0.1:8767').rstrip('/')
    parsed = urlparse(origin)
    if (parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.path
            or parsed.query or parsed.fragment or parsed.username or parsed.password
            or parsed.scheme == 'http' and parsed.hostname not in ('127.0.0.1', 'localhost', '::1', 'testserver')):
        raise ValueError('https_public_origin_or_loopback_required')
    secure = parsed.scheme == 'https'

    def check_origin(request):
        # Browsers send Origin for fetch POST; no cross-site state changes.
        if request.headers.get('origin') not in (None, origin):
            raise HTTPException(403, 'origin_not_allowed')
        if request.headers.get('sec-fetch-site') == 'cross-site':
            raise HTTPException(403, 'origin_not_allowed')

    def authenticated(request: Request):
        user = store.session(request.cookies.get(COOKIE))
        if user is None:
            raise HTTPException(401, 'login_required')
        return user

    app.state.portal_authenticated = authenticated

    def provider_ready(provider):
        return bool(os.environ.get(f'UNIMATCH_{provider.upper()}_CLIENT_ID')
                    and os.environ.get(f'UNIMATCH_{provider.upper()}_CLIENT_SECRET'))

    @router.get('/api/auth/config')
    def config():
        return {'providers': {key: provider_ready(key) for key in PROVIDERS}}

    @router.get('/api/auth/me')
    def me(request: Request):
        return authenticated(request)

    @router.post('/api/auth/logout')
    def logout(request: Request):
        check_origin(request)
        with store.connect() as db:
            db.execute('DELETE FROM sessions WHERE token=?', (hashed(request.cookies.get(COOKIE, '')),))
        response = JSONResponse({'ok': True})
        response.delete_cookie(COOKIE, path='/', secure=secure, httponly=True, samesite='lax')
        return response

    @router.post('/api/auth/start/{provider}')
    async def start(provider: str, request: Request):
        check_origin(request)
        if provider not in PROVIDERS or not provider_ready(provider):
            raise HTTPException(503, 'social_login_not_configured')
        client_ip = request.client.host if request.client else 'unknown'
        if not app.state.portal_auth_start_rate_limiter.allow(client_ip):
            raise HTTPException(429, 'auth_start_rate_limited', headers={
                'Retry-After': str(app.state.portal_auth_start_rate_limiter.window_seconds)})
        verifier = secrets.token_urlsafe(48)
        state = store.create_pending(provider, verifier)
        params = {'client_id': os.environ[f'UNIMATCH_{provider.upper()}_CLIENT_ID'],
                  'redirect_uri': f'{origin}/api/auth/callback/{provider}',
                  'response_type': 'code', 'scope': PROVIDERS[provider][3], 'state': state}
        if provider != 'facebook':
            params.update(code_challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode(),
                          code_challenge_method='S256')
        response = JSONResponse({'url': PROVIDERS[provider][0] + '?' + urlencode(params)})
        response.set_cookie('unimatch_oauth', state, max_age=300, httponly=True, secure=secure, samesite='lax', path='/api/auth/callback')
        return response

    @router.get('/api/auth/callback/{provider}')
    async def callback(provider: str, request: Request, state: str = '', code: str = ''):
        bound = request.cookies.get('unimatch_oauth', '')
        if (not state or len(state) > 200 or not bound or not hmac.compare_digest(state, bound)
                or provider not in PROVIDERS):
            raise HTTPException(400, 'invalid_oauth_state')
        pending = store.consume_pending(state)
        if not pending or pending['provider'] != provider or not code or len(code) > 4096:
            raise HTTPException(400, 'expired_oauth_state')
        if not provider_ready(provider):
            raise HTTPException(503, 'social_login_not_configured')
        params = {'client_id': os.environ[f'UNIMATCH_{provider.upper()}_CLIENT_ID'],
                  'client_secret': os.environ[f'UNIMATCH_{provider.upper()}_CLIENT_SECRET'], 'code': code,
                  'redirect_uri': f'{origin}/api/auth/callback/{provider}', 'grant_type': 'authorization_code'}
        if provider != 'facebook':
            params['code_verifier'] = pending['verifier']
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                exchange = await client.post(PROVIDERS[provider][1], data=params, headers={'Accept': 'application/json'})
                exchange.raise_for_status()
                access = exchange.json()['access_token']
                profile = await client.get(PROVIDERS[provider][2], headers={'Authorization': f'Bearer {access}', 'Accept': 'application/json'})
                profile.raise_for_status()
                identity = profile.json()
            subject = str(identity.get('sub') or identity.get('id') or '')
            if not subject:
                raise ValueError()
            session = store.create_session(provider, subject, str(identity.get('name') or identity.get('login') or 'Sinh viên'))
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return RedirectResponse('/login.html?error=provider', status_code=303)
        response = RedirectResponse('/landing.html', status_code=303)
        response.set_cookie(COOKIE, session, max_age=28800, secure=secure, httponly=True, samesite='lax', path='/')
        response.delete_cookie('unimatch_oauth', path='/api/auth/callback')
        return response

    @router.get('/api/rebuild/training')
    def training(request: Request):
        # Existing local operators can use the same bearer authorization as matching.
        if request.headers.get('authorization') and hasattr(app.state, 'rebuild_authorize'):
            app.state.rebuild_authorize(request)
        else:
            authenticated(request)
        if getattr(app.state,'semester_run',None) is not None:
            from src.serving.semester_service import semester_telemetry
            active=app.state.rebuild_get_service()
            return semester_telemetry(app.state.semester_run,active.versions)
        path = getattr(app.state, 'training_report', ROOT / 'docs/validation/github_retraining_numeric_20261023.json')
        if not path.is_file():
            raise HTTPException(503, 'training_report_unavailable')
        report = json.loads(path.read_bytes())
        service = getattr(app.state, 'rebuild_service', None)
        if not service or service.versions.get('selection_run_id') != report['experiment']['run_id']:
            raise HTTPException(409, 'training_report_does_not_match_active_models')
        models = {}
        target = max(report['experiment']['plan']['evaluation_steps'])
        for algorithm in ('ppo', 'dqn'):
            rows = [row for row in report['curves'] if row['algorithm'] == algorithm]
            plateau = report['plateau'][algorithm]
            models[algorithm] = {'trained_steps': min(row['actual_steps'] for row in report['jobs'] if row['algorithm'] == algorithm),
                'target_steps': target, 'selected_steps': report['selected'][algorithm]['checkpoint_steps'],
                'seeds': len(report['experiment']['plan']['seeds']), 'plateau': plateau['plateau_in_tested_budget'],
                'criterion': plateau['criterion'], 'observed_range': plateau['range'],
                'curve': [{'steps': row['total_steps'], 'mean': row['validation']['objective']['mean'],
                           'ci95': row['validation']['objective']['ci95'],
                           'compatibility': row['validation']['mean_compatibility']['mean']} for row in rows]}
        baseline = next(row['metrics']['objective'] for row in report['baselines'] if row['algorithm'] == 'hungarian')
        return {'mode': 'saved_experiment', 'run_id': report['experiment']['run_id'],
                'updated_at': path.stat().st_mtime, 'models': models, 'baseline_objective': baseline,
                'test_evaluated': False, 'validation_students': report['feature_summary']['train_validation_test'][1],
                'source': 'GitHub đã duyệt + hồ sơ giảng viên chính thức',
                'production_promoted': False}

    # Put exact endpoints before the frontend StaticFiles catch-all.
    old = list(app.router.routes)
    app.include_router(router)
    app.router.routes[:] = app.router.routes[len(old):] + old
