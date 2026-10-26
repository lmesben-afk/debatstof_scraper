import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from core.models import DebateItem
from run_scraper import calculate_story_potential


def article(title, deck='', media_type='national'):
    return DebateItem('','','Test',media_type,'',title,deck,'','Debat','https://example.com','','')


class EditorialTests(unittest.TestCase):
    def test_concrete_value_conflicts_beat_generic_topics(self):
        pairs = [
            ('Kommunen indfører kønsopdelt svømning: borgere kritiserer ulige adgang til svømmehallen', 'Debat om svømning'),
            ('Forældre vælger hjemmepasning: kommunens tilskud udfordrer arbejdsudbud og ligestilling', 'Forældre og børn'),
            ('Byrådet har vedtaget solcellepark ved landsbyen: naboer protesterer mod støj og tab af ejendomsret', 'Grøn omstilling er vigtig'),
            ('Virksomheder afviser nye afgiftskrav: investeringer forsinkes og arbejdspladser lukker', 'Virksomheder er vigtige for samfundet'),
        ]
        for strong, weak in pairs:
            with self.subTest(strong=strong):
                strong_score, reasons=calculate_story_potential(article(strong))
                self.assertGreater(strong_score,calculate_story_potential(article(weak))[0])
                self.assertTrue(any('sammenhæng' in reason for reason in reasons))

    def test_partial_evidence_has_intermediate_scores(self):
        weak = article('Virksomheder er vigtige')
        partial = article('Virksomheder advarer: investeringer og arbejdspladser er truet')
        strong = article('Byrådet indfører nye afgiftskrav: virksomheder afviser tab af investeringer og arbejdspladser i Esbjerg')
        scores = [calculate_story_potential(item)[0] for item in (weak, partial, strong)]
        self.assertLess(scores[0], scores[1])
        self.assertLess(scores[1], scores[2])
        self.assertGreaterEqual(scores[2], 60)
        self.assertLessEqual(scores[2],100)

    def test_source_type_alone_gives_no_bonus_and_no_substring_matches(self):
        title='En principiel diskussion om samfundet'
        self.assertEqual(calculate_story_potential(article(title)),calculate_story_potential(article(title,media_type='regional')))
        from core.editorial import keyword_hits
        self.assertEqual(keyword_hits('Et ansvarligt selskab i skattekammeret',['skat','ansvar']),[])
        self.assertEqual(keyword_hits('Virksomhederne protesterer',['virksomhed*']),['virksomhed*'])

    def test_no_negative_feedback_or_repeated_bonus(self):
        from app.app import build_feedback_signals, feedback_signal_for_article
        articles=[{'url':str(i),'mikroemner':['tema']} for i in range(4)]
        self.assertEqual(build_feedback_signals(articles,{})['tema']['score'],0)
        signals={'a':{'score':5,'reasons':['a']},'b':{'score':5,'reasons':['b']}}
        self.assertEqual(feedback_signal_for_article({'mikroemner':['a','b']},signals)[0],5)
        item=article('Hjemmepasning og arbejdsudbud')
        self.assertEqual(calculate_story_potential(item),calculate_story_potential(item,topic_bonus={'familieliv_og_arbejde':15}))

    def test_rescore_backup_preserves_feedback_and_is_idempotent(self):
        import os, sqlite3
        from db.database import initialize_database, write_items_to_sqlite, save_feedback_to_db
        from run_scraper import item_to_app_dict
        from rescore_db import ensure_current_scoring
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{'SQLITE_DB_PATH':str(Path(folder)/'data.db')}):
            initialize_database()
            item=article('Byrådet har vedtaget vindmøller: lokale naboer protesterer mod støj')
            write_items_to_sqlite([item_to_app_dict(item)])
            save_feedback_to_db(item.url,1,1,2,'interessant')
            ensure_current_scoring()
            ensure_current_scoring()
            self.assertEqual(len(list((Path(folder)/'backups').glob('*.db'))),1)
            with sqlite3.connect(Path(folder)/'data.db') as conn:
                self.assertEqual(conn.execute('SELECT interesting FROM feedback').fetchone()[0],1)
                self.assertEqual(conn.execute('SELECT story_score FROM artikler').fetchone()[0],calculate_story_potential(item)[0])
