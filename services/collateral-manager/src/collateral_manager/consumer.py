"""Kafka consumer loop for the collateral manager."""

import asyncio
import json
import logging
from decimal import Decimal

from confluent_kafka import Consumer, KafkaError

from ccp_shared.config import CCPSettings
from ccp_shared.db.connection import get_ledger_connection
from ccp_shared.idempotency import process_if_new
from collateral_manager.operations import deposit_collateral, transfer_to_margin

logger = logging.getLogger(__name__)

SERVICE_NAME = "collateral-manager"


async def consume_loop(
    settings: CCPSettings,
    topics: list[str],
    group_id: str,
) -> None:
    """Run the Kafka consumer loop for collateral events.

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
    logger.info("Collateral consumer subscribed to %s", topics)

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

                conn = get_ledger_connection(settings)
                try:
                    conn.autocommit = False
                    if event_id and not process_if_new(conn, SERVICE_NAME, event_id):
                        conn.commit()
                        consumer.commit(message=msg)
                        continue
                    _handle_event(conn, event_type, event)
                    conn.commit()
                finally:
                    conn.close()
            except Exception:
                logger.exception("Failed to process collateral event")

            consumer.commit(message=msg)
    finally:
        consumer.close()


def _handle_event(conn, event_type: str, event: dict) -> None:
    """Route event to the appropriate handler."""
    if event_type == "collateral.deposit.requested":
        deposit_collateral(
            conn,
            member_id=event["member_id"],
            amount=Decimal(event["amount"]),
            currency=event.get("currency", "USD"),
        )
    elif event_type == "margin.call.issued":
        member_id = event["member_id"]
        call_amount = Decimal(event["call_amount"])
        transfer_to_margin(conn, member_id, call_amount, "MARGIN_IM")
        logger.info(
            "Auto-responded to margin call for member %s: %s",
            member_id, call_amount,
        )
    else:
        logger.warning("Unknown event type: %s", event_type)
