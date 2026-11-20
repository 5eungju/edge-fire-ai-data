# EDGE-FIRE 백엔드 파이프라인

## 로컬 개발 서버 실행 방법
1. 가상환경 생성 및 활성화:
   `python -m venv venv`
   `.\venv\Scripts\activate.bat` (Windows)
2. 패키지 설치:
   `pip install -r requirements.txt`
3. 백엔드 서버 구동:
   `uvicorn main:app --reload`
4. API 명세 확인:
   `http://127.0.0.1:8000/docs`