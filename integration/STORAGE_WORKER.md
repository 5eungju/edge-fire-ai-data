# C 저장소 기반 이미지 연동

개인 통합 브랜치 `codex/storage-worker-integration`에서 실행한다. 공유 팀 저장소와 기존 개인 작업 폴더의 미커밋 변경은 보존했다.
기본 실행 폴더는 `work/EDGEFIRE-storage-integration`이며, 기존 학습은 별도로 계속 실행된다.

## 흐름

```text
프론트 이미지 업로드 → 백엔드가 C에 이미지 + SQLite PENDING 작업 저장
독립 AI 워커 → 작업 claim → 로컬 모델 추론 → C에 결과 JSON + annotated.jpg 저장
백엔드가 완료 결과 조회 → 프론트가 저장된 이미지와 탐지 목록 표시
```

프론트와 백엔드의 웹 통신은 유지한다. 백엔드와 이미지 AI 사이에는 HTTP 호출이 없다.
이미지 분석에 8101번 AI 서버를 시작하지 않는다. 환경·가스 관측은 보관만 하며 별도 위험 예측이 수행됐다고 표시하지 않는다.

## 실제 저장 위치

기본 C 저장소는 작업공간의 `outputs/edgefire_storage_v1`이다. `EDGEFIRE_RUNTIME_ROOT`로 다른 로컬 경로를 명시할 수 있다.

```text
edgefire_storage_v1/
  runtime.json                  # 비공개 웹 인증키·설정·프로세스 ID
  metadata.sqlite               # 작업, 안정적인 프로젝트/저장소/노드 UUID, 워커 heartbeat
  objects/{object_id}            # 업로드 원본
  results/{job_id}/{claim}/
    result.json
    annotated.jpg
  models/vision_snapshot_{sha}.pt
  models/vision_snapshot_{sha}.json
  logs/worker.log
  logs/backend.log
  logs/frontend.log
```

학습 중 체크포인트를 별도 파일로 고정하고 SHA·모델 버전·학습 위치를 기록한다. 학습 원본 `last.pt`를 변경하지 않는다.
이번에 사용한 스냅샷은 학습 245,696장 지점의 체크포인트다. 모델 성능을 정식 검증하거나 최종 승격한 것이 아니다.
사용 중인 워커를 먼저 정지한 뒤에만 스냅샷을 교체할 수 있다.

## 준비

저장소 루트에서 실행한다. 기존 Python/Node 의존성이 설치돼 있다면 다시 설치할 필요가 없다.

```powershell
py -m pip install -r edgefire_AI/requirements-vision-training.txt -r edgefire_back/requirements.txt -r integration/requirements.txt
py integration/prepare_storage_snapshot.py --source <C의 GPU last.pt> --root <C의 저장소> --training-status <C의 GPU status.json>
```

기본 경로와 다른 저장소를 선택했다면 해당 PowerShell에서 다음을 설정한다.

```powershell
$env:EDGEFIRE_RUNTIME_ROOT = '<C의 저장소 절대 경로>'
```

프론트 패키지가 없는 새 컴퓨터에서는 `edgefire_front`에서 `npm ci`를 먼저 실행한다.
이번 노트북의 분리 작업 복사본은 기존 개인 복사본의 `node_modules`를 junction으로 재사용했으며 재설치하지 않았다.

```powershell
cd edgefire_front
node node_modules/next/dist/bin/next build --webpack
cd ..
py integration/run_local.py start
```

화면: http://127.0.0.1:3200
백엔드: http://127.0.0.1:8200

```powershell
py integration/run_local.py status
py integration/run_local.py stop --only worker
py integration/run_local.py start --only worker
py integration/run_local.py stop
```

`stop`은 이 통합 실행기의 세 프로세스만 대상으로 한다. 코랩, 학습 데이터 bridge, 터널을 종료하지 않는다.
비공개 `runtime.json`, 모델 파일, 이미지, SQLite를 GitHub에 올리지 않는다.

## 상태·재시도·중단 복구

- `PENDING → RUNNING → COMPLETED` 또는 `FAILED`로 기록한다.
- `BEGIN IMMEDIATE`로 한 작업을 한 워커만 확보한다. 처리 중 임대 시간을 갱신한다.
- 워커가 사라져 임대가 만료되면 다른 워커가 복구한다. 반복 중단은 최대3회 후 실패로 남긴다.
- 각 claim은 서로 다른 결과 폴더를 사용한다. 오래된 워커가 뒤늦게 결과를 써도 새 워커의 결과를 덮어쓰지 못한다.
- JSON/이미지는 임시 파일을 완전히 쓴 뒤 교체하고, DB가 완료를 가리킨 뒤에만 프론트에 제공한다.
- 실패 작업만 명시적으로 재시도한다. 완료된 작업 재시도는409로 거부한다.
- 백엔드 재시작은 진행 중인 작업을 일괄 실패로 바꾸지 않는다.
- 입력 SHA 불일치와 추론 오류는 실패로 표시하며 정상/안전 결과로 대체하지 않는다.

현재 SQLite WAL 큐는 **동일 노트북/로컬 파일시스템**용이다. 팀원 PC나 네트워크 공유 폴더에서의 다중 호스트 운용은 검증하지 않았다.
다른 서버에 배포하려면 공용 객체 저장소와 서버형 작업 DB/큐 등의 구성에 맞춘 별도 연동이 필요하다.

## 모델·학습 표시

사용하는 모델의 실제 구조가 `SegmentationModel`인지 확인하고 분할 predictor를 명시한다.
이는 사용자 정의 학습 체크포인트의 기본 task 메타데이터가 detect로 읽히는 문제를 방지한다.
출력에는 모델 ID/SHA, 입력 SHA, 클래스, 점수, 박스·다각형, 처리 시각이 포함된다.
`operational_use=false`, `model_status=training_snapshot_not_validated`를 표시하며 점수를 산불 발생 확률로 해석하지 않는다.
프론트는 실제 저장된 표시 이미지를 사용하므로 화면 크기에 따른 SVG 박스 정렬 오차를 피한다.

학습 상태는 별도의 C GPU 수신 JSON을 읽는다. 코랩 Linux PID를 Windows PID로 조회하지 않는다.
최근 상태 수신 여부와 시각을 표시하고, 오래된 training 기록은 확인 필요 상태로 표시한다.

## 검증

```powershell
py -m unittest discover -s integration -p test_storage_queue.py -v
py integration/test_storage.py -v
```

실제 프론트 프록시에 기존 산불 학습 이미지 1장을 보내 `PENDING → COMPLETED`를 확인했다.
독립 워커가 현재 스냅샷으로 `white_gray_smoke` 1개를 출력했고, C의 JSON/표시 이미지와 프론트 조회 응답이 일치했다.
이것은 연동 확인이며 정확도나 미탐/오탐 성능 측정이 아니다.
무인증 백엔드401, 잘못된 Origin403, 완료 작업 재시도409, 실패 후 재시도 완료를 확인했다.
큐 동시 claim, 임대 만료 fencing, 느린 추론의 heartbeat, 입력 변조 거부, 백엔드 재초기화 보존도 검사했다.
프론트 production build와 TypeScript 검사를 통과했다. 브라우저 화면의 원격 조작은 하지 않았다.
