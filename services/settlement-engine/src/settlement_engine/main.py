"""Settlement Engine — DVP and cash settlement orchestration."""

import asyncio
import logging

from fastapi import FastAPI

from ccp_shared.config import CCPSettings
from settlement_engine.consumer import consume_loop

logger = logging.getLogger(__name__)
app = FastAPI(title="CCP Settlement Engine")
settings = CCPSettings()


@app.get("/health")
def health():
    return {"status": "ok", "service": "settlement-engine"}


@app.on_event("startup")
async def start_consumers():
    asyncio.create_task(
        consume_loop(
            settings,
            topics=["settlement.instructions.created"],
            group_id="settlement-engine",
        )
    )
