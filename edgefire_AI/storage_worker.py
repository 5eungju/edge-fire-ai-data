"""Poll a shared SQLite queue, infer locally, and atomically publish results."""
import argparse
import hashlib
import io
import json
import logging
from pathlib import Path
import signal
import threading
import uuid

from PIL import Image
from storage_queue import StorageQueue

LOG = logging.getLogger(__name__)


class VisionPredictor:
    def __init__(self, weights, model_id):
        import torch
        from ultralytics import YOLO
        torch.set_num_threads(1)
        self.model = YOLO(str(weights))
        from ultralytics.nn.tasks import SegmentationModel
        if not isinstance(self.model.model, SegmentationModel):
            raise ValueError('Expected a segmentation model checkpoint')
        # Custom training checkpoints inherit DEFAULT_CFG task metadata. Select
        # the segmentation predictor from the actual architecture explicitly.
        self.model.task = 'segment'
        self.model.model.task = 'segment'
        self.model.model.args['task'] = 'segment'
        self.model.overrides['task'] = 'segment'
        self.sha = hashlib.sha256(Path(weights).read_bytes()).hexdigest()
        self.model_id = model_id

    def __call__(self, raw):
        with Image.open(io.BytesIO(raw)) as source:
            if source.width * source.height > 30_000_000 or source.getexif().get(274, 1) != 1:
                raise ValueError('이미지 크기 또는 방향을 확인해 주세요.')
            image = source.convert('RGB')
        prediction = self.model.predict(image, device='cpu', imgsz=512, conf=.25, max_det=100, verbose=False)[0]
        detections = []
        for index, box in enumerate(prediction.boxes):
            cid = int(box.cls.item())
            polygon = prediction.masks.xyn[index].tolist() if prediction.masks is not None else []
            detections.append(dict(class_id=cid, class_name=prediction.names[cid], score=round(float(box.conf.item()), 5),
                                   bbox_xyxy=box.xyxy[0].tolist(), polygon_normalized=polygon))
        annotated = Image.fromarray(prediction.plot()[:, :, ::-1])
        output = io.BytesIO()
        annotated.save(output, format='JPEG', quality=95)
        result = dict(status='RESEARCH_RESULT', model_id=self.model_id, model_sha256=self.sha,
                      model_status='training_snapshot_not_validated', width=image.width, height=image.height,
                      detections=detections, operational_use=False,
                      notice='학습 중 모델의 연동 시험 결과입니다. 분류 점수는 산불 발생 확률이나 안전 판정이 아닙니다.')
        return result, output.getvalue()


def process_one(queue, infer, lease_seconds=120):
    job = queue.claim(lease_seconds=lease_seconds)
    if job is None:
        return False
    stop_renewal = threading.Event()
    def renew():
        while not stop_renewal.wait(max(.05, min(10, lease_seconds / 3))):
            if not queue.renew(job['id'], job['claim_token'], lease_seconds):
                return
    heartbeat = threading.Thread(target=renew, daemon=True)
    heartbeat.start()
    try:
        raw = queue.path('objects/' + job['object_id']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != job['sha256']:
            raise ValueError('저장된 입력 이미지의 SHA256이 일치하지 않습니다.')
        result, annotated = infer(raw)
        if not queue.complete(job, result, annotated):
            LOG.warning('Lost job lease; artifacts not published: %s', job['id'])
    except Exception as exc:
        queue.fail(job, exc)
        LOG.exception('Image job failed: %s', job['id'])
    finally:
        stop_renewal.set()
        heartbeat.join(timeout=2)
    return True


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--model-id', required=True)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    queue = StorageQueue(args.root)
    worker_id = 'WORKER_' + uuid.uuid4().hex
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    infer = VisionPredictor(args.model, args.model_id)
    assessment_queue = StorageQueue(args.root / 'assessments')
    from multi_model_storage import infer_assessment
    def heartbeat():
        while not stop.is_set():
            queue.worker_status(worker_id, args.model_id)
            stop.wait(5)
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        while not stop.is_set() and not (queue.root / 'worker.STOP').exists():
            worked = process_one(queue, infer)
            assessment_worked = process_one(assessment_queue, lambda raw: infer_assessment(args.root, raw))
            if args.once:
                break
            if not worked and not assessment_worked:
                stop.wait(.5)
    finally:
        stop.set()
        thread.join(timeout=6)
        queue.worker_status(worker_id, args.model_id, 'STOPPED')


if __name__ == '__main__':
    main()
