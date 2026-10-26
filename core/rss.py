"""RSS collection shared by the two Flask views; data is separate from debatstof.db."""
import concurrent.futures
from contextlib import contextmanager
import datetime as dt
import email.utils
import html
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import time
import urllib.request
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from core.settings import DATA_DIR

TIMEZONE = ZoneInfo('Europe/Copenhagen')
SOURCES = {
    'tv2': {
        'TV 2 ØST': 'https://www.tv2east.dk/rss',
        'TV MIDTVEST': 'https://www.tvmidtvest.dk/rss',
        'TV 2 ØSTJYLLAND': 'https://www.tv2ostjylland.dk/rss',
        'TV 2 Kosmopol': 'https://www.tv2kosmopol.dk/rss',
        'TV SYD': 'https://www.tvsyd.dk/rss',
        'TV 2 Fyn': 'https://www.tv2fyn.dk/rss',
        'TV 2 Nord': 'https://www.tv2nord.dk/rss',
        'TV 2/Bornholm': 'https://www.tv2bornholm.dk/rss',
    },
    'international': {
        'BBC World': 'https://feeds.bbci.co.uk/news/world/rss.xml',
        'POLITICO Europe': 'https://www.politico.eu/feed/',
        'The Guardian World': 'https://www.theguardian.com/world/rss',
        'NYTimes World': 'https://rss.nytimes.com/services/xml/rss/nyt/World.xml',
        'Sky News World': 'https://feeds.skynews.com/feeds/rss/world.xml',
        'NRK Toppsaker': 'https://www.nrk.no/toppsaker.rss',
        'SVT Nyheter Väst': 'https://www.svt.se/nyheter/lokalt/vast/rss.xml',
        'VG Nyheter': 'https://www.vg.no/rss/feed/?limit=50',
        'Aftenposten': 'https://www.aftenposten.no/rss',
    },
}
TITLES = {'tv2': 'TV 2-regionerne', 'international': 'Internationale medier'}


def db_path():
    return Path(os.environ.get('RSS_DB_PATH', DATA_DIR / 'rss.db'))


def today():
    return dt.datetime.now(TIMEZONE).date().isoformat()


