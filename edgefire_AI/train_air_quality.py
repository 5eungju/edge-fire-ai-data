"""Read real hourly workbooks; fit next-hour CO, never fabricate wildfire labels."""
import argparse
import copy
import hashlib
import io
import json
import math
import os
import sqlite3
import time
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from datetime import datetime,timedelta
from pathlib import Path

os.environ['OMP_NUM_THREADS']='2';os.environ['MKL_NUM_THREADS']='2'
from status_io import write_status
NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
POLLUTANTS=['SO2','CO','O3','NO2','PM10','PM25']
FEATURES=['CO_t','CO_lag1','CO_lag2','CO_lag24','SO2_t','O3_t','NO2_t','PM10_t','PM25_t','hour_sin','hour_cos','weekday_sin','weekday_cos']


def timestamp(value):
    text=str(value).strip()
    if len(text)!=10 or not text.isdigit():raise ValueError('Invalid timestamp')
    hour=int(text[-2:])
    if not 0<=hour<=24:raise ValueError('Invalid hour')
    return (datetime.strptime(text[:8],'%Y%m%d')+timedelta(hours=hour)).strftime('%Y-%m-%dT%H:%M')


def value(raw):
    try:
        result=float(raw)
        return result if math.isfinite(result) and result>=0 else None
    except (ValueError,TypeError):return None


def rows(book):
    with zipfile.ZipFile(io.BytesIO(book)) as archive:
        shared=[]
        if 'xl/sharedStrings.xml' in archive.namelist():
            for _,e in ET.iterparse(archive.open('xl/sharedStrings.xml'),events=['end']):
                if e.tag.endswith('}si'):
                    shared.append(''.join(t.text or '' for t in e.iter() if t.tag.endswith('}t')));e.clear()
        sheet=next(n for n in archive.namelist() if n.startswith('xl/worksheets/sheet') and n.endswith('.xml'))
        for _,e in ET.iterparse(archive.open(sheet),events=['end']):
            if not e.tag.endswith('}row'):continue
            record={}
            for cell in e:
                reference=cell.attrib.get('r','');column=''.join(c for c in reference if c.isalpha())
                item=cell.find('m:v',NS);text=item.text if item is not None else ''.join(cell.itertext())
                if cell.attrib.get('t')=='s':text=shared[int(text)]
                record[column]=text
            yield record
            e.clear()


def input_features(series,i):
    if i<24 or i>=len(series):return None
    record=series[i];at=datetime.fromisoformat(record[0]);indices=[i,i-1,i-2,i-24]
    if any(series[j][0]!=(at-timedelta(hours=i-j)).strftime('%Y-%m-%dT%H:%M') for j in indices):return None
    # SQL columns time, SO2, CO, O3, NO2, PM10, PM25.
    if any(series[j][2] is None for j in indices):return None
    return [series[j][2] for j in indices]+[record[j] for j in [1,3,4,5,6]]+[
        math.sin(2*math.pi*at.hour/24),math.cos(2*math.pi*at.hour/24),
        math.sin(2*math.pi*at.weekday()/7),math.cos(2*math.pi*at.weekday()/7)]


