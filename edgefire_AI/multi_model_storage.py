"""Trusted local research models, joined through storage, with missing-input abstention."""
import hashlib
import io
import json
import math
from pathlib import Path

from PIL import Image
from storage_queue import StorageQueue


def validate_request(payload):
    allowed={'vision_job_id','chemical_cid','temperature_c','response_features','reference_case_id'}
    if not isinstance(payload,dict) or set(payload)-allowed:raise ValueError('Unknown assessment fields')
    if len(json.dumps(payload,ensure_ascii=False))>50000:raise ValueError('Assessment input too large')
    job=payload.get('vision_job_id')
    if job is not None:
        import re
        if not isinstance(job,str) or not re.fullmatch(r'JOB_[a-f0-9]{32}',job):raise ValueError('Invalid image job ID')
    cid=payload.get('chemical_cid')
    if cid is not None and (not isinstance(cid,str) or not cid.isdigit() or len(cid)>15):raise ValueError('CID must be digits')
    features=payload.get('response_features',{})
    if not isinstance(features,dict) or len(features)>100:raise ValueError('Invalid response features')
    for key,value in features.items():
        if not isinstance(key,str) or isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
            raise ValueError('Response inputs must be finite numbers')
    temp=payload.get('temperature_c',25)
    if isinstance(temp,bool) or not isinstance(temp,(int,float)) or not math.isfinite(temp) or not -100<=temp<=1000:
        raise ValueError('Invalid temperature')
    if payload.get('reference_case_id') is not None and (not isinstance(payload['reference_case_id'],str) or len(payload['reference_case_id'])>150):
        raise ValueError('Invalid reference case ID')
    if payload.get('reference_case_id') and features:raise ValueError('Do not mix a historical case with supplied context')
    return payload


def registry(storage):
    path=Path(storage)/'models/multi_model_registry.json'
    if not path.exists():return None
    item=json.loads(path.read_text(encoding='utf-8'))
    root=Path(item['root']).resolve()
    if root.drive.upper()!='C:' or not root.is_dir():raise ValueError('Trusted model registry must point to C:')
    for relative,digest in item['sha256'].items():
        target=(root/relative).resolve()
        if not target.is_relative_to(root):raise ValueError('Model registry path escapes root')
        if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise ValueError('Registered model changed: '+relative)
    return item


def model_status(storage):
    item=registry(storage)
    if item is None:return dict(status='TRAINING_OR_NOT_REGISTERED',operational_use=False)
    root=Path(item['root'])
    chemical=json.loads((root/'chemical/comparison.json').read_text(encoding='utf-8'))
    response=json.loads((root/'response_models/comparison.json').read_text(encoding='utf-8'))
    return dict(status='RESEARCH_MODELS_REGISTERED',model_version=item['version'],operational_use=False,
        chemical={k:dict(selected_model=v['selected_model'],validation_baseline_exceeded=v['validation_baseline_exceeded'],
            test_mae=v['test_mae'],target_transform=v['target_transform'],units_verified=False) for k,v in chemical.items()},
        response=dict(selected_model=response['selected_model'],validation_baseline_exceeded=response['validation_baseline_exceeded'],
            validation_macro_f1=response['validation'][response['selected_model']]['macro_f1'],
            majority_validation_macro_f1=response['validation']['majority_baseline']['macro_f1'],
            scope='Dataset-annotated risk during an existing fire; not ignition probability',
            test_is_retrospective=True),connection_type='independent models sharing storage, not a learned multimodal fusion')


def reference_examples(storage):
    item=registry(storage)
    if not item:return dict(cases=[],chemical_cids=[])
    root=Path(item['root']);case=json.loads((root/'response_cases.json').read_text(encoding='utf-8'))['cases']
    catalog=json.loads((root/'chemical/catalog.json').read_text(encoding='utf-8'))['records']
    from train_three_dataset_extensions import split_molecule
    cids=[cid for cid,r in catalog.items() if split_molecule(r['smiles'])=='train' and r['measurements'].get('flash_point')]
    return dict(cases=[dict(id=r['id'],event_id=r['event_id']) for r in case[:5]],chemical_cids=cids[:5],
        scope='Training reference examples only; not held-out performance evidence')


