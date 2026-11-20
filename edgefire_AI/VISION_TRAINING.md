# 산불 영상 1차 학습

이 실행은 전체 원본 63만 장 중 전처리한 1,758장으로 수행하는 파일럿 학습입니다. 연기·화염 등을 영역별로 인식하는 YOLO26n-seg 사전학습 가중치를 미세조정합니다. 발생 이전 산불 확률을 직접 학습한 모델은 아닙니다.

CPU 실행 설정: 6개 연산 스레드 요청(현재 최초 실행은 프레임워크 기본값 8개 적용), 배치 4, 입력 416픽셀, 최대 10 epoch, 검증 성능 개선이 없으면 patience=5 조기 종료. 이미지·마스크에 같은 변환을 적용하며 수평 반전, 크기/이동, 제한된 mosaic 및 색상 증강을 적용합니다. 416픽셀은 CPU 실험용이며 먼 거리의 작은 연기·불꽃 인식에 불리할 수 있습니다.

학습 1,197장, 검증 264장, 시험 297장. 카메라 식별자 중복과 원본 바이트 중복을 학습 시작 전에 다시 검사합니다. 검증 지표로 가중치를 선택하고 학습 완료 후에만 시험셋을 평가합니다. 카메라 식별자 분리를 위해 제공된 Training/Validation을 재구성했으므로 공식 분할 성능과 직접 비교할 수 없습니다.

```powershell
py -m pip install -r requirements-vision-training.txt
py train_vision.py
```

출력 기본 경로: E:/AI_Work/edgefire_vision/training/yolo26n_seg_pilot_01-2 (최초 실행의 실제 경로)
- weights/last.pt: 중단 후 재개할 체크포인트
- weights/best.pt: 검증 성능에 따라 선택한 가중치
- results.csv: epoch별 학습·검증 지표
- heldout_test_metrics.json: 학습 완료 후 시험셋 지표
- E:/AI_Work/edgefire_vision/training_status.json: 기본 상태 파일 (--status로 변경 가능)

재개:
```powershell
py train_vision.py --resume E:/AI_Work/edgefire_vision/training/yolo26n_seg_pilot_01/weights/last.pt
```

전체 학습 전 추가 전처리: 전체 JSON 본문과 마스크 품질 검사, 연속 프레임의 시간 간격 샘플링 및 유사 영상 중복 조사, 실제 장소가 다른 카메라 ID로 반복되는지 검토, 실제/합성 데이터별 성능 평가, 클래스·객체 크기 불균형 분석, 작은 연기용 해상도/타일링 검토. 밝기·흐림 등은 연기 및 안개와 관계가 있으므로 일괄 삭제하지 말고 표시 후 검토합니다. 원본 이미지를 임의로 선명하게 만들거나 마스크를 생성하지 않습니다.

공식 참고: https://docs.ultralytics.com/tasks/segment/ 및 https://docs.ultralytics.com/modes/train/

전체 JSON 검사 실행: `py audit_vision_labels.py`. 진행 상황은 E:/AI_Work/edgefire_vision/full_label_audit/status.json, 최종 결과는 summary.json, 검토 대상은 issues.jsonl에 저장합니다. 검사로 발견한 원본 파일은 삭제하지 않습니다.
