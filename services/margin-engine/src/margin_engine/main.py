"""Margin Engine — IM/VM calculation and margin call management."""

import asyncio
import json
import logging

from fastapi import FastAPI

from ccp_shared.config import CCPSettings
from ccp_shared.db.connection import get_ledger_connection
from margin_engine.calculator import recalculate_margins
from margin_engine.consumer import consume_loop

logger = logging.getLogger(__name__)
app = FastAPI(title="CCP Margin Engine")
settings = CCPSettings()


@app.get("/health")
def health():
    return {"status": "ok", "service": "margin-engine"}


@app.on_event("startup")
async def start_consumers():
    asyncio.create_task(
        consume_loop(
            settings,
            topics=["trades.novated", "prices.updated"],
            group_id="margin-engine",
        )
    )
