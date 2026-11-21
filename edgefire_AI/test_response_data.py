import unittest
import tempfile
import sqlite3
import json
from pathlib import Path
from prepare_response_data import canonical_id,features_from_source,extract
from audit_response_data import audit,incident_split
from clean_response_data import normalize_target


class ResponseDataTests(unittest.TestCase):
    def test_only_explicit_label_aliases_are_merged(self):
        self.assertEqual(normalize_target('매우높음'),'매우 높음')
        self.assertEqual(normalize_target('중간'),'보통')
        self.assertIsNone(normalize_target('중간에서 높음'))
        self.assertIsNone(normalize_target('5'))
        self.assertIsNone(normalize_target('매우 낮음'))

    def test_pairing_uses_event_position_and_time(self):
        self.assertEqual(canonical_id('/GN20220305_S_P0036_T113.json'),canonical_id('/GN20220305_T_P0036_T113.json'))

    def test_future_outcomes_and_answers_cannot_enter_features(self):
        source={'source_data_info':{'weather_conditions':{'wind_speed':2.3},
            'end_timestamp':'future','affected_area':4190,'target':'높음'},'decision_answer':'unsafe'}
        result=features_from_source(source)
        self.assertEqual(result['weather_conditions.wind_speed'],2.3)
        self.assertEqual(len(result),23)
        self.assertFalse(any('end_timestamp' in k or 'target' in k or 'affected_area' in k for k in result))

    def test_event_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'incident_id_mismatch'):
            extract({'raw_data_info':{'fire_info':{'fire_incident_id':'OTHER'}}},{},'/GN20220305_S_P1_T1.json')

    def test_audit_detects_event_overlap_and_conflicting_targets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            db=sqlite3.connect(root/'response_samples.sqlite')
            db.execute('CREATE TABLE samples(event_id TEXT,official_split TEXT,target TEXT,record TEXT,feature_hash TEXT)')
            for split,target in [('train','높음'),('validation','낮음')]:
                db.execute('INSERT INTO samples VALUES(?,?,?,?,?)',('EVENT',split,target,json.dumps({'features':{'wind':2}}),'same-input'))
            db.commit();db.close()
            report=audit(root)
            self.assertEqual(report['official_split_overlapping_event_count'],1)
            self.assertEqual(report['contradictory_input_group_count'],1)
            self.assertFalse(report['training_ready'])
            self.assertEqual(sum('EVENT' in rows for rows in report['incident_split_groups'].values()),1)
