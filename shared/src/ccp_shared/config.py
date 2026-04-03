"""CCP Clearing House shared configuration via Pydantic Settings."""

import json

from pydantic_settings import BaseSettings


class CCPSettings(BaseSettings):
    """Central configuration for all CCP services.

    Reads from environment variables.
    All field names map to uppercase env vars automatically.
    """

    model_config = {"env_file_encoding": "utf-8"}

    # Postgres
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "ccp_clearing"

    postgres_admin_user: str = "admin_user"
    postgres_admin_password: str = "admin_secret_change_me"

    postgres_ledger_user: str = "ledger_user"
    postgres_ledger_password: str = "ledger_secret_change_me"

    postgres_readonly_user: str = "readonly_user"
    postgres_readonly_password: str = "readonly_secret_change_me"

    # Kafka
    kafka_bootstrap_servers: str = "localhost:9092"

    # Service ports and intervals
    api_gateway_port: int = 8000
    price_oracle_interval_seconds: int = 30
    outbox_poll_interval_seconds: int = 1
    outbox_batch_size: int = 100

    # Risk
    margin_call_deadline_minutes: int = 60

    # MPC signing
    mpc_threshold: int = 2
    mpc_total_nodes: int = 3
    signing_gateway_host: str = "signing-gateway"
    signing_gateway_port: int = 8010

    # API keys (JSON string: {"key": "role", ...})
    api_keys: str = "{}"

    def ledger_dsn(self) -> str:
        """Return PostgreSQL connection string for ledger operations."""
        return (
            f"postgresql://{self.postgres_ledger_user}"
            f":{self.postgres_ledger_password}"
            f"@{self.postgres_host}:{self.postgres_port}"
            f"/{self.postgres_db}"
        )

    def readonly_dsn(self) -> str:
        """Return PostgreSQL connection string for read-only queries."""
        return (
            f"postgresql://{self.postgres_readonly_user}"
            f":{self.postgres_readonly_password}"
            f"@{self.postgres_host}:{self.postgres_port}"
            f"/{self.postgres_db}"
        )

    def admin_dsn(self) -> str:
        """Return PostgreSQL connection string for admin/DDL operations."""
        return (
            f"postgresql://{self.postgres_admin_user}"
            f":{self.postgres_admin_password}"
            f"@{self.postgres_host}:{self.postgres_port}"
            f"/{self.postgres_db}"
        )

    def parsed_api_keys(self) -> dict[str, str]:
        """Parse API_KEYS JSON string into a dict.

        Returns:
            Mapping of API key string to role name.
        """
        return json.loads(self.api_keys)
