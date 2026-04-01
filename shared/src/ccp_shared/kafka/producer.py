"""Kafka producer wrapper for CCP event publishing."""

import json
from typing import Any

from confluent_kafka import Producer

from ccp_shared.config import CCPSettings


class KafkaProducer:
    """Wraps confluent_kafka.Producer with JSON serialization.

    Args:
        settings: CCP configuration with Kafka bootstrap servers.
    """

    def __init__(self, settings: CCPSettings) -> None:
        self._producer = Producer({
            "bootstrap.servers": settings.kafka_bootstrap_servers,
        })

    def produce(
        self,
        topic: str,
        key: str,
        value: dict[str, Any],
        headers: list[tuple[str, bytes]] | None = None,
    ) -> None:
        """Publish a JSON-serialized message to a Kafka topic.

        Args:
            topic: Target Kafka topic.
            key: Message key for partitioning.
            value: Message payload (serialized to JSON).
            headers: Optional list of (name, value) header tuples.
        """
        kwargs: dict[str, Any] = {
            "topic": topic,
            "key": key.encode("utf-8"),
            "value": json.dumps(value, default=str).encode("utf-8"),
        }
        if headers:
            kwargs["headers"] = headers
        self._producer.produce(**kwargs)
        self._producer.poll(0)

    def flush(self, timeout: float = 5.0) -> int:
        """Flush pending messages.

        Args:
            timeout: Maximum seconds to wait.

        Returns:
            Number of messages still in the queue.
        """
        return self._producer.flush(timeout)
