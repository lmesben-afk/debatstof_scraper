"""Merge an old database as data only; never replace the active database."""
import datetime as dt
import json
from pathlib import Path
import sqlite3
import uuid

from core.utils import canonicalize_url_for_dedupe
from db.database import get_db_path, initialize_database

ARTICLE_COLUMNS = ('artikel_id', 'fundet_kl', 'udgivet_kl', 'medie', 'medietype',
                   'region', 'rubrik', 'manchet', 'forfatter', 'debat_type', 'url',
                   'fundet_via', 'temaer', 'entiteter', 'jp_signaler', 'story_score',
                   'status', 'kørsel_id', 'mikroemner')
FEEDBACK_COLUMNS = ('url', 'interesting', 'opened', 'feedback_score', 'feedback_label', 'opdateret_kl')


def read_rows(conn, table, columns):
    definition = conn.execute('SELECT type, sql FROM sqlite_master WHERE name=?', (table,)).fetchone()
    if not definition or definition[0] != 'table' or 'VIRTUAL TABLE' in (definition[1] or '').upper():
        raise ValueError(f'Filen mangler en almindelig {table}-tabel.')
    available = {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}
    required = set(columns) - {'mikroemner'}
    if not required.issubset(available):
        raise ValueError(f'Tabellen {table} har et ukendt format.')
    names = ', '.join(f'"{c}"' if c in available else 'NULL' for c in columns)
    rows = conn.execute(f'SELECT {names} FROM {table} LIMIT 100001').fetchall()
    if len(rows) > 100000:
        raise ValueError('Databasen indeholder for mange poster til denne import.')
    return rows


def import_database(source_path):
    source_path = Path(source_path).resolve()
    try:
        with sqlite3.connect(source_path.as_uri() + '?mode=ro', uri=True) as source:
            source.execute('PRAGMA trusted_schema=OFF')
            articles = read_rows(source, 'artikler', ARTICLE_COLUMNS)
            feedback = read_rows(source, 'feedback', FEEDBACK_COLUMNS) if source.execute(
                "SELECT 1 FROM sqlite_master WHERE name='feedback'").fetchone() else []
            for row in articles:
                if not row[0] or not row[10] or not row[ARTICLE_COLUMNS.index("rubrik")]:
                    raise ValueError('En artikel mangler id, URL eller rubrik.')
                for column, expected in [('temaer', list), ('entiteter', dict),
                                         ('jp_signaler', list), ('mikroemner', list)]:
                    raw = row[ARTICLE_COLUMNS.index(column)]
                    if raw and not isinstance(json.loads(raw), expected):
                        raise ValueError('En artikel har et ugyldigt dataformat.')
    except (sqlite3.DatabaseError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError('Filen kunne ikke læses som en gyldig debatstof-database.') from exc

    initialize_database()
    target_path = get_db_path()
    backup_dir = target_path.parent / 'backups'
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f'before-import-{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}.db'
    with sqlite3.connect(target_path) as target, sqlite3.connect(backup_path) as backup:
        target.backup(backup)
    added = 0
    feedback_added = 0
    with sqlite3.connect(target_path, timeout=20) as target:
        target.execute('BEGIN IMMEDIATE')
        existing = target.execute('SELECT artikel_id, url FROM artikler').fetchall()
        ids = {r[0] for r in existing}
        urls = {canonicalize_url_for_dedupe(r[1]) for r in existing if r[1]}
        names = ', '.join(f'"{c}"' for c in ARTICLE_COLUMNS)
        placeholders = ', '.join('?' for _ in ARTICLE_COLUMNS)
        for row in articles:
            url = canonicalize_url_for_dedupe(row[10])
            if row[0] in ids or url in urls:
                continue
            target.execute(f'INSERT INTO artikler ({names}) VALUES ({placeholders})', row)
            ids.add(row[0])
            urls.add(url)
            added += 1
        for row in feedback:
            feedback_added += target.execute(
                'INSERT OR IGNORE INTO feedback (url, interesting, opened, feedback_score, feedback_label, opdateret_kl) '
                'VALUES (?, ?, ?, ?, ?, ?)', row).rowcount
    return {'articles': added, 'skipped': len(articles) - added, 'feedback': feedback_added,
            'backup': backup_path.name}
