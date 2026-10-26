import importlib
import os
from pathlib import Path
import re
import tempfile
import time
import unittest
from unittest.mock import patch

from core import rss

RSS = b'''<rss><channel><item><guid>test-id</guid><title>Nyhed fra regionen</title>
<link>https://example.com/nyhed</link><description>&lt;p&gt;En manchet&lt;/p&gt;</description>
<pubDate>Mon, 26 Oct 2026 12:00:00 GMT</pubDate></item></channel></rss>'''


class RssTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        folder = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'RSS_DB_PATH': str(folder / 'rss.db'),
                    'SQLITE_DB_PATH': str(folder / 'debatstof.db'),
                    'APP_USERNAME': 'reader', 'APP_PASSWORD': 'password'})
        self.env.start()
        self.addCleanup(self.env.stop)
        from db.database import initialize_database
        initialize_database()
        import app.app as module
        self.web = importlib.reload(module)
        self.web.app.config['TESTING'] = True
        self.client = self.web.app.test_client()
        self.auth = {'Authorization': 'Basic cmVhZGVyOnBhc3N3b3Jk'}

    def collect(self, app='tv2'):
        self.assertTrue(rss.claim_refresh(app))
        with patch.object(rss, 'fetch', return_value=RSS):
            rss.refresh(app)

    def test_daily_merge_read_flags_and_restart(self):
        self.collect()
        source = next(iter(rss.SOURCES['tv2']))
        articles, counts, new_counts, job = rss.view('tv2', source)
        self.assertEqual(len(articles), 1)
        self.assertTrue(articles[0]['is_new'])
        self.assertEqual(job['created'], 8)
        rss.mark_viewed('tv2', source)
        self.assertNotIn(source, rss.view('tv2', source)[2])
        response = self.client.get('/rss/tv2/open', query_string={'guid':'test-id','source':source},headers=self.auth)
        self.assertEqual(response.headers['Location'], 'https://example.com/nyhed')
        self.collect()
        self.assertTrue(rss.view('tv2',source)[0][0]['read'])
        self.assertEqual(rss.view('tv2',source)[3]['created'], 0)
        # Feed item falls out of RSS, but remains in today's saved collection.
        self.assertTrue(rss.claim_refresh('tv2'))
        with patch.object(rss, 'fetch', return_value=b'<rss><channel/></rss>'):
            rss.refresh('tv2')
        rss.initialize(recover=True)
        self.assertEqual(len(rss.view('tv2',source)[0]),1)
        with patch.object(rss, 'today', return_value='2099-01-01'):
            self.assertEqual(rss.view('tv2',source)[0],[])

    def test_auth_and_csrf(self):
        for path in ['/rss/tv2','/rss/international','/rss/tv2/open']:
            self.assertEqual(self.client.get(path).status_code,401)
        self.assertEqual(self.client.post('/rss/tv2/refresh',headers=self.auth).status_code,400)
        self.assertEqual(self.client.post('/rss/tv2/refresh',headers={**self.auth,'Origin':'https://other.example'}).status_code,403)
        self.assertEqual(self.client.get('/rss/unknown',headers=self.auth).status_code,404)
        self.assertEqual(self.client.get('/rss/tv2?source=unknown',headers=self.auth).status_code,404)

    def test_real_background_refresh_and_both_pages(self):
        for app in rss.SOURCES:
            response=self.client.get('/rss/'+app,headers=self.auth)
            token=re.search(r'name="token" value="([^"]+)"',response.text).group(1)
            with patch.object(rss, 'fetch', return_value=RSS):
                result=self.client.post('/rss/'+app+'/refresh',data={'token':token},headers=self.auth)
                self.assertEqual(result.status_code,302)
                for attempt in range(200):
                    with rss.connect() as conn:
                        job=conn.execute('SELECT state FROM refresh WHERE app=?',(app,)).fetchone()
                    if job['state'] not in ('queued','running'):
                        break
                    time.sleep(.01)
                self.assertEqual(job['state'],'finished')
            response=self.client.get('/rss/'+app,headers=self.auth)
            self.assertEqual(response.status_code,200)
            self.assertIn('Nyhed fra regionen',response.text)
            self.assertIn('En manchet',response.text)
        # RSS collections are distinct and debatstof data is untouched.
        with rss.connect() as conn:
            self.assertEqual(conn.execute('SELECT count(DISTINCT app) FROM articles').fetchone()[0],2)
        from db.database import get_stats
        self.assertEqual(get_stats()['total'],0)

    def test_failed_feeds_preserve_data_and_recover_interrupted_job(self):
        self.collect()
        self.assertTrue(rss.claim_refresh('tv2'))
        self.assertFalse(rss.claim_refresh('tv2'))
        with patch.object(rss, 'collect_source',side_effect=OSError('test feed unavailable')), self.assertLogs(level='ERROR'):
            rss.refresh('tv2')
        source=next(iter(rss.SOURCES['tv2']))
        articles,_,_,job=rss.view('tv2',source)
        self.assertEqual(len(articles),1)
        self.assertEqual(job['state'],'error')
        self.assertTrue(rss.claim_refresh('tv2'))
        rss.initialize(recover=True)
        self.assertEqual(rss.view('tv2',source)[3]['state'],'interrupted')

    def test_missing_teaser_uses_article_metadata(self):
        feed = RSS.replace(b'&lt;p&gt;En manchet&lt;/p&gt;', b'')
        with patch.object(rss, 'fetch', side_effect=[feed, b'<html><meta name="description" content="Manchet fra artiklen"></html>']):
            self.assertEqual(rss.collect_source('https://example.com/rss')[0]['teaser'], 'Manchet fra artiklen')

    def test_atom_parser_and_invalid_feed(self):
        rows=rss.parse_feed(b'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
          <id>x</id><title>Atom article</title><link href="https://example.com/atom"/>
          <summary>Summary</summary><updated>2026-10-26T12:00:00Z</updated></entry></feed>''')
        self.assertEqual(rows[0]['url'],'https://example.com/atom')
        self.assertGreater(rows[0]['published_at'],0)
        with self.assertRaises(ValueError):
            rss.parse_feed(b'<html><body>Access denied</body></html>')
        self.assertEqual(rss.parse_feed(b'<rss><channel><item><guid>x</guid><link>javascript:alert(1)</link></item></channel></rss>'),[])


if __name__ == '__main__':
    unittest.main()
