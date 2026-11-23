import os, sys, tempfile, unittest, io, json
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
    def test_air_data_auth_and_invalid_station(self):
        self.assertEqual(self.client.get('/api/v1/storage/air-quality/stations').status_code,401)
        with patch.dict(os.environ,{'AIR_QUALITY_ROOT':TEMP.name}):
            status=self.client.get('/api/v1/storage/air-quality/stations',headers=self.headers).json()
            self.assertEqual(status['status'],'PREPARING')
            self.assertEqual(self.client.get('/api/v1/storage/air-quality/series',headers=self.headers,params={'station':'../runtime'}).status_code,422)
    def test_assessment_routes_require_auth_and_registered_models(self):
        self.assertEqual(self.client.get('/api/v1/storage/models').status_code,401)
        status=self.client.get('/api/v1/storage/models',headers=self.headers).json()
        self.assertEqual(status['status'],'TRAINING_OR_NOT_REGISTERED')
        self.assertEqual(self.client.post('/api/v1/storage/assessments',headers=self.headers,json={}).status_code,409)
        self.assertEqual(self.client.post('/api/v1/storage/assessments',headers=self.headers,json={'chemical_cid':'../file'}).status_code,422)
    def test_auth_and_stable_ids(self):
        self.assertEqual(self.client.get('/api/v1/storage/config').status_code,401)
        a=self.client.get('/api/v1/storage/config',headers=self.headers).json()
        b=self.client.get('/api/v1/storage/config',headers=self.headers).json()
        self.assertEqual(a,b);self.assertTrue(a['project_id'].startswith('PRJ_'))
    def test_upload_persistence_and_path_safety(self):
        stream=io.BytesIO();Image.new('RGB',(24,24),'red').save(stream,format='PNG');raw=stream.getvalue()
        response=self.client.post('/api/v1/storage/jobs',headers=self.headers,files={'image':('../../outside.png',raw,'image/png')})
        self.assertEqual(response.status_code,202,response.text);job=response.json();self.assertEqual(job['status'],'PENDING')
        image=self.client.get('/api/v1/storage/jobs/'+job['id']+'/image',headers=self.headers)
        self.assertEqual(image.content,raw)
        self.assertEqual(self.client.post('/api/v1/storage/jobs/'+job['id']+'/retry',headers=self.headers).status_code,409)
        self.assertFalse((Path(TEMP.name).parent/'outside.png').exists())
    def test_region_photos_are_isolated_and_assignment_persists(self):
        stream=io.BytesIO();Image.new('RGB',(24,24),'blue').save(stream,format='PNG');raw=stream.getvalue()
        def upload(region=None):
            return self.client.post('/api/v1/storage/jobs',headers=self.headers,files={'image':('photo.png',raw,'image/png')},data={} if region is None else {'region_id':region})
        a=upload('seoul').json();b=upload('chuncheon').json();old=upload().json()
        def ids(region):
            return [j['id'] for j in self.client.get('/api/v1/storage/jobs',headers=self.headers,params={'region':region}).json()]
        self.assertIn(a['id'],ids('seoul'));self.assertNotIn(b['id'],ids('seoul'))
        self.assertIn(old['id'],ids('unassigned'));self.assertNotIn(old['id'],ids('seoul'))
        route='/api/v1/storage/jobs/'+old['id']+'/location'
        self.assertEqual(self.client.post(route,json={'region_id':'seoul'}).status_code,401)
        self.assertEqual(self.client.post(route,headers=self.headers,json={'region_id':[]}).status_code,422)
        self.assertEqual(self.client.post(route,headers=self.headers,json={'region_id':'gangneung'}).status_code,200)
        self.assertIn(old['id'],ids('gangneung'));self.assertNotIn(old['id'],ids('unassigned'))
        self.assertEqual(upload('../map').status_code,422)
        self.assertEqual(self.client.get('/api/v1/storage/jobs',headers=self.headers,params={'region':'../map'}).status_code,422)
        self.assertEqual(self.client.get('/api/v1/storage/jobs/'+a['id'],headers=self.headers).json()['region_id'],'seoul')
    def test_dead_training_worker_is_not_reported_as_running(self):
        path=Path(TEMP.name)/'training.json'
        path.write_text(json.dumps({'phase':'training','pid':99999999,'epoch':5,'started_utc':'2026-11-20T00:00:00+00:00'}))
        with patch.dict(os.environ,{'TRAINING_STATUS_PATH':str(path)}):
            result=self.client.get('/api/v1/storage/training-status',headers=self.headers).json()
        self.assertEqual(result['phase'],'stopped')
        self.assertFalse(result['worker_alive'])
    def test_invalid_image_and_unavailable_job(self):
        self.assertEqual(self.client.post('/api/v1/storage/jobs',headers=self.headers,files={'image':('a.jpg',b'not an image','image/jpeg')}).status_code,422)
        self.assertEqual(self.client.get('/api/v1/storage/jobs/no-job',headers=self.headers).status_code,404)

if __name__=='__main__':unittest.main()
