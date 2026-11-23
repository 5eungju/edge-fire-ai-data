import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from fire_forecast.run import arrival, feature_collection, audit, train_occurrence
from fire_forecast.service import validate, calculate, regions
from fire_forecast.catalog import POINTS, REGIONS, NAMES


class GridTests(unittest.TestCase):
    def test_expanded_regions_share_names_and_valid_coordinates(self):
        self.assertEqual(len(POINTS),18)
        self.assertEqual(len(REGIONS),len(POINTS))
        self.assertEqual(set(REGIONS),set(NAMES))
        for key,coordinates in REGIONS.items():
            self.assertEqual(validate({'region':key})[1:3],coordinates)

    def test_region_input_and_coordinates(self):
        self.assertEqual(validate({'region':'seoul'})[1:3],(37.5665,126.978))
        self.assertEqual(validate({'region':'map','latitude':37.7,'longitude':128.1})[1:3],(37.7,128.1))
        for payload in [{'region':'unknown'},{'region':'map'},{'latitude':True,'longitude':127},
                        {'latitude':0,'longitude':127},{'region':'seoul','path':'../secret'}]:
            with self.assertRaises(ValueError):validate(payload)

    def test_selected_region_time_and_geojson_center(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for name,lat,lon in [('seoul',37.5665,126.978),('gangneung',37.7519,128.8761)]:
                data=dict(latitude=lat,longitude=lon,hourly_units={'wind_speed_10m':'m/s'},hourly={
                    'time':['2025-12-01T12:00','2025-12-01T13:00'],
                    'wind_speed_10m':[1,8],'wind_direction_10m':[0,270],'relative_humidity_2m':[40,20]})
                (root/f'weather_{name}_20251201_10.json').write_text(json.dumps(data),encoding='utf-8')
            first=calculate(root,{'region':'seoul'})
            second=calculate(root,{'region':'gangneung','input_time':'2025-12-01T13:00'})
            self.assertEqual(first['metadata']['longitude'],126.978)
            self.assertEqual(second['metadata']['weather_region'],'gangneung')
            self.assertEqual(second['metadata']['wind_ms'],8)
            self.assertNotEqual(first['metadata']['request_id'],second['metadata']['request_id'])
            self.assertEqual(second,calculate(root,{'region':'gangneung','input_time':'2025-12-01T13:00'}))
            self.assertEqual(len(regions(root)['regions']),2)
            with self.assertRaises(ValueError):calculate(root,{'input_time':'2026-01-01T00:00'})
    def test_wind_from_north_spreads_south_faster(self):
        t=arrival(8,0,30,n=11)
        self.assertLess(t[7,5],t[3,5])

    def test_no_wind_symmetry(self):
        t=arrival(0,90,30,n=11)
        self.assertAlmostEqual(t[5,7],t[5,3])
        self.assertAlmostEqual(t[5,7],t[7,5])

    def test_nonburnable_wall_blocks_spread(self):
        fuel=np.ones((11,11));fuel[:,6]=0
        t=arrival(5,270,30,n=11,fuel=fuel)
        self.assertTrue(np.isinf(t[:,7:]).all())

    def test_horizon_is_monotone_and_coordinates_closed(self):
        t=arrival(4,90,40,base_m_min=3,n=11)
        features=feature_collection(t,37.88,127.76,20)['features']
        counts=[f['properties']['area_m2'] for f in features]
        self.assertEqual(counts,sorted(counts))
        for f in features:
            for polygon in f['geometry']['coordinates']:
                self.assertEqual(polygon[0][0],polygon[0][-1])

    def test_missing_labels_do_not_train(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);train_occurrence(root)
            self.assertFalse(json.loads((root/'occurrence_training_status.json').read_text())['trained'])
            self.assertEqual(audit(root)['observed_events'],0)

    def test_invalid_weather_rejected(self):
        for args in [(float('nan'),0,30),(-1,0,30),(1,0,101)]:
            with self.assertRaises(ValueError):arrival(*args,n=11)


if __name__=='__main__':unittest.main()
