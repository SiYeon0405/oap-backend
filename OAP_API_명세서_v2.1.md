# OAP API 명세서 v2.1

## 1. 문서 정보

| 항목 | 값 |
|---|---|
| 프로젝트 | OAP 2.1 |
| API 문서 버전 | 2.1 |
| Backend | FastAPI |
| Database | PostgreSQL / Supabase |
| 인증 | JWT Secure HttpOnly Cookie |
| 기준 | 현재 OpenAPI 3.1, Router/Schema, 실제 HTTP 검증 결과 |

## 2. 공통 정보

- 로컬 Base URL: `http://localhost:8000`
- 모든 JSON 요청의 `Content-Type`: `application/json`
- 인증 쿠키:
  - `access_token`: HttpOnly, path `/`, 기본 만료 30분
  - `refresh_token`: HttpOnly, path `/api/v1/auth`, 기본 만료 14일
- JWT는 응답 JSON으로 제공하지 않는다.
- `Authorization: Bearer`를 사용하지 않는다.
- 브라우저 `fetch`는 `credentials: "include"`, Axios는
  `withCredentials: true`가 필요하다.
- Postman에서는 같은 `baseUrl`의 Cookie Jar를 사용한다. 로그인 응답의
  `Set-Cookie`가 저장되며 이후 요청에 자동 전송된다.
- 운영 기본 쿠키는 `Secure=true`, `SameSite=None`이다. HTTPS가 없는
  localhost 또는 서버 IP에서는 Postman이 Secure Cookie를 보내지 않을 수 있다.
- 현재 허용 Origin은 `http://localhost:3000`, `http://localhost:3001`,
  `http://localhost:5173`이다. refresh/logout/회원 탈퇴는 전달된 Origin 또는
  Referer가 이 목록에 없으면 403을 반환한다.

오류 응답은 FastAPI의 `detail` 구조를 사용한다.

```json
{"detail": "Not authenticated"}
```

검증 오류는 다음 형태다.

```json
{
  "detail": [
    {
      "loc": ["body", "field"],
      "msg": "validation message",
      "type": "validation_error"
    }
  ]
}
```

## 3. Health API

### GET /health

- 설명: 애플리케이션 상태 확인
- 인증: 불필요
- 성공: `200 OK`
- 쿠키 변경: 없음

```json
{"status": "ok"}
```

### GET /health/db

- 설명: PostgreSQL 연결 상태 확인
- 인증: 불필요
- 성공: `200 OK`
- 오류: `503` — DB 연결 실패, `{"detail":"database connection failed"}`
- 쿠키 변경: 없음

```json
{"status": "ok", "database": "connected"}
```

## 4. Auth API

### POST /api/v1/auth/signup

- 설명: 사용자 회원가입. 자동 로그인이나 토큰 발급은 하지 않는다.
- 인증: 불필요
- 성공: `201 Created`
- 오류:
  - `409` — 이메일 중복, `{"detail":"Email already exists"}`
  - `422` — 요청 검증 실패
- 쿠키 변경: 없음

요청 필드:

| 필드 | 타입 | 필수 | 제약 |
|---|---|---:|---|
| `email` | string | O | 3~320자, 이메일 형식, 소문자 정규화 |
| `password` | string | O | 8~72자, UTF-8 72바이트 이하 |
| `name` | string/null | X | 최대 100자, 공백 문자열 불가 |

```json
{
  "email": "user@example.com",
  "password": "example-password",
  "name": "홍길동"
}
```

```json
{
  "id": 1,
  "email": "user@example.com",
  "name": "홍길동",
  "status": "ACTIVE",
  "createdAt": "2026-07-30T10:00:00Z"
}
```

### POST /api/v1/auth/login

- 설명: 이메일/비밀번호 로그인 및 Access/Refresh Cookie 발급
- 인증: 불필요
- 성공: `200 OK`
- 오류:
  - `401` — 자격 증명 불일치 또는 비활성 사용자,
    `{"detail":"Invalid email or password"}`
  - `422` — 요청 검증 실패
- 쿠키 변경: `access_token`, `refresh_token` 설정

