import base64
import datetime as dt
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {
            'DATA_DIR': self.tmp.name, 'SQLITE_DB_PATH': str(self.folder / 'data.db'),
            'APP_USERNAME': 'reader', 'APP_PASSWORD': 'test-only-password', 'RENDER': 'true'})
        self.env.start()
        self.addCleanup(self.env.stop)
        from db.database import initialize_database
        initialize_database()
        initialize_database()
        import app.app as module
        self.web = importlib.reload(module)
        self.web.FEEDBACK_FILE = self.folder / 'feedback.json'
        self.web.app.config['TESTING'] = True
        self.client = self.web.app.test_client()
        self.auth = {'Authorization': 'Basic ' + base64.b64encode(b'reader:test-only-password').decode()}

    def test_login_and_health(self):
        self.assertEqual(self.client.get('/healthz').json, {'status': 'ok'})
        for route in ['/', '/statistik', '/topscorere', '/static/style.css']:
            self.assertEqual(self.client.get(route).status_code, 401)
        self.assertEqual(self.client.post('/interesting', data={'url': 'https://example.com'}).status_code, 401)
        wrong = {'Authorization': 'Basic ' + base64.b64encode(b'reader:wrong').decode()}
        self.assertEqual(self.client.get('/', headers=wrong).status_code, 401)
        for route in ['/', '/statistik', '/topscorere']:
            self.assertEqual(self.client.get(route, headers=self.auth).status_code, 200)
        self.assertEqual(self.client.post('/interesting', headers={**self.auth, 'Origin': 'https://other.example'}).status_code, 403)

    def test_article_feedback_persistence(self):
        from db.database import write_items_to_sqlite, get_stats, get_all_feedback_from_db
        from core.models import DebateItem
        from run_scraper import item_to_app_dict
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        item = DebateItem(now, now, 'Altinget', 'Nationalt', 'Danmark',
                          'Debat om sundhed og psykiatri', '', 'Test', 'Debat',
                          'https://example.com/debat/test', 'fixture', 'ny')
        write_items_to_sqlite([item_to_app_dict(item)])
        write_items_to_sqlite([item_to_app_dict(item)])
        self.assertEqual(get_stats()['total'], 1)
        self.assertIn(item.title, self.client.get('/', headers=self.auth).text)
        self.assertEqual(self.client.post('/interesting', data={'url': item.url}, headers=self.auth).status_code, 302)
        self.assertTrue(get_all_feedback_from_db()[item.url]['interesting'])
        self.assertIn(item.title, self.client.get('/?interesting=1', headers=self.auth).text)
        # Reload the application against the same disk, as after a deployment.
        self.web = importlib.reload(self.web)
        self.assertTrue(get_all_feedback_from_db()[item.url]['interesting'])
        self.assertIn(item.title, self.web.app.test_client().get('/', headers=self.auth).text)

    def test_hosted_start_requires_login(self):
        env = dict(os.environ)
        env.pop('APP_PASSWORD')
        result = subprocess.run([sys.executable, '-c', 'import wsgi'], env=env, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'APP_USERNAME and APP_PASSWORD', result.stderr)

    def test_scraper_without_env_file(self):
        import run_scraper as scraper
        from core.models import DebateItem
        from db.database import get_stats
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        item = DebateItem(now, now, 'Altinget', 'Nationalt', 'Danmark', 'Debat om sundhed', '', 'Test',
                          'Debat', 'https://example.com/debat/test', 'fixture', 'ny')
        with patch.object(scraper, 'get_external_scraper', return_value=lambda *args, **kwargs: [item]):
            scraper.run(False, 1, 'Altinget', 0, False, None,
                        str(self.folder / 'articles.json'), str(self.folder / 'new.json'))
        self.assertEqual(get_stats()['total'], 1)
        self.assertEqual(json.loads((self.folder / 'articles.json').read_text())['count'], 1)


if __name__ == '__main__':
    unittest.main()
