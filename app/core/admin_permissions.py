ROLE_PERMISSIONS = {
    "analyst": frozenset({"dashboard:read", "events:read", "errors:read"}),
    "support": frozenset(
        {"dashboard:read", "users:read", "events:read", "errors:read"}
    ),
    "super_admin": frozenset(
        {
            "dashboard:read",
            "users:read",
            "events:read",
            "errors:read",
            "audit:read",
            "admins:manage",
        }
    ),
}


class InvalidAdminRoleError(ValueError):
    pass


def permissions_for_role(role: str) -> frozenset[str]:
    try:
        return ROLE_PERMISSIONS[role]
    except KeyError as exc:
        raise InvalidAdminRoleError("Invalid administrator role") from exc


def role_has_permission(role: str, permission: str) -> bool:
    return permission in permissions_for_role(role)
