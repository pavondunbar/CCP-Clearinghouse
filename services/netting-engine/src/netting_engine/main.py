"""FastAPI application for the CCP netting engine service."""

import logging
import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, HTTPException

from ccp_shared.config import CCPSettings
from ccp_shared.db.connection import (
    get_ledger_connection,
    get_readonly_connection,
)
from ccp_shared.enums import NettingCycleType

from netting_engine.consumer import start_netting_consumer
from netting_engine.netting import run_netting_cycle

logger = logging.getLogger(__name__)


def _get_settings() -> CCPSettings:
    """Return application settings."""
    return CCPSettings()


def _get_ledger_conn(
    settings: CCPSettings = Depends(_get_settings),
) -> psycopg.Connection:
    """Yield a ledger database connection."""
    conn = get_ledger_connection(settings)
    try:
        yield conn
    finally:
        conn.close()


def _get_readonly_conn(
    settings: CCPSettings = Depends(_get_settings),
) -> psycopg.Connection:
    """Yield a read-only database connection."""
    conn = get_readonly_connection(settings)
    try:
        yield conn
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Start Kafka consumer in background on startup."""
    settings = CCPSettings()
    consumer_thread = threading.Thread(
        target=start_netting_consumer,
        args=(settings,),
        daemon=True,
    )
    consumer_thread.start()
    logger.info("Netting engine started with Kafka consumer")
    yield


app = FastAPI(
    title="CCP Netting Engine",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    """Return service health status."""
    return {"status": "ok", "service": "netting-engine"}


@app.post("/netting/trigger")
def trigger_netting(
    cut_off_time: datetime | None = None,
    cycle_type: str = "ad_hoc",
    conn: psycopg.Connection = Depends(_get_ledger_conn),
) -> dict[str, Any]:
    """Manually trigger a netting cycle.

    Args:
        cut_off_time: Include trades novated at or before.
            Defaults to current UTC time.
        cycle_type: Type of netting cycle (scheduled, ad_hoc).
            Defaults to ad_hoc.
        conn: Injected ledger database connection.

    Returns:
        Dict with cycle summary including cycle_id and counts.
    """
    if cut_off_time is None:
        cut_off_time = datetime.now(timezone.utc)

    try:
        netting_type = NettingCycleType(cycle_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid cycle_type: {cycle_type}",
        )

    result = run_netting_cycle(conn, netting_type, cut_off_time)
    return result


@app.get("/netting/cycles")
def list_cycles(
    limit: int = 20,
    conn: psycopg.Connection = Depends(_get_readonly_conn),
) -> list[dict[str, Any]]:
    """List recent netting cycles.

    Args:
        limit: Maximum number of cycles to return.
        conn: Injected read-only database connection.

    Returns:
        List of netting cycle dicts ordered by creation time.
    """
    rows = conn.execute(
        """
        SELECT id, cycle_type, status, cut_off_time, created_at
        FROM netting_cycles
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (limit,),
    ).fetchall()

    return [
        {
            "id": str(row[0]),
            "cycle_type": row[1],
            "status": row[2],
            "cut_off_time": row[3].isoformat() if row[3] else None,
            "created_at": row[4].isoformat() if row[4] else None,
        }
        for row in rows
    ]


@app.get("/netting/cycles/{cycle_id}/obligations")
def get_obligations(
    cycle_id: UUID,
    conn: psycopg.Connection = Depends(_get_readonly_conn),
) -> list[dict[str, Any]]:
    """Get net obligations for a specific netting cycle.

    Args:
        cycle_id: UUID of the netting cycle.
        conn: Injected read-only database connection.

    Returns:
        List of net obligation dicts for the cycle.
    """
    rows = conn.execute(
        """
        SELECT id, member_id, instrument_id,
               net_quantity, net_amount, settlement_amount
        FROM net_obligations
        WHERE netting_cycle_id = %s
        ORDER BY member_id, instrument_id
        """,
        (str(cycle_id),),
    ).fetchall()

    return [
        {
            "id": str(row[0]),
            "member_id": str(row[1]),
            "instrument_id": str(row[2]),
            "net_quantity": str(row[3]),
            "net_amount": str(row[4]),
            "settlement_amount": str(row[5]),
        }
        for row in rows
    ]
