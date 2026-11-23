import sqlite3
import unittest
from collections import Counter
from datetime import datetime,timedelta
from train_air_quality import timestamp,value,input_features,features,insert_batch


class AirQualityTests(unittest.TestCase):
    def test_midnight_and_missing_sentinel(self):
        self.assertEqual(timestamp('2026013124'),'2026-02-01T00:00')
        self.assertIsNone(value('-999'));self.assertIsNone(value('nan'));self.assertEqual(value('0'),0)
        with self.assertRaises(ValueError):timestamp('2026010125')

    def test_inference_needs_only_past_and_training_needs_future(self):
        start=datetime(2026,1,1)
        series=[((start+timedelta(hours=i)).strftime('%Y-%m-%dT%H:%M'),.003,.3,.02,.01,20,10) for i in range(26)]
        self.assertEqual(input_features(series[:25],24),features(series,24))
        self.assertIsNone(features(series[:25],24))
        missing=series.copy();missing[0]=(series[0][0],.003,None,.02,.01,20,10)
        self.assertIsNone(input_features(missing,24))
        gap=series[:23]+series[24:];self.assertIsNone(input_features(gap,24))

    def test_identical_duplicates_once_and_conflicts_all_quarantined(self):
        db=sqlite3.connect(':memory:')
        db.execute('CREATE TABLE measurements(station TEXT,time TEXT,SO2 REAL,CO REAL,O3 REAL,NO2 REAL,PM10 REAL,PM25 REAL,source TEXT,PRIMARY KEY(station,time))')
        db.execute('CREATE TEMP TABLE incoming AS SELECT * FROM measurements WHERE 0')
        db.execute('CREATE INDEX incoming_key ON incoming(station,time)')
        db.execute('CREATE TABLE excluded_keys(station TEXT,time TEXT,PRIMARY KEY(station,time))')
        db.execute('CREATE TABLE conflicts(station TEXT,time TEXT,first_values TEXT,second_values TEXT)')
        counts=Counter();row=('111121','2026-01-01T01:00',.003,.3,.02,.01,20,10,'source')
        insert_batch(db,[row,row],counts);self.assertEqual(db.execute('SELECT COUNT(*) FROM measurements').fetchone()[0],1)
        conflict=tuple(.9 if i==3 else v for i,v in enumerate(row))
        insert_batch(db,[conflict],counts);self.assertEqual(db.execute('SELECT COUNT(*) FROM measurements').fetchone()[0],0)
        insert_batch(db,[row],counts);self.assertEqual(db.execute('SELECT COUNT(*) FROM measurements').fetchone()[0],0)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM excluded_keys').fetchone()[0],1)
        second=('222222',*row[1:]);conflicting_second=('222222',*conflict[1:])
        insert_batch(db,[second,conflicting_second],counts)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM measurements').fetchone()[0],0)


if __name__=='__main__':unittest.main()
