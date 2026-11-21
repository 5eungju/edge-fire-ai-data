import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from PIL import Image


def write_shard(path,identifier,split):
    stream=io.BytesIO();Image.new('RGB',(32,24),(40,80,120)).save(stream,format='JPEG')
    with zipfile.ZipFile(path,'w') as archive:
        archive.writestr('shard_manifest.jsonl',json.dumps({'id':identifier,'split':split,'site_group':identifier})+'\n')
        archive.writestr('images/'+split+'/'+identifier+'.jpg',stream.getvalue())
        archive.writestr('labels/'+split+'/'+identifier+'.txt','0 0.1 0.1 0.8 0.1 0.5 0.8\n')
        archive.writestr('annotations_original/'+split+'/'+identifier+'.json','{}')


class RelocatedShardTests(unittest.TestCase):
    def run_audit(self,root,prior):
        return subprocess.run([sys.executable,str(Path(__file__).with_name('audit_full_shards.py')),
            '--source',str(root),'--extra-shards',str(prior),'--output',str(root/'audit')],
            capture_output=True,text=True,encoding='utf8')

    def test_old_and_new_directories_are_read_without_modifying_shards(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'active';prior=Path(temporary)/'prior'
            (root/'shards').mkdir(parents=True);prior.mkdir()
            paths=[root/'shards/new.zip',prior/'old.zip']
            write_shard(paths[0],'new','train');write_shard(paths[1],'old','test')
            before=[hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
            (root/'status.json').write_text(json.dumps({'phase':'paused_missing_source_archives','accepted':2}))
            result=self.run_audit(root,prior);self.assertEqual(result.returncode,0,result.stderr)
            report=json.loads((root/'audit/status.json').read_text())
            self.assertEqual(report['images_audited'],2)
            self.assertFalse(report['full_export_completed'])
            self.assertEqual(before,[hashlib.sha256(p.read_bytes()).hexdigest() for p in paths])

    def test_colliding_shard_names_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'active';prior=Path(temporary)/'prior'
            (root/'shards').mkdir(parents=True);prior.mkdir()
            write_shard(root/'shards/same.zip','one','train');write_shard(prior/'same.zip','two','test')
            (root/'status.json').write_text(json.dumps({'phase':'preprocessing','accepted':2}))
            result=self.run_audit(root,prior)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('Duplicate shard names',result.stderr)
