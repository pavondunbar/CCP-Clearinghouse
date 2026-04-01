"""Consumer-side idempotency layer for event deduplication."""

import logging

import psycopg

logger = logging.getLogger(__name__)


def process_if_new(
    conn: psycopg.Connection,
    service_name: str,
    event_id: str,
) -> bool:
    """Check if event was already processed; if not, mark it.

    Uses INSERT ... ON CONFLICT DO NOTHING and checks rowcount
    to atomically determine whether this is a new event.

    Args:
        conn: Open database connection (within a transaction).
        service_name: Identifier for the consuming service.
        event_id: UUID string of the event.

    Returns:
        True if the event is new and was marked as processed.
        False if it was already processed (duplicate).
    """
    cur = conn.execute(
        """
        INSERT INTO processed_events (service_name, event_id)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
        """,
        (service_name, event_id),
    )
    is_new = cur.rowcount > 0
    if not is_new:
        logger.debug(
            "Duplicate event skipped: service=%s event_id=%s",
            service_name,
            event_id,
        )
    return is_new
