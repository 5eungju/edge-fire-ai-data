import json
import tempfile
import unittest
from pathlib import Path

from multi_model_storage import validate_request, registry, model_status


class MultiModelContractTests(unittest.TestCase):
    def test_absent_models_are_not_claimed_available(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(model_status(folder)['status'],'TRAINING_OR_NOT_REGISTERED')

    def test_invented_detections_and_unknown_fields_rejected(self):
        for payload in [{'detections':[]},{'chemical_cid':'../../runtime.json'},
                        {'vision_job_id':'../file'},{'response_features':{'humidity':float('nan')}},
                        {'response_features':{'wind':True}},{'temperature_c':float('inf')}]:
            with self.assertRaises(ValueError):validate_request(payload)

    def test_historical_and_current_context_cannot_be_mixed(self):
        with self.assertRaises(ValueError):
            validate_request(dict(reference_case_id='case',response_features={'wind':1.0}))

    def test_minimal_context_is_allowed_for_explicit_abstention(self):
        self.assertEqual(validate_request({}),{})

    def test_registry_rejects_model_tampering(self):
        import hashlib
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'models').mkdir();model=root/'model.joblib';model.write_bytes(b'initial')
            payload=dict(root=str(root),sha256={'model.joblib':hashlib.sha256(b'initial').hexdigest()})
            (root/'models/multi_model_registry.json').write_text(json.dumps(payload),encoding='utf-8')
            self.assertIsNotNone(registry(root));model.write_bytes(b'changed')
            with self.assertRaises(ValueError):registry(root)


if __name__=='__main__':unittest.main()
