import copy
import unittest
from model_selection import select_candidate, score_candidate


def candidate(name, f1, latency):
    return {'name': name, 'result': {'split': 'val', 'evaluation_ids_sha256': 'same-validation-set',
      'operating_point': {'confidence': .25, 'per_class': [
        {'class_name': c, 'precision': f1, 'recall': f1, 'f1': f1}
        for c in ['black_smoke','white_gray_smoke','flame','cloud','fog_haze','chimney_smoke']]},
      'benchmark': {'p95_ms': latency}}}


class SelectionTests(unittest.TestCase):
    def test_test_set_cannot_choose_model(self):
        row = candidate('a', .5, 80)
        row['result']['split'] = 'test'
        with self.assertRaises(ValueError):
            score_candidate(row['result'])

    def test_different_validation_sets_rejected(self):
        a, b = candidate('a', .5, 80), candidate('b', .6, 90)
        b['result']['evaluation_ids_sha256'] = 'different'
        with self.assertRaises(ValueError):
            select_candidate([a, b])

    def test_speed_only_breaks_predeclared_near_tie(self):
        winner, _ = select_candidate([candidate('accurate', .6, 100), candidate('faster', .595, 50)])
        self.assertEqual(winner['name'], 'faster')
        winner, _ = select_candidate([candidate('accurate', .6, 100), candidate('much_worse', .55, 10)])
        self.assertEqual(winner['name'], 'accurate')


if __name__ == '__main__':
    unittest.main()
