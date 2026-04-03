"""Settlement Engine -- DVP and cash settlement orchestration."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ccp_shared.config import CCPSettings
from settlement_engine.consumer import consume_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
settings = CCPSettings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start settlement consumer on startup, cancel on shutdown."""
    task = asyncio.create_task(
        consume_loop(
            settings,
            topics=["settlement.instructions.created"],
            group_id="settlement-engine",
        )
    )
    logger.info("Settlement consumer started")
    yield
    task.cancel()
    logger.info("Settlement consumer stopped")


app = FastAPI(title="CCP Settlement Engine", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "service": "settlement-engine"}
