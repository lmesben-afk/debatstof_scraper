import importlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch


class AnalysisExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        folder = Path(self.tmp.name)
        self.db = folder / 'archive.db'
        self.env = patch.dict(os.environ, {'SQLITE_DB_PATH': str(self.db), 'RSS_DB_PATH': str(folder/'rss.db'),
                                          'APP_USERNAME': 'reader', 'APP_PASSWORD': 'export-password'})
        self.env.start()
        self.addCleanup(self.env.stop)
        from db.database import initialize_database
        initialize_database()
        import app.app as module
        self.web = importlib.reload(module)
        self.web.app.config['TESTING'] = True
        self.client = self.web.app.test_client()
        import base64
        self.auth = {'Authorization': 'Basic ' + base64.b64encode(b'reader:export-password').decode()}
        from core.models import DebateItem
        from run_scraper import item_to_app_dict
        from db.database import write_items_to_sqlite, save_feedback_to_db
        for i, date in enumerate(['2020-01-01T12:00:00+00:00','2099-01-01T12:00:00+00:00']):
            article = DebateItem(date,date,'Testmedie','regional','Danmark','Kritik af skat og afgifter',
                                 'En debat om frit valg og virksomheder','Test','Debat',
                                 f'https://example.com/article/{i}','fixture','ny')
            write_items_to_sqlite([item_to_app_dict(article)])
        save_feedback_to_db('https://example.com/article/0',1,1,2,'interessant')
        # Confirm historic scores stay distinguishable from freshly recomputed rules.
        with sqlite3.connect(self.db) as conn:
            conn.execute('UPDATE artikler SET story_score=1')

    def test_auth_and_download_include_all_dates_and_actual_rules(self):
        self.assertEqual(self.client.get('/analyse').status_code,401)
        self.assertEqual(self.client.get('/analyse/download').status_code,401)
        page = self.client.get('/analyse',headers=self.auth)
        self.assertEqual(page.status_code,200)
        self.assertIn('Download analysefil',page.text)
        before = self.db.read_bytes()
        response = self.client.get('/analyse/download',headers=self.auth)
        self.assertEqual(response.status_code,200)
        self.assertIn('attachment;',response.headers['Content-Disposition'])
        self.assertIn('.json',response.headers['Content-Disposition'])
        data = response.json
        self.assertEqual(data['summary']['article_count'],2)
        self.assertEqual(data['summary']['starred_count'],1)
        self.assertEqual(data['summary']['feedback_count'],1)
        self.assertEqual(len(data['articles']),2)
        old = next(a for a in data['articles'] if a['url'].endswith('/0'))
        other = next(a for a in data['articles'] if a['url'].endswith('/1'))
        self.assertTrue(old['feedback']['interesting'])
        self.assertIsNone(other['feedback'])
        self.assertIsNone(old['display_recent'])
        self.assertIsNotNone(other['display_recent'])
        self.assertEqual(old['stored']['score'],1)
        self.assertGreater(old['current_rules']['score_without_learning'],1)
        self.assertEqual(data['rules']['keyword_constants']['CONFLICT_KEYWORDS'][0],'kritik')
        self.assertIn('score += 20',data['rules']['implementation']['run_scraper.py'])
        self.assertIn('max(min(total, 25), -10)',data['rules']['implementation']['app/app.py'])
        self.assertNotIn('export-password',response.text)
        self.assertNotIn('APP_PASSWORD',response.text)
        self.assertEqual(self.db.read_bytes(),before)
        self.assertEqual(set(data['summary']['review_groups']).difference({'kontrol','udvikling'}),set())
        repeated = self.client.get('/analyse/download',headers=self.auth).json
        self.assertEqual([a['review_group'] for a in data['articles']], [a['review_group'] for a in repeated['articles']])
        self.assertEqual(data['rules']['sha256'],repeated['rules']['sha256'])
        from db.database import get_feedback_bonus_by_topic
        self.assertEqual(data['learning_bonus_snapshot'],get_feedback_bonus_by_topic())

    def test_empty_archive_reports_error(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute('DELETE FROM artikler')
        response = self.client.get('/analyse/download',headers=self.auth)
        self.assertEqual(response.status_code,400)
        self.assertIn('Arkivet er tomt',response.text)

    def test_duplicate_urls_stay_in_same_review_group(self):
        with sqlite3.connect(self.db) as conn:
            row=conn.execute('SELECT * FROM artikler LIMIT 1').fetchone()
            columns=[r[1] for r in conn.execute('PRAGMA table_info(artikler)')]
            row=list(row)
            row[columns.index('artikel_id')]='duplicate-id'
            conn.execute('INSERT INTO artikler VALUES ('+','.join('?' for _ in row)+')',row)
        data=self.client.get('/analyse/download',headers=self.auth).json
        groups={}
        for article in data['articles']:
            groups.setdefault(article['url'],set()).add(article['review_group'])
        self.assertTrue(all(len(g)==1 for g in groups.values()))


if __name__ == '__main__':
    unittest.main()
