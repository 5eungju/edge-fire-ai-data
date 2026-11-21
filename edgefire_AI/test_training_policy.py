import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from training_policy import validate_data_policy, validate_generic_pretrained


class PolicyTests(unittest.TestCase):
    def test_later_review_can_block_a_previously_audited_dataset(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);data=root/'pilot_yolo_seg/dataset.yaml'
            (root/'subsequent_review.json').write_text(json.dumps({'training_allowed':False}),encoding='utf8')
            records=[{'site_group':s,'split':s} for s in ['train','val','test']]
            with self.assertRaisesRegex(ValueError,'Later spatial review'):
                validate_data_policy(data,records)

    def test_visual_review_is_a_required_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'pilot_yolo_seg').mkdir()
            (root/'quality_audit').mkdir()
            records = [{'site_group': s, 'split': s} for s in ['train','val','test']]
            manifest = root/'pilot_manifest.jsonl'
            manifest.write_text('\n'.join(json.dumps(r) for r in records))
            digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
            (root/'validation.json').write_text(json.dumps({'passed':True,'manifest_sha256':digest,'plan_sha256':'plan'}))
            quality = {'manifest_sha256':digest,'selected_location_name_overlap_count':0,'cross_split_visual_similarity_candidates':1}
            (root/'quality_audit/summary.json').write_text(json.dumps(quality))
            data = root/'pilot_yolo_seg/dataset.yaml'
            data.write_text('path: '+data.parent.as_posix()+'\ntrain: images/train\nval: images/val\ntest: images/test\n')
            with self.assertRaisesRegex(ValueError,'Unresolved'):
                validate_data_policy(data, records)
            quality['cross_split_visual_similarity_candidates'] = 0
            (root/'quality_audit/summary.json').write_text(json.dumps(quality))
            self.assertTrue(validate_data_policy(data, records)['spatial'])
            manifest.write_text(manifest.read_text()+'\n')
            with self.assertRaisesRegex(ValueError,'stale'):
                validate_data_policy(data, records)

    def test_unknown_wildfire_weights_cannot_start_fresh_spatial_experiment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            weights = root/'weights.pt'
            weights.write_bytes(b'previous wildfire fine tune')
            registry = root/'registry.json'
            registry.write_text(json.dumps([{'sha256':'different','pretrained_classes':80}]))
            with self.assertRaisesRegex(ValueError,'generic pretrained'):
                validate_generic_pretrained(weights, registry)


if __name__ == '__main__':
    unittest.main()
