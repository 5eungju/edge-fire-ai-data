import os, sys, tempfile, unittest, io
from pathlib import Path
from unittest.mock import patch
from PIL import Image

TEMP=tempfile.TemporaryDirectory()
os.environ['STORAGE_ROOT']=TEMP.name
os.environ['LOCAL_API_TOKEN']='test-only-secret'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'edgefire_back'))
from fastapi.testclient import TestClient
from main import app

class StorageContract(unittest.TestCase):
    def setUp(self):self.client=TestClient(app);self.headers={'X-API-Key':'test-only-secret'}
    def test_auth_and_stable_ids(self):
        self.assertEqual(self.client.get('/api/v1/storage/config').status_code,401)
        a=self.client.get('/api/v1/storage/config',headers=self.headers).json()
        b=self.client.get('/api/v1/storage/config',headers=self.headers).json()
        self.assertEqual(a,b);self.assertTrue(a['project_id'].startswith('PRJ_'))
    def test_upload_persistence_and_path_safety(self):
        stream=io.BytesIO();Image.new('RGB',(24,24),'red').save(stream,format='PNG');raw=stream.getvalue()
        with patch('storage_api.process_job'):
            response=self.client.post('/api/v1/storage/jobs',headers=self.headers,files={'image':('../../outside.png',raw,'image/png')})
        self.assertEqual(response.status_code,202,response.text);job=response.json()
        image=self.client.get('/api/v1/storage/jobs/'+job['id']+'/image',headers=self.headers)
        self.assertEqual(image.content,raw)
        self.assertEqual(self.client.post('/api/v1/storage/jobs/'+job['id']+'/retry',headers=self.headers).status_code,409)
        self.assertFalse((Path(TEMP.name).parent/'outside.png').exists())
    def test_invalid_image_and_unavailable_job(self):
        self.assertEqual(self.client.post('/api/v1/storage/jobs',headers=self.headers,files={'image':('a.jpg',b'not an image','image/jpeg')}).status_code,422)
        self.assertEqual(self.client.get('/api/v1/storage/jobs/no-job',headers=self.headers).status_code,404)

if __name__=='__main__':unittest.main()
