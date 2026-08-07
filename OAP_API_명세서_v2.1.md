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
| OpenAPI operation 수 | 18 |
| Postman 요청 수 | 28 |

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
- 운영 API와 프론트 Origin은 아직 미확정이며 실제 값은 배포 환경에서 주입한다.
- `APP_ENV=production`에서는 `/docs`, `/redoc`, `/openapi.json`을 노출하지 않는다.
- `CORS_ALLOWED_ORIGINS`는 comma-separated Origin 목록이다. 미설정 시 개발 기본값은
  `http://localhost:3000`, `http://localhost:3001`, `http://localhost:5173`이다.
  빈 값과 중복은 제거하고 끝의 `/`는 정규화하며 wildcard는 허용하지 않는다.
  refresh/logout/회원 탈퇴는 CORS middleware와 같은 목록을 사용하고, 전달된 Origin
  또는 Referer가 이 목록에 없으면 403을 반환한다.

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

`SignupResponse.name`과 로그인 계열에서 사용하는 `LoginResponse.name`은 현재
Schema 기준 `string | null`이다. DB의 `users.name NOT NULL`과의 차이는 이 문서
마지막의 잔여 정합성 검토사항을 참고한다.

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
| `name` | string | O | 1~100자, trim 후 빈 문자열 또는 공백만 입력 불가 |
| `termsAgreed` | boolean | O | 반드시 `true` |
| `privacyAgreed` | boolean | O | 반드시 `true` |
| `marketingAgreed` | boolean | X | 선택 동의, 생략 시 `false` |

```json
{
  "email": "user@example.com",
  "password": "example-password",
  "name": "홍길동",
  "termsAgreed": true,
  "privacyAgreed": true,
  "marketingAgreed": false
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

### POST /api/v1/auth/google

- 설명: Google Identity Services가 발급한 단기 ID Token을 백엔드에서 검증하고 로그인한다. 신규 사용자에게는 필수·선택 동의 이력을 저장한다.
- 인증: 사전 로그인 불필요. 허용된 `Origin` 또는 `Referer` 필요
- 성공: `200 OK`
- 쿠키 변경: `access_token`, `refresh_token` 설정
- 오류:
  - `401`: 잘못된 토큰, 만료된 토큰, audience 불일치 또는 미인증 Google 이메일
  - `403`: 허용되지 않은 Origin/Referer
  - `409`: 같은 이메일이 다른 로그인 방식으로 이미 등록됨
  - `422`: 요청 검증 실패 또는 유효하지 않은 Google 프로필
  - `503`: `GOOGLE_CLIENT_ID` 미설정

| 필드 | 타입 | 필수 | 제약 |
|---|---|---:|---|
| `idToken` | string | O | 빈 문자열 불가 |
| `termsAgreed` | boolean | O | 반드시 `true` |
| `privacyAgreed` | boolean | O | 반드시 `true` |
| `marketingAgreed` | boolean | X | 생략 시 `false` |

동의 필드는 신규 사용자 생성 시에만 이력으로 저장한다. 이미 같은
`google_sub`로 연결된 사용자의 재로그인도 `termsAgreed=true`와
`privacyAgreed=true`를 보내야 하지만 기존 동의 이력을 중복 생성하지 않는다.

```json
{
  "idToken": "<short-lived-google-id-token>",
  "termsAgreed": true,
  "privacyAgreed": true,
  "marketingAgreed": false
}
```

```json
{"id": 1, "email": "user@example.com", "name": "홍길동", "status": "ACTIVE"}
```

> 실제 Google ID Token은 문서, 로그, localStorage 또는 sessionStorage에 저장하지 않는다.

### GET /api/v1/auth/consents

- 설명: 현재 사용자의 필수 동의와 마케팅 동의의 현재 상태 및 전체 이력을 조회한다.
- 인증: `access_token` HttpOnly Cookie 필요
- Request Body: 없음
- 성공: `200 OK`
- 오류: `401` Access Cookie가 없거나 유효하지 않음
- 쿠키 변경: 없음

```json
{
  "current": [
    {"type": "TERMS", "documentVersion": "1.0", "agreed": true, "occurredAt": "2026-08-06T10:00:00Z"},
    {"type": "PRIVACY", "documentVersion": "1.0", "agreed": true, "occurredAt": "2026-08-06T10:00:00Z"},
    {"type": "MARKETING", "documentVersion": "1.0", "agreed": false, "occurredAt": "2026-08-06T10:00:00Z"}
  ],
  "history": []
}
```

### PATCH /api/v1/auth/consents/marketing

- 설명: 마케팅 동의 또는 철회 이력을 추가한다.
- 인증: `access_token` HttpOnly Cookie 및 허용된 Origin/Referer 필요
- 성공: `200 OK`
- 오류:
  - `401`: Access Cookie가 없거나 유효하지 않음
  - `403`: 허용되지 않은 Origin/Referer
  - `422`: `agreed`가 boolean이 아니거나 요청 검증 실패
- 쿠키 변경: 없음

```json
{"agreed": true}
```

```json
{"type": "MARKETING", "documentVersion": "1.0", "agreed": true, "occurredAt": "2026-08-06T10:05:00Z"}
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
  - `401` — 인증 실패, 재인증 값 누락, 가입 방식과 맞지 않는 재인증 값,
    잘못된 비밀번호·Google ID Token 또는 Google `sub` 불일치
  - `403` — 허용되지 않은 Origin/Referer
  - `422` — 요청 검증 실패
  - `503` — Google 계정 재인증에 필요한 `GOOGLE_CLIENT_ID` 미설정
