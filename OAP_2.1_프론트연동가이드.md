# OAP 2.1 프론트 연동 가이드

## 기본 원칙

OAP는 JWT를 Secure HttpOnly Cookie로 전달한다. 프론트엔드는 토큰 값을 읽거나
저장하지 않고 브라우저의 Cookie 처리를 사용한다.

금지 사항:

- `localStorage` 또는 `sessionStorage`에 JWT 저장
- JWT를 직접 decode해 로그인 상태 판단
- `Authorization: Bearer` 수동 설정
- 로그인/refresh 응답에서 토큰 필드 추출 시도

## 회원가입과 Google 로그인

이메일 회원가입은 `name`, `termsAgreed=true`, `privacyAgreed=true`가 필수다.
`marketingAgreed`는 생략할 수 있고 기본값은 `false`다. 회원가입만으로 로그인되지는
않는다.

```javascript
await api.post("/api/v1/auth/signup", {
  email, password, name,
  termsAgreed: true,
  privacyAgreed: true,
  marketingAgreed: false,
});
```

`name`은 서버에서 trim하며 빈 문자열이나 공백만으로 구성된 값은 422로 거부된다.
필수 동의가 `false`여도 422이고, 마케팅 미동의는 가입 실패 사유가 아니다.
이미 등록된 이메일은 409를 반환한다.

Google 로그인은 Google Identity Services가 발급한 단기 ID Token을 백엔드로
전송한다. ID Token은 저장하지 않는다.

```javascript
await api.post("/api/v1/auth/google", {
  idToken: googleCredential,
  termsAgreed: true,
  privacyAgreed: true,
  marketingAgreed: false,
});
```

응답과 Cookie 계약은 이메일 로그인과 같다. 같은 이메일의 일반 계정은 자동으로
연결하지 않고 409를 반환한다.

Google Identity Services의 공개 설정값인 Client ID는 프론트 설정에 둘 수 있지만,
Google Client Secret은 프론트 번들에 포함하면 안 된다. `idToken`은 백엔드 요청에
즉시 사용하고 localStorage/sessionStorage에 장기 저장하지 않는다. 신규 Google
사용자는 검증된 Google 프로필로 생성되고 동의 이력이 저장되며, 이미
`google_sub`가 연결된 사용자는 기존 계정으로 로그인한다. 재로그인 요청에도
`termsAgreed=true`와 `privacyAgreed=true`를 보내지만 서버는 기존 동의 이력을
중복 생성하지 않는다. `GOOGLE_CLIENT_ID`가 설정되지 않은 경우 503을 반환한다.

운영 API와 프론트 Origin은 아직 미확정이다. 운영 환경에서는
`CORS_ALLOWED_ORIGINS`로 프론트 Origin을 주입하며 Swagger, ReDoc, OpenAPI JSON은
노출하지 않는다.

## fetch

```javascript
const response = await fetch(
  `${API_BASE_URL}/api/v1/auth/me`,
  {
    method: "GET",
    credentials: "include",
  },
);
```

JSON Body가 있는 요청:

```javascript
await fetch(`${API_BASE_URL}/api/v1/auth/login`, {
  method: "POST",
  credentials: "include",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({email, password}),
});
```

## Axios

인스턴스에 공통 설정하는 방식을 권장한다.

```javascript
import axios from "axios";

export const api = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
  headers: {"Content-Type": "application/json"},
});
```

## 로그인 상태 확인

페이지 초기화 또는 보호 화면 진입 시 다음 API를 호출한다.

```http
GET /api/v1/auth/me
```

- 200: 응답 사용자 정보를 로그인 상태로 사용
- 401: Access Token이 없거나 사용할 수 없음

JWT 만료 시간을 프론트에서 decode해 로그인 상태를 결정하지 않는다.

## 401 및 Refresh 처리

보호 API가 401을 반환하면:

1. `POST /api/v1/auth/refresh`를 최대 1회 호출한다.
2. refresh가 200이면 실패했던 원 요청을 최대 1회 재시도한다.
3. refresh도 401이면 로그인 화면으로 이동한다.
4. refresh 요청 자체에는 다시 refresh interceptor를 적용하지 않는다.
5. 원 요청 재시도가 다시 401이어도 추가 refresh를 반복하지 않는다.

