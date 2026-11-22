"""Train real chemical property targets and expanded incident-disjoint response labels.

All new artifacts stay on C. Existing vision training and source datasets are read-only.
No generated gas data, ignition labels, geographic perimeters or chain-of-thought targets.
"""
import argparse
import copy
import csv
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
import zipfile
from collections import defaultdict, Counter
from pathlib import Path

os.environ['OMP_NUM_THREADS']='2'
os.environ['MKL_NUM_THREADS']='2'
from status_io import write_status


def save(path,value):
    if not write_status(path,value): raise OSError('Cannot save artifact '+str(path))


def number(value):
    try:
        result=float(value)
        return result if math.isfinite(result) else None
    except (TypeError,ValueError):return None


def split_molecule(identity):
    x=int(hashlib.sha256(('chemical-structure-v1/'+identity).encode()).hexdigest()[:8],16)/2**32
    return 'train' if x<.7 else 'val' if x<.85 else 'test'


def chemical(source,root,update):
    import numpy as np
    import joblib
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.neural_network import MLPRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import mean_absolute_error,r2_score
    from threadpoolctl import threadpool_limits
    out=root/'chemical';out.mkdir(exist_ok=True)
    descriptors=['mw','h_donor','h_acceptor','logp','tpsa','aromatic_ring']
    descriptors+=['No_'+name+'_groups' for name in ['alcohol','amide','amine','ester','ether','imide','ketene','ketone','phenol','sulfoxide','sulfone','sulfonamide','sulfate','phosphate','cyano','azide','azo']]
    descriptors+=['No_halogen_atoms']
    tasks={'flash_point':('flash_point_properties','flash_point','fp'),
           'heat_of_combustion':('heat_of_combustion_properties','heat_combustion','heat_comb'),
           'vapor_pressure':('vapor_pressure_properties','vapor_pressure','vp')}
    grouped={t:defaultdict(list) for t in tasks};catalog={};source_rows=0;rejected=Counter();provenance=[]
    archives=[p for p in sorted(source.rglob('*.zip')) if p.name.startswith(('TL_','VL_'))]
    for ai,path in enumerate(archives):
        provenance.append(dict(path=str(path),bytes=path.stat().st_size,mtime_ns=path.stat().st_mtime_ns))
        with zipfile.ZipFile(path) as archive:
            for member in archive.namelist():
                if not member.endswith('.json'):continue
                record=json.loads(archive.read(member));source_rows+=1
                common=record.get('common_properties',{});smiles=common.get('smiles');cid=str(common.get('cid') or '')
                if not smiles or not cid:rejected['missing_structure_or_cid']+=1;continue
                x=[number(common.get(k)) for k in descriptors]
                # Structural text, not CID integers or target-related GHS/property fields.
                identity=smiles
                catalog.setdefault(cid,dict(cid=cid,name=common.get('iupac_name'),smiles=smiles,
                    descriptors=dict(zip(descriptors,x)),measurements={},source=str(path),member=member))
                for task,(section,key,field) in tasks.items():
                    for item in record.get(section,{}).get(key,[]):
                        target=number(item.get(field))
                        if target is None:continue
                        temp=number(item.get('temp_celsius'))
                        if task!='flash_point' and temp is None:
                            rejected[task+'_missing_temperature']+=1;continue
                        if task=='vapor_pressure' and target<=0:
                            rejected['nonpositive_vapor_pressure']+=1;continue
                        transformed=math.log10(target) if task=='vapor_pressure' else target
                        group=(identity,temp if task!='flash_point' else None)
                        grouped[task][group].append(dict(x=x,target=transformed,cid=cid,
                            source=str(path),member=member,datasource=item.get('datasource')))
                        catalog[cid]['measurements'].setdefault(task,[]).append(dict(value=target,
                            temperature_c=temp,datasource=item.get('datasource'),units_verified=False))
        update(phase='extracting_chemical',archive=ai+1,archives=len(archives),label_records=source_rows)
    save(out/'catalog.json',dict(records=catalog,descriptors=descriptors,source_rows=source_rows,
        provenance=provenance,rejected=dict(rejected),units_verified=False))
    reports={}
    with threadpool_limits(limits=2):
      for task,groups in grouped.items():
        rows=[]
        for (identity,temp),members in sorted(groups.items(),key=lambda item:str(item[0])):
            values=np.array([m['target'] for m in members]);representative=members[0]
            rows.append(dict(group=identity,split=split_molecule(identity),cid=representative['cid'],
                x=representative['x']+([] if task=='flash_point' else [temp]),target=float(np.median(values)),
                measurement_count=len(values),measurement_range=float(np.ptp(values))))
        features=descriptors+([] if task=='flash_point' else ['temperature_c'])
        sets={s:[r for r in rows if r['split']==s] for s in ['train','val','test']}
        if min(map(len,sets.values()))<10:raise ValueError('Insufficient molecular groups for '+task)
        for a,b in [('train','val'),('train','test'),('val','test')]:
            if {r['group'] for r in sets[a]} & {r['group'] for r in sets[b]}:raise ValueError('Molecule leakage')
        x={s:np.array([[np.nan if v is None else v for v in r['x']] for r in batch]) for s,batch in sets.items()}
        y={s:np.array([r['target'] for r in batch]) for s,batch in sets.items()}
        imputer=SimpleImputer(strategy='median',keep_empty_features=True).fit(x['train'])
        xi={s:imputer.transform(v) for s,v in x.items()}
        scaler=StandardScaler().fit(xi['train']);xs={s:scaler.transform(v) for s,v in xi.items()}
        mean=float(y['train'].mean());scale=max(float(y['train'].std()),1e-6)
        neural=MLPRegressor(hidden_layer_sizes=(96,48),activation='relu',batch_size=min(256,len(y['train'])),
            learning_rate_init=.001,alpha=.01,random_state=42)
        best=None;best_mae=math.inf;history=[]
        for epoch in range(1,41):
            neural.partial_fit(xs['train'],(y['train']-mean)/scale)
            score=float(mean_absolute_error(y['val'],neural.predict(xs['val'])*scale+mean))
            history.append(dict(epoch=epoch,val_mae=score))
            if score<best_mae:best_mae=score;best=copy.deepcopy(neural);best_epoch=epoch
            update(phase='training_chemical_mlp',task=task,epoch=epoch,val_mae=score)
            if epoch-best_epoch>=6:break
        update(phase='training_chemical_boosting',task=task)
        boosting=HistGradientBoostingRegressor(max_iter=100,max_leaf_nodes=15,l2_regularization=1,
            early_stopping=False,random_state=42).fit(xi['train'],y['train'])
        boost_mae=float(mean_absolute_error(y['val'],boosting.predict(xi['val'])))
        baseline=float(mean_absolute_error(y['val'],np.full(len(y['val']),np.median(y['train']))))
        selected='neural_mlp' if best_mae<boost_mae else 'histogram_boosting'
        chosen=best if selected=='neural_mlp' else boosting
        pred=chosen.predict(xs['test'])*scale+mean if selected=='neural_mlp' else chosen.predict(xi['test'])
        accepted=min(best_mae,boost_mae)<baseline
        model=dict(model=chosen,selected_model=selected,imputer=imputer,scaler=scaler,
            target_mean=mean,target_scale=scale,features=features,task=task,target_transform='log10' if task=='vapor_pressure' else 'identity',
            validation_baseline_exceeded=accepted,operational_use=False,units_verified=False)
        joblib.dump(model,out/(task+'.joblib'))
        reports[task]=dict(split_counts={s:len(v) for s,v in sets.items()},
            validation_mae=dict(median_baseline=baseline,neural_mlp=best_mae,histogram_boosting=boost_mae),
            selected_model=selected,test_mae=float(mean_absolute_error(y['test'],pred)),test_r2=float(r2_score(y['test'],pred)),
            validation_baseline_exceeded=accepted,target_units='source values, units not certified',
            target_transform=model['target_transform'],aggregation='median of source measurements at same structure/temperature',
            history=history,limitations=['Exact SMILES-disjoint, not scaffold-disjoint; aliases may remain',
            'Mixed measurement methods/units require domain review; no gas detection claim'])
        with (out/(task+'_samples.jsonl')).open('w',encoding='utf-8') as stream:
            for row in rows:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
        save(out/'comparison.json',reports)
    return reports


