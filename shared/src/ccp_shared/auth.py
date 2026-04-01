"""Application-level RBAC for CCP Clearing House."""

from enum import Enum


class Role(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    SYSTEM = "system"
    SIGNER = "signer"
    VIEWER = "viewer"


ROLE_PERMISSIONS: dict[Role, set[str]] = {
    Role.ADMIN: {
        "trade.submit",
        "trade.read",
        "member.read",
        "member.manage",
        "withdrawal.approve",
        "netting.trigger",
        "reconcile.run",
        "dlq.read",
    },
    Role.OPERATOR: {
        "trade.submit",
        "trade.read",
        "member.read",
        "netting.trigger",
    },
    Role.SYSTEM: {
        "event.publish",
        "state.transition",
        "settlement.execute",
    },
    Role.SIGNER: {
        "sign.transaction",
    },
    Role.VIEWER: {
        "trade.read",
        "member.read",
    },
}


def resolve_role(api_keys: dict[str, str], api_key: str) -> Role | None:
    """Look up the role for a given API key.

    Args:
        api_keys: Mapping of API key -> role name.
        api_key: The key provided in the Authorization header.

    Returns:
        The resolved Role, or None if key is unknown.
    """
    role_name = api_keys.get(api_key)
    if role_name is None:
        return None
    try:
        return Role(role_name)
    except ValueError:
        return None


def has_permission(role: Role, permission: str) -> bool:
    """Check if a role has a specific permission.

    Args:
        role: The actor's role.
        permission: The permission to check (e.g. 'trade.submit').

    Returns:
        True if the role includes the permission.
    """
    return permission in ROLE_PERMISSIONS.get(role, set())
