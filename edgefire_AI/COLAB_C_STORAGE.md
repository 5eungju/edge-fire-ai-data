# 코랩 GPU 학습 / 노트북 데이터 / C 결과 저장

2026-11-22 사용자가 코랩 GPU 사용과 C드라이브 결과 저장을 선택했다.
원본 ZIP을 옮기거나 222GiB 전체를 먼저 복사하지 않는 방식이다. 이미지 바이트의 네트워크 전송은 필요하다.

## 실제 실행 경로

- 원본과 기존 전처리 ZIP: C/E에 있는 파일을 읽기만 한다. E에는 새 파일을 쓰지 않는다.
- 학습 목록: 전체 598,500장의 메타데이터와 검토 제외 목록을 담은 약 127MiB SQLite.
- 코랩 입력: 인증된 임시 HTTPS 연결로 요청한 학습·검증 이미지만 전달한다.
- 코랩 모델: Tesla T4에서 CUDA를 사용한다. 노트북 GPU나 코랩 CPU로 대체하지 않는다.
- 저장: GPU 체크포인트·상태·설정·검증 결과를 C의 전용 실행 폴더로 전송한다. Drive를 마운트하거나 업로드하지 않는다.
- 전체 학습은 440,207장, 검증은 79,218장이다. 최종 시험 54,826장은 이 연결에서 제공하지 않는다.

실행 코드는 `train_full_stream.py`, `colab_stream_client.py`, `colab_stream_bridge.py`이다.
백엔드·프론트 소스 수정과 별개의 AI 실험 경로이며 모델을 자동 서비스 배포하지 않는다.

## 전송 최적화와 재현

처음에는 원래 JPEG를 그대로 전달했다. T4 계산보다 네트워크 전송이 느려 약 2장/초 수준이었다.
GPU 체크포인트를 C에 저장한 뒤 다음 학습 전송 변환을 명시적으로 적용했다.

```text
train: 원본 JPEG SHA 확인 → 종횡비 유지, 긴 변 최대 512픽셀 → JPEG quality95, 4:4:4
val:   원본 JPEG 그대로
```

원본 ZIP은 변경하지 않는다. 학습 JPEG 재인코딩은 손실 변환이며 색상/픽셀을 완전히 보존하는 것은 아니다.
분할 다각형의 정규화 좌표와 객체·클래스·split은 유지한다. 종횡비 반올림에 의한 미세한 좌표 차이가 가능하다.
검증 이미지는 원래 JPEG를 그대로 전달하여 재인코딩된 학습 이미지로 검증을 대체하지 않는다.
성능 향상 여부는 전체 검증 결과로 판단해야 하며, 처리 속도 향상을 모델 정확도 향상으로 해석하지 않는다.

새 전송 변환은 `transport_preprocess`로 체크포인트 설정에 기록한다.
코드·전처리가 바뀐 실행은 `--fork-checkpoint`를 명시해야 한다. 원래 데이터 식별자와
imgsz/batch/epochs/seed/lr가 일치해야 optimizer와 epoch 안의 위치를 이어받는다.
부모 체크포인트 SHA와 부모 소스 SHA를 기록하고 원래 실행을 보존한다.

## 준비 및 실행

먼저 `export_full_portable.py`로 검토 목록을 준비한다. 상세 절차는 `FULL_STREAM_TRAINING.md` 참조.
실제 이미지 ZIP을 원격 머신으로 복사하는 단계는 이 스트리밍 경로에서 사용하지 않는다.

```powershell
py edgefire_AI/prepare_colab_stream.py --portable <C의 전체 목록 폴더> --output <C의 새 연결 폴더>
py edgefire_AI/colab_stream_bridge.py --workspace <노트북 작업공간> --portable <전체 목록 폴더> --run <C의 GPU 결과 폴더> --package <연결 폴더/bootstrap.zip> --credentials <연결 폴더/credentials.json> --train-max-side 512
```

bridge는 `127.0.0.1:8787`에만 바인딩한다. 별도의 임시 HTTPS 터널을 이 포트에 연결한다.
이번 실행에서는 [Cloudflare의 공식 Quick Tunnel](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)을 사용했다.
이는 임시 실험 연결이며 가용성이 보장되는 운영 서비스가 아니다. 터널 프로그램은 공식 릴리스의 SHA256을 확인했다.

```powershell
cloudflared tunnel --url http://127.0.0.1:8787 --no-autoupdate --protocol http2
py edgefire_AI/prepare_colab_stream.py --portable <전체 목록 폴더> --output <연결 폴더> --url <실제 임시 HTTPS 주소>
```

만들어진 **비공개 노트북**을 VS Code Colab 커널에서 실행한다. 비공개 노트북/connection JSON에는
임시 인증키가 있으므로 GitHub에 올리지 않는다. 공개 템플릿은 `colab/EDGEFIRE_C_Stream_GPU.ipynb`이다.
새 코랩 세션에서 재개하려면 C에 마지막으로 저장된 `last.pt`와 해당 실행의 고정 코드·설정이 필요하다.
코랩 세션 종료 시 메모리와 임시 디스크가 사라질 수 있으므로 C 수신 기록을 기준으로 복구한다.

## 저장 및 접근 범위

모든 경로는 인증키가 있어야 접근할 수 있다. 임의 경로 읽기, 폴더 목록, 명령 실행은 제공하지 않는다.
학습/검증 split과 승인된 ID를 확인한 뒤 기존 ZIP CRC와 원본 JPEG SHA를 대조한다.
클라이언트는 전송된 JPEG/라벨 SHA, 원본 이미지 식별자, 전송 변환을 다시 확인한다.
최종 시험 엔드포인트는 비활성 상태다.

업로드는 지정된 학습 파일명으로 제한하며 크기와 SHA256이 일치할 때만 C에 원자 교체한다.
서버는 업로드된 체크포인트를 unpickle하거나 실행하지 않는다. C에 최소 2GiB를 남기도록 검사한다.
체크포인트는 새 실행의 5배치 후, 이후 약 120초마다 저장하고 C 수신 SHA를 확인한다.
연결 장애가 계속되면 학습을 오류로 중단하며 CPU로 몰래 대체하지 않는다.

C의 해당 GPU 결과 폴더에 `STOP` 파일을 만들면 약 30초 간격 제어 확인 후 현재 배치를 마치고 저장·정지한다.
노트북 전원, SSD, 인터넷, bridge와 터널이 계속 작동해야 한다. 화면을 통한 AI 조작이 없어도 실행 코드는 동작한다.
인증키는 해당 연결을 종료하거나 새 키로 서버를 시작할 때 무효화된다.

## 실제 검사와 현재 한계

무인증 접근, 잘못된 split/제외 ID, 임의 저장 파일명, 잘못된 SHA, 과대 업로드, 잘못된 JSON 식별자 차단을 검사했다.
학습 전송 리사이즈의 종횡비, 4:4:4 색상, 픽셀 오차와 실제 8장 전송도 확인했다.
실제 T4 학습 체크포인트를 C에서 읽어 CUDA 설정, 6개 클래스, 학습 위치, 부모 SHA를 확인했다.
기존 CPU 실행은 22,178장에서 저장 후 정지했고 파일은 보존했다.
전체 GPU epoch/전체 검증은 아직 끝나지 않았으며 공식 정확도나 최적 모델 확정은 보고하지 않는다.
