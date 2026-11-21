import unittest
from review_full_quality import stable_fold_policy


class FullQualityReviewTests(unittest.TestCase):
    def test_preserves_train_and_only_excludes_conflicting_evaluation_rows(self):
        rows=[('A','s1','train'),('B','s2','test'),('C','s3','val'),('D','s4','test'),('E','s5','train')]
        links=[{'camera_a':'A','camera_b':'B','reviewed_by':'visual_review','reason':'Matching road geometry'},
               {'camera_a':'B','camera_b':'C','reviewed_by':'visual_review','reason':'Matching skyline'}]
        policy,_,unused=stable_fold_policy(rows,links)
        self.assertTrue(policy['s1']['keep']);self.assertFalse(policy['s2']['keep']);self.assertFalse(policy['s3']['keep'])
        self.assertTrue(policy['s4']['keep']);self.assertTrue(policy['s5']['keep']);self.assertFalse(unused)
        self.assertEqual(policy['s1']['canonical_site'],policy['s3']['canonical_site'])
        self.assertEqual(policy['s2']['original_split'],'test')

    def test_validation_test_conflict_keeps_original_validation_subset(self):
        rows=[('A','s1','val'),('B','s2','test')]
        link={'camera_a':'A','camera_b':'B','reviewed_by':'visual_review','reason':'Matching railing'}
        policy,_,_=stable_fold_policy(rows,[link])
        self.assertTrue(policy['s1']['keep']);self.assertFalse(policy['s2']['keep'])

    def test_rejects_automatic_links_and_inconsistent_original_components(self):
        with self.assertRaises(ValueError):stable_fold_policy([('A','s1','train'),('B','s1','test')],[])
        with self.assertRaises(ValueError):stable_fold_policy([('A','s1','train'),('B','s2','test')],[{'camera_a':'A','camera_b':'B','reason':'Metric only'}])


if __name__=='__main__':unittest.main()
