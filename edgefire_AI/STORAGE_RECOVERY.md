# SSD I/O 중단 이후 작업 기록 복구

전처리와 품질 검사에서 경로 소실 및 SQLite `disk I/O error`가 발생했다.
Windows가 E: exFAT 볼륨을 Warning / Full Repair Needed로 보고했다. 원본
`AI_Data` 폴더의 압축파일 경로는 현재 접근할 수 없어 원본 전처리를 재개하지
못했다. 이 관찰만으로 SSD 하드웨어 고장이나 원본 영구 소실을 확정하지 않는다.

작업 DB·WAL·상태와 전체 후보 목록은 C:로 복사해 원본 백업을 보존했다.
복사한 세 SQLite DB의 quick_check는 통과했고, 후보 목록 SHA256도 기존과
일치했다. 커밋된 전처리 392,000장에 해당하는 ZIP 392개가 존재하는지 확인했다.
이는 모든 ZIP의 이미지 내용이 정상이라는 검사 완료를 뜻하지 않는다.

기존 묶음은 E:에서 읽기만 하고, 품질 검사·후속 재검사의 DB와 상태는 C:에서
쓰도록 재개했다. 백업과 실제 작업 복사본은 분리했다. 원본 볼륨에 자동 복구,
삭제, 포맷이나 이동은 수행하지 않았다. 관리자 파일시스템 진단 명령은 OS의
접근 거부로 실행되지 않았다.

## 경로를 분리하는 실행 옵션

전처리의 `--existing-shards`와 품질 검사의 `--extra-shards`는 이전에 저장한
ZIP 디렉터리를 읽기 전용 입력으로 추가한다. 복제한 작업 DB의 설정 경로를
새 디렉터리로 명시적으로 변경한 뒤 사용한다. 같은 이름의 ZIP이 여러 입력에
있으면 중단한다. 이전 커밋이 참조하는 ZIP이 누락돼도 전처리를 진행하지 않는다.

```powershell
# 실제 원본 압축파일 경로가 정상임을 확인한 후에만 실행할 수 있다.
py edgefire_AI/preprocess_full_inventory.py --inventory C:/recovery/backup/inventory/full_source_inventory.jsonl --output C:/recovery/active/preprocess --existing-shards E:/AI_Work/edgefire_full_export_v1/shards --budget-gib 15 --min-free-gib 20

# 기존 저장 결과에 대한 품질 검사는 원본 압축파일 없이 별도로 진행 가능하다.
py edgefire_AI/audit_full_shards.py --source C:/recovery/active/preprocess --extra-shards E:/AI_Work/edgefire_full_export_v1/shards --output C:/recovery/active/quality --follow
py edgefire_AI/recheck_capped_similarity.py --source C:/recovery/active/quality --output C:/recovery/active/uncapped --follow
```

예시의 `C:/recovery`는 작업 위치에 맞춰 바꾼다. 실제 로컬 활성 경로는
워크스페이스 `outputs/active_pipeline.json`에 기록하며, 그 개인 경로 파일이나
DB·원본·백업 자료는 GitHub에 업로드하지 않는다.

분리된 전처리의 저장 제한은 새 디렉터리의 출력 용량에 적용한다. 상태에는
이전 묶음 용량과 새 묶음 용량을 따로 기록하고 합계도 표시한다. 원본 압축파일
또는 기존 묶음을 읽을 수 없으면 중단하며, 누락된 파일을 학습 성공으로 숨기지
않는다. SSD 복구 전까지 전체 전처리·전체 데이터 학습이 실행 중이라고 보고하면
안 된다.
