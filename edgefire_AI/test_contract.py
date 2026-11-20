"""AI 폴더만 검사합니다. 외부 서버나 데이터 다운로드를 실행하지 않습니다."""
import unittest,os
from unittest.mock import patch
from fastapi.testclient import TestClient
import app as service

class ContractTests(unittest.TestCase):
 def setUp(self):
  token_patch=patch.dict(os.environ,{'LOCAL_API_TOKEN':'test-only-secret'});token_patch.start();self.addCleanup(token_patch.stop)
  self.client=TestClient(service.app,headers={'X-API-Key':'test-only-secret'})
 def test_private_post_requires_token(self):
  self.assertEqual(TestClient(service.app).post('/api/v1/ai/assess',json={'node_id':'N1'}).status_code,401)
 def test_gas_only_is_not_inferred(self):
  with patch.object(service,'model',None):
   response=self.client.post('/api/v1/ai/assess',json={'node_id':'GAS-Node-02','gas_data':{'CO':85,'H2':38,'VOC':100}})
  self.assertEqual(response.status_code,200);data=response.json()
  self.assertIsNone(data['risk_level']);self.assertEqual(data['status'],'INSUFFICIENT_INPUT');self.assertEqual(data['gas_data']['CO'],85)
 def test_no_model_is_not_normal(self):
  with patch.object(service,'model',None):
   data=self.client.post('/api/v1/ai/assess',json={'node_id':'N1','environment':{'temperature':25,'humidity_percent':30,'wind_speed':5}}).json()
   self.assertEqual(data['status'],'AI_UNAVAILABLE');self.assertIsNone(data['risk_level'])
   self.assertEqual(self.client.post('/wildfire/assess',json={'temperature':25,'humidity_percent':30,'wind_speed':5}).status_code,503)
 def test_reject_bad_inputs(self):
  for env in [{'temperature':25,'humidity_percent':101,'wind_speed':5},{'temperature':25,'humidity_percent':30,'wind_speed':-1},{'temperature':25,'humidity_percent':30}]:
   self.assertEqual(self.client.post('/api/v1/ai/assess',json={'node_id':'N1','environment':env}).status_code,422)
  response=self.client.post('/wildfire/assess',content='{"temperature":NaN,"humidity_percent":30,"wind_speed":5}',headers={'Content-Type':'application/json'})
  self.assertEqual(response.status_code,422)
 def test_real_model_and_mapping(self):
  if service.model is None:self.skipTest('MODEL_PATH not provided; real model test skipped')
  payload={'node_id':'NODE_WUI_0102','sequence_no':12,'timestamp':1795090000,'gas_data':{'CO':0,'H2':0,'VOC':0},'environment':{'temperature':25,'humidity_percent':30,'wind_speed':5}}
  response=self.client.post('/api/v1/ai/assess',json=payload);self.assertEqual(response.status_code,200);data=response.json()
  self.assertEqual(data['status'],'RESEARCH_RESULT');self.assertIn(data['risk_level'],range(1,6));self.assertFalse(data['ai']['operational_use'])
  self.assertEqual(data['risk_level'],service.LABELS.index(data['ai']['predicted_annotation_level'])+1)
  self.assertEqual(data['timestamp'],payload['timestamp']);self.assertEqual(data['sequence_no'],12)
  payload['gas_data']={'CO':900,'H2':500,'VOC':400}
  high=self.client.post('/api/v1/ai/assess',json=payload).json()
  self.assertEqual(data['ai']['class_scores'],high['ai']['class_scores'])
 def test_existing_routes(self):
  self.assertEqual(self.client.get('/health').status_code,200)
  self.assertEqual(self.client.get('/model-info').status_code,200)
  self.assertIn('/api/v1/ai/assess',self.client.get('/openapi.json').json()['paths'])

if __name__=='__main__':unittest.main()
