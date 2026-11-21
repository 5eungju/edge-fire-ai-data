import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import numpy as np


class RecheckResumeTests(unittest.TestCase):
    def test_short_final_checkpoint_batch_and_fully_cached_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'quality';output=root/'recheck';source.mkdir()
            db=sqlite3.connect(source/'quality.sqlite');db.execute('PRAGMA journal_mode=WAL')
            db.executescript('CREATE TABLE sketches(id TEXT PRIMARY KEY,split TEXT,dhash TEXT,rgb BLOB,r REAL,g REAL,b REAL); CREATE TABLE capped(id TEXT PRIMARY KEY);')
            pixels=np.zeros((16,16,3),dtype=np.float32).tobytes()
            for i in range(123):
                identifier=f'image_{i:04d}';split='train' if i<53 else 'test'
                db.execute('INSERT INTO sketches VALUES(?,?,?,?,?,?,?)',(identifier,split,'0000000000000000',pixels,0.,0.,0.))
                if i<53:db.execute('INSERT INTO capped VALUES(?)',(identifier,))
            db.commit()
            (source/'status.json').write_text(json.dumps({'full_export_completed':True,'images_audited':123}),encoding='utf-8')
            script=Path(__file__).with_name('recheck_capped_similarity.py')
            for _ in range(2):
                subprocess.run([sys.executable,str(script),'--source',str(source),'--output',str(output)],check=True,capture_output=True,text=True)
                result=sqlite3.connect(output/'recheck.sqlite')
                self.assertEqual(result.execute('SELECT count(*) FROM progress WHERE through_rowid=123').fetchone()[0],53)
                self.assertEqual(result.execute('SELECT count(*) FROM candidates').fetchone()[0],53*70)
                result.close()
                status=json.loads((output/'status.json').read_text(encoding='utf-8'))
                self.assertTrue(status['full_source_audit_completed'])
                self.assertEqual(status['images_checked_through_snapshot'],53)
            db.close()


if __name__=='__main__':unittest.main()
