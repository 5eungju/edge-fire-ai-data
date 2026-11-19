"""합성 시계열의 패턴 분류 전용. 가스 식별·산불 확증 모델이 아닙니다."""
from pathlib import Path
import os
from typing import Literal
import numpy as np,joblib
from pydantic import BaseModel,ConfigDict,Field
from fastapi import HTTPException
BASE=Path(__file__).resolve().parent
CHANNELS=['CO','H2','VOC']
PATTERNS=['background','multichannel_rise','transient_interference','sensor_artifact']
class Values(BaseModel):
 model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
 CO:float=Field(ge=0,le=1e9)
 H2:float=Field(ge=0,le=1e9)
 VOC:float=Field(ge=0,le=1e9)
class Baseline(Values):
 CO:float=Field(gt=0,le=1e9)
 H2:float=Field(gt=0,le=1e9)
 VOC:float=Field(gt=0,le=1e9)
class SimulationRequest(BaseModel):
 model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
 simulation:Literal[True]
 baseline:Baseline
 history:list[Values]=Field(min_length=3,max_length=120)
 sample_interval_seconds:float=Field(gt=0,le=3600)

def extract(history,baseline,interval):
 # 샘플링 간격을 반영한 기준값 대비 변화. 임의의 독성/화재 임계값을 쓰지 않습니다.
 a=np.array([[v[k] for k in CHANNELS] for v in history],dtype=float)
 b=np.array([baseline[k] for k in CHANNELS]);r=np.log1p(a/b)
 seconds=interval*(len(r)-1)
 return np.concatenate([r[-1],r.mean(axis=0),r.std(axis=0),(r[-1]-r[0])/seconds,np.max(np.abs(np.diff(r,axis=0)),axis=0)]).tolist()

_bundle=None
def infer(request:SimulationRequest):
 global _bundle
 path=Path(os.getenv('GAS_MODEL_PATH',str(BASE/'gas_simulation.joblib')))
 if _bundle is None:
  if not path.is_file():raise HTTPException(503,detail='합성 가스 모델이 없습니다. train_gas_demo.py를 실행하세요.')
  _bundle=joblib.load(path)
 features=extract([x.model_dump() for x in request.history],request.baseline.model_dump(),request.sample_interval_seconds)
 model=_bundle['model'];scores=model.predict_proba([features])[0];label=int(model.predict([features])[0])
 return {'status':'SIMULATION_ONLY','data_origin':'synthetic','predicted_pattern':PATTERNS[label],'class_scores':{PATTERNS[int(c)]:round(float(v),6) for c,v in zip(model.classes_,scores)},'risk_level':None,'operational_use':False,'model_version':'gas-simulation-v1','meaning':'합성 신호 패턴 분류 점수. 실제 가스 위험도·화재 확증·물질 종류가 아닙니다.','metrics':_bundle['metrics']}