@contextmanager
def connect(path=None):
    conn = sqlite3.connect(path or db_path(), timeout=20)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def initialize(recover=False):
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS articles (
              app TEXT, source TEXT, guid TEXT, day TEXT, title TEXT, url TEXT,
              teaser TEXT, fetched_at INTEGER, published_at INTEGER, read INTEGER DEFAULT 0,
              PRIMARY KEY(app, source, guid, day));
            CREATE TABLE IF NOT EXISTS views (
              app TEXT, source TEXT, day TEXT, viewed_at INTEGER,
              PRIMARY KEY(app, source, day));
            CREATE TABLE IF NOT EXISTS refresh (
              app TEXT PRIMARY KEY, state TEXT, created INTEGER DEFAULT 0,
              started_at INTEGER, finished_at INTEGER, failed_sources TEXT DEFAULT '[]');
        ''')
        if recover:
            conn.execute("UPDATE refresh SET state='interrupted', finished_at=? WHERE state IN ('queued','running')", (int(time.time()),))


def text(value):
    return ' '.join(re.sub(r'<[^>]*>', ' ', html.unescape(value or '')).split())


def timestamp(value):
    if not value:
        return 0
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (ValueError, TypeError):
        try:
            parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return 0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return int(parsed.timestamp())


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (compatible; RSS-overblik/1.0)'})
    with urllib.request.urlopen(request, timeout=20) as response:
        data = response.read(5 * 1024 * 1024 + 1)
        if len(data) > 5 * 1024 * 1024:
            raise ValueError('Feedet er for stort')
        return data


def parse_feed(content):
    root = ET.fromstring(content)
    atom = '{http://www.w3.org/2005/Atom}'
    items = root.findall('.//item')
    if root.tag == atom + 'feed':
        items = root.findall(atom + 'entry')
    elif root.tag not in ('rss', '{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF'):
        raise ValueError('Svaret er ikke et RSS- eller Atom-feed')
    output = []
    for item in items[:500]:
        if item.tag == atom + 'entry':
            links = item.findall(atom + 'link')
            url = next((link.get('href', '') for link in links if link.get('rel', 'alternate') == 'alternate'), '')
            guid = item.findtext(atom + 'id') or url
            title = item.findtext(atom + 'title')
            description = item.findtext(atom + 'summary') or item.findtext(atom + 'content')
            date = item.findtext(atom + 'published') or item.findtext(atom + 'updated')
        else:
            url = item.findtext('link') or ''
            guid = item.findtext('guid') or url
            title = item.findtext('title')
            description = item.findtext('description')
            date = item.findtext('pubDate')
        if guid and url.startswith(('https://', 'http://')):
            output.append({'guid': guid, 'title': text(title) or '(uden titel)',
                           'url': url, 'teaser': text(description)[:1000], 'published_at': timestamp(date)})
    return output


def collect_source(source_url):
    articles = parse_feed(fetch(source_url))
    for article in articles:
        if article['teaser']:
            continue
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(fetch(article['url']), 'lxml')
            meta = soup.select_one('meta[property="og:description"], meta[name="description"]')
            if meta:
                article['teaser'] = text(meta.get('content', ''))[:1000]
        except Exception:
            logging.warning('Kunne ikke hente manchet: %s', article['url'])
    return articles


def refresh(app, path=None):
    """Run once, merge results transactionally, preserving read flags and old feed items."""
    started = time.time()
    day = today()
    failed = []
    created = 0
    try:
        with connect(path) as conn:
            conn.execute("UPDATE refresh SET state='running', started_at=? WHERE app=?", (started, app))
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(collect_source, url): source for source, url in SOURCES[app].items()}
            for future in concurrent.futures.as_completed(futures):
                source = futures[future]
                try:
                    articles = future.result()
                except Exception:
                    logging.exception('RSS-feed fejlede: %s / %s', app, source)
                    failed.append(source)
                    continue
                with connect(path) as conn:
                    for article in articles:
                        if app == 'tv2':
                            start, end = day_bounds(day)
                            if not start <= article['published_at'] < end:
                                continue
                        inserted = conn.execute('''INSERT OR IGNORE INTO articles
                            (app,source,guid,day,title,url,teaser,fetched_at,published_at)
                            VALUES (?,?,?,?,?,?,?,?,?)''', (app, source, article['guid'], day,
                            article['title'], article['url'], article['teaser'], time.time(),
                            article['published_at'] or started)).rowcount
                        created += inserted
                        if not inserted:
                            conn.execute('''UPDATE articles SET title=?,url=?,
                                teaser=CASE WHEN ? != '' THEN ? ELSE teaser END,
                                published_at=CASE WHEN ? > 0 THEN ? ELSE published_at END
                                WHERE app=? AND source=? AND guid=? AND day=?''',
                                (article['title'], article['url'], article['teaser'], article['teaser'],
                                 article['published_at'], article['published_at'],app,source,article['guid'],day))
        state = 'error' if len(failed) == len(SOURCES[app]) else 'finished'
        with connect(path) as conn:
            conn.execute('''UPDATE refresh SET state=?,created=?,finished_at=?,failed_sources=? WHERE app=?''',
                         (state, created, int(time.time()), json.dumps(failed), app))
    except Exception:
        logging.exception('RSS-opdatering afbrudt: %s', app)
        with connect(path) as conn:
            conn.execute("UPDATE refresh SET state='error', finished_at=? WHERE app=?", (int(time.time()),app))
        raise


def claim_refresh(app):
    with connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        job = conn.execute('SELECT state FROM refresh WHERE app=?', (app,)).fetchone()
        if job and job['state'] in ('queued', 'running'):
            return False
        conn.execute('''INSERT INTO refresh (app,state,created,started_at,finished_at,failed_sources)
            VALUES (?,'queued',0,?,NULL,'[]') ON CONFLICT(app) DO UPDATE SET
            state='queued',created=0,started_at=excluded.started_at,finished_at=NULL,failed_sources='[]' ''', (app,int(time.time())))
    return True


def day_bounds(day):
    date = dt.date.fromisoformat(day)
    start = dt.datetime.combine(date, dt.time.min, tzinfo=TIMEZONE)
    end = dt.datetime.combine(date + dt.timedelta(days=1), dt.time.min, tzinfo=TIMEZONE)
    return start.timestamp(), end.timestamp()


def view(app, source):
    day = today()
    where = 'a.app=? AND a.day=?'
    params = [app, day]
    order = 'a.fetched_at DESC,a.published_at DESC'
    if app == 'tv2':
        start, end = day_bounds(day)
        where += ' AND a.published_at>=? AND a.published_at<?'
        params += [start, end]
        order = 'a.published_at DESC,a.fetched_at DESC'
    with connect() as conn:
        rows = conn.execute(f'SELECT a.* FROM articles a WHERE {where} AND a.source=? ORDER BY {order}',
                            [*params, source]).fetchall()
        counts = {r['source']: r['n'] for r in conn.execute(
            f'SELECT a.source,count(*) n FROM articles a WHERE {where} GROUP BY a.source', params)}
        seen = conn.execute('SELECT viewed_at FROM views WHERE app=? AND source=? AND day=?',(app,source,day)).fetchone()
        new_counts = {r['source']: r['n'] for r in conn.execute(f'''SELECT a.source,count(*) n FROM articles a
            LEFT JOIN views v ON v.app=a.app AND v.source=a.source AND v.day=a.day
            WHERE {where} AND a.fetched_at>COALESCE(v.viewed_at,0) GROUP BY a.source''',params)}
        job = conn.execute('SELECT * FROM refresh WHERE app=?',(app,)).fetchone()
    articles = [dict(r, is_new=r['fetched_at'] > (seen['viewed_at'] if seen else 0)) for r in rows]
    return articles, counts, new_counts, dict(job) if job else None


def mark_viewed(app, source):
    with connect() as conn:
        conn.execute('INSERT INTO views VALUES (?,?,?,?) ON CONFLICT(app,source,day) DO UPDATE SET viewed_at=excluded.viewed_at',
                     (app,source,today(),time.time()))
