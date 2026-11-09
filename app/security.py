"""Browser password prompt; hosting must terminate HTTPS."""
import hmac
import json
import secrets
import tempfile
from pathlib import Path
from functools import lru_cache
import os
from urllib.parse import urlsplit

from flask import Response, abort, request, render_template
from itsdangerous import URLSafeTimedSerializer, BadSignature
from werkzeug.security import generate_password_hash, check_password_hash
from core.settings import DATA_DIR


def password_file():
    return Path(os.environ.get("APP_PASSWORD_FILE", DATA_DIR / "app-password.json"))


@lru_cache(maxsize=8)
def verified_password(encoded, candidate):
    return check_password_hash(encoded, candidate)


def save_password(value):
    path = password_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump({"password_hash": generate_password_hash(value)}, handle)
        temporary.replace(path)
        verified_password.cache_clear()
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def protect_app(app):
    username = os.environ.get('APP_USERNAME', '')
    password = os.environ.get('APP_PASSWORD', '')
    tokens = URLSafeTimedSerializer(secrets.token_hex(32), salt='change-password')
    if os.environ.get('RENDER') and (not username or not password):
        raise RuntimeError('Set APP_USERNAME and APP_PASSWORD before deploying.')
    if bool(username) != bool(password):
        raise RuntimeError('APP_USERNAME and APP_PASSWORD must both be set.')

    @app.before_request
    def authenticate():
        if request.path == '/healthz':
            return None
        if username:
            auth = request.authorization
            valid = False
            if auth and auth.type == 'basic' and hmac.compare_digest((auth.username or '').encode(), username.encode()):
                try:
                    path = password_file()
                    if path.exists():
                        encoded = json.loads(path.read_text(encoding='utf-8'))['password_hash']
                        valid = verified_password(encoded, auth.password or '')
                    else:
                        valid = hmac.compare_digest((auth.password or '').encode(), password.encode())
                except (OSError, ValueError, KeyError, TypeError):
                    return Response('Login temporarily unavailable', 503)
            if not valid:
                return Response('Login required', 401,
                                {'WWW-Authenticate': 'Basic realm="Debatstof", charset="UTF-8"'})
        if request.method == 'POST' or request.path == '/open' or request.endpoint == 'rss.open_article':
            origin = request.headers.get('Origin')
            if request.headers.get('Sec-Fetch-Site') == 'cross-site':
                abort(403)
            if origin and urlsplit(origin).netloc != request.host:
                abort(403)

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        return response

    @app.get('/healthz')
    def health():
        return {'status': 'ok'}


    @app.route('/adgangskode', methods=['GET', 'POST'])
    def change_password():
        if not username:
            abort(403, 'Login skal være konfigureret først.')
        request.max_content_length = 16 * 1024
        error = None
        saved = False
        if request.method == 'POST':
            try:
                tokens.loads(request.form.get('token', ''), max_age=1800)
            except BadSignature:
                abort(400, 'Formularen er udløbet. Åbn siden igen.')
            value = request.form.get('new_password', '')
            if len(value) < 8 or len(value) > 256:
                error = 'Vælg en adgangskode på mellem 8 og 256 tegn.'
            elif value != request.form.get('confirm_password', ''):
                error = 'De to adgangskoder er ikke ens.'
            else:
                save_password(value)
                saved = True
        return render_template('password.html', nav_active='adgangskode', error=error, saved=saved,
                               token=tokens.dumps('change'), micro_options=[], alle_medier=[]), (400 if error else 200)
