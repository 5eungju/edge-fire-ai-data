import unittest
import numpy as np
from recheck_capped_similarity import candidate_indices


class CappedRecheckTests(unittest.TestCase):
    def test_no_candidate_cap_and_only_new_cross_split_rows(self):
        n=700
        hits=candidate_indices(np.zeros(n,dtype=np.uint64),np.zeros((n,3),dtype=np.float32),
            np.array(['test']*n),np.arange(1,n+1),0,np.zeros(3),'train',0)
        self.assertEqual(len(hits),700)
        hits=candidate_indices(np.zeros(n,dtype=np.uint64),np.zeros((n,3),dtype=np.float32),
            np.array(['test']*n),np.arange(1,n+1),0,np.zeros(3),'train',650)
        self.assertEqual(len(hits),50)
        self.assertEqual(hits.tolist(),list(range(650,700)))

    def test_incremental_ranges_match_exhaustive_scalar_search(self):
        rng=np.random.default_rng(42)
        hashes=rng.integers(0,256,size=500,dtype=np.uint64)
        colors=rng.uniform(0,.12,size=(500,3)).astype(np.float32)
        splits=np.array(['train','test','val','test']*125)
        rowids=np.arange(1,501)*3
        value=7;color=np.array([.06,.06,.06],dtype=np.float32)
        for after in [0,3,37,700,1498,1500,2000]:
            expected=[i for i in range(500) if rowids[i]>after and splits[i]!='train'
                      and (int(hashes[i])^value).bit_count()<=4
                      and all(abs(float(colors[i,j])-float(color[j]))<.05 for j in range(3))]
            self.assertEqual(candidate_indices(hashes,colors,splits,rowids,value,color,'train',after).tolist(),expected)

    def test_distance_color_and_split_filters(self):
        hits=candidate_indices(np.array([0,15,31,0,0],dtype=np.uint64),
            np.array([[0,0,0],[0,0,0],[0,0,0],[.2,0,0],[0,0,0]],dtype=np.float32),
            np.array(['test','test','test','test','train']),np.arange(1,6),0,np.zeros(3),'train',0)
        self.assertEqual(hits.tolist(),[0,1])
