"""시험셋을 쓰지 않고 검증셋에서 모델 점수 임계값의 영향을 조사합니다."""
import os
os.environ['OMP_NUM_THREADS']='1';os.environ['MKL_NUM_THREADS']='1';os.environ['YOLO_AUTOINSTALL']='false'
import argparse,json,hashlib
from pathlib import Path
import numpy as np

def main():
 p=argparse.ArgumentParser();p.add_argument('--weights',default='E:/AI_Work/edgefire_vision/training/yolo26n_seg_pilot_01-2/weights/best.pt');p.add_argument('--data',default='E:/AI_Work/edgefire_vision/pilot_yolo_seg/dataset.yaml');p.add_argument('--output',default='E:/AI_Work/edgefire_vision/calibration_v1.json');a=p.parse_args()
 import torch
 from ultralytics import YOLO,settings
 settings.update({k:False for k in ['sync','wandb','mlflow','comet','clearml'] if k in settings});torch.set_num_threads(1)
 model=YOLO(a.weights);result=model.val(data=a.data,split='val',imgsz=512,batch=4,device='cpu',workers=0,plots=False,verbose=False,conf=.001,max_det=100,project=str(Path(a.output).parent/'calibration'),name='validation_only')
 metric=result.seg;classes=[int(v) for v in metric.ap_class_index];hazard=[i for i,c in enumerate(classes) if c in [0,1,2]];grid=[]
 for threshold in [.05,.075,.1,.125,.15,.2,.25,.35,.5]:
  index=int(np.argmin(np.abs(metric.px-threshold)));precision=np.asarray(metric.p_curve)[:,index];recall=np.asarray(metric.r_curve)[:,index];f1=np.asarray(metric.f1_curve)[:,index]
  grid.append({'threshold':threshold,'macro_mask_f1':float(f1.mean()),'hazard_mask_precision':float(precision[hazard].mean()),'hazard_mask_recall':float(recall[hazard].mean()),'per_class':[{'name':result.names[c],'precision':float(precision[i]),'recall':float(recall[i]),'f1':float(f1[i])} for i,c in enumerate(classes)]})
 eligible=[r for r in grid if r['hazard_mask_precision']>=.2];selected=max(eligible,key=lambda r:r['macro_mask_f1']) if eligible else None;baseline=next(r for r in grid if r['threshold']==.25)
 report={'model_sha256':hashlib.sha256(Path(a.weights).read_bytes()).hexdigest(),'evaluation_split':'validation_only','input_size':512,'max_detections':100,'grid':grid,'default_025':baseline,'candidate':selected,'automatically_applied':False,'operational_use':False,'warning':'Exploratory threshold selection on small camera-ID split validation; not probability calibration, not independent spatial validation. Test data not used.'}
 Path(a.output).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print('CALIBRATION_COMPLETE',json.dumps({'baseline':baseline,'candidate':selected},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