def expanded_response(source,clean,root,update):
    from prepare_response_data import canonical_id
    out=root/'response_data';out.mkdir(exist_ok=True)
    with (clean/'samples.csv').open(encoding='utf-8',newline='') as stream:
        reader=csv.DictReader(stream);old_columns=reader.fieldnames;allowed={r['id']:r for r in reader}
    report=json.loads((clean/'cleaning_report.json').read_text(encoding='utf-8'))
    extras=['Infra_Social.population','Infra_Social.households','Infra_Social.vulnerable',
        'Infra_Social.fire_station_distance','Infra_Social.Important_Infra_distance',
        'occurrence_status.drought_duration_days','occurrence_status.fire_length','occurrence_status.flame_length']
    categories=['fuel_conditions.fuel_type','Infra_Social.road_accessibility','occurrence_status.fire_intensity']
    extra_names=extras+[f'{name}.bucket_{i}' for name in categories for i in range(8)]
    names=report['feature_names']+extra_names
    counts=Counter();zero=Counter();seen=set();event_meta={};train_candidates=[]
    packages=[p for p in sorted(source.rglob('*.zip')) if p.name.startswith(('TS_','VS_'))]
    with (out/'samples.csv').open('w',encoding='utf-8',newline='') as stream:
      writer=csv.DictWriter(stream,fieldnames=old_columns+extra_names);writer.writeheader()
      for zi,path in enumerate(packages):
        with zipfile.ZipFile(path) as archive:
          for member in archive.namelist():
            if not member.endswith('.json'):continue
            identifier=canonical_id(member)
            if identifier not in allowed:continue
            old=allowed.pop(identifier);raw=json.loads(archive.read(member));info=raw['source_data_info'];values={}
            for key in extras:
                section,name=key.split('.');value=number(info.get(section,{}).get(name));values[key]=0.0 if value is None else value
                if value is None:zero[key]+=1
            for key in categories:
                section,name=key.split('.');text=str(info.get(section,{}).get(name) or 'UNKNOWN')
                bucket=int(hashlib.sha256(text.encode()).hexdigest()[:8],16)%8
                values.update({f'{key}.bucket_{i}':int(i==bucket) for i in range(8)})
            values_full={name:float(old[name]) if name in old else values[name] for name in names}
            digest=hashlib.sha256(json.dumps(values_full,sort_keys=True).encode()).hexdigest()
            if digest in seen:raise ValueError('Duplicate extended feature vector needs review')
            seen.add(digest);old['feature_sha256']=digest;writer.writerow(old|values);counts[old['split']]+=1
            fire=raw['raw_data_info']['fire_info']
            event_meta.setdefault(old['event_id'],dict(start_timestamp=fire.get('start_timestamp'),
                final_track_present=bool(fire.get('fire_spread_track')),track_has_per_vertex_timestamps=False))
            if old['split']=='train':
                rank=hashlib.sha256(identifier.encode()).hexdigest()
                train_candidates.append((rank,dict(id=identifier,event_id=old['event_id'],
                    features=values_full,source_archive=str(path),source_member=member,annotated_risk=old['target'])))
        update(phase='extracting_expanded_response',archive=zi+1,archives=len(packages),rows=sum(counts.values()))
    if allowed:raise ValueError('Some previously cleaned source records were not found: '+str(len(allowed)))
    with (out/'samples.csv').open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    report.update(feature_names=names,samples_csv_sha256=digest,accepted=sum(counts.values()),
        added_features=extra_names,expanded_missing_values_zero_filled=dict(zero),
        operationally_validated=False,prior_test_already_evaluated=True)
    report['limitations']+=['Expanded current-fire state/infra features; not pre-ignition forecast',
        'Fire length/intensity/flame length timing and units require review before live deployment',
        'Original test split was evaluated in an earlier experiment; results are retrospective research',
        'Final affected area/end time/spread track/total wildfire duration excluded from features']
    save(out/'cleaning_report.json',report);save(out/'boundary_semantics_audit.json',dict(events=event_meta,
        warning='fire_spread_track is present but has no vertex timestamps; not hourly observed perimeters'))
    # Grounded historical case retrieval: only source-side context is indexed.
    selected=[record for rank,record in sorted(train_candidates,key=lambda item:item[0])[:1500]]
    label_archives={str(p):p for p in source.rglob('*.zip') if p.name.startswith(('TL_','VL_'))}
    by_archive=defaultdict(list)
    for record in selected:by_archive[record['source_archive']].append(record)
    cases=[]
    for sp,records in by_archive.items():
        src=Path(sp);prefix='TL_' if src.name.startswith('TS_') else 'VL_'
        matches=[p for p in label_archives.values() if p.name==prefix+src.name[3:]]
        if len(matches)!=1:raise ValueError('Ambiguous label archive')
        with zipfile.ZipFile(matches[0]) as archive:
            index={canonical_id(n):n for n in archive.namelist() if n.endswith('.json')}
            for record in records:
                label=json.loads(archive.read(index[record['id']]))['labelling_data_info']
                recommendation=label['countermeasures']['immediate_recommendation']
                cases.append(record|dict(question=label.get('query',{}).get('query_text'),
                    historical_recommendation=recommendation,label_archive=str(matches[0]),label_member=index[record['id']]))
    save(root/'response_cases.json',dict(cases=cases,feature_names=names,scope='Historical reference cases only; not current instructions'))
    return out


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--downloads',type=Path,default=Path.home()/'Downloads')
    p.add_argument('--clean-response',type=Path,default=Path('E:/AI_Work/edgefire_response_clean_v1'))
    args=p.parse_args();root=args.output.resolve()
    if root.drive.upper()!='C:':raise ValueError('All new outputs must stay on C:')
    root.mkdir(parents=True,exist_ok=True)
    if (root/'pipeline_status.json').exists():raise FileExistsError('Use a fresh experiment directory')
    state=dict(pid=os.getpid(),started=time.time(),operational_use=False)
    def update(**values):
        state.update(values,updated=time.time());save(root/'pipeline_status.json',state)
    update(phase='starting')
    try:
        chemical(next(args.downloads.glob('57.*')),root,update)
        update(phase='chemical_completed')
        clean=root/'response_original_clean';shutil.copytree(args.clean_response,clean)
        response=expanded_response(next(args.downloads.glob('38.*')),clean,root,update)
        update(phase='training_response_models')
        with (root/'response_training.log').open('w',encoding='utf-8') as log:
            subprocess.run([sys.executable,str(Path(__file__).with_name('train_response_models.py')),
                '--data',str(response),'--output',str(root/'response_models'),'--epochs','20'],
                stdout=log,stderr=subprocess.STDOUT,check=True)
        update(phase='completed',model_root=str(root))
    except BaseException as exc:
        update(phase='failed',error=str(exc));raise


if __name__=='__main__':main()
