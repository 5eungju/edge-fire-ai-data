# EDGE-FIRE 개인 통합 복사본

현재 실행 안내는 [integration/README.md](integration/README.md)에 있습니다.

공유팀 저장소 main f97b78d10796b24ed80140520ca0d85e5bfa5af5를 team_snapshot에 보존하고 개인 백엔드·프론트·AI를 연결했습니다. 공유 저장소는 수정하지 않았습니다.

- edgefire_AI: 전처리·학습·모델 비교·추론 Python 코드
- edgefire_back: 이미지 저장·SQLite 기록·AI 연결 백엔드 복사본
- edgefire_front: 실제 분석 화면과 공유팀 시연 화면
- models: 학습 완료 첫 모델, 성능 지표와 해시
- team_snapshot: 공유팀 원본 파일 보관

표본 모델 비교는 완료됐으며 전체 이미지 전처리·교차 분할 품질 검사를 진행하고 있습니다. 전체 데이터 학습은 아직 시작 전입니다. 후속 전수 범위 검사에서 V4 분할의 두 카메라가 같은 배경을 공유하는 것을 확인해, 해당 분할의 새 학습을 차단했습니다. 과거 성능 수치는 보존하지만 독립 장소 시험 결과로 확정하지 않습니다. 자세한 내용은 [전체 데이터 준비 안내](edgefire_AI/FULL_DATA_PREPARATION.md)를 참조하세요.

현재 모델은 연구 시제품이며 산불 발생 전 확률·안전 판정이나 실제 경보 자동화를 검증하지 않았습니다. 대응방안 모델 비교도 기준선을 넘지 못해 실사용 대상으로 채택하지 않았습니다.

---

# 기존 데이터 준비 안내

AI Hub 산불 이미지 데이터(데이터셋 71330)를 내려받고, 이미지와 세그멘테이션 라벨을 점검하는 Python 프로젝트입니다. Colab 대신 **VS Code + WSL Ubuntu**를 기준으로 구성했습니다. AI Hub는 Windows에서 API 다운로드할 때 WSL 사용을 권장합니다.

## 데이터 선택

전체 원본은 이미지 70만 장, 약 662GB입니다. 파일목록에는 아래 묶음이 있습니다.

| 파일 | filekey | 크기 | 용도 |
|---|---:|---:|---|
| VL.zip | 485847 | 160.40MB | 라벨 구조 점검만 (이미지 없음) |
| VS.zip | 485846 | 73.52GB | 검증 이미지 (VL 라벨과 짝지을 때) |
| TL.zip | 485845 | 1.24GB | 학습 라벨 |
| TS.zip + 조각 | 485839–485844 | 약 588.32GB | 전체 학습 이미지 |

작은 데이터로 먼저 시작하려면 AI Hub 상세 페이지의 `샘플(경량) 데이터` 버튼이 제공되는지 확인하세요. API 묶음은 filekey 단위로 다운로드되므로 VS/TL/TS는 용량을 확인한 뒤 선택합니다. AI Hub Shell은 압축 해제 중 다운로드 크기의 2~3배 공간을 쓸 수 있습니다.

## VS Code에서 시작

1. Windows에 WSL Ubuntu와 VS Code의 WSL 확장을 설치하고, 이 저장소를 WSL 환경에서 엽니다.
2. VS Code 터미널에서 가상환경을 만들고 필요한 패키지를 설치합니다:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install --upgrade pip
   ```

3. AI Hub에서 dataset 71330 다운로드 승인을 받은 다음, 라벨 구조만 먼저 확인합니다:

   ```bash
   bash scripts/download_aihub.sh 485847
   ```

   처음 실행할 때 API 키를 묻습니다. 입력은 화면에 표시되지 않습니다. 이후 이미지가 있는 파일을 받으려면 승인과 저장공간을 확인하고 filekey를 지정합니다. 예를 들어 `bash scripts/download_aihub.sh 485846`은 73.52GB 검증 이미지 전체를 받습니다.

4. 압축이 풀린 파일을 점검하고 전처리 CSV를 만듭니다:

   ```bash
   python scripts/preprocess_aihub.py --data-dir data/raw --output-dir data/processed
   ```

   결과는 `image_manifest.csv`, `annotations.csv`, `invalid_json.csv`, `summary.json`입니다. 이미지 파일과 JSON은 원본 폴더에 그대로 두고, 매칭 여부와 bbox 형식 등을 결과표에 기록합니다.

## 모델

AI Hub 설명의 모델은 Swin Transformer 기반 instance segmentation입니다. 상세 페이지의 모델 다운로드 버튼에서는 파일 전송이 시작되지 않았습니다. 우선 공식 Swin Transformer 저장소의 `swin_tiny_patch4_window7_224.pth` 백본 가중치를 [다운로드](https://github.com/SwinTransformer/storage/releases/download/v1.0.0/swin_tiny_patch4_window7_224.pth)해 `models/`에 보관했습니다. 파일은 약 109MB이며, 이미지 분류용 ImageNet 사전학습 백본입니다. AI Hub 산불 fine-tuned 전체 모델이 아니므로 Mask R-CNN 구조와 산불 데이터로 이어서 fine-tuning해야 합니다. 공식 MMDetection의 [Swin-T Mask R-CNN 설정](https://github.com/open-mmlab/mmdetection/blob/main/configs/swin/mask-rcnn_swin-t-p4-w7_fpn_1x_coco.py)은 이 백본 체크포인트를 초기 가중치로 사용합니다.

## 공개 저장소 보안

원본 데이터, 압축 파일, API 키, 모델 가중치를 공개 GitHub에 올리지 마세요. `.gitignore`가 데이터와 일반적인 가중치 확장자를 제외합니다. AI Hub 이용 조건에 따라 데이터 공유와 재배포를 제한하세요.
