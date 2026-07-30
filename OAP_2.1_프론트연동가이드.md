# OAP 2.1 프론트 연동 가이드

## 기본 원칙

OAP는 JWT를 Secure HttpOnly Cookie로 전달한다. 프론트엔드는 토큰 값을 읽거나
저장하지 않고 브라우저의 Cookie 처리를 사용한다.

금지 사항:

- `localStorage` 또는 `sessionStorage`에 JWT 저장
- JWT를 직접 decode해 로그인 상태 판단
- `Authorization: Bearer` 수동 설정
- 로그인/refresh 응답에서 토큰 필드 추출 시도

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

## 로그인과 로그아웃

- signup은 계정만 생성하며 자동 로그인하지 않는다.
- login 성공 후 Cookie가 설정된다.
- logout은 현재 기기의 Refresh Token family를 폐기하고 두 Cookie를 삭제한다.
- 다른 기기 로그인 세션은 유지된다.

logout/refresh/회원 탈퇴는 브라우저 Origin 검증 대상이다.

## 분석 요청 소유권

- 분석 API에는 `userId`를 보내지 않는다.
- 새 분석 요청은 Access Cookie의 현재 사용자에게 자동 귀속된다.
- 다른 사용자의 `requestId` 또는 없는 `requestId` 접근은 404로 처리된다.

## 회원 탈퇴

```javascript
await api.delete("/api/v1/auth/me", {
  data: {password: currentPassword},
});
```

성공하면 계정과 사용자 소유 분석 데이터가 물리 삭제되고 인증 Cookie도 삭제된다.
Knowledge 데이터는 유지되며 동일 이메일 재가입이 가능하다.

## 현재 배포 제한

- 실제 프론트 배포 주소가 확정되지 않았다.
- HTTPS가 구성되지 않았다.
- CORS/Origin 허용 목록은 현재 localhost 3000, 3001, 5173뿐이다.
- 운영 기본 `Secure=true`, `SameSite=None` Cookie는 HTTPS가 필요하다.
- 실제 배포 도메인이 확정되면 Backend CORS/Origin 목록과 Cookie domain을 함께
  수정하고 HTTPS 환경에서 재검증해야 한다.
- HTTP localhost 또는 서버 IP에서는 Postman과 브라우저가 Secure Cookie를
  전송하지 않아 인증이 실패할 수 있다.
