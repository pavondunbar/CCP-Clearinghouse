"""Mock price feed generator for the CCP price oracle."""

import logging
import random
from decimal import Decimal
from typing import Any

import psycopg

from ccp_shared.config import CCPSettings
from ccp_shared.kafka.outbox import insert_outbox_event

logger = logging.getLogger(__name__)

BASE_PRICES: dict[str, Decimal] = {
    "BTC-PERP": Decimal("65000"),
    "ETH-FUTURE-Q2": Decimal("3500"),
    "BTC-OPTION-30K": Decimal("2500"),
    "AAPL-TOKEN": Decimal("175"),
    "TBOND-10Y": Decimal("98.5"),
    "REALESTATE-RWA-1": Decimal("250000"),
}


def generate_prices(
    conn: psycopg.Connection, settings: CCPSettings
) -> list[dict[str, Any]]:
    """Generate new mock prices for all active instruments.

    For each active instrument, applies a random walk to the last
    known price (or a base price if none exists) and inserts the
    new price into price_feeds. Refreshes the latest_prices
    materialized view and emits an outbox event.

    Args:
        conn: Open database connection (ledger-level privileges).
        settings: CCP configuration (unused but available for future
            tuning parameters).

    Returns:
        List of dicts with instrument_id, symbol, and new price.
    """
    instruments = _fetch_active_instruments(conn)
    if not instruments:
        logger.warning("No active instruments found")
        return []

    last_prices = _fetch_last_prices(conn)
    updated: list[dict[str, Any]] = []

    with conn.transaction():
        for inst_id, symbol in instruments:
            last_price = last_prices.get(
                inst_id, BASE_PRICES.get(symbol, Decimal("100"))
            )
            new_price = _random_walk(last_price)
            _insert_price_feed(conn, inst_id, new_price)
            updated.append({
                "instrument_id": str(inst_id),
                "symbol": symbol,
                "price": str(new_price),
            })

        conn.execute(
            "REFRESH MATERIALIZED VIEW CONCURRENTLY latest_prices"
        )

        if updated:
            insert_outbox_event(
                conn,
                aggregate_type="price_feed",
                aggregate_id=instruments[0][0],
                event_type="price.updated",
                topic="prices.updated",
                payload={"prices": updated},
            )

    return updated


def _fetch_active_instruments(
    conn: psycopg.Connection,
) -> list[tuple]:
    """Return (id, symbol) for all active instruments."""
    return conn.execute(
        "SELECT id, symbol FROM instruments "
        "WHERE is_active = true ORDER BY symbol"
    ).fetchall()


def _fetch_last_prices(
    conn: psycopg.Connection,
) -> dict:
    """Return {instrument_id: Decimal(price)} from latest_prices view."""
    rows = conn.execute(
        "SELECT instrument_id, price FROM latest_prices"
    ).fetchall()
    return {row[0]: Decimal(str(row[1])) for row in rows}


def _random_walk(last_price: Decimal) -> Decimal:
    """Apply a Gaussian random walk to a price.

    Args:
        last_price: The previous price.

    Returns:
        New price, guaranteed positive (floored at 0.01).
    """
    factor = Decimal(str(1 + random.gauss(0, 0.02)))
    new_price = last_price * factor
    return max(new_price.quantize(Decimal("0.00000001")), Decimal("0.01"))


def _insert_price_feed(
    conn: psycopg.Connection,
    instrument_id: Any,
    price: Decimal,
) -> None:
    """Insert a single price feed record."""
    conn.execute(
        """
        INSERT INTO price_feeds (instrument_id, price, source)
        VALUES (%s, %s, 'mock')
        """,
        (str(instrument_id), str(price)),
    )
