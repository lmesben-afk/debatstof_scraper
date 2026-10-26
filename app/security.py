"""Browser password prompt; hosting must terminate HTTPS."""
import hmac
import os
from urllib.parse import urlsplit

from flask import Response, abort, request


def protect_app(app):
    username = os.environ.get('APP_USERNAME', '')
    password = os.environ.get('APP_PASSWORD', '')
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
            if not (auth and auth.type == 'basic'
                    and hmac.compare_digest((auth.username or '').encode(), username.encode())
                    and hmac.compare_digest((auth.password or '').encode(), password.encode())):
                return Response('Login required', 401,
                                {'WWW-Authenticate': 'Basic realm="Debatstof", charset="UTF-8"'})
        if request.method == 'POST' or request.path == '/open':
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