def features(series,i):
    if i+1>=len(series) or series[i+1][2] is None:return None
    at=datetime.fromisoformat(series[i][0])
    if series[i+1][0]!=(at+timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M'):return None
    return input_features(series,i)


def insert_batch(db,batch,counts):
    """Keep identical duplicates once; quarantine all conflicting key values."""
    db.execute('DELETE FROM incoming')
    db.executemany('INSERT INTO incoming VALUES(?,?,?,?,?,?,?,?,?)',batch)
    same=' AND '.join(f'a.{name} IS b.{name}' for name in POLLUTANTS)
    columns=','.join('a.'+n for n in POLLUTANTS)+','+','.join('b.'+n for n in POLLUTANTS)
    pairs=db.execute(f'SELECT a.station,a.time,{columns} FROM measurements a JOIN incoming b USING(station,time) WHERE NOT({same})').fetchall()
    pairs+=db.execute(f'SELECT a.station,a.time,{columns} FROM incoming a JOIN incoming b USING(station,time) WHERE a.rowid<b.rowid AND NOT({same})').fetchall()
    for row in pairs:
        db.execute('INSERT INTO conflicts VALUES(?,?,?,?)',(row[0],row[1],json.dumps(row[2:8]),json.dumps(row[8:14])))
        db.execute('INSERT OR IGNORE INTO excluded_keys VALUES(?,?)',(row[0],row[1]))
    db.execute('DELETE FROM measurements WHERE EXISTS(SELECT 1 FROM excluded_keys e WHERE e.station=measurements.station AND e.time=measurements.time)')
    cursor=db.execute('INSERT OR IGNORE INTO measurements SELECT i.* FROM incoming i WHERE NOT EXISTS(SELECT 1 FROM excluded_keys e WHERE e.station=i.station AND e.time=i.time)')
    counts['ignored_duplicate_or_quarantined_rows']+=len(batch)-cursor.rowcount
    db.commit()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,default=Path.home()/'Downloads/2026.zip')
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();root=args.output.resolve()
    if root.drive.upper()!='C:':raise ValueError('Use C: storage')
    root.mkdir(parents=True,exist_ok=True)
    if (root/'status.json').exists():raise FileExistsError('Preserve previous run')
    state=dict(pid=os.getpid(),phase='ingesting',started=time.time(),wildfire_classifier=False)
    def update(**kw):state.update(kw,updated=time.time());write_status(root/'status.json',state)
    update()
    try:
      db=sqlite3.connect(root/'measurements.sqlite')
      db.execute('CREATE TABLE stations(code TEXT PRIMARY KEY,region TEXT,name TEXT,network TEXT,address TEXT)')
      db.execute('CREATE TABLE measurements(station TEXT,time TEXT,SO2 REAL,CO REAL,O3 REAL,NO2 REAL,PM10 REAL,PM25 REAL,source TEXT,PRIMARY KEY(station,time))')
      db.execute('CREATE TEMP TABLE incoming AS SELECT * FROM measurements WHERE 0')
      db.execute('CREATE INDEX incoming_key ON incoming(station,time)')
      db.execute('CREATE TABLE excluded_keys(station TEXT,time TEXT,PRIMARY KEY(station,time))')
      db.execute('CREATE TABLE conflicts(station TEXT,time TEXT,first_values TEXT,second_values TEXT)')
      counts=Counter();missing=Counter();source_info=[];batch=[]
      with zipfile.ZipFile(args.source) as archive:
        for entry in archive.infolist():
          if not entry.filename.endswith('.xlsx'):continue
          book=archive.read(entry);source_info.append(dict(member=entry.filename,sha256=hashlib.sha256(book).hexdigest()))
          iterator=rows(book);header=next(iterator)
          if [header.get(chr(65+i)) for i in range(12)]!=['지역','망','측정소코드','측정소명','측정일시','SO2','CO','O3','NO2','PM10','PM25','주소']:
              raise ValueError('Unexpected workbook schema')
          for row in iterator:
            counts['source_rows']+=1;region=str(row.get('A',''))
            if not region.startswith(('서울','경기','인천','강원')):continue
            code=str(row.get('C',''))
            if not code.isdigit():counts['invalid_station']+=1;continue
            try:at=timestamp(row.get('E'))
            except ValueError:counts['invalid_time']+=1;continue
            numbers=[value(row.get(chr(70+j))) for j in range(6)]
            for key,n in zip(POLLUTANTS,numbers):
                if n is None:missing[key]+=1
            db.execute('INSERT OR IGNORE INTO stations VALUES(?,?,?,?,?)',(code,region,row.get('D'),row.get('B'),row.get('L')))
            batch.append((code,at,*numbers,entry.filename));counts['regional_rows']+=1
            if len(batch)>=5000:
                insert_batch(db,batch,counts);batch=[]
                update(member=entry.filename,counts=dict(counts))
          if batch:insert_batch(db,batch,counts);batch=[]
          update(member=entry.filename,counts=dict(counts))
      counts['retained_unique_observations']=db.execute('SELECT COUNT(*) FROM measurements').fetchone()[0]
      counts['quarantined_conflicting_keys']=db.execute('SELECT COUNT(*) FROM excluded_keys').fetchone()[0]
      import numpy as np
      import joblib
      from sklearn.ensemble import HistGradientBoostingRegressor
      from sklearn.neural_network import MLPRegressor
      from sklearn.impute import SimpleImputer
      from sklearn.preprocessing import StandardScaler
      from sklearn.metrics import mean_absolute_error,mean_squared_error
      from threadpoolctl import threadpool_limits
      samples={s:[] for s in ['train','val','test']};targets={s:[] for s in samples};example=None;station_counts={}
      for code, in db.execute('SELECT code FROM stations ORDER BY code'):
        series=db.execute('SELECT time,SO2,CO,O3,NO2,PM10,PM25 FROM measurements WHERE station=? ORDER BY time',(code,)).fetchall()
        station_counts[code]=len(series)
        for i in range(24,len(series)-1):
            x=features(series,i)
            if x is None:continue
            target_time=series[i+1][0]
            split='train' if target_time<'2026-03-24T00:00' else 'val' if target_time<'2026-04-01T00:00' else 'test'
            samples[split].append([np.nan if v is None else v for v in x]);targets[split].append(series[i+1][2])
            if split=='test' and example is None:example=dict(station=code,input_time=series[i][0],target_time=target_time,features=x,actual_next_co_ppm=series[i+1][2])
      update(phase='training',split_counts={s:len(v) for s,v in samples.items()})
      x={s:np.asarray(v,dtype=np.float32) for s,v in samples.items()};y={s:np.asarray(v,dtype=np.float32) for s,v in targets.items()};del samples,targets
      if min(len(v) for v in y.values())<100:raise ValueError('Insufficient temporal folds')
      imputer=SimpleImputer(strategy='median').fit(x['train']);xi={s:imputer.transform(v) for s,v in x.items()}
      scaler=StandardScaler().fit(xi['train']);xs={s:scaler.transform(v) for s,v in xi.items()}
      mean=float(y['train'].mean());scale=max(float(y['train'].std()),1e-6)
      def metric(truth,pred):return dict(mae_ppm=float(mean_absolute_error(truth,pred)),rmse_ppm=float(math.sqrt(mean_squared_error(truth,pred))))
      persistence=metric(y['val'],x['val'][:,0]);history=[];best=None;best_score=math.inf
      with threadpool_limits(limits=2):
        network=MLPRegressor(hidden_layer_sizes=(64,32),batch_size=1024,learning_rate_init=.0005,alpha=.01,random_state=42)
        for epoch in range(1,21):
            network.partial_fit(xs['train'],(y['train']-mean)/scale)
            score=metric(y['val'],np.maximum(0,network.predict(xs['val'])*scale+mean));history.append(dict(epoch=epoch,**score))
            if score['mae_ppm']<best_score:best_score=score['mae_ppm'];best=copy.deepcopy(network);best_epoch=epoch
            update(phase='training_mlp',epoch=epoch,validation_mae_ppm=score['mae_ppm'])
            if epoch-best_epoch>=4:break
        update(phase='training_boosting')
        boosting=HistGradientBoostingRegressor(max_iter=100,max_leaf_nodes=15,l2_regularization=1,early_stopping=False,random_state=42).fit(xi['train'],y['train'])
        boost=metric(y['val'],np.maximum(0,boosting.predict(xi['val'])))
        selected='neural_mlp' if best_score<boost['mae_ppm'] else 'histogram_boosting';model=best if selected=='neural_mlp' else boosting
        predicted=np.maximum(0,model.predict(xs['test'])*scale+mean if selected=='neural_mlp' else model.predict(xi['test']))
        neural_val=metric(y['val'],np.maximum(0,best.predict(xs['val'])*scale+mean))
      report=dict(task='next_hour_ambient_CO_forecast',selected_model=selected,
        validation=dict(persistence=persistence,neural_mlp=neural_val,histogram_boosting=boost),
        selected_test=metric(y['test'],predicted),test_persistence=metric(y['test'],x['test'][:,0]),
        validation_baseline_exceeded=min(best_score,boost['mae_ppm'])<persistence['mae_ppm'],
        split_counts={s:len(v) for s,v in y.items()},stations=len(station_counts),source_counts=dict(counts),missing=dict(missing),
        temporal_split='Target timestamps: before March 24 train; March 24-31 validation; April onward test',
        features=FEATURES,history=history,operational_use=False,wildfire_classifier=False,
        units=dict(SO2='ppm',CO='ppm',O3='ppm',NO2='ppm',PM10='ug/m3',PM25='ug/m3'),
        source_archive=str(args.source),source_sha256=hashlib.sha256(args.source.read_bytes()).hexdigest(),workbooks=source_info,
        timestamp_interpretation='YYYYMMDDHH, HH=24 rolls to next-day 00:00; Korean local time',
        limitations=['Ambient stations, not near-fire H2/VOC sensors','No incident labels; no wildfire sensitivity/specificity claim',
        'Temporal holdout at same station population; not station-external evaluation','2026 monthly provisional/confirmed source status requires provenance review'],
        reference_urls=['https://www.airkorea.or.kr/web/last_amb_hour_data','https://m.airkorea.or.kr/info/standard/in'])
      joblib.dump(dict(model=model,imputer=imputer,scaler=scaler,target_mean=mean,target_scale=scale,
          selected_model=selected,features=FEATURES,validation_baseline_exceeded=report['validation_baseline_exceeded']),root/'co_forecast.joblib')
      report['model_sha256']=hashlib.sha256((root/'co_forecast.joblib').read_bytes()).hexdigest()
      write_status(root/'comparison.json',report);write_status(root/'example.json',example)
      update(phase='completed',selected_model=selected,validation_baseline_exceeded=report['validation_baseline_exceeded'])
      print(json.dumps(dict(selected_model=selected,counts=dict(counts),split_counts=report['split_counts'])))
    except BaseException as exc:
      update(phase='failed',error=str(exc));raise


if __name__=='__main__':main()
