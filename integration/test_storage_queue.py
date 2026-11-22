import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'edgefire_AI'))
from storage_queue import StorageQueue
from storage_worker import process_one


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.queue = StorageQueue(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_only_one_worker_claims_a_job(self):
        item = self.queue.enqueue(b'fixture', 'image/png')
        barrier = threading.Barrier(4)
        claimed = []
        def claim():
            barrier.wait()
            claimed.append(self.queue.claim())
        threads = [threading.Thread(target=claim) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(job is not None for job in claimed), 1)
        self.assertEqual(self.queue.get(item['id'])['attempts'], 1)
        StorageQueue(self.temp.name)  # Backend restart must not fail or steal a live job.
        self.assertEqual(self.queue.get(item['id'])['status'], 'RUNNING')

    def test_expired_worker_is_fenced_from_new_result(self):
        item = self.queue.enqueue(b'fixture', 'image/png')
        old = self.queue.claim()
        with self.queue.db() as db:
            db.execute('UPDATE jobs SET lease_until=0 WHERE id=?', (item['id'],))
        new = self.queue.claim()
        self.assertNotEqual(old['claim_token'], new['claim_token'])
        self.assertTrue(self.queue.complete(new, {'model_id': 'new'}, b'new-annotated'))
        self.assertFalse(self.queue.complete(old, {'model_id': 'stale'}, b'stale-annotated'))
        row = self.queue.get(item['id'])
        self.assertEqual(row['result']['model_id'], 'new')
        self.assertEqual(self.queue.path(row['annotated_path']).read_bytes(), b'new-annotated')
        self.assertEqual(json.loads(self.queue.path(row['result_path']).read_text('utf8'))['job_id'], item['id'])

    def test_worker_persists_results_and_rejects_changed_input(self):
        item = self.queue.enqueue(b'fixture', 'image/png')
        self.queue.path('objects/' + item['object_id']).write_bytes(b'tampered')
        calls = []
        def infer(raw):
            calls.append(raw)
            return {'model_id': 'test', 'detections': []}, b'annotated'
        process_one(self.queue, infer)
        self.assertEqual(calls, [])
        self.assertEqual(self.queue.get(item['id'])['status'], 'FAILED')
        self.assertTrue(self.queue.retry(item['id']))
        self.queue.path('objects/' + item['object_id']).write_bytes(b'fixture')
        process_one(self.queue, infer)
        self.assertEqual(self.queue.get(item['id'])['status'], 'COMPLETED')
        self.assertEqual(len(calls), 1)
        self.assertFalse(self.queue.retry(item['id']))

    def test_lease_is_renewed_during_slow_inference(self):
        item = self.queue.enqueue(b'fixture', 'image/png')
        def infer(raw):
            time.sleep(1.1)
            self.assertIsNone(self.queue.claim())
            return {'model_id': 'slow'}, b'annotated'
        process_one(self.queue, infer, lease_seconds=.7)
        self.assertEqual(self.queue.get(item['id'])['status'], 'COMPLETED')

    def test_storage_path_cannot_escape_root(self):
        with self.assertRaises(ValueError):
            self.queue.atomic_bytes('../outside', b'no')


if __name__ == '__main__':
    unittest.main()
