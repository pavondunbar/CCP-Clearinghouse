"""Kafka consumer wrapper with DLQ support for CCP event consumption."""

import json
import logging
import traceback
from collections.abc import Callable
from typing import Any

import psycopg
from confluent_kafka import Consumer, KafkaError

from ccp_shared.config import CCPSettings

logger = logging.getLogger(__name__)


class KafkaConsumer:
    """Wraps confluent_kafka.Consumer with JSON deserialization and DLQ.

    Uses manual offset commit: offsets are committed after successful
    processing or after routing a failed message to the dead letter
    queue.

    Args:
        settings: CCP configuration with Kafka bootstrap servers.
        group_id: Consumer group identifier.
        topics: List of topics to subscribe to.
    """

    def __init__(
        self,
        settings: CCPSettings,
        group_id: str,
        topics: list[str],
    ) -> None:
        self._consumer = Consumer({
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        })
        self._consumer.subscribe(topics)
        self._settings = settings
        self._group_id = group_id
        self._running = False

    def poll_loop(
        self,
        callback: Callable[[str, str | None, dict[str, Any]], None],
        poll_timeout: float = 1.0,
    ) -> None:
        """Run a blocking poll loop, calling callback for each message.

        On callback success, commits the offset. On failure, inserts
        the event into the dead_letter_events table, then commits.

        Args:
            callback: Function receiving (topic, key, deserialized_value).
            poll_timeout: Seconds to wait per poll iteration.
        """
        self._running = True
        while self._running:
            msg = self._consumer.poll(poll_timeout)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                logger.error("Kafka consumer error: %s", msg.error())
                continue

            topic = msg.topic()
            key = (
                msg.key().decode("utf-8")
                if msg.key() is not None
                else None
            )
            try:
                value = json.loads(msg.value().decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                self._send_to_dlq(
                    topic,
                    key,
                    msg.value(),
                    exc,
                )
                self._consumer.commit(message=msg)
                continue

            try:
                callback(topic, key, value)
            except Exception as exc:
                logger.exception(
                    "Message processing failed, routing to DLQ: "
                    "topic=%s key=%s",
                    topic,
                    key,
                )
                self._send_to_dlq(topic, key, value, exc)

            self._consumer.commit(message=msg)

    def _send_to_dlq(
        self,
        topic: str,
        key: str | None,
        payload: Any,
        error: Exception,
    ) -> None:
        """Insert a failed message into the dead_letter_events table."""
        try:
            conn = psycopg.connect(self._settings.ledger_dsn())
            try:
                if isinstance(payload, bytes):
                    json_payload = payload.decode("utf-8", errors="replace")
                elif isinstance(payload, dict):
                    json_payload = json.dumps(payload, default=str)
                else:
                    json_payload = str(payload)

                conn.execute(
                    """
                    INSERT INTO dead_letter_events
                        (service_name, topic, event_key, payload,
                         error_message, error_traceback)
                    VALUES (%s, %s, %s, %s::jsonb, %s, %s)
                    """,
                    (
                        self._group_id,
                        topic,
                        key,
                        json_payload,
                        str(error),
                        traceback.format_exc(),
                    ),
                )
                conn.commit()
                logger.info(
                    "Message routed to DLQ: topic=%s key=%s",
                    topic,
                    key,
                )
            finally:
                conn.close()
        except Exception:
            logger.exception(
                "Failed to insert into DLQ: topic=%s key=%s",
                topic,
                key,
            )

    def stop(self) -> None:
        """Signal the poll loop to stop."""
        self._running = False

    def close(self) -> None:
        """Stop polling and close the underlying consumer."""
        self.stop()
        self._consumer.close()
