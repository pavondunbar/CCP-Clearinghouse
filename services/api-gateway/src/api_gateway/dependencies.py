"""FastAPI dependency injection for database connections and auth."""

from collections.abc import Generator
from functools import lru_cache

import psycopg
from fastapi import Depends, HTTPException, Request

from ccp_shared.auth import Role, has_permission, resolve_role
from ccp_shared.config import CCPSettings
from ccp_shared.db.connection import (
    get_ledger_connection,
    get_readonly_connection,
)


@lru_cache(maxsize=1)
def get_settings() -> CCPSettings:
    """Return cached application settings.

    Returns:
        Shared CCPSettings instance.
    """
    return CCPSettings()


def get_ledger_conn() -> Generator[psycopg.Connection, None, None]:
    """Yield a ledger database connection, closing it after use.

    Yields:
        An open psycopg Connection for ledger operations.
    """
    settings = get_settings()
    conn = get_ledger_connection(settings)
    try:
        yield conn
    finally:
        conn.close()


def get_readonly_conn() -> Generator[psycopg.Connection, None, None]:
    """Yield a read-only database connection, closing it after use.

    Yields:
        An open psycopg Connection for read-only queries.
    """
    settings = get_settings()
    conn = get_readonly_connection(settings)
    try:
        yield conn
    finally:
        conn.close()


def get_current_role(
    request: Request,
    settings: CCPSettings = Depends(get_settings),
) -> Role:
    """Extract and validate the API key from the Authorization header.

    Args:
        request: The incoming HTTP request.
        settings: Application settings with API keys.

    Returns:
        The resolved Role for the authenticated caller.

    Raises:
        HTTPException: 401 if no key provided, 403 if key invalid.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header",
        )
    api_key = auth_header[7:]
    api_keys = settings.parsed_api_keys()
    if not api_keys:
        return Role.ADMIN

    role = resolve_role(api_keys, api_key)
    if role is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key",
        )
    return role


def require_permission(permission: str):
    """Return a FastAPI dependency that checks a specific permission.

    Args:
        permission: The required permission string.

    Returns:
        A dependency function that raises 403 on failure.
    """
    def _check(role: Role = Depends(get_current_role)) -> Role:
        if not has_permission(role, permission):
            raise HTTPException(
                status_code=403,
                detail=f"Permission denied: {permission}",
            )
        return role
    return _check
