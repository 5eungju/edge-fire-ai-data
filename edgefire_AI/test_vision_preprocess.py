import sys, tempfile, zipfile, unittest, copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from split_zip_reader import ZipReader
from prepare_vision_dataset import polygons, EXPECTED_NAMES, fold
class PreprocessTests(unittest.TestCase):
 def test_zip_members_and_crc(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'fixture.zip'
   with zipfile.ZipFile(path,'w') as archive:
    archive.writestr('한글/a.txt',b'abc'*100,compress_type=zipfile.ZIP_DEFLATED)
    archive.writestr('b.txt',b'123',compress_type=zipfile.ZIP_STORED)
   reader=ZipReader(path)
   entries=list(reader.entries())
   with zipfile.ZipFile(path) as reference:
    for entry in entries:self.assertEqual(reader.read(entry),reference.read(entry.name))
   entries[0].crc=0
   with self.assertRaisesRegex(ValueError,'CRC'):reader.read(entries[0])
   reader.close()
 def test_cross_volume_read(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp); archive=root/'fixture.zip'
   with zipfile.ZipFile(archive,'w') as writer:writer.writestr('a',b'a')
   reader=ZipReader(archive)
   first=root/'one';second=root/'two';first.write_bytes(b'abc');second.write_bytes(b'defg')
   reader.parts=[first,second];reader.sizes=[3,4]
   self.assertEqual(reader.span(0,2,4),b'cdef')
   self.assertEqual(reader.span(0,4,2),b'ef')
   with self.assertRaisesRegex(ValueError,'outside'):reader.span(0,6,2)
   reader.close()
 def test_polygon_validation(self):
  data={'images':[{'id':1,'width':100,'height':100}],'categories':[{'id':k,'name':v} for k,v in EXPECTED_NAMES.items()],'annotations':[{'image_id':1,'category_id':3,'segmentation':[[0,0,100,0,100,100]]}]}
  segments,counts,_=polygons(data,100,100)
  self.assertEqual(segments,[(2,[(0.,0.),(1.,0.),(1.,1.)])]);self.assertEqual(counts['flame'],1)
  with self.assertRaisesRegex(ValueError,'dimension'):polygons(data,99,100)
  broken=copy.deepcopy(data);broken['annotations'][0]['segmentation'].append([0,0,1,0,1,1])
  with self.assertRaisesRegex(ValueError,'multipart'):polygons(broken,100,100)
  broken=copy.deepcopy(data);broken['annotations'][0]['segmentation'][0][0]=-2
  with self.assertRaisesRegex(ValueError,'out_of_bounds'):polygons(broken,100,100)
 def test_group_determinism(self):
  self.assertEqual(fold('BC002001'),fold('BC002001'))
if __name__=='__main__':unittest.main()
