"""Kafka consumer loop for the settlement engine."""

import asyncio
import json
import logging

from confluent_kafka import Consumer, KafkaError

from ccp_shared.chain.registry import ChainRegistry
from ccp_shared.chain.stubs import StubChainAdapter
from ccp_shared.config import CCPSettings
from ccp_shared.db.connection import get_ledger_connection
from ccp_shared.idempotency import process_if_new
from ccp_shared.signing.client import SigningClient
from ccp_shared.trace import TraceContext
from settlement_engine.settler import settle_instruction

logger = logging.getLogger(__name__)

SERVICE_NAME = "settlement-engine"


def _build_chain_registry() -> ChainRegistry:
    """Build the chain registry with available adapters."""
    registry = ChainRegistry()
    stub = StubChainAdapter()
    registry.register("ethereum-mainnet", stub)
    registry.register("polygon-mainnet", stub)
    return registry


async def consume_loop(
    settings: CCPSettings,
    topics: list[str],
    group_id: str,
) -> None:
    """Run the Kafka consumer loop for settlement instructions.

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
    chain_registry = _build_chain_registry()
    signing_client = SigningClient(settings)
    logger.info("Settlement consumer subscribed to %s", topics)

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
                instruction_id = event.get("instruction_id")
                if not instruction_id:
                    logger.warning("No instruction_id in event")
                    consumer.commit(message=msg)
                    continue

                conn = get_ledger_connection(settings)
                try:
                    conn.autocommit = False
                    if event_id and not process_if_new(conn, SERVICE_NAME, event_id):
                        conn.commit()
                        consumer.commit(message=msg)
                        continue
                    result = settle_instruction(
                        conn, instruction_id,
                        chain_registry, signing_client, trace,
                    )
                    conn.commit()
                    logger.info("Settlement result: %s", result)
                finally:
                    conn.close()

            except Exception:
                logger.exception("Failed to process settlement event")

            consumer.commit(message=msg)
    finally:
        consumer.close()
