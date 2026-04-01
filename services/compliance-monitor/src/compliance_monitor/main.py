"""Compliance Monitor — exposure monitoring and alert generation."""

import asyncio
import logging

from fastapi import FastAPI

from ccp_shared.config import CCPSettings
from compliance_monitor.consumer import consume_loop
from compliance_monitor.monitors import run_all_monitors

logger = logging.getLogger(__name__)
app = FastAPI(title="CCP Compliance Monitor")
settings = CCPSettings()


@app.get("/health")
def health():
    return {"status": "ok", "service": "compliance-monitor"}


@app.get("/alerts")
def get_recent_alerts():
    """Return recent compliance alerts."""
    from ccp_shared.db.connection import get_readonly_connection

    conn = get_readonly_connection(settings)
    try:
        rows = conn.execute(
            """
            SELECT aggregate_id, event_type, payload, created_at
            FROM outbox_events
            WHERE event_type = 'compliance.alert.raised'
            ORDER BY created_at DESC LIMIT 50
            """
        ).fetchall()
        return [
            {
                "aggregate_id": str(r[0]),
                "event_type": r[1],
                "payload": r[2],
                "created_at": str(r[3]),
            }
            for r in rows
        ]
    finally:
        conn.close()


@app.on_event("startup")
async def start_consumers():
    asyncio.create_task(
        consume_loop(
            settings,
            topics=["trades.novated", "margin.requirement.updated", "default.declared"],
            group_id="compliance-monitor",
        )
    )
