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
