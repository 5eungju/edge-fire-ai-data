import json
import unittest
import numpy as np
from json_numbers import dumps


class JsonNumbersTests(unittest.TestCase):
    def test_nested_evaluation_numbers_roundtrip(self):
        result = json.loads(dumps({'per_class': [{'instances': np.int64(7),
            'score': np.float32(.5), 'valid': np.bool_(True)}],
            'curve': np.array([1, 2], dtype=np.int64)}))
        self.assertEqual(result['per_class'][0], {'instances': 7, 'score': .5, 'valid': True})
        self.assertIs(type(result['per_class'][0]['instances']), int)
        self.assertEqual(result['curve'], [1, 2])

    def test_unknown_and_nonfinite_fail_explicitly(self):
        with self.assertRaises(TypeError):
            dumps({'value': object()})
        with self.assertRaises(ValueError):
            dumps({'value': np.float64('nan')})
