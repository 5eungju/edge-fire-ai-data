"""카메라 그룹으로 분리한 산불 영상 표본의 분할 모델 학습."""
import argparse, json, os, time, traceback, hashlib
from pathlib import Path
from datetime import datetime, timezone
from status_io import write_status
from training_policy import validate_data_policy, validate_generic_pretrained

def main():
 parser=argparse.ArgumentParser()
 parser.add_argument('--data',default='E:/AI_Work/edgefire_vision/pilot_yolo_seg/dataset.yaml')
 parser.add_argument('--project',default='E:/AI_Work/edgefire_vision/training')
 parser.add_argument('--name',default='yolo26n_seg_pilot_01')
 parser.add_argument('--epochs',type=int,default=10)
 parser.add_argument('--eval-split',choices=['val','test'],default='test')
 parser.add_argument('--benchmark-validation-count',type=int,default=0)
 parser.add_argument('--imgsz',type=int,default=416)
 parser.add_argument('--batch',type=int,default=4)
 parser.add_argument('--threads',type=int,default=6)
 parser.add_argument('--weights',default='yolo26n-seg.pt')
 parser.add_argument('--baseline-metrics',type=Path)
 parser.add_argument('--comparison-output',type=Path)
 parser.add_argument('--resume',type=Path)
 parser.add_argument('--status',default='E:/AI_Work/edgefire_vision/training_status.json')
 args=parser.parse_args()
 os.environ['OMP_NUM_THREADS']=str(args.threads)
 os.environ['MKL_NUM_THREADS']=str(args.threads)
 os.environ['YOLO_AUTOINSTALL']='false'
 status_path=Path(args.status);status_path.parent.mkdir(parents=True,exist_ok=True)
 state={'training_script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'pid':os.getpid(),'phase':'initializing','started_utc':datetime.now(timezone.utc).isoformat(),'config':vars(args)|{'resume':str(args.resume) if args.resume else None},'operationally_validated':False,'dataset_scope':'Camera-group split subset; not the entire 630000-image dataset'}
 def update(**values):
  state.update(values);state['updated_utc']=datetime.now(timezone.utc).isoformat()
  write_status(status_path,state)
 update()
 try:
  import torch, ultralytics
  from ultralytics import YOLO, settings
  torch.set_num_threads(args.threads)
  settings.update({k:False for k in ['sync','wandb','mlflow','comet','clearml'] if k in settings})
  data=Path(args.data).resolve()
  if not data.is_file():raise FileNotFoundError(data)
  manifest=data.parent.parent/'pilot_manifest.jsonl';manifest_records=[json.loads(line) for line in manifest.read_text(encoding='utf8').splitlines()];groups={s:set() for s in ['train','val','test']};hashes=set();counts={s:0 for s in groups}
  for row in manifest_records:
   groups[row['split']].add(row['group_id']);counts[row['split']]+=1
   if row['raw_sha256'] in hashes:raise ValueError('Duplicate raw image')
   hashes.add(row['raw_sha256'])
  for a,b in [('train','val'),('train','test'),('val','test')]:
   if groups[a]&groups[b]:raise ValueError('Camera group leakage')
  if any(v==0 for v in counts.values()):raise ValueError('Empty split')
  policy=validate_data_policy(data,manifest_records)
  if policy['spatial'] and not args.resume:validate_generic_pretrained(args.weights,Path(__file__).with_name('generic_pretrained_manifest.json'))
  update(phase='loading_pretrained_model',split_counts=counts,torch_version=torch.__version__,ultralytics_version=ultralytics.__version__,device='cpu',dataset_manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest())
  model=YOLO(str(args.resume) if args.resume else args.weights)
  if policy['spatial'] and args.resume:
   if Path(model.ckpt['train_args']['data']).resolve()!=data:raise ValueError('Resume checkpoint uses different data')
   provenance=json.loads((args.resume.parent.parent/'training_data_provenance.json').read_text(encoding='utf8'))
   if provenance['manifest_sha256']!=policy['manifest_sha256']:raise ValueError('Resume dataset changed')
  batch_number=[0];epoch_started=[time.monotonic()]
  def epoch_start(trainer):
   torch.set_num_threads(args.threads)
   if policy['spatial']:
    provenance_path=Path(trainer.save_dir)/'training_data_provenance.json'
    if not provenance_path.exists():provenance_path.write_text(json.dumps(policy,indent=2),encoding='utf8')
   batch_number[0]=0;epoch_started[0]=time.monotonic();update(phase='training',epoch=int(trainer.epoch)+1,epochs=int(trainer.epochs),batches_completed_in_epoch=0,run_directory=str(trainer.save_dir))
  def batch_end(trainer):
   batch_number[0]+=1
   if batch_number[0]==1 or batch_number[0]%10==0:
    update(phase='training',epoch=int(trainer.epoch)+1,batches_completed_in_epoch=batch_number[0],epoch_elapsed_seconds=round(time.monotonic()-epoch_started[0],1),loss={str(k):float(v) for k,v in trainer.tloss.items()} if isinstance(trainer.tloss,dict) else [float(v) for v in trainer.tloss.detach().cpu().flatten()])
  def epoch_end(trainer):
   update(phase='epoch_saved',completed_epochs=min(int(trainer.epoch)+1,int(trainer.epochs)),validation_metrics={k:float(v) for k,v in trainer.metrics.items()},last_checkpoint=str(trainer.last),best_checkpoint=str(trainer.best))
  model.add_callback('on_train_epoch_start',epoch_start);model.add_callback('on_train_batch_end',batch_end);model.add_callback('on_fit_epoch_end',epoch_end)
  kwargs={'resume':True} if args.resume else dict(data=str(data),epochs=args.epochs,imgsz=args.imgsz,batch=args.batch,device='cpu',workers=0,cache=False,amp=False,seed=42,deterministic=True,optimizer='AdamW',lr0=0.001,lrf=0.01,weight_decay=0.0005,warmup_bias_lr=0.0,patience=5,save=True,save_period=1,project=str(Path(args.project).resolve()),name=args.name,exist_ok=False,plots=True,verbose=False,close_mosaic=2,mosaic=0.5,mixup=0.0,degrees=0.0,flipud=0.0,fliplr=0.5)
  model.train(**kwargs)
  best=Path(model.trainer.best)
  if not best.is_file():raise RuntimeError('Training completed without best checkpoint')
  update(phase='evaluating_'+args.eval_split,best_checkpoint=str(best))
  evaluator=YOLO(str(best));metrics=evaluator.val(data=str(data),split=args.eval_split,imgsz=args.imgsz,batch=args.batch,device='cpu',workers=0,plots=True,max_det=100,project=str(Path(args.project).resolve()),name=args.name+'_'+args.eval_split+'_evaluation')
  result={'status':'completed','model':str(best),'split':args.eval_split,'image_count':counts[args.eval_split],'evaluation_ids_sha256':hashlib.sha256('\n'.join(sorted(row['id'] for row in manifest_records if row['split']==args.eval_split)).encode()).hexdigest(),'model_sha256':hashlib.sha256(best.read_bytes()).hexdigest(),'metrics':{k:float(v) for k,v in metrics.results_dict.items()},'per_class':metrics.summary(),'operationally_validated':False,'limitations':['Pilot sample only; balanced collection sampling differs from deployment distribution.','Smoke/fire recognition is not a calibrated pre-ignition wildfire probability.','See preprocessing manifest for the camera/site grouping policy.','Small distant smoke/flames require separate size-specific evaluation.','Validation is used for model selection; independent test evaluation requires a finalized choice.']}
  import numpy as np
  mask=metrics.seg;index=int(np.argmin(np.abs(mask.px-.25)))
  result['operating_point']={'confidence':.25,'max_detections':100,'per_class':[{'class_name':metrics.names[int(cid)],'precision':float(mask.p_curve[i,index]),'recall':float(mask.r_curve[i,index]),'f1':float(mask.f1_curve[i,index])} for i,cid in enumerate(mask.ap_class_index)]}
  result['training_script_sha256']=state['training_script_sha256']
  result['library_versions']={'torch':torch.__version__,'ultralytics':ultralytics.__version__}
  result['optimizer_configuration']={key:getattr(model.trainer.args,key) for key in ['optimizer','lr0','weight_decay','warmup_bias_lr','warmup_epochs','batch','seed']}
  result['parameters']=sum(p.numel() for p in evaluator.model.parameters())
  if args.benchmark_validation_count:
   torch.set_num_threads(1)
   paths=sorted((data.parent/'images/val').glob('*.jpg'))[:args.benchmark_validation_count]
   if not paths:raise ValueError('No validation images for benchmark')
   for _ in range(2):evaluator.predict(str(paths[0]),imgsz=args.imgsz,device='cpu',conf=.25,max_det=100,verbose=False)
   timings=[]
   for path in paths:
    started=time.perf_counter();pred=evaluator.predict(str(path),imgsz=args.imgsz,device='cpu',conf=.25,max_det=100,verbose=False)[0]
    if pred.masks is not None:_=pred.masks.xyn
    timings.append((time.perf_counter()-started)*1000)
   result['benchmark']={'p50_ms':float(np.percentile(timings,50)),'p95_ms':float(np.percentile(timings,95)),'images':len(paths),'threads':1,'scope':'Local file load, model prediction and polygon conversion; excludes HTTP/queue latency.'}
  (Path(model.trainer.save_dir)/('heldout_test_metrics.json' if args.eval_split=='test' else 'validation_metrics.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf8')
  if args.baseline_metrics:
   baseline=json.loads(args.baseline_metrics.read_text(encoding='utf8'))
   comparison={'baseline_model':baseline['model'],'candidate_model':result['model'],'evaluation':'Same previously inspected test; exploratory comparison, not a fresh blind test.','metrics':{k:{'baseline':baseline['metrics'][k],'candidate':v,'difference':v-baseline['metrics'][k]} for k,v in result['metrics'].items() if k in baseline['metrics']},'per_class':result['per_class'],'operationally_validated':False}
   comparison_path=args.comparison_output or Path(model.trainer.save_dir)/'model_comparison.json'
   comparison_path.parent.mkdir(parents=True,exist_ok=True);comparison_path.write_text(json.dumps(comparison,ensure_ascii=False,indent=2),encoding='utf8')
  update(phase='completed',result=result)
 except BaseException as exc:
  update(phase='interrupted' if isinstance(exc,KeyboardInterrupt) else 'failed',error=str(exc),traceback=traceback.format_exc());raise
if __name__=='__main__':main()
