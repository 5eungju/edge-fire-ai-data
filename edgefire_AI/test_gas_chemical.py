import unittest,json
from pathlib import Path
from fastapi.testclient import TestClient
from app import app
BASE=Path(__file__).resolve().parent
class GasChemicalTests(unittest.TestCase):
 def setUp(self):self.client=TestClient(app)
 def example(self):
  return {'simulation':True,'baseline':{'CO':5,'H2':5,'VOC':5},'sample_interval_seconds':5,'history':[{'CO':5+i*2,'H2':5+i,'VOC':5+i*3} for i in range(8)]}
 def test_requires_explicit_simulation(self):
  p=self.example();p['simulation']=False
  self.assertEqual(self.client.post('/api/v1/ai/gas/assess',json=p).status_code,422)
 def test_reject_zero_baseline(self):
  p=self.example();p['baseline']['CO']=0
  self.assertEqual(self.client.post('/api/v1/ai/gas/assess',json=p).status_code,422)
 def test_trained_synthetic_model(self):
  response=self.client.post('/api/v1/ai/gas/assess',json=self.example())
  self.assertEqual(response.status_code,200);r=response.json()
  self.assertEqual(r['status'],'SIMULATION_ONLY');self.assertIsNone(r['risk_level']);self.assertFalse(r['operational_use'])
 def test_no_fusion_with_real_risk(self):
  r=self.client.post('/api/v1/ai/assess',json={'node_id':'GAS-Node-02','gas_simulation':self.example()}).json()
  self.assertIsNone(r['risk_level']);self.assertEqual(r['status'],'INSUFFICIENT_INPUT');self.assertEqual(r['ai']['simulated_gas']['data_origin'],'synthetic')
 def test_catalog_provenance(self):
  catalog=json.loads((BASE/'chemical_catalog.json').read_text(encoding='utf8'));cid=next(iter(catalog['records']))
  r=self.client.get('/api/v1/ai/chemicals/'+cid);self.assertEqual(r.status_code,200)
  d=r.json();self.assertEqual(d['data_origin'],'AI_Hub_chemical_dataset');self.assertIsNone(d['risk_level']);self.assertFalse(d['operational_use'])
  for values in d['properties'].values():
   for value in values:self.assertFalse(value['units_verified'])
  self.assertEqual(self.client.get('/api/v1/ai/chemicals/invalid').status_code,422)
  self.assertEqual(self.client.get('/api/v1/ai/chemicals/999999999999999999').status_code,404)
if __name__=='__main__':unittest.main()