간단한 fetch 예:

```javascript
async function requestWithRefresh(path, options = {}) {
  const requestOptions = {...options, credentials: "include"};
  let response = await fetch(`${API_BASE_URL}${path}`, requestOptions);

  if (response.status !== 401 || path === "/api/v1/auth/refresh") {
    return response;
  }

  const refreshed = await fetch(`${API_BASE_URL}/api/v1/auth/refresh`, {
    method: "POST",
    credentials: "include",
  });

  if (!refreshed.ok) {
    window.location.assign("/login");
    return response;
  }

  return fetch(`${API_BASE_URL}${path}`, requestOptions);
}
```

동시에 여러 API가 401을 반환할 수 있으므로 실제 구현에서는 진행 중인 refresh
Promise를 공유해 중복 rotation을 막아야 한다.

백엔드는 refresh 성공 시 Refresh Token을 회전한다. 이미 교체되었거나 폐기된
토큰의 재사용은 해당 token family를 폐기하므로, 프론트의 동시 refresh 호출을
반드시 하나의 Promise로 단일화한다.

## 로그인과 로그아웃

- signup은 계정만 생성하며 자동 로그인하지 않는다.
- login 성공 후 Cookie가 설정된다.
- logout은 현재 기기의 Refresh Token family를 폐기하고 두 Cookie를 삭제한다.
- 다른 기기 로그인 세션은 유지된다.

logout/refresh/회원 탈퇴는 브라우저 Origin 검증 대상이다.

로그아웃은 반드시 서버 API를 호출한 뒤 클라이언트 사용자 상태를 제거한다.
HttpOnly Cookie는 JavaScript로 직접 읽거나 삭제하지 않고 서버의 Set-Cookie
응답으로 삭제한다.

## 분석 요청 소유권

- 분석 API에는 `userId`를 보내지 않는다.
- 새 분석 요청은 Access Cookie의 현재 사용자에게 자동 귀속된다.
- 다른 사용자의 `requestId` 또는 없는 `requestId` 접근은 404로 처리된다.

## 회원 탈퇴

일반 계정은 현재 비밀번호로 재인증한다.

```javascript
await api.delete("/api/v1/auth/me", {
  data: {password: currentPassword},
});
```

Google 계정은 탈퇴 버튼을 확정한 직후 Google Identity Services에서 새로운 ID
Token을 받아 재인증한다. 로그인 때 받은 기존 토큰을 저장해 재사용하지 않는다.

```javascript
const freshIdToken = await requestFreshGoogleIdToken();

await api.delete("/api/v1/auth/me", {
  data: {idToken: freshIdToken},
});
```

`password`와 `idToken`을 동시에 보내지 않는다. 둘 다 없거나 가입 방식과 맞지
않는 값을 보내면 401이다. 잘못된 비밀번호·토큰 또는 Google `sub` 불일치도
401이며, 서버에 `GOOGLE_CLIENT_ID`가 설정되지 않은 경우 503이다.

성공하면 계정과 사용자 소유 분석 데이터가 물리 삭제되고 인증 Cookie도 삭제된다.
Knowledge 데이터는 유지되며 동일 이메일 재가입이 가능하다.

삭제는 되돌리기 어렵다. DB의 cascade 정책에 따라 Refresh Session, 필수·마케팅
동의 이력, 분석 요청, 인터뷰, 리포트와 리포트 인용 관계가 함께 제거된다.

## 동의 조회와 마케팅 동의 변경

프론트는 DB 테이블을 직접 다루지 않고 다음 API만 사용한다.

```javascript
const consents = await api.get("/api/v1/auth/consents");

await api.patch("/api/v1/auth/consents/marketing", {
  agreed: false,
});
```

- 응답은 `current`와 `history` 배열이며 각 항목은 `type`, `documentVersion`,
  `agreed`, `occurredAt`을 가진다.
