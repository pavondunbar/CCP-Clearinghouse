"""Kafka consumer loop for the compliance monitor."""

import asyncio
import json
import logging

from confluent_kafka import Consumer, KafkaError

from ccp_shared.config import CCPSettings
from ccp_shared.db.connection import get_readonly_connection
from ccp_shared.idempotency import process_if_new
from compliance_monitor.monitors import (
    check_large_trade,
    check_margin_coverage,
    check_member_concentration,
    run_all_monitors,
)

logger = logging.getLogger(__name__)

SERVICE_NAME = "compliance-monitor"


async def consume_loop(
    settings: CCPSettings,
    topics: list[str],
    group_id: str,
) -> None:
    """Run the Kafka consumer loop for compliance monitoring.

    Args:
        settings: Application settings.
        topics: Kafka topics to subscribe to.
        group_id: Consumer group ID.
    """
    conf = {
        "bootstrap.servers": settings.kafka_bootstrap_servers,
        "group.id": group_id,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    }
    consumer = Consumer(conf)
    consumer.subscribe(topics)
    logger.info("Compliance consumer subscribed to %s", topics)

    try:
        while True:
            msg = await asyncio.to_thread(consumer.poll, 1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                logger.error("Consumer error: %s", msg.error())
                continue

            try:
                event = json.loads(msg.value().decode("utf-8"))
                event_id = event.get("event_id", "")
                event_type = event.get("event_type", "")

                conn = get_readonly_connection(settings)
                try:
                    if event_id:
                        ledger_conn = __import__(
                            "psycopg"
                        ).connect(settings.ledger_dsn())
                        try:
                            if not process_if_new(ledger_conn, SERVICE_NAME, event_id):
                                ledger_conn.commit()
                                consumer.commit(message=msg)
                                continue
                            ledger_conn.commit()
                        finally:
                            ledger_conn.close()
                    _handle_event(conn, event_type, event)
                finally:
                    conn.close()
            except Exception:
                logger.exception("Failed to process compliance event")

            consumer.commit(message=msg)
    finally:
        consumer.close()


def _handle_event(conn, event_type: str, event: dict) -> None:
    """Route event to appropriate compliance check."""
    if event_type == "trade.novated":
        for trade in event.get("novated_trades", []):
            check_large_trade(conn, trade)
        check_member_concentration(conn)
    elif event_type == "margin.requirement.updated":
        check_margin_coverage(conn)
    elif event_type == "default.declared":
        alerts = run_all_monitors(conn)
        if alerts:
            logger.warning(
                "Default triggered %d compliance alerts",
                len(alerts),
            )
    else:
        logger.debug("Unhandled event type: %s", event_type)
