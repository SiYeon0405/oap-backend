import getpass
import sys

from pydantic import ValidationError

from app.services.admin_bootstrap_service import (
    AdminAlreadyExistsError,
    AdminBootstrapService,
)
from app.services.admin_security import AdminSecurityConfigurationError


def main() -> int:
    if len(sys.argv) != 1:
        print("명령행 인수를 지원하지 않습니다.", file=sys.stderr)
        return 1

    try:
        email = input("관리자 이메일: ")
        name = input("관리자 이름: ")
        password = getpass.getpass("비밀번호: ")
        confirmation = getpass.getpass("비밀번호 확인: ")
        if password != confirmation:
            print("비밀번호가 일치하지 않습니다.", file=sys.stderr)
            return 1

        result = AdminBootstrapService().create_first_admin(
            email=email,
            name=name,
            password=password,
        )
    except AdminAlreadyExistsError:
        print("최초 관리자 계정이 이미 존재합니다.", file=sys.stderr)
        return 1
    except ValidationError:
        print("관리자 입력값이 올바르지 않습니다.", file=sys.stderr)
        return 1
    except AdminSecurityConfigurationError:
        print("관리자 보안 설정이 올바르지 않습니다.", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, Exception):
        print("최초 관리자 계정 생성에 실패했습니다.", file=sys.stderr)
        return 1

    print("최초 관리자 계정이 생성되었습니다.")
    print(f"계정 라벨: {result.account_label}")
    print(f"발급자: {result.issuer}")
    print(f"Authenticator 등록 URI: {result.otpauth_uri}")
    print("이 정보는 최초 등록을 위해 한 번만 표시됩니다.")
    print("안전한 Authenticator에 즉시 등록하십시오.")
    print("화면 공유 및 로그 저장을 하지 마십시오.")
    print("등록하지 않고 터미널을 닫으면 임의 복구 기능이 없습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