- 쿠키 변경: Access/Refresh Cookie 삭제

| 필드 | 타입 | 필수 | 제약 |
|---|---|---:|---|
| `password` | string/null | X | 일반 계정 재인증용, 1~72자 및 UTF-8 72바이트 이하 |
| `idToken` | string/null | X | Google 계정 재인증용 최신 Google ID Token |

두 필드는 Schema상 optional이지만 현재 계정의 가입 방식에 맞는 한 필드는 반드시
필요하다. 일반 계정은 `password`만, Google 계정은 `idToken`만 전송한다.

일반 계정 요청:

```json
{"password": "current-password"}
```

Google 계정 요청:

```json
{"idToken": "fresh-google-id-token"}
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
  "serviceSummary": {"title": "서비스 요약", "summary": "...", "insights": [], "recommendations": []},
  "marketAnalysis": {"title": "시장 분석", "summary": "...", "insights": [], "recommendations": [], "metrics": [], "purchaseFactors": [], "opportunityMatrix": null, "demandTrend": null},
  "competitorAnalysis": {"title": "경쟁 분석", "summary": "...", "insights": [], "recommendations": [], "competitorCount": null, "analyzedCopyCount": null, "messageCoverage": [], "competitors": []},
  "targetCustomerAnalysis": {"title": "고객 분석", "summary": "...", "insights": [], "recommendations": [], "segments": [], "scoringModelVersion": null},
  "marketingStrategy": {"title": "마케팅 전략", "summary": "...", "insights": [], "recommendations": [], "executionPhases": [], "currentKpiValue": null, "targetAchievementRate": null, "previousReportDelta": null, "actualCampaignPerformance": null, "recommendationOutcomeGap": null},
  "platformRecommendation": {"title": "플랫폼 추천", "summary": "...", "insights": [], "recommendations": [], "rankedPlatforms": [], "currentKpiValue": null, "targetAchievementRate": null, "previousReportDelta": null, "actualCampaignPerformance": null, "recommendationOutcomeGap": null},
  "reportMeta": {"schemaVersion": "3.0", "requestId": 123, "generatedAt": "2026-08-01T00:00:00Z", "dataAsOf": null, "overallConfidence": null, "evidenceCount": 0, "analysisLocale": "ko-KR"},
  "headlineMetrics": [
    {"key": "market_attractiveness", "label": "시장 매력도", "value": null, "unit": "score", "scale": null, "direction": "higher_is_better", "displayLevel": null, "displayText": null, "valueType": "estimated", "confidence": null, "sampleSize": null, "evidenceIds": [], "calculation": null, "asOf": null},
    {"key": "competitive_intensity", "label": "경쟁 강도", "value": null, "unit": "score", "scale": null, "direction": "lower_is_better", "displayLevel": null, "displayText": null, "valueType": "estimated", "confidence": null, "sampleSize": null, "evidenceIds": [], "calculation": null, "asOf": null},
    {"key": "target_clarity", "label": "타깃 명확도", "value": null, "unit": "score", "scale": null, "direction": "higher_is_better", "displayLevel": null, "displayText": null, "valueType": "estimated", "confidence": null, "sampleSize": null, "evidenceIds": [], "calculation": null, "asOf": null},
    {"key": "evidence_coverage", "label": "근거 커버리지", "value": 0, "unit": "count", "scale": null, "direction": "higher_is_better", "displayLevel": null, "displayText": null, "valueType": "observed", "confidence": 1, "sampleSize": null, "evidenceIds": [], "calculation": "실제 report_citations 행 수", "asOf": null}
  ]
}
```

