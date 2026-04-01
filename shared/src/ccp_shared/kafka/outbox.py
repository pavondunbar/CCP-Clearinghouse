"""Transactional outbox event insertion for reliable event publishing."""

import json
import uuid
from typing import Any
from uuid import UUID

import psycopg


def insert_outbox_event(
    conn: psycopg.Connection,
    aggregate_type: str,
    aggregate_id: UUID,
    event_type: str,
    topic: str,
    payload: dict[str, Any],
    trace_id: str | None = None,
) -> str:
    """Insert an event into the outbox_events table.

    Generates a unique event_id and embeds it in the payload for
    downstream consumer idempotency. Optionally stores trace_id
    for audit correlation.

    Args:
        conn: An open psycopg Connection (within a transaction).
        aggregate_type: Type of aggregate (e.g., 'trade', 'member').
        aggregate_id: UUID of the aggregate instance.
        event_type: Event name (e.g., 'TradeSubmitted').
        topic: Target Kafka topic.
        payload: Event payload to serialize as JSON.
        trace_id: Optional trace UUID for audit correlation.

    Returns:
        The generated event_id string.
    """
    event_id = str(uuid.uuid4())
    payload_with_id = {**payload, "event_id": event_id}
    if trace_id:
        payload_with_id["trace_id"] = trace_id

    conn.execute(
        """
        INSERT INTO outbox_events
            (aggregate_type, aggregate_id, event_type,
             topic, payload, trace_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            aggregate_type,
            str(aggregate_id),
            event_type,
            topic,
            json.dumps(payload_with_id, default=str),
            trace_id,
        ),
    )
    return event_id
