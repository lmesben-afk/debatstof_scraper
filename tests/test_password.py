import base64
import importlib
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch


class PasswordTests(unittest.TestCase):
    def test_change_persists_and_revokes_previous_password(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
                'APP_USERNAME':'reader', 'APP_PASSWORD':'previous-test-password',
                'APP_PASSWORD_FILE':str(Path(tmp)/'password.json'), 'RSS_DB_PATH':str(Path(tmp)/'rss.db')}):
            import app.app as module
            web=importlib.reload(module)
            client=web.app.test_client()
            def auth(value):
                return {'Authorization':'Basic '+base64.b64encode(('reader:'+value).encode()).decode()}
            old=auth('previous-test-password')
            new=auth('new-test-password')
            self.assertEqual(client.get('/adgangskode').status_code,401)
            self.assertEqual(client.post('/adgangskode',headers=old).status_code,400)
            page=client.get('/adgangskode',headers=old)
            token=re.search('name="token" value="([^"]+)"',page.text).group(1)
            response=client.post('/adgangskode',headers=old,data={
                'token':token,'new_password':'new-test-password','confirm_password':'different'})
            self.assertEqual(response.status_code,400)
            self.assertFalse(Path(tmp,'password.json').exists())
            response=client.post('/adgangskode',headers=old,data={
                'token':token,'new_password':'new-test-password','confirm_password':'new-test-password'})
            self.assertEqual(response.status_code,200)
            self.assertNotIn('new-test-password',Path(tmp,'password.json').read_text())
            for path in ['/adgangskode','/rss/tv2','/rss/international']:
                self.assertEqual(client.get(path,headers=old).status_code,401)
                self.assertEqual(client.get(path,headers=new).status_code,200)
            web=importlib.reload(module)
            self.assertEqual(web.app.test_client().get('/adgangskode',headers=new).status_code,200)
            self.assertEqual(web.app.test_client().get('/adgangskode',headers=old).status_code,401)
            Path(tmp,'password.json').write_text('broken')
            self.assertEqual(web.app.test_client().get('/adgangskode',headers=old).status_code,503)


if __name__=='__main__':
    unittest.main()
