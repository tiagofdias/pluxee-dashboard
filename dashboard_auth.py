"""Credential-based Pluxee login with opaque, temporary server-memory sessions."""
import hashlib
import hmac
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

from flask import Blueprint, g, jsonify, redirect, request, send_from_directory
import cloud_store as config
import pluxee_mobile_auth

blueprint = Blueprint('dashboard_auth', __name__)
COOKIE = 'pluxee_session'
SESSION_HOURS = 8
_sessions = {}
_limits = {}
_lock = threading.RLock()
_rate_salt = secrets.token_bytes(32)


def secure_cookie():
    return config.setting('RENDER').lower() in ('true', '1') or request.is_secure


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _purge():
    now = datetime.now(timezone.utc)
    for key, row in list(_sessions.items()):
        if datetime.fromisoformat(row['expires_at']) <= now:
            _sessions.pop(key)
            row['account'].close()
    for key, (started, count) in list(_limits.items()):
        if time.monotonic() - started > 900:
            _limits.pop(key)


def session_for_request():
    token = request.cookies.get(COOKIE, '')
    if not 40 <= len(token) <= 128:
        return None
    with _lock:
        _purge()
        return _sessions.get(token_hash(token))


def revoke_session(row):
    with _lock:
        _sessions.pop(row['token_hash'], None)
    row['account'].close()
    row.pop('snapshot', None)


def same_origin():
    origin = request.headers.get('Origin')
    expected = config.setting('APP_ORIGIN') or request.host_url.rstrip('/')
    return (not origin or origin.rstrip('/') == expected.rstrip('/')) and request.headers.get('Sec-Fetch-Site') not in ('cross-site', 'none')


def check_private_request():
    path = request.path.rstrip('/') or '/'
    if path in ('/data.json', '/static/data.json') or path.startswith('/data/'):
        return jsonify(error='Este ficheiro não é público.'), 404
    if path.startswith('/static/'):
        asset = path.removeprefix('/static/')
        public = {'style.css', 'login.css', 'app.js', 'auth.js', 'login.js', 'demo-data.js', 'manifest.json', 'sw.js', 'login.html'}
        if asset == 'index.html':
            return redirect('/')
        if asset not in public and not (asset.startswith('icons/') and '..' not in asset):
            return jsonify(error='Não encontrado.'), 404
    # Existing owner-monitor integrations are independently authenticated.
    if path == '/api/cron/check':
        expected = config.setting('CRON_SECRET')
        if not expected or not hmac.compare_digest(request.headers.get('Authorization', ''), 'Bearer ' + expected):
            return jsonify(error='Não autorizado.'), 403
        return None
    if path == '/api/telegram/webhook':
        expected = config.setting('TELEGRAM_WEBHOOK_SECRET')
        if not expected or not hmac.compare_digest(request.headers.get('X-Telegram-Bot-Api-Secret-Token', ''), expected):
            return jsonify(error='Não autorizado.'), 403
        return None
    public_api = {'/api/auth/login', '/api/auth/session'}
    needs_auth = path.startswith('/api/') and path not in public_api
    if path in ('/', '/index.html') or needs_auth:
        g.private_session = session_for_request()
        if not g.private_session:
            return redirect('/login') if not needs_auth else (jsonify(error='É necessário iniciar sessão.'), 401)
    if path.startswith('/api/auth/') and request.method not in ('GET', 'HEAD', 'OPTIONS'):
        if not same_origin() or request.headers.get('X-Pluxee-Request') != '1':
            return jsonify(error='Pedido inválido.'), 403
    if needs_auth:
        # A Pluxee login gives access only to that user's card, never the server
        # owner's monitor, logs, environment configuration or push subscribers.
        if path not in {'/api/balance', '/api/auth/logout', '/api/notifications/status'}:
            return jsonify(error='Esta operação não está disponível nesta sessão.'), 403
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            if not same_origin() or not hmac.compare_digest(request.headers.get('X-CSRF-Token', ''), g.private_session['csrf_token']):
                return jsonify(error='Pedido inválido. Atualiza a página.'), 403
    return None


@blueprint.get('/login')
def login_page():
    return send_from_directory('static', 'login.html')


@blueprint.get('/demo')
@blueprint.get('/demo.html')
def demo_page():
    return send_from_directory('static', 'index.html')


@blueprint.get('/api/auth/session')
def session_info():
    row = session_for_request()
    if not row:
        return jsonify(authenticated=False, configured=True, provider='pluxee'), 401
    return jsonify(authenticated=True, configured=True, provider='pluxee',
                   csrf_token=row['csrf_token'], push_available=False,
                   display_name=row['account'].display_name)


def _reserve_attempt(email):
    ip = request.remote_addr or 'unknown'
    keys = [(hmac.new(_rate_salt, ('ip:' + ip).encode(), hashlib.sha256).hexdigest(), 10),
            (hmac.new(_rate_salt, ('account:' + email.strip().casefold()).encode(), hashlib.sha256).hexdigest(), 2)]
    with _lock:
        _purge()
        if len(_limits) > 2048:
            return None
        now = time.monotonic()
        if any(_limits.get(key, (now, 0))[1] >= limit for key, limit in keys):
            return None
        for key, limit in keys:
            started, count = _limits.get(key, (now, 0))
            _limits[key] = (started, count + 1)
    return keys[1][0]


@blueprint.post('/api/auth/login')
def login():
    if not request.is_secure and request.remote_addr not in ('127.0.0.1', '::1'):
        return jsonify(error='Usa uma ligação HTTPS para iniciar sessão.'), 400
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error='Pedido inválido.'), 400
    email, password = data.get('email'), data.get('password')
    if not isinstance(email, str) or '@' not in email or not 3 <= len(email) <= 254 or not isinstance(password, str) or not 1 <= len(password) <= 1024:
        return jsonify(error='Indica o email e a palavra-passe da tua conta Pluxee.'), 400
    email_limit = _reserve_attempt(email)
    if not email_limit:
        return jsonify(error='Demasiadas tentativas. Aguarda 15 minutos antes de voltar a tentar.'), 429
    with _lock:
        if len(_sessions) >= 128:
            return jsonify(error='O serviço está ocupado. Tenta novamente mais tarde.'), 503
    try:
        account = pluxee_mobile_auth.login(email, password, origin_ip=request.remote_addr or '')
    except pluxee_mobile_auth.MobileLoginError as error:
        return jsonify(error=str(error)), 401
    except pluxee_mobile_auth.MobileUnavailable as error:
        return jsonify(error=str(error)), 503
    # Never save the email/password. Only the upstream session and card references
    # remain in this process until logout, expiry or server restart.
    token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    expiry = datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)
    row = {'token_hash': token_hash(token), 'csrf_token': csrf,
           'expires_at': expiry.isoformat(), 'account': account, 'snapshot': None}
    previous = session_for_request()
    if previous:
        revoke_session(previous)
    with _lock:
        _sessions[row['token_hash']] = row
        _limits.pop(email_limit, None)
    response = jsonify(success=True)
    response.set_cookie(COOKIE, token, max_age=SESSION_HOURS*3600, httponly=True,
                        secure=secure_cookie(), samesite='Lax', path='/')
    return response


@blueprint.post('/api/auth/logout')
def logout():
    revoke_session(g.private_session)
    response = jsonify(success=True)
    response.delete_cookie(COOKIE, path='/', secure=secure_cookie(), httponly=True, samesite='Lax')
    response.headers['Clear-Site-Data'] = '"cache", "storage"'
    return response
