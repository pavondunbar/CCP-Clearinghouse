"""Compliance monitoring checks for CCP risk metrics."""

import logging
import uuid
from decimal import Decimal

import psycopg

from ccp_shared.kafka.outbox import insert_outbox_event

logger = logging.getLogger(__name__)

CONCENTRATION_THRESHOLD_PCT = Decimal("30")
MARGIN_COVERAGE_MIN_RATIO = Decimal("1.0")
LARGE_TRADE_THRESHOLD_USD = Decimal("10000000")
COVER2_MULTIPLIER = Decimal("2")


def run_all_monitors(conn: psycopg.Connection) -> list[dict]:
    """Run all compliance monitors and return any alerts generated.

    Args:
        conn: Read-only database connection.

    Returns:
        List of alert dicts for any breached thresholds.
    """
    alerts = []
    alerts.extend(check_member_concentration(conn))
    alerts.extend(check_margin_coverage(conn))
    alerts.extend(check_default_fund_adequacy(conn))
    return alerts


def check_member_concentration(conn: psycopg.Connection) -> list[dict]:
    """Alert if any single member holds >30% of total open interest."""
    alerts = []
    rows = conn.execute(
        """
        SELECT member_id, SUM(ABS(net_quantity)) as member_oi
        FROM member_positions
        GROUP BY member_id
        """
    ).fetchall()

    total_oi = sum(abs(Decimal(str(r[1]))) for r in rows if r[1])
    if total_oi == Decimal("0"):
        return alerts

    for member_id, member_oi in rows:
        oi = abs(Decimal(str(member_oi))) if member_oi else Decimal("0")
        pct = (oi / total_oi) * Decimal("100")
        if pct > CONCENTRATION_THRESHOLD_PCT:
            alert = {
                "alert_type": "member_concentration",
                "member_id": str(member_id),
                "concentration_pct": str(pct),
                "threshold_pct": str(CONCENTRATION_THRESHOLD_PCT),
                "member_oi": str(oi),
                "total_oi": str(total_oi),
            }
            _emit_alert(conn, str(member_id), alert)
            alerts.append(alert)
    return alerts


def check_margin_coverage(conn: psycopg.Connection) -> list[dict]:
    """Alert if aggregate margin coverage ratio drops below 1.0."""
    alerts = []
    row = conn.execute(
        """
        SELECT
            COALESCE(SUM(posted_amount), 0) AS total_posted,
            COALESCE(SUM(required_amount), 0) AS total_required
        FROM margin_requirements
        WHERE margin_type = 'INITIAL'
        """
    ).fetchone()

    if not row:
        return alerts

    total_posted = Decimal(str(row[0]))
    total_required = Decimal(str(row[1]))

    if total_required == Decimal("0"):
        return alerts

    ratio = total_posted / total_required
    if ratio < MARGIN_COVERAGE_MIN_RATIO:
        alert = {
            "alert_type": "margin_coverage_low",
            "coverage_ratio": str(ratio),
            "min_ratio": str(MARGIN_COVERAGE_MIN_RATIO),
            "total_posted": str(total_posted),
            "total_required": str(total_required),
        }
        _emit_alert(conn, "system", alert)
        alerts.append(alert)
    return alerts


def check_default_fund_adequacy(conn: psycopg.Connection) -> list[dict]:
    """Alert if total default fund is below Cover-2 requirement.

    Cover-2: default fund must cover losses from the two largest
    member exposures simultaneously defaulting.
    """
    alerts = []

    member_exposures = conn.execute(
        """
        SELECT mr.member_id,
               SUM(mr.required_amount) as total_exposure
        FROM margin_requirements mr
        JOIN members m ON m.id = mr.member_id AND m.status = 'active'
        GROUP BY mr.member_id
        ORDER BY total_exposure DESC
        LIMIT 2
        """
    ).fetchall()

    cover2_requirement = sum(
        Decimal(str(r[1])) for r in member_exposures if r[1]
    )

    total_fund_row = conn.execute(
        """
        SELECT COALESCE(SUM(ab.balance), 0)
        FROM account_balances ab
        JOIN accounts a ON a.id = ab.account_id
        WHERE a.account_type = 'DEFAULT_FUND' AND a.pool = 'AVAILABLE'
          AND ab.balance > 0
        """
    ).fetchone()

    total_fund = Decimal(str(total_fund_row[0])) if total_fund_row else Decimal("0")

    if cover2_requirement > Decimal("0") and total_fund < cover2_requirement:
        alert = {
            "alert_type": "default_fund_inadequate",
            "total_fund": str(total_fund),
            "cover2_requirement": str(cover2_requirement),
            "shortfall": str(cover2_requirement - total_fund),
        }
        _emit_alert(conn, "system", alert)
        alerts.append(alert)
    return alerts


def check_large_trade(conn: psycopg.Connection, trade_data: dict) -> list[dict]:
    """Alert if a trade notional exceeds the large trade threshold."""
    alerts = []
    quantity = Decimal(str(trade_data.get("quantity", "0")))
    price = Decimal(str(trade_data.get("price", "0")))
    notional = quantity * price

    if notional > LARGE_TRADE_THRESHOLD_USD:
        alert = {
            "alert_type": "large_trade",
            "trade_id": trade_data.get("original_trade_id", "unknown"),
            "notional": str(notional),
            "threshold": str(LARGE_TRADE_THRESHOLD_USD),
            "buyer": trade_data.get("buyer_member_id", ""),
            "seller": trade_data.get("seller_member_id", ""),
        }
        _emit_alert(conn, trade_data.get("original_trade_id", "system"), alert)
        alerts.append(alert)
    return alerts


def _emit_alert(conn: psycopg.Connection, aggregate_id: str, alert: dict) -> None:
    """Write a compliance alert to the outbox."""
    try:
        agg_uuid = uuid.UUID(aggregate_id)
    except (ValueError, AttributeError):
        agg_uuid = uuid.uuid4()

    insert_outbox_event(
        conn,
        aggregate_type="compliance",
        aggregate_id=agg_uuid,
        event_type="compliance.alert.raised",
        topic="compliance.alert.raised",
        payload=alert,
    )
    logger.warning("Compliance alert: %s", alert.get("alert_type", "unknown"))
