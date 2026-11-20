# 산불 영상 데이터 전처리

원본 분할 ZIP을 병합하거나 전체 해제하지 않고 읽습니다. 백엔드와 프론트엔드 변경은 필요하지 않습니다.

실행 환경: Python 3.12, requirements-vision-preprocess.txt.

```powershell
py -m pip install -r requirements-vision-preprocess.txt
py prepare_vision_dataset.py --data-root E:/AI_Data --output E:/AI_Work/edgefire_vision --pilot-count 1800 --max-side 1280
```

전체 압축 목록에서 이미지와 JSON의 상대 경로를 대조하고 SQLite 색인을 만듭니다. 실제 이미지와 JSON 본문의 CRC·크기·좌표 검사는 선택된 표본에 대해서만 수행합니다. 전체 663GiB의 무결성 검사나 모든 라벨의 내용 검사를 완료했다는 의미가 아닙니다.

카메라/배경 식별자를 SHA256으로 고정 분할합니다. 제공된 Training과 Validation을 합친 뒤 다시 나누므로 공식 검증셋의 성능과 직접 비교할 수 없습니다. 동일 카메라 식별자가 학습·검증·시험에 동시에 들어가지 않도록 검사합니다. 실제 장소 식별자 자체가 다르게 부여된 사례나 비슷한 프레임은 별도 검토가 필요합니다.

파일럿은 컬렉션별 균등 표집으로 만들어 원본의 빈도를 재현하지 않습니다. 1800은 목표 수이며 반올림·검증 탈락으로 실제 수가 달라집니다. 이미지 긴 변은 최대 1280픽셀로 줄이고 종횡비를 유지합니다. 원본 JSON도 표본과 함께 보관합니다.

YOLO segmentation 클래스: 0 흑색연기, 1 백색/회색연기, 2 화염, 3 구름, 4 안개/연무, 5 굴뚝연기.

단일 다각형만 변환하며 multipart/RLE/crowd, 잘못된 좌표·치수·파일명은 해당 이미지를 제외하고 quarantine/rejected.jsonl에 기록합니다. 다각형 자기 교차는 검사하지 않습니다. 원본 바이트가 같은 표본은 파일럿 내에서 제외합니다.

출력: vision_index.sqlite, preprocess_summary.json, pilot_manifest.jsonl, pilot_yolo_seg/dataset.yaml, images·labels·annotations_original 폴더, qa 시각 검토 이미지.

출력 디렉터리는 실행별로 새 경로를 사용하세요. 표본 목록이 이미 있으면 덮어쓰기를 차단합니다. 원본 디렉터리 내부 출력은 금지합니다. 원본 파일은 수정하지 않습니다.

이 단계는 학습용 입력 준비입니다. 영상 모델 학습, 산불 발생 확률 예측, 실시간 서비스 성능 검증은 별도 단계입니다.
