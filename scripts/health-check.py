"""Verify health of all CCP Clearing House services."""

import os
import sys
import urllib.request
import urllib.error

import psycopg


SERVICES = [
    ("api-gateway", "http://localhost:8000/health"),
    ("trade-ingestion", "http://localhost:8001/health"),
    ("outbox-publisher", "http://localhost:8002/health"),
    ("netting-engine", "http://localhost:8003/health"),
    ("margin-engine", "http://localhost:8004/health"),
    ("collateral-manager", "http://localhost:8005/health"),
    ("settlement-engine", "http://localhost:8006/health"),
    ("liquidation-engine", "http://localhost:8007/health"),
    ("price-oracle", "http://localhost:8008/health"),
    ("compliance-monitor", "http://localhost:8009/health"),
    ("signing-gateway", "http://localhost:8010/health"),
]

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://readonly_user:readonly_secret_change_me"
    "@localhost:5432/ccp_clearing",
)


def check_service(name: str, url: str) -> bool:
    """Check if a service health endpoint responds with 200."""
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            healthy = resp.status == 200
            status = "OK" if healthy else f"HTTP {resp.status}"
    except (urllib.error.URLError, TimeoutError) as exc:
        healthy = False
        status = str(exc)

    icon = "+" if healthy else "FAIL"
    print(f"  [{icon}] {name}: {status}")
    return healthy


def check_postgres() -> bool:
    """Verify PostgreSQL is reachable and has expected tables."""
    try:
        with psycopg.connect(DB_URL) as conn:
            conn.execute("SELECT 1")
            row = conn.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            ).fetchone()
            table_count = row[0] if row else 0
            print(f"  [+] PostgreSQL: {table_count} tables")
            return table_count > 0
    except Exception as exc:
        print(f"  [FAIL] PostgreSQL: {exc}")
        return False


def check_kafka() -> bool:
    """Verify Kafka is reachable by checking bootstrap connection."""
    try:
        from confluent_kafka.admin import AdminClient

        admin = AdminClient({"bootstrap.servers": "localhost:9092"})
        metadata = admin.list_topics(timeout=5)
        topic_count = len(metadata.topics)
        print(f"  [+] Kafka: {topic_count} topics")
        return True
    except Exception as exc:
        print(f"  [FAIL] Kafka: {exc}")
        return False


def main() -> None:
    """Run all health checks."""
    print("CCP Clearing House Health Check")
    print("=" * 40)

    all_healthy = True

    print("\nInfrastructure:")
    all_healthy &= check_postgres()
    all_healthy &= check_kafka()

    print("\nServices:")
    for name, url in SERVICES:
        all_healthy &= check_service(name, url)

    print()
    if all_healthy:
        print("All checks passed.")
    else:
        print("Some checks failed.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
