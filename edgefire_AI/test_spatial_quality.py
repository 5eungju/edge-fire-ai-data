import unittest
from prepare_spatial_dataset import filename_resolution, validate_geometry
from plan_spatial_split import Components, conservative_place


class SpatialQualityTests(unittest.TestCase):
    def test_known_filename_typo_only(self):
        self.assertIsNone(filename_resolution('a.jpg', 'a.jpg'))
        self.assertEqual(filename_resolution('백색백색회색연기_001.jpg', '백색회색연기_001.jpg')['rule'], 'repeated_white_smoke_token')
        with self.assertRaises(ValueError):
            filename_resolution('백색백색회색연기_001.jpg', '백색회색연기_002.jpg')

    def test_self_intersection_is_rejected(self):
        validate_geometry([(0, [(0, 0), (1, 0), (1, 1), (0, 1)])])
        with self.assertRaisesRegex(ValueError, 'invalid_polygon_geometry'):
            validate_geometry([(0, [(0, 0), (1, 1), (1, 0), (0, 1)])])

    def test_component_transitivity(self):
        groups = Components()
        groups.union('camera:A', 'place:X')
        groups.union('camera:B', 'place:X')
        groups.union('camera:B', 'place:Y')
        self.assertEqual(groups.find('camera:A'), groups.find('place:Y'))

    def test_conservative_mountain_grouping(self):
        a = 'Real/강원도강릉시춘갑봉공터_RD001001/001/a.jpg'
        b = 'Synthetic/춘갑봉공터_BC001001/001/b.jpg'
        self.assertEqual(conservative_place(a), conservative_place(b))


if __name__ == '__main__':
    unittest.main()
