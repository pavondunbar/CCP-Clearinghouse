"""Collateral Manager — deposits, withdrawals, and two-pool management."""

import asyncio
import logging

from fastapi import FastAPI

from ccp_shared.config import CCPSettings
from collateral_manager.consumer import consume_loop

logger = logging.getLogger(__name__)
app = FastAPI(title="CCP Collateral Manager")
settings = CCPSettings()


@app.get("/health")
def health():
    return {"status": "ok", "service": "collateral-manager"}


@app.on_event("startup")
async def start_consumers():
    asyncio.create_task(
        consume_loop(
            settings,
            topics=["collateral.deposit.requested", "margin.call.issued"],
            group_id="collateral-manager",
        )
    )
