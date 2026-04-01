"""Kafka consumer loop for the liquidation engine."""

import asyncio
import json
import logging
from decimal import Decimal

from confluent_kafka import Consumer, KafkaError

from ccp_shared.config import CCPSettings
from ccp_shared.db.connection import get_ledger_connection
from ccp_shared.idempotency import process_if_new
from ccp_shared.trace import TraceContext
from liquidation_engine.waterfall import execute_waterfall

logger = logging.getLogger(__name__)

SERVICE_NAME = "liquidation-engine"


async def consume_loop(
    settings: CCPSettings,
    topics: list[str],
    group_id: str,
) -> None:
    """Run the Kafka consumer loop for default events.

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
    logger.info("Liquidation consumer subscribed to %s", topics)

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
                trace = TraceContext.from_kafka_payload(event)

                conn = get_ledger_connection(settings)
                try:
                    conn.autocommit = False
                    if event_id and not process_if_new(conn, SERVICE_NAME, event_id):
                        conn.commit()
                        consumer.commit(message=msg)
                        continue
                    _handle_event(conn, event_type, event, trace)
                    conn.commit()
                finally:
                    conn.close()
            except Exception:
                logger.exception("Failed to process liquidation event")

            consumer.commit(message=msg)
    finally:
        consumer.close()


def _handle_event(
    conn, event_type: str, event: dict, trace: TraceContext,
) -> None:
    """Route event to default handler."""
    if event_type == "margin.call.breached":
        member_id = event["member_id"]
        exposure = Decimal(event.get("call_amount", "0"))
        execute_waterfall(
            conn,
            member_id=member_id,
            trigger_reason=f"Margin call breached: {event.get('margin_call_id', 'unknown')}",
            total_exposure=exposure,
            trace=trace,
        )
    elif event_type == "settlement.failed":
        instruction_id = event.get("instruction_id", "unknown")
        member_id = event.get("from_member_id", event.get("member_id", ""))
        exposure = Decimal(event.get("amount", "0"))
        if member_id:
            execute_waterfall(
                conn,
                member_id=member_id,
                trigger_reason=f"Settlement failed: {instruction_id}",
                total_exposure=exposure,
                trace=trace,
            )
    else:
        logger.warning("Unknown event type: %s", event_type)
