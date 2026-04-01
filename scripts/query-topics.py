#!/usr/bin/env python3
"""Kafka topic query CLI for CCP Clearing House.

Usage:
    python scripts/query-topics.py list
    python scripts/query-topics.py read <topic> [--limit N] [--from-beginning]

Examples:
    python scripts/query-topics.py list
    python scripts/query-topics.py read trades.submitted --limit 10
    python scripts/query-topics.py read settlement.completed --from-beginning
"""

import argparse
import json
import os
import sys
import uuid

from confluent_kafka import Consumer, KafkaException, TopicPartition
from confluent_kafka.admin import AdminClient


BOOTSTRAP = os.environ.get(
    "KAFKA_BOOTSTRAP_SERVERS", "kafka:9092"
)


def cmd_list(args: argparse.Namespace) -> None:
    """List all Kafka topics with partition counts."""
    admin = AdminClient({"bootstrap.servers": BOOTSTRAP})
    try:
        metadata = admin.list_topics(timeout=10)
    except KafkaException as exc:
        print(f"Failed to connect to Kafka: {exc}", file=sys.stderr)
        sys.exit(1)

    topics = sorted(metadata.topics.keys())
    if not topics:
        print("No topics found.")
        return

    print(f"{'Topic':<50} Partitions")
    print("-" * 62)
    for name in topics:
        partitions = len(metadata.topics[name].partitions)
        print(f"{name:<50} {partitions}")
    print(f"\n{len(topics)} topic(s) total")


def cmd_read(args: argparse.Namespace) -> None:
    """Read messages from a Kafka topic."""
    group_id = f"query-topics-{uuid.uuid4().hex[:8]}"
    consumer = Consumer({
        "bootstrap.servers": BOOTSTRAP,
        "group.id": group_id,
        "auto.offset.reset": "earliest" if args.from_beginning else "latest",
        "enable.auto.commit": "false",
    })

    try:
        metadata = consumer.list_topics(args.topic, timeout=10)
        if args.topic not in metadata.topics:
            print(f"Topic '{args.topic}' not found.", file=sys.stderr)
            sys.exit(1)

        partitions = [
            TopicPartition(args.topic, p)
            for p in metadata.topics[args.topic].partitions
        ]
        consumer.assign(partitions)

        if args.from_beginning:
            for tp in partitions:
                tp.offset = 0
            consumer.assign(partitions)

        count = 0
        empty_polls = 0
        max_empty = 3

        while count < args.limit:
            msg = consumer.poll(timeout=2.0)
            if msg is None:
                empty_polls += 1
                if empty_polls >= max_empty:
                    break
                continue
            if msg.error():
                print(f"Consumer error: {msg.error()}", file=sys.stderr)
                continue

            empty_polls = 0
            count += 1

            value = msg.value()
            try:
                decoded = json.loads(value) if value else None
                payload = json.dumps(decoded, indent=2)
            except (json.JSONDecodeError, TypeError):
                payload = value.decode("utf-8", errors="replace") if value else ""

            print(f"--- Message {count} ---")
            print(f"  Partition: {msg.partition()}")
            print(f"  Offset:    {msg.offset()}")
            print(f"  Key:       {msg.key()}")
            print(f"  Payload:   {payload}")
            print()

        if count == 0:
            print("No messages found.")
        else:
            print(f"{count} message(s) read")

    finally:
        consumer.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Query Kafka topics in the CCP Clearing House"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List all topics")

    read_parser = subparsers.add_parser(
        "read", help="Read messages from a topic"
    )
    read_parser.add_argument("topic", help="Topic name to read from")
    read_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum messages to read (default: 10)",
    )
    read_parser.add_argument(
        "--from-beginning",
        action="store_true",
        help="Read from the beginning of the topic",
    )

    args = parser.parse_args()
    if args.command == "list":
        cmd_list(args)
    elif args.command == "read":
        cmd_read(args)


if __name__ == "__main__":
    main()