def infer_assessment(storage,raw):
    import numpy as np
    import joblib
    payload=validate_request(json.loads(raw));item=registry(storage)
    if item is None:raise ValueError('Research models have not been registered yet')
    root=Path(item['root']);answer=dict(operational_use=False,model_version=item['version'],
        connection_type='independent models sharing storage, not a learned fusion',
        gas=dict(status='NO_SENSOR_DATA'),thermal=dict(status='NO_THERMAL_DATA'))
    if payload.get('vision_job_id'):
        image=StorageQueue(storage).get(payload['vision_job_id'])
        if image['status']!='COMPLETED':raise ValueError('Image analysis must finish first')
        answer['vision']=dict(job_id=image['id'],model_id=image['result']['model_id'],
            detections=image['result']['detections'],notice='Detection score is not ignition probability')
    cases=json.loads((root/'response_cases.json').read_text(encoding='utf-8'))
    features=payload.get('response_features',{})
    reference=payload.get('reference_case_id')
    if reference:
        case=next((r for r in cases['cases'] if r['id']==reference),None)
        if case is None:raise ValueError('Reference case not found')
        features=case['features'];answer['input_kind']='historical_training_case'
    else:answer['input_kind']='user_supplied_context'
    report=json.loads((root/'response_models/comparison.json').read_text(encoding='utf-8'))
    names=report['feature_names'];unknown=set(features)-set(names)
    if unknown:raise ValueError('Unknown response feature names')
    missing=[k for k in names if k not in features]
    if missing:
        answer['response']=dict(status='INSUFFICIENT_INPUT',missing_features=missing,
            notice='No gas, terrain, fire state or social inputs are invented from an image')
    elif not report['validation_baseline_exceeded']:
        answer['response']=dict(status='REJECTED_FAILED_VALIDATION_BASELINE')
    else:
        values=np.array([[features[k] for k in names]],dtype=np.float32)
        if report['selected_model']=='histogram_boosting':
            model=joblib.load(root/'response_models/response_hgb.joblib');index=int(model.predict(values)[0])
        else:
            import torch
            torch.set_num_threads(1)
            checkpoint=torch.load(root/'response_models/response_mlp.pt',map_location='cpu',weights_only=True)
            dims=checkpoint['architecture']
            model=torch.nn.Sequential(torch.nn.Linear(dims[0],dims[1]),torch.nn.SiLU(),torch.nn.Dropout(.15),
                torch.nn.Linear(dims[1],dims[2]),torch.nn.SiLU(),torch.nn.Dropout(.15),torch.nn.Linear(dims[2],dims[3]))
            model.load_state_dict(checkpoint['state_dict']);model.eval()
            with torch.inference_mode():
                index=int(model(torch.tensor((values-np.array(checkpoint['mean']))/np.array(checkpoint['scale']),dtype=torch.float32)).argmax(1)[0])
        answer['response']=dict(status='RESEARCH_ANNOTATION_PREDICTION',annotated_risk=report['classes'][index],
            selected_model=report['selected_model'],notice='Not a live safety judgment or ignition forecast')
    if features and not missing:
        matrix=np.array([[r['features'][k] for k in names] for r in cases['cases']],dtype=np.float32)
        scale=matrix.std(axis=0);scale[scale<1e-6]=1
        distances=np.mean(((matrix-np.array([features[k] for k in names]))/scale)**2,axis=1)
        selected=np.argsort(distances)[:3]
        answer['historical_references']=[dict(id=cases['cases'][i]['id'],event_id=cases['cases'][i]['event_id'],
            recommendation=cases['cases'][i]['historical_recommendation'],distance=float(distances[i]),
            source=cases['cases'][i]['label_archive'],member=cases['cases'][i]['label_member'],
            notice='Quoted historical annotation; not an instruction for the current location') for i in selected]
    cid=payload.get('chemical_cid')
    if not cid:answer['chemical']=dict(status='NO_MATERIAL_ID',notice='An image cannot identify chemical composition')
    else:
        catalog=json.loads((root/'chemical/catalog.json').read_text(encoding='utf-8'))['records'];record=catalog.get(cid)
        if not record:raise ValueError('Chemical CID not found')
        predictions={}
        for task in ['flash_point','heat_of_combustion','vapor_pressure']:
            bundle=joblib.load(root/'chemical'/(task+'.joblib'))
            if not bundle['validation_baseline_exceeded']:
                predictions[task]=dict(status='REJECTED_FAILED_VALIDATION_BASELINE');continue
            x=[[payload.get('temperature_c',25) if k=='temperature_c' else record['descriptors'].get(k) for k in bundle['features']]]
            values=bundle['imputer'].transform(np.array([[np.nan if v is None else v for v in x[0]]]))
            if bundle['selected_model']=='neural_mlp':
                value=float(bundle['model'].predict(bundle['scaler'].transform(values))[0])*bundle['target_scale']+bundle['target_mean']
            else:value=float(bundle['model'].predict(values)[0])
            predictions[task]=dict(value=value,target_transform=bundle['target_transform'],units_verified=False,
                selected_model=bundle['selected_model'])
        answer['chemical']=dict(status='RESEARCH_PROPERTY_ESTIMATE',cid=cid,name=record['name'],predictions=predictions,
            notice='Native source units/log targets need review; these are not gas measurements or a hazard verdict')
    image=Image.new('RGB',(32,32),'black');stream=io.BytesIO();image.save(stream,format='JPEG')
    return answer,stream.getvalue()
