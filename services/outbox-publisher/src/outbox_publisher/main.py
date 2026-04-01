"""FastAPI application for the CCP Outbox Publisher service."""

import asyncio
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI

from ccp_shared.config import CCPSettings
from ccp_shared.db.connection import get_ledger_connection

from outbox_publisher.publisher import poll_and_publish

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
    """Manage the outbox publisher background task lifecycle.

    Starts the polling loop on startup and cancels it on shutdown.

    Args:
        application: The FastAPI application instance.
    """
    settings = CCPSettings()
    task = asyncio.create_task(poll_and_publish(settings))
    logger.info("Outbox publisher background task started")
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        logger.info("Outbox publisher background task stopped")


app = FastAPI(
    title="CCP Outbox Publisher",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
def health_check() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok", "service": "outbox-publisher"}


@app.get("/metrics")
def get_metrics() -> dict[str, int]:
    """Return outbox event counts.

    Returns:
        Dict with published_count and pending_count.
    """
    settings = CCPSettings()
    conn = get_ledger_connection(settings)
    try:
        cur = conn.execute(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE published_at IS NOT NULL
                ) AS published_count,
                COUNT(*) FILTER (
                    WHERE published_at IS NULL
                ) AS pending_count
            FROM outbox_events
            """
        )
        row = cur.fetchone()
        if row is None:
            return {"published_count": 0, "pending_count": 0}
        return {
            "published_count": row[0],
            "pending_count": row[1],
        }
    finally:
        conn.close()
