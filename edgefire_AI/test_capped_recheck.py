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

    def test_distance_color_and_split_filters(self):
        hits=candidate_indices(np.array([0,15,31,0,0],dtype=np.uint64),
            np.array([[0,0,0],[0,0,0],[0,0,0],[.2,0,0],[0,0,0]],dtype=np.float32),
            np.array(['test','test','test','test','train']),np.arange(1,6),0,np.zeros(3),'train',0)
        self.assertEqual(hits.tolist(),[0,1])
