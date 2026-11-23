"""Read archived real measurements and predict one-hour CO; no wildfire judgment."""
import hashlib
import json
import math
import sqlite3
from contextlib import closing
from datetime import datetime,timedelta
from pathlib import Path


def status(root):
    p=Path(root)/'status.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {'phase':'not_prepared'}


def stations(root):
    root=Path(root);state=status(root)
    if state['phase']!='completed':return dict(status='PREPARING',phase=state['phase'],stations=[])
    with closing(sqlite3.connect((root/'measurements.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
        rows=db.execute('SELECT code,region,name,network FROM stations ORDER BY region,name').fetchall()
    return dict(status='READY',stations=[dict(code=r[0],region=r[1],name=r[2],network=r[3]) for r in rows],
        scope='2026 January-April archived ambient observations, not live hardware',
        units={'CO':'ppm','SO2':'ppm','O3':'ppm','NO2':'ppm','PM10':'ug/m3','PM25':'ug/m3'},H2_available=False,VOC_available=False)


def series(root,station,end=None):
    root=Path(root)
    if not isinstance(station,str) or not station.isdigit() or len(station)>15:raise ValueError('측정소 코드가 올바르지 않습니다.')
    if status(root)['phase']!='completed':return dict(status='PREPARING',rows=[])
    if end:
        if len(end)!=16:raise ValueError('시각 형식을 확인해 주세요.')
        datetime.strptime(end,'%Y-%m-%dT%H:%M')
    with closing(sqlite3.connect((root/'measurements.sqlite').as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        site=db.execute('SELECT code,region,name,network FROM stations WHERE code=?',(station,)).fetchone()
        if site is None:raise ValueError('등록된 측정소가 없습니다.')
        rows=db.execute('SELECT time,SO2,CO,O3,NO2,PM10,PM25 FROM measurements WHERE station=? AND time<=? ORDER BY time DESC LIMIT 49',
            (station,end or '9999')).fetchall()[::-1]
        report=json.loads((root/'comparison.json').read_text(encoding='utf-8'))
        forecast=dict(status='INSUFFICIENT_CONTIGUOUS_CO_HISTORY')
        if rows:
            from train_air_quality import input_features
            features=input_features([tuple(r) for r in rows],len(rows)-1)
            if features is not None and report['validation_baseline_exceeded']:
                import numpy as np
                import joblib
                model_path=root/'co_forecast.joblib'
                # Early runs may not have included the checksum field; create no silent trust bypass.
                expected=report.get('model_sha256')
                if not expected or hashlib.sha256(model_path.read_bytes()).hexdigest()!=expected:raise ValueError('CO 모델 무결성 확인이 필요합니다.')
                bundle=joblib.load(model_path)
                x=bundle['imputer'].transform([[np.nan if v is None else v for v in features]])
                if bundle['selected_model']=='neural_mlp':pred=float(bundle['model'].predict(bundle['scaler'].transform(x))[0])*bundle['target_scale']+bundle['target_mean']
                else:pred=float(bundle['model'].predict(x)[0])
                forecast=dict(status='RESEARCH_FORECAST',CO_ppm=max(0,pred),input_time=rows[-1]['time'],
                    target_time=(datetime.fromisoformat(rows[-1]['time'])+timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M'),
                    model=report['selected_model'],wildfire_probability=None)
            elif features is not None:forecast=dict(status='REJECTED_FAILED_PERSISTENCE_BASELINE')
    return dict(status='READY',station=dict(site),rows=[dict(r) for r in rows[-24:]],forecast=forecast,
        source='User supplied 2026.zip, hourly ambient measurement archive',H2_available=False,
        note='과거 대기측정 자료·다음 시간 CO 추정입니다. 실시간 장비나 산불 발생 판정이 아닙니다.',
        validation=report['validation'],test=report['selected_test'])
