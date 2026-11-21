import io
import random
import unittest
from PIL import Image
from audit_full_shards import hash_bands,signature


class FullShardAuditTests(unittest.TestCase):
    def test_radius_four_candidates_share_at_least_one_band(self):
        rng=random.Random(42)
        for distance in range(5):
            for _ in range(100):
                value=rng.getrandbits(64);other=value
                for bit in rng.sample(range(64),distance):other^=1<<bit
                self.assertTrue(set(hash_bands(value))&set(hash_bands(other)))

    def test_encoded_image_signature_is_repeatable(self):
        stream=io.BytesIO();Image.new('RGB',(40,30),(40,80,120)).save(stream,format='JPEG')
        a,tiny,color=signature(stream.getvalue());b,tiny2,color2=signature(stream.getvalue())
        self.assertEqual(a,b);self.assertEqual(tiny.tobytes(),tiny2.tobytes())
        self.assertEqual(tuple(color),tuple(color2))
