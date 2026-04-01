"""Kafka consumer loop for trade ingestion."""

import logging
from typing import Any

import psycopg

from ccp_shared.config import CCPSettings
from ccp_shared.idempotency import process_if_new
from ccp_shared.kafka.consumer import KafkaConsumer
from ccp_shared.trace import TraceContext
from trade_ingestion.novation import process_trade

logger = logging.getLogger(__name__)

SERVICE_NAME = "trade-ingestion"


def run_consumer(settings: CCPSettings) -> None:
    """Start a blocking Kafka consumer for trade submissions.

    Args:
        settings: CCP configuration with Kafka and Postgres DSNs.
    """
    consumer = KafkaConsumer(
        settings=settings,
        group_id=SERVICE_NAME,
        topics=["trades.submitted"],
    )
    logger.info("Listening on 'trades.submitted' topic")

    def handle_message(
        topic: str,
        key: str | None,
        value: dict[str, Any],
    ) -> None:
        """Process a single Kafka message with idempotency."""
        logger.info(
            "Received trade message on %s: key=%s", topic, key
        )
        event_id = value.get("event_id", "")
        trace = TraceContext.from_kafka_payload(value)

        with psycopg.connect(settings.ledger_dsn()) as conn:
            if event_id and not process_if_new(conn, SERVICE_NAME, event_id):
                conn.commit()
                return
            process_trade(conn, value, trace)
            conn.commit()

    try:
        consumer.poll_loop(handle_message)
    finally:
        consumer.close()
        logger.info("Trade consumer shut down")
