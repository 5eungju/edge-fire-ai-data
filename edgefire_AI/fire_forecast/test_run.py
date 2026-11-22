import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from fire_forecast.run import arrival, feature_collection, audit, train_occurrence


class GridTests(unittest.TestCase):
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
