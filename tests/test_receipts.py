import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import email_alerts
from scout import Ledger, API, AccessStop
ROOT=Path(__file__).resolve().parents[1]
class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.c=json.loads((ROOT/'config.json').read_text())
        self.c['email_enabled']=True
        self.c['email_recipients']=['user4@example.com','user2@example.com']
        self.r=dict(id='receipt',name='Example gloves',price_cents=24000,url='https://csfloat.com/item/receipt',time='now')
    def test_two_recipients_persisted_and_sent_once(self):
        with tempfile.TemporaryDirectory() as d,patch('email_alerts.send') as send:
            path=str(Path(d)/'db');l=Ledger(path)
            l.record_manual('receipt',24000)
            l.confirm('receipt',self.r,self.c)
            l.db.close();l=Ledger(path)
            email_alerts.flush_purchases(l.db,self.c)
            email_alerts.flush_purchases(l.db,self.c)
            self.assertEqual(send.call_count,2)
            self.assertEqual({call.args[2] for call in send.call_args_list},set(self.c['email_recipients']))
    def test_first_failure_does_not_block_backup(self):
        with tempfile.TemporaryDirectory() as d,patch('email_alerts.send',side_effect=[OSError(),None,None]) as send:
            l=Ledger(str(Path(d)/'db'));l.record_manual('receipt',24000);l.confirm('receipt',self.r,self.c)
            email_alerts.flush_purchases(l.db,self.c)
            self.assertEqual(send.call_count,2)
            self.assertEqual(l.db.execute("SELECT COUNT(*) FROM purchase_emails WHERE status='sent'").fetchone()[0],1)
            l.db.execute("UPDATE purchase_emails SET last_attempt=0 WHERE status='failed'")
            email_alerts.flush_purchases(l.db,self.c)
            self.assertEqual(send.call_count,3)
            self.assertEqual(l.db.execute("SELECT COUNT(*) FROM purchase_emails WHERE status='sent'").fetchone()[0],2)
    def test_receipt_does_not_claim_delivery(self):
        with tempfile.TemporaryDirectory() as d,patch('email_alerts.send') as send:
            l=Ledger(str(Path(d)/'db'));l.record_manual('receipt',24000);l.confirm('receipt',self.r,self.c)
            email_alerts.flush_purchases(l.db,self.c)
            body=send.call_args.args[1]
            self.assertIn('do not buy this listing again',body)
            self.assertIn('does not mean a trade offer has arrived',body)
    def test_access_errors_stop_without_retry(self):
        for status in (401,403,429):
            api=API('fake',15)
            with patch.object(api.opener,'open',side_effect=urllib.error.HTTPError('https://csfloat.com',status,'error',{},None)) as request:
                with self.assertRaises(AccessStop):api.call('/me')
                self.assertEqual(request.call_count,1)

if __name__=='__main__':unittest.main()
