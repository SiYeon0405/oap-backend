# oap-backend
AI-powered business validation and marketing strategy platform backend

## Run

Create `.env` from `.env.example` and set your local PostgreSQL password.

```bash
uvicorn app.main:app --reload
```

## Health Check

- `GET /health`
- `GET /health/db`

## OAP 2.1 운영 검증

- `oap-backend.service`와 Nginx: active
- Uvicorn: `127.0.0.1:8000`에만 바인딩, 외부 8000 포트 접근 차단 확인
- `http://ooap.co.kr/health`: `301 Moved Permanently`
- 리다이렉트 위치: `https://ooap.co.kr/health`
- `https://ooap.co.kr/health`: `200 OK`
- `https://ooap.co.kr/health/db`: `200 OK`, Supabase PostgreSQL 연결 정상
- 검증 과정에서 DB 스키마·데이터·Migration·API 코드 변경 없음
