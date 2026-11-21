import unittest
from build_full_inventory import classify


class FullInventoryTests(unittest.TestCase):
    def setUp(self):
        self.record = {'role':'TS','key':'frame1','label_member':'frame1.json','group_id':'camera1'}
        self.mapping = {'camera1':{'split':'train','group_key':'site1'}}

    def test_preserves_frozen_site_split_and_marks_unvalidated(self):
        state, site = classify(self.record,self.mapping,set())
        self.assertEqual(state,'pending_pixel_and_label_validation')
        self.assertEqual(site,{'split':'train','group_key':'site1'})

    def test_corruption_and_unknown_cameras_are_not_silently_admitted(self):
        self.assertEqual(classify(self.record,self.mapping,{('TS','frame1')})[0],'excluded_archive_corruption')
        self.assertEqual(classify(self.record,{},set())[0],'excluded_unmapped_camera')
        self.assertEqual(classify(self.record|{'label_member':None},self.mapping,set())[0],'excluded_missing_label')
