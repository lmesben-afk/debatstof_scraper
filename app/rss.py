"""Authenticated RSS pages using the existing Flask server and persistent disk."""
import concurrent.futures
import datetime as dt
import json
import secrets
from urllib.parse import urlsplit

from flask import Blueprint, abort, redirect, render_template, request, url_for
from itsdangerous import BadSignature, URLSafeTimedSerializer

from core import rss

bp = Blueprint('rss', __name__, url_prefix='/rss')
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix='rss-refresh')
_tokens = URLSafeTimedSerializer(secrets.token_hex(32), salt='rss-refresh')


def validate_app(app):
    if app not in rss.SOURCES:
        abort(404)


def display_time(value):
    return dt.datetime.fromtimestamp(value, rss.TIMEZONE).strftime('%d/%m %H:%M') if value else ''


@bp.get('/<app>')
def index(app):
    validate_app(app)
    source = request.args.get('source', next(iter(rss.SOURCES[app])))
    if source not in rss.SOURCES[app]:
        abort(404)
    articles, counts, new_counts, job = rss.view(app, source)
    active = job and job['state'] in ('queued', 'running')
    if not active:
        rss.mark_viewed(app, source)
    for article in articles:
        article['time'] = display_time(article['published_at'] or article['fetched_at'])
    return render_template('rss.html', nav_active='rss-' + app, micro_options=[], alle_medier=[],
                           app_id=app,title=rss.TITLES[app],sources=rss.SOURCES[app],source=source,
                           articles=articles,counts=counts,new_counts=new_counts,total=sum(counts.values()),
                           job=job,active=active,last_updated=display_time(job['finished_at']) if job else '',
                           failed_sources=json.loads(job['failed_sources']) if job else [],
                           token=_tokens.dumps(app))


@bp.post('/<app>/refresh')
def refresh(app):
    validate_app(app)
    try:
        if _tokens.loads(request.form.get('token', ''), max_age=3600) != app:
            abort(400)
    except BadSignature:
        abort(400, 'Siden er udløbet. Åbn RSS-siden igen.')
    if rss.claim_refresh(app):
        try:
            _executor.submit(rss.refresh, app, rss.db_path())
        except Exception:
            with rss.connect() as conn:
                conn.execute("UPDATE refresh SET state='error' WHERE app=?", (app,))
            raise
    source = request.form.get('source')
    return redirect(url_for('rss.index', app=app, source=source) if source in rss.SOURCES[app]
                    else url_for('rss.index', app=app))


@bp.get('/<app>/open')
def open_article(app):
    validate_app(app)
    guid = request.args.get('guid')
    source = request.args.get('source')
    with rss.connect() as conn:
        article = conn.execute('SELECT url FROM articles WHERE app=? AND source=? AND guid=? AND day=?',
                               (app,source,guid,rss.today())).fetchone()
        if not article or urlsplit(article['url']).scheme not in ('https','http'):
            abort(404)
        conn.execute('UPDATE articles SET read=1 WHERE app=? AND source=? AND guid=? AND day=?',
                     (app,source,guid,rss.today()))
    return redirect(article['url'])


def register(app):
    rss.initialize(recover=True)
    app.register_blueprint(bp)
