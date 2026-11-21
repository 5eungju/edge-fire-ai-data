import sqlite3
import unittest
import numpy as np
from audit_full_shards import find_candidates,hash_bands


class CandidateLookupTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.db.executescript('''CREATE TABLE sketches(id TEXT PRIMARY KEY,split TEXT,r REAL,g REAL,b REAL,dhash TEXT,rgb BLOB);
          CREATE TABLE bands(band INTEGER,value INTEGER,id TEXT);
          CREATE INDEX band_lookup ON bands(band,value);
          CREATE INDEX sketch_filter_cover ON sketches(id,split,r,g,b,dhash);''')
        for i in range(800):
            split='train' if i<100 else 'test'
            color=.3 if 100<=i<200 else 0.
            identifier=f'image_{i:04d}'
            self.db.execute('INSERT INTO sketches VALUES(?,?,?,?,?,?,?)',(identifier,split,color,color,color,'0000000000000000',b'RGB must not be fetched during filtering'))
            self.db.executemany('INSERT INTO bands VALUES(?,?,?)',[(band,bucket,identifier) for band,bucket in hash_bands(0)])

    def tearDown(self): self.db.close()

    def test_split_color_filters_and_search_cap(self):
        found,capped=find_candidates(self.db,0,np.zeros(3),'train',256)
        self.assertTrue(capped)
        self.assertEqual(list(found),[f'image_{i:04d}' for i in range(200,456)])
        found,capped=find_candidates(self.db,0,np.zeros(3),'train',1000)
        self.assertFalse(capped)
        self.assertEqual(len(found),600)

    def test_scalar_filter_does_not_read_rgb_column(self):
        def authorize(action,table,column,*rest):
            return sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_READ and table=='sketches' and column=='rgb' else sqlite3.SQLITE_OK
        self.db.set_authorizer(authorize)
        found,capped=find_candidates(self.db,0,np.zeros(3),'train',256)
        self.assertEqual(len(found),256)
        self.assertTrue(capped)


if __name__=='__main__':unittest.main()
