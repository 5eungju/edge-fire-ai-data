# 산불 상황 위험 등급 API — 연구 시제품

기존 산불 사례의 기상·지형 정보로 데이터에 주석된 위험 등급을 분류합니다. 실제 AI 허브 로컬 자료를 표본 추출해 학습한 Random Forest 모델입니다. 산불 발생 확률이나 확산 속도를 예측하는 시스템은 아니며, 실측 영상·가스 감지는 포함하지 않습니다. 합성 가스 패턴 분류 MLP와 화학물성 조회 모듈은 별도 시험 기능으로 추가했습니다.

## 실행

Python 3.12에서 이 폴더를 열고 실행합니다.

먼저 별도로 전달된 `wildfire_api_prototype.zip`에서 `model.joblib`을 꺼내 이 `edgefire_AI/` 폴더에 넣으세요. 모델은 공개 GitHub에 포함하지 않습니다. 또는 `MODEL_PATH` 환경변수로 파일 경로를 지정할 수 있습니다. 직접 재학습하려면 아래 `train.py` 절차를 실행하세요.

전달 모델 SHA-256: `880343783e7d44195ba2d02b53412ba09f36a9c795f126666600abb9895949f6`.

```powershell
py -m pip install -r requirements.txt
py app.py
```

API 문서: http://127.0.0.1:8001/docs

- `GET /health`: 서버 상태·모델 버전
- `GET /model-info`: 실제 평가 수치·학습 변수·한계
- `POST /wildfire/assess`: 주석 위험 등급 예측

## 요청 예시

```json
{
  "temperature": 25,
  "humidity_percent": 30,
  "wind_speed": 5,
  "wind_direction": 90,
  "rainfall": 0,
  "past_rainfall_7days": 0,
  "elevation": 300,
  "slope": 15,
  "slope_aspect": 180
}
```

온도·습도·풍속은 필수입니다. 나머지는 생략할 수 있고 학습 데이터의 중앙값으로 채웁니다. 결측 필드는 응답의 `missing_optional_fields`에 표시합니다. NaN·Infinity·정의되지 않은 추가 필드·범위 밖 입력은 422 오류를 반환합니다. 풍속·강수·고도 등의 단위는 구축 명세와 서비스 센서의 단위를 대조한 뒤 연동해야 합니다.

## 응답과 연동

`predicted_annotation_level`은 기존 산불 사례의 주석 등급을 예측한 값입니다. `class_scores`는 보정되지 않은 분류 점수이며 산불 발생 확률이 아닙니다. `operational_use=false`는 현장 경보용으로 검증되지 않았음을 뜻합니다. 시험 목적을 넘어 대피·진화 의사결정에 직접 사용하지 않습니다.

백엔드는 JSON 요청을 보내고 결과·모델 버전을 저장하면 됩니다. 예를 들어 Python에서는:

```python
import json, urllib.request
payload = {"temperature": 25, "humidity_percent": 30, "wind_speed": 5}
request = urllib.request.Request(
    "http://127.0.0.1:8001/wildfire/assess",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"}, method="POST")
with urllib.request.urlopen(request) as response:
    print(json.load(response))
```

기본 실행 주소는 같은 PC에서만 접근 가능합니다. 다른 서버에서 호출하려면 백엔드 담당자가 코드를 배포하고 인증·TLS·네트워크 접근을 구성해야 합니다. 이 시제품은 인증이 없으며 인터넷에 바로 공개하지 않습니다.

## 학습·평가

`train.py`는 Downloads의 38번 데이터셋 Training ZIP에서 사건별 최대 250개를 재현 가능한 난수로 추출합니다. 모델 평가에는 사건별 75:25 분할을 사용하며, 학습 사건과 평가 사건의 교집합을 0으로 확인합니다. 제공된 Validation을 공식 성능으로 사용한 것이 아니라 내부 사건 보류 평가입니다. 실제 수치는 `metrics.json`에 기록됩니다. 정답이 불균형하므로 다수 클래스 기준선의 macro-F1과 비교합니다. 원본 전체 학습 결과로 표현해서는 안 됩니다.

학습 입력은 기온·습도·풍속·강수·최근 강수·고도·경사·풍향·사면 방향입니다. 종료 시각·최종 피해면적·대응 정답·최종 확산 경로를 입력에서 제외합니다. 경사 값이 0~90 범위를 벗어나면 결측으로 취급합니다. 방향 변수는 사인·코사인으로 변환합니다.

등급 표현의 통합은 `features.py`의 임시 규칙입니다. `안전/양호→매우 낮음`, `보통/중간→보통`, `높음/위험→높음` 등이 포함됩니다. 전문가가 검토한 공식 등급 매핑은 아닙니다. 입력과 라벨 정합성 문제, 비산불 대조군 부재, 지역·시간 편향 때문에 현장 위험을 검증한 모델로 볼 수 없습니다.

재학습:

```powershell
py train.py "C:\Users\tmdwn\Downloads"
```

`model.joblib`은 이 작업에서 직접 학습한 파일입니다. 출처를 모르는 joblib/pickle 모델은 로드하지 마세요.


## 공유 프로젝트에 맞춘 설정

변경 범위는 이 `edgefire_AI/` 폴더뿐입니다. `edgefire_back/`, `edgefire_front/`는 수정하지 않았습니다. 백엔드는 기존 8000번, AI는 8001번 포트를 사용합니다. AI 서버가 백엔드 WebSocket을 대신 열거나 프론트로 메시지를 직접 전송하지 않습니다.

- `POST /wildfire/assess`: 환경 변수만 받는 기존 시험용 인터페이스
- `POST /api/v1/ai/assess`: 기존 센서 패킷 필드와 선택적 `environment`를 받는 연동용 인터페이스
- `GET /health`: `model_loaded`로 모델 유무 확인. 모델이 없어도 서버와 명세는 열립니다.
- `AI_HOST`, `AI_PORT`, `MODEL_PATH`: 실행 환경변수. `.env.example`은 참고 파일이며 자동으로 읽지 않습니다.

백엔드 담당자용 상세 안내는 [INTEGRATION.md](INTEGRATION.md)를 확인하세요. `py integration_example.py`는 AI 서버만 호출하며 기존 백엔드/프론트에는 영향을 주지 않습니다.

## 계약 테스트

```powershell
py -m pip install -r requirements-test.txt
py -m unittest -v test_contract
```

모델 파일이 없으면 실제 모델 추론 테스트 1개가 건너뛰어집니다. 전달된 모델을 이 폴더에 넣거나 MODEL_PATH를 지정한 상태에서 실행하면 실제 모델 추론과 가스값의 비사용 여부까지 검증합니다. `smoke_test.py`는 실행 중인 AI 서버에 대한 HTTP 검사이며 기본 포트는 8001입니다.


## 합성 가스·화학물질 시험 기능

[SYNTHETIC_DATA.md](SYNTHETIC_DATA.md)에 생성 규칙·학습 방법·한계를 기록했습니다. `POST /api/v1/ai/gas/assess`는 합성 패턴 분류만 지원하며 실제 위험 단계는 반환하지 않습니다. `GET /api/v1/ai/chemicals/{cid}`는 실제 원시 화학물성 조회이며 AI 위험성 예측은 아닙니다.

추가 테스트: `py -m unittest -v test_contract test_gas_chemical`. 먼저 `train_gas_demo.py`, `build_chemical_catalog.py`로 로컬 자료를 생성하세요. 별도 전달 ZIP에는 생성된 모델과 자료가 들어 있습니다.