- 필수약관·개인정보 동의 이력과 마케팅 선택 동의 이력은 서버에서 분리 저장된다.
- 마케팅 동의와 철회 모두 새로운 이력으로 기록된다. 프론트의 현재 Boolean 표시는
  `current`의 최신 상태이며 서버 이력 전체를 대체하지 않는다.

## 리포트 목록과 근거 조회

프론트가 마지막 `requestId` 하나만 저장해 목록을 구성하지 않는다.

1. `GET /api/v1/reports?page=0&size=20`으로 현재 사용자의 완료 리포트 목록을 조회한다.
2. 선택한 항목의 `requestId`로
   `GET /api/v1/analysis-requests/{requestId}/report`를 호출한다.
3. 같은 `requestId`로
   `GET /api/v1/analysis-requests/{requestId}/report/citations`를 호출한다.

없는 요청과 다른 사용자의 요청은 모두 404로 처리되어 소유권 정보가 노출되지 않는다.

## Cookie, CORS와 배포

- Access Cookie: HttpOnly, 기본 Secure=true, 기본 SameSite=None, Path `/`,
  Access Token 만료 시간과 같은 Max-Age.
- Refresh Cookie: HttpOnly, 기본 Secure=true, 기본 SameSite=None,
  Path `/api/v1/auth`, Refresh Token 만료 기간과 같은 Max-Age.
- `COOKIE_SECURE`와 `COOKIE_SAMESITE`는 배포 환경에서 변경할 수 있다.
  Cookie domain은 `COOKIE_DOMAIN`이 설정된 경우에만 사용되므로 문서에서 특정
  domain을 가정하지 않는다.
- Refresh Cookie의 제한된 Path 때문에 `/api/v1/auth` 밖의 API에는 Refresh
  Cookie가 전송되지 않는 것이 정상이다.
- `CORS_ALLOWED_ORIGINS`는 comma-separated 목록이며 미설정 시
  `http://localhost:3000`, `http://localhost:3001`, `http://localhost:5173`을
  개발 기본값으로 사용한다. 빈 값과 중복은 제거하고 끝의 `/`는 정규화한다.
- CORS는 credentials를 허용하므로 `Access-Control-Allow-Origin: *`를 사용할 수 없다.
- 운영 프론트와 API 주소는 아직 미확정이며, 확정 후 HTTPS Origin을 배포 환경변수로 주입한다.
- HTTP localhost 또는 서버 IP에서는 Postman과 브라우저가 Secure Cookie를
  전송하지 않아 인증이 실패할 수 있다.

## Report schemaVersion 3.0 렌더링

- 기존 6개 섹션의 `title`, `summary`, `insights`, `recommendations`를 항상 텍스트 fallback으로 유지한다.
- `headlineMetrics`는 상단 카드로 표시하되 `value=null`이면 숫자를 만들지 말고 `displayText` 또는 기존 요약을 사용한다.
- `direction=lower_is_better`인 경쟁 강도는 낮은 값을 긍정적으로 표시한다.
- `valueType`과 `confidence`를 함께 표시해 observed/derived/estimated를 구분한다.
- `marketAnalysis.purchaseFactors`, `competitorAnalysis.messageCoverage`, `targetCustomerAnalysis.segments`, `marketingStrategy.executionPhases`, `platformRecommendation.rankedPlatforms`가 비어 있으면 해당 차트를 숨긴다.
- P1 `opportunityMatrix`, `demandTrend`, `competitors`, `scoreBreakdown`이 없거나 비어 있으면 차트를 숨기며 임의 데이터를 만들지 않는다.
- P2 필드가 `null`이면 실제 성과 연동 전 상태이므로 달성률이나 성과를 표시하지 않는다.
- `evidenceIds`는 citations API의 `evidence_id`와 연결해 근거 툴팁을 표시한다.
- `expected_effect`는 예상 가설이며 보장된 효과로 표현하지 않는다.
- Legacy `schemaVersion=2.1-legacy`는 기존 텍스트 중심 화면으로 표시한다.
- 동일 점수의 고객군·플랫폼은 API 입력 순서를 유지하는 안정 정렬을 전제로 한다.