위 숫자와 ID는 응답 형태를 설명하기 위한 예시이며 운영 성과 보장값이 아니다.
`score`는 `0~100`, confidence/rate는 `0~1`, 근거 없는 값은 `null`이다.
Legacy 데이터는 기존 텍스트를 유지하고 `schemaVersion="2.1-legacy"`, 신규 배열 `[]`, 신규 단일값 `null`로 반환한다.
전체 시각화 계약은 `docs/OAP_report_visual_metrics_backend_contract.md`를 따른다.

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

### GET /api/v1/reports

- 설명: 인증된 현재 사용자의 완료 리포트를 최신 생성순으로 조회
- Query: `page` 기본 `0`, 최솟값 `0`; `size` 기본 `20`, 허용 범위 `1~100`
- 성공: `200 OK` (빈 목록 포함)
- 오류: `401`, `422`
- 요청에 `userId`를 받지 않으며 다른 사용자의 항목은 반환하지 않는다.

```json
{
  "items": [
    {
      "requestId": 1,
      "serviceName": "서비스명",
      "oneLineDescription": "한 줄 설명",
      "industry": "산업",
      "status": "COMPLETED",
      "createdAt": "2026-08-01T00:00:00Z"
    }
  ],
  "page": 0,
  "size": 20,
  "totalElements": 1,
  "totalPages": 1
}
```

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
- 일반 계정은 현재 비밀번호로 재인증한다.
- Google 계정은 탈퇴 직전에 새로 발급받은 Google ID Token으로 재인증하며,
  검증된 `sub`가 현재 사용자의 `google_sub`와 일치해야 한다.
- `password`와 `idToken`을 동시에 보내지 않는다.
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

## 9. 잔여 정합성 검토사항

- 실제 DB의 `users.name`은 `NOT NULL`이고 회원가입 요청도 `name` 필수이지만,
  현재 `SignupResponse.name`과 `LoginResponse.name` Schema는 `string | null`을
  허용한다. 이 문서의 응답 계약은 현재 Schema를 따라 `name`을 nullable로
  간주하며, 향후 코드 계약을 강화할지는 별도 검토한다.
| `404` | 분석 데이터가 없거나 현재 사용자의 소유가 아님 |
| `409` | 회원가입 이메일 중복 |
| `422` | Body, Path, Cookie 등 FastAPI/Pydantic 요청 검증 실패 |
| `503` | DB Health 연결 실패 |

현재 Router/OpenAPI에서 명시적으로 확인되지 않은 400과 500은 이 문서의 API
계약 오류로 추가하지 않았다.
