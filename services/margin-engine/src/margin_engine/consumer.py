"""Kafka consumer loop for the margin engine."""

import asyncio
import json
import logging

from confluent_kafka import Consumer, KafkaError

from ccp_shared.config import CCPSettings
from ccp_shared.db.connection import get_ledger_connection
from ccp_shared.idempotency import process_if_new
from ccp_shared.trace import TraceContext
from margin_engine.calculator import recalculate_margins

logger = logging.getLogger(__name__)

SERVICE_NAME = "margin-engine"


async def consume_loop(
    settings: CCPSettings,
    topics: list[str],
    group_id: str,
) -> None:
    """Run the Kafka consumer loop for margin recalculations.

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
    logger.info("Margin consumer subscribed to %s", topics)

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
                trace = TraceContext.from_kafka_payload(event)

                conn = get_ledger_connection(settings)
                try:
                    conn.autocommit = False
                    if event_id and not process_if_new(conn, SERVICE_NAME, event_id):
                        conn.commit()
                        continue
                    calls = recalculate_margins(conn, settings, trace)
                    conn.commit()
                    if calls:
                        logger.info("Issued %d margin calls", len(calls))
                finally:
                    conn.close()

            except Exception:
                logger.exception("Failed to process margin event")

            consumer.commit(message=msg)
    finally:
        consumer.close()
