# EDGE-FIRE 산불 AI 데이터 준비

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
