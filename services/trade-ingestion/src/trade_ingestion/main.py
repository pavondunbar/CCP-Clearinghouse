"""Trade ingestion service -- FastAPI entry point."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ccp_shared.config import CCPSettings
from trade_ingestion.consumer import run_consumer

logger = logging.getLogger(__name__)
settings = CCPSettings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start Kafka consumer on startup, cancel on shutdown."""
    task = asyncio.create_task(
        asyncio.to_thread(run_consumer, settings)
    )
    logger.info("Trade ingestion consumer started")
    yield
    task.cancel()
    logger.info("Trade ingestion consumer stopped")


app = FastAPI(title="Trade Ingestion", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok", "service": "trade-ingestion"}