| 필드 | 타입 | 필수 | 제약 |
|---|---|---:|---|
| `email` | string | O | 3~320자, 이메일 형식 |
| `password` | string | O | 1~72자, UTF-8 72바이트 이하 |

```json
{"email": "user@example.com", "password": "example-password"}
```

```json
{"id": 1, "email": "user@example.com", "name": "홍길동", "status": "ACTIVE"}
```

### GET /api/v1/auth/me

- 설명: Access Cookie로 현재 로그인 사용자 조회
- 인증: `access_token` HttpOnly Cookie 필요
- 성공: `200 OK`
- 오류: `401` — 쿠키 없음, 만료·위조 토큰, 삭제·비활성 사용자
- 쿠키 변경: 없음

```json
{"id": 1, "email": "user@example.com", "name": "홍길동", "status": "ACTIVE"}
```

### POST /api/v1/auth/refresh

- 설명: Refresh Cookie를 검증하고 두 토큰을 Rotation한다.
- 인증: `refresh_token` HttpOnly Cookie 필요
- Request Body: 없음
- 성공: `200 OK`
- 오류:
  - `401` — 쿠키 없음, 만료·위조·폐기·재사용 토큰, 비활성 사용자
  - `403` — 허용되지 않은 Origin/Referer
- 쿠키 변경: 새 `access_token`, 새 `refresh_token` 설정

```json
{"id": 1, "email": "user@example.com", "name": "홍길동", "status": "ACTIVE"}
```

### POST /api/v1/auth/logout

- 설명: 현재 Refresh Token family만 폐기한다. 쿠키가 없거나 잘못되어도
  로그아웃 응답과 쿠키 삭제는 성공한다.
- 인증: 별도 Access 인증 불필요
- Request Body: 없음
- 성공: `200 OK`
- 오류: `403` — 허용되지 않은 Origin/Referer
- 쿠키 변경: Access/Refresh Cookie 삭제

```json
{"detail": "Logged out"}
```

### DELETE /api/v1/auth/me

- 설명: 현재 로그인한 본인의 계정과 소유 데이터를 물리 삭제한다.
- 인증: `access_token` HttpOnly Cookie 필요
- 성공: `200 OK`
- 오류:
  - `401` — 인증 실패 또는 현재 비밀번호 불일치
  - `403` — 허용되지 않은 Origin/Referer
  - `422` — 요청 검증 실패
- 쿠키 변경: Access/Refresh Cookie 삭제

| 필드 | 타입 | 필수 | 제약 |
|---|---|---:|---|
| `password` | string | O | 1~72자, UTF-8 72바이트 이하 |

```json
{"password": "current-password"}
```

```json
{"detail": "Account deleted"}
```

## 5. 분석 API

모든 분석 API는 `access_token` HttpOnly Cookie가 필요하다. 인증이 없으면
401이다. `userId`를 Body로 받지 않으며 새 분석 요청은 현재 로그인 사용자에게
자동 귀속된다. 존재하지 않거나 다른 사용자가 소유한 `requestId`는 404로
처리한다.

### POST /api/v1/analysis-requests

- 설명: 현재 사용자의 분석 요청 생성
- 성공: `201 Created`
- 오류: `401`, `422`
- 쿠키 변경: 없음

| 필드 | 타입 | 필수 |
|---|---|---:|
| `serviceName` | string | O |
| `oneLineDescription` | string | O |
| `industry` | string | O |
| `mainQuestion` | string | O |

```json
{
  "serviceName": "OAP",
  "oneLineDescription": "사업 분석 서비스",
  "industry": "SaaS",
  "mainQuestion": "시장 진입 전략은?"
}
```

```json
{"requestId": 1, "status": "INTERVIEWING"}
```

### GET /api/v1/analysis-requests/{requestId}/interview

- 설명: 소유한 분석 요청의 인터뷰 이력 조회
- 성공: `200 OK`
- 오류: `401`, `404`, `422`
- 쿠키 변경: 없음

```json
{
  "requestId": 1,
  "status": "INTERVIEWING",
  "messages": [
    {"role": "ASSISTANT", "content": "질문 내용"}
  ]
}
```

