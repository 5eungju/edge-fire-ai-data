from pathlib import Path
import os,json,time
import joblib
from fastapi import FastAPI,HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel,Field,ConfigDict
from features import LABELS,vector
from gas_simulation import SimulationRequest,infer as infer_gas
from chemical_catalog import lookup as lookup_chemical
BASE=Path(__file__).resolve().parent
model_path=Path(os.environ.get('MODEL_PATH',str(BASE/'model.joblib')))
metrics=json.loads((BASE/'metrics.json').read_text(encoding='utf8'))
model=None
if model_path.is_file():
 bundle=joblib.load(model_path);model=bundle['model'];metrics=bundle['metrics']
app=FastAPI(title='EDGE-FIRE AI 연구 시제품',version=metrics['model_version'],description='산불 사례 주석 등급 분류, 합성 가스 신호 패턴 분류, 원시 화학물성 조회. 실제 가스 위험도·물질 식별·화재 확증 모델은 아닙니다.')
@app.exception_handler(RequestValidationError)
async def validation_error(request,exc):
 return JSONResponse(status_code=422,content={'detail':[{'loc':list(e['loc']),'msg':e['msg'],'type':e['type']} for e in exc.errors()]})
class Observation(BaseModel):
 model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
 temperature:float=Field(ge=-80,le=70,description='섭씨')
 humidity_percent:float=Field(ge=0,le=100)
 wind_speed:float=Field(ge=0,le=100,description='데이터와 입력 단위의 일치 여부 확인 필요')
 wind_direction:float|None=Field(default=None,ge=0,le=360)
 rainfall:float|None=Field(default=None,ge=0)
 past_rainfall_7days:float|None=Field(default=None,ge=0)
 elevation:float|None=Field(default=None,ge=-500,le=9000)
 slope:float|None=Field(default=None,ge=0,le=90)
 slope_aspect:float|None=Field(default=None,ge=0,le=360)
@app.get('/health')
def health():return {'status':'ok' if model is not None else 'model_missing','model_loaded':model is not None,'model_version':metrics['model_version'],'mode':'research_prototype'}
@app.get('/model-info')
def info():return metrics
@app.post('/wildfire/assess')
def assess(obs:Observation):
 if model is None:raise HTTPException(status_code=503,detail='모델 파일이 없습니다. edgefire_AI/model.joblib 또는 MODEL_PATH를 확인하세요.')
 data=obs.model_dump();x=vector(data);prediction=int(model.predict([x])[0]);scores=model.predict_proba([x])[0]
 return {'model_version':metrics['model_version'],'task':'existing_wildfire_annotation_classification','predicted_annotation_level':LABELS[prediction],'class_scores':{LABELS[int(c)]:round(float(p),6) for c,p in zip(model.classes_,scores)},'score_meaning':'보정되지 않은 모델 분류 점수이며 산불 발생 확률이 아닙니다.','missing_optional_fields':[k for k,v in data.items() if v is None],'limitations':metrics['limitations'],'operational_use':False}

class GasMetrics(BaseModel):
 model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
 CO:float=Field(ge=0)
 H2:float=Field(ge=0)
 VOC:float=Field(ge=0)

class TelemetryAssessment(BaseModel):
 """기존 백엔드 센서 필드를 보존하고 기상 입력을 선택적으로 추가합니다."""
 model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
 node_id:str=Field(min_length=1,max_length=100)
 sequence_no:int|None=Field(default=None,ge=0)
 timestamp:int=Field(default_factory=lambda:int(time.time()),ge=0)
 gas_data:GasMetrics|None=None
 camera_azimuth:float|None=Field(default=None,ge=0,le=360)
 environment:Observation|None=None
 gas_simulation:SimulationRequest|None=None

DISPLAY_LEVELS=['정상','관심','주의','경계','심각']

@app.post('/api/v1/ai/assess')
def assess_telemetry(payload:TelemetryAssessment):
 packet=payload.model_dump(exclude_none=True)
 packet.pop('environment',None)
 packet.pop('gas_simulation',None)
 ai={'status':'INSUFFICIENT_INPUT','risk_level':None,'risk_label':None,'model_version':metrics['model_version'],'operational_use':False,'missing_required_fields':[]}
 if payload.environment is None:
  ai['missing_required_fields']=['environment.temperature','environment.humidity_percent','environment.wind_speed']
 elif model is None:
  ai['status']='AI_UNAVAILABLE'
 else:
  result=assess(payload.environment)
  level=LABELS.index(result['predicted_annotation_level'])+1
  ai.update(result)
  ai.update({'status':'RESEARCH_RESULT','risk_level':level,'risk_label':DISPLAY_LEVELS[level-1]})
 if payload.gas_simulation is not None:
  ai['simulated_gas']=infer_gas(payload.gas_simulation)
 return {**packet,'event_type':'hazard_assessment','risk_level':ai['risk_level'],'status':ai['status'],'ai':ai}

@app.post('/api/v1/ai/gas/assess')
def assess_gas(payload:SimulationRequest):return infer_gas(payload)

@app.get('/api/v1/ai/chemicals/{cid}')
def get_chemical(cid:str):
 if not cid.isdigit():raise HTTPException(422,detail='CID는 숫자 문자열이어야 합니다.')
 return lookup_chemical(cid)

if __name__=='__main__':
 import uvicorn
 uvicorn.run(app,host=os.environ.get('AI_HOST','127.0.0.1'),port=int(os.environ.get('AI_PORT','8001')))
