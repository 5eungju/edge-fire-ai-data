"""로컬 AI 허브 ZIP에서 사건별 표본을 추출해 기준 모델을 학습합니다."""
from pathlib import Path
import json,zipfile,collections,random,sys,joblib
import numpy as np
from sklearn.model_selection import GroupShuffleSplit
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.ensemble import RandomForestClassifier
from sklearn.dummy import DummyClassifier
from sklearn.metrics import classification_report,confusion_matrix,balanced_accuracy_score,f1_score
from features import FEATURES,LABELS,normalize_label,vector
BASE=Path(__file__).resolve().parent
root=Path(sys.argv[1]) if len(sys.argv)>1 else Path.home()/'Downloads'
folder=next(root.glob('38.*'));rng=random.Random(42);records=[];unknown=collections.Counter()
for z in sorted(folder.rglob('TL_*.zip')):
 rawpath=next(folder.rglob(z.name.replace('TL_','TS_')))
 with zipfile.ZipFile(z) as labels,zipfile.ZipFile(rawpath) as raw:
  byevent=collections.defaultdict(list)
  for name in labels.namelist():
   if name.endswith('.json'):byevent[Path(name).stem.split('_')[0]].append(name)
  source={Path(n).stem:n for n in raw.namelist() if n.endswith('.json')}
  for event,names in sorted(byevent.items()):
   for name in rng.sample(sorted(names),min(250,len(names))):
    lab=json.loads(labels.read(name))['labelling_data_info'];verdict=lab.get('decision_answer',{}).get('safety_verdict',{});label=normalize_label(verdict.get('safety_level',''))
    if label is None:unknown[verdict.get('safety_level','')]+=1;continue
    sid=Path(name).stem.replace('_T_P','_S_P');source_name=source.get(sid)
    if source_name is None:continue
    d=json.loads(raw.read(source_name));src=d['source_data_info'];obs={**src.get('weather_conditions',{}),**src.get('terrain_conditions',{})}
    records.append({'id':Path(name).stem,'event':event,'x':vector(obs),'y':label})
 print(z.name,'sampled',len(records),flush=True)
X=np.array([r['x'] for r in records]);y=np.array([r['y'] for r in records]);groups=np.array([r['event'] for r in records])
train,test=next(GroupShuffleSplit(n_splits=1,test_size=.25,random_state=42).split(X,y,groups))
assert not set(groups[train]) & set(groups[test])
model=make_pipeline(SimpleImputer(strategy='median',add_indicator=True),RandomForestClassifier(n_estimators=160,max_depth=12,min_samples_leaf=8,class_weight='balanced_subsample',random_state=42,n_jobs=2))
model.fit(X[train],y[train]);pred=model.predict(X[test]);dummy=DummyClassifier(strategy='most_frequent').fit(X[train],y[train]);dp=dummy.predict(X[test])
metrics={'task':'기존 산불 사례의 주석 위험 등급 재현; 발생 확률·확산 속도 예측 아님','model_version':'prototype-2026-11-19','features':FEATURES,'sample_limit_per_incident':250,'sample_rows':len(records),'train_rows':len(train),'test_rows':len(test),'train_incidents':sorted(set(groups[train])),'test_incidents':sorted(set(groups[test])),'incident_overlap':0,'class_counts':{LABELS[i]:int(sum(y==i)) for i in range(5)},'unmapped_labels':dict(unknown),'model_macro_f1':f1_score(y[test],pred,labels=list(range(5)),average='macro',zero_division=0),'dummy_macro_f1':f1_score(y[test],dp,labels=list(range(5)),average='macro',zero_division=0),'model_balanced_accuracy':balanced_accuracy_score(y[test],pred),'classification_report':classification_report(y[test],pred,labels=list(range(5)),target_names=LABELS,zero_division=0,output_dict=True),'confusion_matrix':confusion_matrix(y[test],pred,labels=list(range(5))).tolist(),'limitations':['표본 기반 기준 모델이며 전체 데이터 학습 아님','위험 등급 표준화는 임시 매핑이며 전문가 확인 필요','모든 자료가 산불 사례로 비산불 상황의 성능을 보장하지 않음','기상·지형 단위는 데이터 구축 명세와 실장 센서 사이 추가 대조 필요','별도 사건 분할이나 장소·시간 유사성에 따른 잔여 편향 가능','모델 점수는 보정된 산불 발생 확률이 아님']}
(BASE/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf8')
joblib.dump({'model':model,'metrics':metrics},BASE/'model.joblib')
print(json.dumps({k:v for k,v in metrics.items() if k in ['sample_rows','train_rows','test_rows','model_macro_f1','dummy_macro_f1','model_balanced_accuracy']},ensure_ascii=True),flush=True)