### POST /api/v1/analysis-requests/{requestId}/interview

- 설명: 인터뷰 답변 저장 및 다음 질문 조회
- 성공: `200 OK`
- 오류: `401`, `404`, `422`
- 쿠키 변경: 없음

```json
{"answer": "사용자 답변"}
```

```json
{
  "nextQuestion": "다음 질문",
  "status": "INTERVIEWING",
  "interviewCompleted": false
}
```

### POST /api/v1/analysis-requests/{requestId}/analyze

- 설명: 소유한 요청의 분석 실행
- Request Body: 없음
- 성공: `200 OK`
- 오류: `401`, `404`, `422`
- 쿠키 변경: 없음

```json
{"requestId": 1, "status": "COMPLETED"}
```

### GET /api/v1/analysis-requests/{requestId}/report

- 설명: 소유한 요청의 분석 리포트 조회
- 성공: `200 OK`
- 오류: `401`, `404`, `422`
- 쿠키 변경: 없음

```json
{
  "serviceSummary": {},
  "marketAnalysis": {},
  "competitorAnalysis": {},
  "targetCustomerAnalysis": {},
  "marketingStrategy": {},
  "platformRecommendation": {}
}
```

### GET /api/v1/analysis-requests/{requestId}/report/citations

- 설명: 소유한 리포트의 섹션별 참조 근거 조회
- 성공: `200 OK`
- 오류: `401`, `404`, `422`
- 쿠키 변경: 없음

각 섹션 값은 다음 evidence 배열이다.

```json
{
  "service_summary": [
    {
      "evidence_id": 1,
      "content": "근거 내용",
      "source": "출처",
      "metadata": {}
    }
  ],
  "market_analysis": [],
  "competitor_analysis": [],
  "target_customer_analysis": [],
  "marketing_strategy": [],
  "platform_recommendation": []
}
```

현재 구현에는 사용자별 분석 내역 목록 API가 없다.

## 6. Refresh Token 정책

- Access Token 기본 만료: 30분
- Refresh Token 기본 만료: 14일
- Access Token은 DB에 저장하지 않는다.
- Refresh Token 원문은 저장하지 않고 SHA-256 해시만 저장한다.
- 로그인마다 독립적인 Token Family를 생성해 다중 기기를 지원한다.
- Refresh 성공 시 기존 세션을 폐기하고 같은 family의 새 토큰으로 Rotation한다.
- 폐기된 Refresh Token이 재사용되면 해당 family 전체를 폐기한다.
- 같은 Refresh Token의 동시 갱신은 DB row lock으로 한 요청만 성공한다.
- 일반 로그아웃은 현재 기기의 family만 폐기하며 다른 기기 family는 유지한다.

## 7. 회원 탈퇴 정책

- 현재 Access Cookie로 인증된 본인만 탈퇴할 수 있다.
- 요청 Body에 `userId`를 받지 않는다.
- 현재 비밀번호 확인이 필요하다.
- User row를 물리 삭제한다.
- Refresh Session, 분석 요청, 인터뷰, 리포트, 인용, Retrieval 실행 및 근거가
  DB CASCADE로 삭제된다.
- Knowledge Document/Chunk와 다른 사용자 데이터는 유지된다.
- 삭제된 이메일로 다시 회원가입할 수 있다.
- 삭제 사용자의 기존 Access/Refresh Token은 거부된다.

## 8. 공통 오류

| 상태 | 실제 사용 위치 |
|---|---|
| `401` | 로그인 실패, Cookie 인증 실패, refresh 실패, 비밀번호 불일치 |
| `403` | refresh/logout/회원 탈퇴의 Origin 또는 Referer 불허 |
| `404` | 분석 데이터가 없거나 현재 사용자의 소유가 아님 |
| `409` | 회원가입 이메일 중복 |
| `422` | Body, Path, Cookie 등 FastAPI/Pydantic 요청 검증 실패 |
| `503` | DB Health 연결 실패 |

현재 Router/OpenAPI에서 명시적으로 확인되지 않은 400과 500은 이 문서의 API
계약 오류로 추가하지 않았다.
