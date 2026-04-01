"""Kafka consumer for netting cycle trigger events."""

import logging
from datetime import datetime, timezone
from typing import Any

from ccp_shared.config import CCPSettings
from ccp_shared.db.connection import get_ledger_connection
from ccp_shared.enums import NettingCycleType
from ccp_shared.idempotency import process_if_new
from ccp_shared.kafka.consumer import KafkaConsumer
from ccp_shared.trace import TraceContext

from netting_engine.netting import run_netting_cycle

logger = logging.getLogger(__name__)

SERVICE_NAME = "netting-engine"


def _handle_netting_trigger(
    topic: str,
    key: str | None,
    value: dict[str, Any],
) -> None:
    """Process a netting cycle trigger event with idempotency.

    Args:
        topic: Kafka topic the message arrived on.
        key: Optional message key.
        value: Deserialized event payload.
    """
    event_id = value.get("event_id", "")
    trace = TraceContext.from_kafka_payload(value)

    cycle_type_str = value.get(
        "cycle_type", NettingCycleType.SCHEDULED.value
    )
    cycle_type = NettingCycleType(cycle_type_str)

    cut_off_str = value.get("cut_off_time")
    if cut_off_str:
        cut_off_time = datetime.fromisoformat(cut_off_str)
    else:
        cut_off_time = datetime.now(timezone.utc)

    settings = CCPSettings()
    conn = get_ledger_connection(settings)
    try:
        if event_id and not process_if_new(conn, SERVICE_NAME, event_id):
            conn.commit()
            return
        result = run_netting_cycle(conn, cycle_type, cut_off_time, trace)
        conn.commit()
        logger.info(
            "Netting cycle triggered via Kafka: %s", result
        )
    finally:
        conn.close()


def start_netting_consumer(settings: CCPSettings) -> None:
    """Start the blocking Kafka consumer for netting triggers.

    Args:
        settings: CCP configuration with Kafka bootstrap servers.
    """
    consumer = KafkaConsumer(
        settings=settings,
        group_id=SERVICE_NAME,
        topics=["netting.cycle.triggered"],
    )
    logger.info("Netting consumer started")
    try:
        consumer.poll_loop(_handle_netting_trigger)
    finally:
        consumer.close()
