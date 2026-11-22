from pathlib import Path
import os
import joblib,math
from fastapi import FastAPI,HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel,Field,ConfigDict
from features import LABELS,vector
BASE=Path(__file__).resolve().parent
model_path=Path(os.environ.get('MODEL_PATH',str(BASE/'model.joblib')))
if not model_path.is_file():
 raise RuntimeError('모델 파일이 없습니다. 전달받은 model.joblib을 api/에 넣거나 MODEL_PATH를 지정하세요. README.md를 참고하세요.')
bundle=joblib.load(model_path);model=bundle['model'];metrics=bundle['metrics']
app=FastAPI(title='산불 상황 위험 등급 API — 연구 시제품',version=metrics['model_version'],description='이미 발생한 산불 사례의 주석 위험 등급을 재현합니다. 산불 발생 확률, 실시간 확산 예측, 이미지·가스 탐지 기능은 제공하지 않습니다.')
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
def health():return {'status':'ok','model_version':metrics['model_version'],'mode':'research_prototype'}
@app.get('/model-info')
def info():return metrics
@app.post('/wildfire/assess')
def assess(obs:Observation):
 data=obs.model_dump();x=vector(data);prediction=int(model.predict([x])[0]);scores=model.predict_proba([x])[0]
 return {'model_version':metrics['model_version'],'task':'existing_wildfire_annotation_classification','predicted_annotation_level':LABELS[prediction],'class_scores':{LABELS[int(c)]:round(float(p),6) for c,p in zip(model.classes_,scores)},'score_meaning':'보정되지 않은 모델 분류 점수이며 산불 발생 확률이 아닙니다.','missing_optional_fields':[k for k,v in data.items() if v is None],'limitations':metrics['limitations'],'operational_use':False}
if __name__=='__main__':
 import uvicorn
 uvicorn.run(app,host='127.0.0.1',port=8000)
