"""AI 단독 호출 예제. 백엔드·프론트·WebSocket에는 아무것도 보내지 않습니다."""
import json,os,urllib.request
payload={'node_id':'NODE_WUI_0102','sequence_no':1,'gas_data':{'CO':12,'H2':5,'VOC':20},'environment':{'temperature':25,'humidity_percent':30,'wind_speed':5,'slope':15,'elevation':300}}
base=os.getenv('AI_SERVICE_URL','http://127.0.0.1:8001').rstrip('/')
request=urllib.request.Request(base+'/api/v1/ai/assess',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'},method='POST')
if __name__=='__main__':
 with urllib.request.urlopen(request,timeout=15) as response:print(json.dumps(json.load(response),ensure_ascii=False,indent=2))
