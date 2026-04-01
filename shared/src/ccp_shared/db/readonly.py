"""Read-only connection wrapper that prevents write operations."""

from typing import Any

import psycopg

from ccp_shared.errors import ValidationError


_ALLOWED_PREFIXES = ("SELECT", "WITH", "EXPLAIN")


class ReadOnlyConnection:
    """Wrapper around a psycopg Connection that only permits SELECT queries.

    Args:
        conn: An open psycopg Connection.
    """

    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def execute(
        self,
        query: str,
        params: tuple[Any, ...] | None = None,
    ) -> psycopg.Cursor:
        """Execute a read-only SQL query.

        Args:
            query: SQL query string (must be a SELECT).
            params: Optional query parameters.

        Returns:
            A psycopg Cursor with query results.

        Raises:
            ValidationError: If the query is not a SELECT statement.
        """
        stripped = query.strip().upper()
        if not stripped.startswith(_ALLOWED_PREFIXES):
            raise ValidationError(
                f"ReadOnlyConnection only allows SELECT queries, "
                f"got: {query[:50]}"
            )
        if params is not None:
            return self._conn.execute(query, params)
        return self._conn.execute(query)

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()

    def __enter__(self) -> "ReadOnlyConnection":
        return self

    def __exit__(self, exc_type: type | None, *_: object) -> None:
        self.close()
