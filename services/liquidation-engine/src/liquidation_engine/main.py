"""Liquidation Engine — default detection and waterfall execution."""

import asyncio
import logging

from fastapi import FastAPI

from ccp_shared.config import CCPSettings
from liquidation_engine.consumer import consume_loop

logger = logging.getLogger(__name__)
app = FastAPI(title="CCP Liquidation Engine")
settings = CCPSettings()


@app.get("/health")
def health():
    return {"status": "ok", "service": "liquidation-engine"}


@app.on_event("startup")
async def start_consumers():
    asyncio.create_task(
        consume_loop(
            settings,
            topics=["margin.call.breached", "settlement.failed"],
            group_id="liquidation-engine",
        )
    )
