"""학습 완료 가중치만 사용하는 로컬 영상 추론 경로."""
import io, os, threading, hashlib
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException
from PIL import Image, UnidentifiedImageError

router = APIRouter(prefix='/api/v1/vision')
LOCK = threading.Lock()
MODEL = None
MODEL_SHA = None
MAX_BYTES = 10 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 30_000_000

def checkpoint():
    return Path(os.environ.get('VISION_MODEL_PATH', 'model_vision.pt'))

@router.get('/info')
def info():
    return {'available': checkpoint().is_file(), 'model_id': os.environ.get('VISION_MODEL_ID', 'vision-pilot-v1'),
            'task': 'smoke_fire_instance_segmentation', 'operational_use': False}

@router.post('/analyze')
def analyze(image: UploadFile = File(...)):
    global MODEL, MODEL_SHA
    raw = image.file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, '이미지는 10MiB 이하로 보내 주세요.')
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            if opened.width * opened.height > 30_000_000:
                raise ValueError('too many pixels')
            if opened.getexif().get(274, 1) != 1:
                raise ValueError('이미지 방향을 바로잡아 저장한 뒤 업로드해 주세요.')
            opened.load()
            rgb = opened.convert('RGB')
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, str(exc) or '지원하지 않는 이미지') from exc
    with LOCK:
        if not checkpoint().is_file():
            raise HTTPException(503, '학습 완료 모델 경로를 설정해 주세요.')
        if MODEL is None:
            import torch
            from ultralytics import YOLO
            torch.set_num_threads(1)
            MODEL = YOLO(str(checkpoint()))
            MODEL_SHA = hashlib.sha256(checkpoint().read_bytes()).hexdigest()
        prediction = MODEL.predict(rgb, device='cpu', imgsz=512, conf=0.25, max_det=100, verbose=False)[0]
        detections = []
        for index, box in enumerate(prediction.boxes):
            cid = int(box.cls.item())
            polygon = prediction.masks.xyn[index].tolist() if prediction.masks is not None else []
            detections.append({'class_id': cid, 'class_name': prediction.names[cid],
                               'score': round(float(box.conf.item()), 5),
                               'bbox_xyxy': box.xyxy[0].tolist(), 'polygon_normalized': polygon})
    return {'status': 'RESEARCH_RESULT', 'model_id': os.environ.get('VISION_MODEL_ID', 'vision-pilot-v1'),
            'model_sha256': MODEL_SHA, 'width': rgb.width, 'height': rgb.height,
            'detections': detections, 'operational_use': False,
            'notice': '영상 객체 분류 점수입니다. 산불 발생 확률이나 안전 판정이 아닙니다.'}
