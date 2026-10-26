import importlib
import io
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from db.import_database import ARTICLE_COLUMNS, import_database
from db.database import initialize_database


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.target = self.folder / 'active.db'
        self.env = patch.dict(os.environ, {'SQLITE_DB_PATH': str(self.target),
                                          'APP_USERNAME': 'reader', 'APP_PASSWORD': 'password'})
        self.env.start()
        self.addCleanup(self.env.stop)
        initialize_database()
        self.source = self.folder / 'old.db'
        with patch.dict(os.environ, {'SQLITE_DB_PATH': str(self.source)}):
            initialize_database()
        with sqlite3.connect(self.source) as conn:
            self.add_article(conn, 'old', 'https://example.com/old', 'Gammel debatartikel')
            self.add_article(conn, 'same-url', 'https://example.com/new', 'Gammel version')
            conn.execute("INSERT INTO feedback VALUES ('https://example.com/new',1,1,2,'gammel','2026-01-01')")
            conn.execute("INSERT INTO feedback VALUES ('https://example.com/old',1,1,2,'interessant','2026-01-01')")
        with sqlite3.connect(self.target) as conn:
            self.add_article(conn, 'new', 'https://example.com/new', 'Nuværende version')
            conn.execute("INSERT INTO feedback VALUES ('https://example.com/new',0,1,1,'åbnet','2026-10-26')")

    def add_article(self, conn, key, url, title):
        values = dict.fromkeys(ARTICLE_COLUMNS, '')
        values.update(artikel_id=key, url=url, rubrik=title, fundet_kl='2026-06-10',
                      mikroemner='[]', entiteter='{}', temaer='[]', jp_signaler='[]', story_score=50)
        columns = ','.join(f'"{c}"' for c in ARTICLE_COLUMNS)
        conn.execute(f'INSERT INTO artikler ({columns}) VALUES ({",".join("?" for _ in ARTICLE_COLUMNS)})',
                     [values[c] for c in ARTICLE_COLUMNS])

    def test_merge_idempotent_and_backup(self):
        result = import_database(self.source)
        self.assertEqual((result['articles'], result['skipped'], result['feedback']), (1, 1, 1))
        with sqlite3.connect(self.target) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM artikler').fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT rubrik FROM artikler WHERE artikel_id='new'").fetchone()[0], 'Nuværende version')
            self.assertEqual(conn.execute("SELECT interesting FROM feedback WHERE url='https://example.com/new'").fetchone()[0], 0)
        with sqlite3.connect(self.folder / 'backups' / result['backup']) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM artikler').fetchone()[0], 1)
        self.assertEqual(import_database(self.source)['articles'], 0)

    def test_invalid_file_leaves_target_unchanged(self):
        self.source.write_bytes(b'not a database')
        with self.assertRaises(ValueError):
            import_database(self.source)
        with sqlite3.connect(self.target) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM artikler').fetchone()[0], 1)

    def test_upload_auth_token_and_archive(self):
        import app.app as module
        web = importlib.reload(module)
        web.FEEDBACK_FILE = self.folder / 'feedback.json'
        web.app.config['TESTING'] = True
        client = web.app.test_client()
        auth = {'Authorization': 'Basic cmVhZGVyOnBhc3N3b3Jk'}
        self.assertEqual(client.get('/import').status_code, 401)
        self.assertEqual(client.post('/import', headers=auth).status_code, 400)
        token = re.search(r'name="token" value="([^"]+)"', client.get('/import', headers=auth).text).group(1)
        response = client.post('/import', headers=auth, data={
            'token': token, 'database': (io.BytesIO(self.source.read_bytes()), 'old.db')})
        self.assertEqual(response.status_code, 200)
        self.assertIn('1 artikler tilføjet', response.text)
        self.assertNotIn('Gammel debatartikel', client.get('/', headers=auth).text)
        archive = client.get('/arkiv', headers=auth)
        self.assertEqual(archive.status_code, 200)
        self.assertIn('Gammel debatartikel', archive.text)
        self.assertIn('Arkiv – alle artikler', archive.text)
        starred = client.get('/arkiv?interesting=1', headers=auth).text
        self.assertIn('Gammel debatartikel', starred)
        self.assertNotIn('Nuværende version', starred)
        response = client.post('/interesting', headers=auth, data={'url': 'https://example.com/old', 'return_to': '/arkiv?page=1'})
        self.assertEqual(response.headers['Location'], '/arkiv?page=1')
        with sqlite3.connect(self.target) as conn:
            self.assertEqual(conn.execute("SELECT interesting FROM feedback WHERE url='https://example.com/old'").fetchone()[0], 0)

    def test_archive_pagination(self):
        with sqlite3.connect(self.target) as conn:
            for i in range(101):
                self.add_article(conn, f'id-{i}', f'https://example.com/{i}', f'Artikel {i:03}')
        import app.app as module
        web = importlib.reload(module)
        response = web.app.test_client().get('/arkiv', headers={'Authorization': 'Basic cmVhZGVyOnBhc3N3b3Jk'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('Side 1 af 2', response.text)
        self.assertIn('/arkiv?page=2', response.text)


if __name__ == '__main__':
    unittest.main()
