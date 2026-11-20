# 장소 중복 조사와 다음 평가 구성

## 후속 재검사: V4 실행 대상

이 문서 아래의 74개 그룹은 최초 장소명 분리 계획입니다. V3 표본의 후속 시각 검사에서 서로 다른 장소명 사이에도 비슷한 배경 34쌍을 찾았습니다. 3개 카메라 관계의 대표 이미지를 직접 검토해 일치하는 건물·산 능선·숲/지붕 배치를 확인했습니다. reviewed_background_links.json에 이 관계를 기록하고 함께 묶어 V4는 72개 그룹으로 구성했습니다. 실제 좌표를 확정한 것은 아닙니다.

현재 엄격한 비교 대상은 E:/AI_Work/edgefire_vision_spatial_v4입니다. 학습 2,543장, 검증 490장, 시험 531장입니다. 출력 3,564장의 이미지 디코딩·파일 연결·라벨 좌표·다각형 검사를 통과했고, 이번 dHash/RGB 조사에서 교차 분할 유사 후보는 0쌍입니다. 검사의 한계 때문에 모든 종류의 중복 부재를 보장하지는 않습니다. V3는 후속 배경 검사를 통과하지 않아 엄격한 모델 비교에 사용하지 않습니다.

V3 전수 재검사에서 소수점 7자리 반올림으로 좁은 틈이 닫히며 다각형이 교차하는 사례 1건을 찾았습니다. 원본 좌표를 바꾸지 않고 파생 YOLO 라벨을 17개 유효 숫자로 저장하도록 수정했습니다. V4는 이 방식으로 생성하고 저장된 라벨을 다시 파싱해 검사했습니다.

재현:

```powershell
py edgefire_AI/plan_spatial_split.py --reviewed-visual-links edgefire_AI/reviewed_background_links.json --output E:/AI_Work/edgefire_spatial_plan_v4
py edgefire_AI/prepare_spatial_dataset.py --plan E:/AI_Work/edgefire_spatial_plan_v4/spatial_split_plan.json --output E:/AI_Work/edgefire_vision_spatial_v4
py edgefire_AI/validate_spatial_dataset.py --root E:/AI_Work/edgefire_vision_spatial_v4 --plan E:/AI_Work/edgefire_spatial_plan_v4/spatial_split_plan.json
py edgefire_AI/audit_spatial_similarity.py --dataset E:/AI_Work/edgefire_vision_spatial_v4 --output E:/AI_Work/edgefire_vision_spatial_v4/quality_audit --split-plan E:/AI_Work/edgefire_spatial_plan_v4/spatial_split_plan.json
```

기존 출력 폴더를 덮어쓰지 않으므로 재생성할 때는 새 출력 경로를 사용하세요. V4 검사 결과와 계획은 integration/reports의 v4 파일들에 보관했습니다.

## 최초 장소명 분리 조사 기록

전체 파일 목록에서 장소명 86개 중 35개가 카메라 기준 분할 여러 곳에 나타났습니다. 두 번째 표본에서는 장소명 29개가 겹치며 1,952장의 이미지가 이 장소명에 속합니다. dHash와 축소 RGB 비교로 교차 분할 유사 이미지 31쌍을 찾았습니다. 상위 네 쌍은 시각 검토에서도 매우 비슷한 배경이 확인됐습니다. 자동 유사도는 중복 확정 기준이 아니므로 원본을 삭제하지 않습니다.

기존 카메라 ID 분할 결과는 독립적인 장소 평가 결과가 아닙니다. 두 번째 학습은 별도 탐색 실험으로 유지하며, 다음 구성은 장소명과 카메라 ID의 연결 성분을 함께 보존합니다. 시루봉·춘갑봉 이름을 포함한 장소는 보수적으로 같은 산악권역으로 묶습니다. 실제 좌표를 검증한 것은 아니며 지나치게 넓게 묶일 수 있습니다.

계획에는 74개 연결 성분과 469개 카메라가 있습니다. 컬렉션별 원본 이미지 수 비율 70/15/15를 목표로 혼합 정수 계획법을 사용하되 같은 성분을 쪼개지 않고, 가능한 컬렉션은 각 분할에 적어도 한 그룹이 존재하도록 제약합니다. SciPy milp/HiGHS의 요청 상대 허용 오차는 2%입니다. 기록된 상대 차이는 약 1.96%로 정확한 전역 최적해를 증명한 것은 아닙니다. 이것은 데이터 배분 문제의 풀이이며 AI 모델이 최적이라는 의미가 아닙니다.

일부 장소에 화염 자료가 몰려 있어 비율을 정확히 맞출 수 없습니다. 예를 들어 시험 분할의 실제 화염 원본은 714장으로, 목표 비율보다 적습니다. 실제 표본 수와 컬렉션별 수량은 추출 결과에서 다시 확인해야 합니다.

추출은 학습 컬렉션별 최대 300장, 검증·시험 각각 최대 60장을 목표로 합니다. 같은 촬영 구간은 최대 10장, 프레임 번호 차이는 최소 60을 적용합니다. 선택 이미지에 대해서 압축 CRC, 치수·카메라·파일명·클래스, 마스크 자기 교차를 검사합니다. 빈 마스크나 복합 마스크는 임의로 수정하지 않습니다. 백색 연기 이름의 반복 오타는 이미지 경로·프레임·카메라·치수가 일치하고 알려진 문자열 규칙으로 정확히 맞는 경우에만 메타데이터 별칭으로 기록합니다. 원본 JSON은 그대로 보관합니다.

**새 장소 평가용 모델은 일반 사전학습 가중치에서 학습해야 합니다.** 기존 첫·둘째 산불 모델은 이 새 평가 장소를 이미 학습했을 수 있어 초기 가중치로 사용하면 안 됩니다. 새 시험셋은 모델·운영 기준 선택에 사용하지 않고, 비교 후보는 같은 공간 분리 데이터와 예산에서 학습·검증합니다.

## 실행

```powershell
py -m pip install -r edgefire_AI/requirements-vision-preprocess.txt
py edgefire_AI/audit_spatial_similarity.py
py edgefire_AI/plan_spatial_split.py
py edgefire_AI/prepare_spatial_dataset.py
py edgefire_AI/test_spatial_quality.py
```

추출 위치는 E:/AI_Work/edgefire_vision_spatial_v3입니다. 데이터 원본은 수정하지 않습니다.

## 첫 모델 점수 기준 조사

검증 264장만 사용해 입력 512, 최대 탐지 100개 조건으로 점수 기준을 조사했습니다. 0.05~0.5의 후보 중 설정한 기준에서는 기존 0.25가 선택돼 서비스 기준을 변경하지 않았습니다. 기준 0.25에서 연기·화염 3종의 평균 마스크 재현율은 약 0.172로 낮습니다. 점수 기준만 바꾸면 문제가 해결된다고 볼 수 없습니다. 이는 확률 보정이나 독립 공간 검증이 아닙니다.

조사 코드: calibrate_vision_thresholds.py. 결과: integration/reports/vision_v1_threshold_analysis.json. 데이터 분리 계획과 유사도 요약도 integration/reports에 보관합니다.

SciPy 공식 API: https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html
