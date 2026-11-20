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

from xgboost import XGBClassifier
from lightgbm import LGBMClassifier
from sklearn.utils.class_weight import compute_sample_weight
from sklearn.metrics import accuracy_score
from threadpoolctl import threadpool_limits
comparison=json.loads((BASE/'model_comparison.json').read_text(encoding='utf8'))
weights=compute_sample_weight('balanced',y[train])
models={'xgboost':XGBClassifier(n_estimators=180,max_depth=4,learning_rate=.05,subsample=.8,colsample_bytree=.8,reg_lambda=1.,objective='multi:softprob',num_class=5,eval_metric='mlogloss',random_state=42,n_jobs=2,tree_method='hist'),'lightgbm':LGBMClassifier(n_estimators=180,num_leaves=15,learning_rate=.05,reg_lambda=1.,class_weight='balanced',random_state=42,n_jobs=2,verbosity=-1)}
for name,classifier in models.items():
 model=make_pipeline(SimpleImputer(strategy='median',add_indicator=True),classifier)
 kwargs={'xgbclassifier__sample_weight':weights} if name=='xgboost' else {}
 with threadpool_limits(limits=2):model.fit(X[train],y[train],**kwargs);pred=model.predict(X[test])
 report=classification_report(y[test],pred,labels=list(range(5)),target_names=LABELS,zero_division=0,output_dict=True)
 result={'macro_f1':float(f1_score(y[test],pred,labels=list(range(5)),average='macro',zero_division=0)),'accuracy':float(accuracy_score(y[test],pred)),'balanced_accuracy':float(balanced_accuracy_score(y[test],pred)),'classification_report':report}
 comparison['results'][name]=result
 print(name,json.dumps(result),flush=True)
(BASE/'model_comparison.json').write_text(json.dumps(comparison,ensure_ascii=False,indent=2),encoding='utf8')
print('BOOST_COMPARISON_COMPLETE',flush=True)
