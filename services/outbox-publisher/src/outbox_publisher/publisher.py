"""Outbox polling loop that publishes pending events to Kafka."""

import asyncio
import logging
from typing import Any
from uuid import UUID

import psycopg

from ccp_shared.config import CCPSettings
from ccp_shared.db.connection import get_ledger_connection
from ccp_shared.kafka.producer import KafkaProducer

logger = logging.getLogger(__name__)


def fetch_unpublished_batch(
    conn: psycopg.Connection,
    batch_size: int,
) -> list[dict[str, Any]]:
    """Fetch a batch of unpublished outbox events with row locking.

    Uses FOR UPDATE SKIP LOCKED to allow concurrent publishers
    without contention.

    Args:
        conn: Database connection (must be in a transaction).
        batch_size: Maximum number of events to fetch.

    Returns:
        List of event dicts with id, aggregate_type, aggregate_id,
        event_type, topic, payload, and trace_id columns.
    """
    cur = conn.execute(
        """
        SELECT id, aggregate_type, aggregate_id,
               event_type, topic, payload, trace_id
        FROM outbox_events
        WHERE published_at IS NULL
        ORDER BY created_at
        LIMIT %s
        FOR UPDATE SKIP LOCKED
        """,
        (batch_size,),
    )
    columns = [desc.name for desc in cur.description]
    return [
        dict(zip(columns, row, strict=True))
        for row in cur.fetchall()
    ]


def publish_batch(
    producer: KafkaProducer,
    events: list[dict[str, Any]],
) -> list[UUID]:
    """Publish a batch of events to Kafka with event_id header.

    Args:
        producer: Kafka producer instance.
        events: List of event dicts from fetch_unpublished_batch.

    Returns:
        List of event IDs that were published.
    """
    published_ids: list[UUID] = []
    for event in events:
        payload = event["payload"]
        event_id = (
            payload.get("event_id", str(event["id"]))
            if isinstance(payload, dict)
            else str(event["id"])
        )
        headers = [("event_id", event_id.encode("utf-8"))]
        producer.produce(
            topic=event["topic"],
            key=str(event["aggregate_id"]),
            value=payload,
            headers=headers,
        )
        published_ids.append(event["id"])
    producer.flush()
    return published_ids


def mark_published(
    conn: psycopg.Connection,
    event_ids: list[UUID],
) -> None:
    """Mark outbox events as published.

    Args:
        conn: Database connection (same transaction as fetch).
        event_ids: List of event IDs to mark as published.
    """
    if not event_ids:
        return
    placeholders = ", ".join(["%s"] * len(event_ids))
    conn.execute(
        f"""
        UPDATE outbox_events
        SET published_at = now()
        WHERE id IN ({placeholders})
        """,
        tuple(str(eid) for eid in event_ids),
    )


def _process_batch(
    settings: CCPSettings,
    producer: KafkaProducer,
) -> int:
    """Process a single batch of outbox events.

    Opens a connection, fetches unpublished events, publishes them
    to Kafka, marks them as published, and commits.

    Args:
        settings: Application configuration.
        producer: Kafka producer instance.

    Returns:
        Number of events published in this batch.
    """
    conn = get_ledger_connection(settings)
    try:
        events = fetch_unpublished_batch(
            conn, settings.outbox_batch_size
        )
        if not events:
            conn.rollback()
            return 0
        published_ids = publish_batch(producer, events)
        mark_published(conn, published_ids)
        conn.commit()
        logger.info("Published %d outbox events", len(published_ids))
        return len(published_ids)
    except Exception:
        conn.rollback()
        logger.exception("Failed to process outbox batch")
        return 0
    finally:
        conn.close()


async def poll_and_publish(settings: CCPSettings) -> None:
    """Main polling loop that continuously publishes outbox events.

    Runs indefinitely, sleeping between batches. Handles errors
    gracefully to avoid crashing the background task.

    Args:
        settings: Application configuration with poll interval
                  and batch size.
    """
    producer = KafkaProducer(settings)
    logger.info(
        "Outbox publisher started: batch_size=%d, interval=%ds",
        settings.outbox_batch_size,
        settings.outbox_poll_interval_seconds,
    )
    while True:
        try:
            count = _process_batch(settings, producer)
            if count == 0:
                await asyncio.sleep(
                    settings.outbox_poll_interval_seconds
                )
            # If we published events, immediately check for more
        except Exception:
            logger.exception("Unexpected error in poll loop")
            await asyncio.sleep(
                settings.outbox_poll_interval_seconds
            )
