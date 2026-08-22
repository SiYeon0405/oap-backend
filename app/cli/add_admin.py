import getpass
import sys

from pydantic import ValidationError

from app.services.admin_add_service import (
    ADMIN_ROLES,
    AdminAddError,
    AdminAddService,
    AdminEmailExistsError,
    InvalidAdminRoleError,
)
from app.services.admin_security import AdminSecurityConfigurationError


def main() -> int:
    if len(sys.argv) != 1:
        print("Command-line arguments are not supported.", file=sys.stderr)
        return 1

    try:
        email = input("Administrator email: ")
        name = input("Administrator name: ")
        password = getpass.getpass("Password: ")
        confirmation = getpass.getpass("Confirm password: ")
        if password != confirmation:
            print("Passwords do not match.", file=sys.stderr)
            return 1
        role = input("Role (analyst/support/super_admin): ").strip()
        if role not in ADMIN_ROLES:
            raise InvalidAdminRoleError

        result = AdminAddService().create_admin(
            email=email,
            name=name,
            password=password,
            role=role,
        )
    except AdminEmailExistsError:
        print("An administrator with that email already exists.", file=sys.stderr)
        return 1
    except InvalidAdminRoleError:
        print("Invalid administrator role.", file=sys.stderr)
        return 1
    except ValidationError:
        print("Invalid administrator input.", file=sys.stderr)
        return 1
    except AdminSecurityConfigurationError:
        print("Administrator security is not configured.", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, AdminAddError, Exception):
        print("Administrator creation failed.", file=sys.stderr)
        return 1

    print("Administrator created.")
    print(f"Account label: {result.account_label}")
    print(f"Issuer: {result.issuer}")
    print(f"Authenticator registration URI: {result.otpauth_uri}")
    print("Register this account in its owner's Authenticator now; do not share it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
