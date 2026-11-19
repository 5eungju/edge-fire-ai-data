"""실행 중인 API의 연동 계약을 검사합니다: py smoke_test.py [http://host:port]"""
import json,sys,urllib.request,urllib.error
base=(sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8001').rstrip('/')
def request(path,data=None):
 req=urllib.request.Request(base+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'})
 try:
  with urllib.request.urlopen(req,timeout=20) as r:return r.status,json.load(r)
 except urllib.error.HTTPError as e:return e.code,json.load(e)
status,health=request('/health');assert status==200 and health['status']=='ok'
payload={'temperature':25,'humidity_percent':30,'wind_speed':5}
status,result=request('/wildfire/assess',payload)
assert status==200 and result['operational_use'] is False
assert len(result['missing_optional_fields'])==6
assert abs(sum(result['class_scores'].values())-1)<.00001
for invalid in [{**payload,'humidity_percent':101},{'temperature':25,'humidity_percent':30},{**payload,'gas_ppm':30},{**payload,'temperature':float('nan')}]:
 status,_=request('/wildfire/assess',invalid);assert status==422
status,schema=request('/openapi.json');assert status==200 and '/wildfire/assess' in schema['paths']
print('PASS: health, inference, missing optional fields, invalid inputs, OpenAPI')
