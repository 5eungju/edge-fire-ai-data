"""허구의 패턴 라벨로 합성 자료를 만들고 MLP를 학습합니다. 외부 데이터 미전송."""
from pathlib import Path
import json,joblib
import numpy as np
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import f1_score,classification_report
from gas_simulation import extract,PATTERNS,CHANNELS
BASE=Path(__file__).resolve().parent;rng=np.random.default_rng(42)
X=[];y=[];groups=[]
with (BASE/'synthetic_gas_demo.jsonl').open('w',encoding='utf8') as stream:
 for episode in range(800):
  label=episode%4;baseline=rng.uniform(2,30,3);interval=float(rng.choice([1,5,10]));points=16
  t=np.linspace(0,1,points);signal=np.ones((points,3))+rng.normal(0,.06,(points,3))
  if label==1:signal+=np.outer(t**rng.uniform(.7,2),rng.uniform(1.5,7,3))
  elif label==2:
   channel=int(rng.integers(0,3));signal[:,channel]+=rng.uniform(2,8)*np.exp(-((t-rng.uniform(.3,.7))/.12)**2)
  elif label==3:
   channel=int(rng.integers(0,3));signal[points//2:,channel]=rng.choice([0.0,10.0])
  data=np.maximum(signal*baseline,0)
  b=dict(zip(CHANNELS,baseline.tolist()))
  for end in [8,12,16]:
   history=[dict(zip(CHANNELS,row.tolist())) for row in data[:end]]
   X.append(extract(history,b,interval));y.append(label);groups.append(episode)
   # 구조화된 상황·라벨을 담지만 실측 사건/대응 지침으로 위장하지 않습니다.
   row={'id':f'SYN_{episode:04d}_{end:02d}','episode_id':episode,'data_origin':'synthetic','simulation':True,'baseline':b,'sample_interval_seconds':interval,'history':history,'label':{'pattern':PATTERNS[label],'generated_by':'simulation_template_v1','operational_use':False}}
   stream.write(json.dumps(row,ensure_ascii=False)+'\n')
X=np.array(X);y=np.array(y);groups=np.array(groups)
train,test=next(GroupShuffleSplit(test_size=.25,random_state=42).split(X,y,groups))
assert not set(groups[train])&set(groups[test])
model=make_pipeline(StandardScaler(),MLPClassifier(hidden_layer_sizes=(48,24),max_iter=500,random_state=42))
model.fit(X[train],y[train]);pred=model.predict(X[test])
metrics={'data_origin':'synthetic','task':'synthetic_signal_pattern_classification','episodes':800,'rows':len(X),'train_rows':len(train),'test_rows':len(test),'episode_overlap':0,'macro_f1_on_synthetic_holdout':float(f1_score(y[test],pred,labels=range(4),average='macro',zero_division=0)),'classification_report':classification_report(y[test],pred,labels=range(4),target_names=PATTERNS,output_dict=True,zero_division=0),'limitation':'동일 생성기의 새 에피소드 평가일 뿐 실제 센서·가스·산불 성능을 나타내지 않습니다.','operational_use':False}
joblib.dump({'model':model,'metrics':metrics},BASE/'gas_simulation.joblib')
(BASE/'gas_simulation_metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(metrics,ensure_ascii=True))
