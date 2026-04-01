"""Price oracle service -- FastAPI entry point."""

import asyncio
import logging
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI

from ccp_shared.config import CCPSettings
from price_oracle.feed import generate_prices

logger = logging.getLogger(__name__)
settings = CCPSettings()


async def _price_update_loop() -> None:
    """Periodically generate new mock prices."""
    interval = settings.price_oracle_interval_seconds
    logger.info("Price update loop started (interval=%ds)", interval)
    while True:
        try:
            with psycopg.connect(settings.ledger_dsn()) as conn:
                prices = generate_prices(conn, settings)
                logger.info("Updated %d instrument prices", len(prices))
        except Exception:
            logger.exception("Price generation failed")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start price update timer on startup, cancel on shutdown."""
    task = asyncio.create_task(_price_update_loop())
    yield
    task.cancel()
    logger.info("Price update loop stopped")


app = FastAPI(title="Price Oracle", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok", "service": "price-oracle"}


@app.get("/prices")
async def get_prices() -> list[dict]:
    """Return the latest price for every active instrument."""
    with psycopg.connect(settings.readonly_dsn()) as conn:
        rows = conn.execute(
            """
            SELECT
                lp.instrument_id,
                i.symbol,
                lp.price,
                lp.source,
                lp.received_at
            FROM latest_prices lp
            JOIN instruments i ON i.id = lp.instrument_id
            WHERE i.is_active = true
            ORDER BY i.symbol
            """
        ).fetchall()
    return [
        {
            "instrument_id": str(row[0]),
            "symbol": row[1],
            "price": str(row[2]),
            "source": row[3],
            "received_at": row[4].isoformat(),
        }
        for row in rows
    ]
