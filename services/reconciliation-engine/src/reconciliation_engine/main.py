"""FastAPI application for the reconciliation engine."""

import logging
from collections.abc import Generator

from fastapi import Depends, FastAPI
from pydantic import BaseModel

from ccp_shared.config import CCPSettings
from ccp_shared.db.connection import get_readonly_connection
from reconciliation_engine.reconciler import run_reconciliation

logger = logging.getLogger(__name__)

app = FastAPI(title="CCP Reconciliation Engine", version="0.1.0")

_last_report: dict | None = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    service: str


class AccountResultResponse(BaseModel):
    """Per-account reconciliation result."""

    account_id: str
    expected_balance: str
    actual_balance: str
    difference: str
    status: str


class ReconciliationReportResponse(BaseModel):
    """Full reconciliation report response."""

    status: str
    global_balance_ok: bool
    journal_integrity_ok: bool
    accounts_checked: int
    mismatches: int
    details: list[AccountResultResponse]


def _get_readonly_conn() -> Generator:
    """Yield a read-only database connection."""
    settings = CCPSettings()
    conn = get_readonly_connection(settings)
    try:
        yield conn
    finally:
        conn.close()


@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Return service health status."""
    return HealthResponse(
        status="ok", service="reconciliation-engine"
    )


@app.post("/reconcile", response_model=ReconciliationReportResponse)
def reconcile(
    conn=Depends(_get_readonly_conn),
) -> ReconciliationReportResponse:
    """Run a full reconciliation check and return the report."""
    global _last_report
    report = run_reconciliation(conn)
    response = ReconciliationReportResponse(
        status=report.status,
        global_balance_ok=report.global_balance_ok,
        journal_integrity_ok=report.journal_integrity_ok,
        accounts_checked=report.accounts_checked,
        mismatches=report.mismatches,
        details=[
            AccountResultResponse(
                account_id=d.account_id,
                expected_balance=str(d.expected_balance),
                actual_balance=str(d.actual_balance),
                difference=str(d.difference),
                status=d.status,
            )
            for d in report.details
        ],
    )
    _last_report = response.model_dump()
    return response


@app.get(
    "/reconcile/latest",
    response_model=ReconciliationReportResponse | None,
)
def get_latest_report() -> ReconciliationReportResponse | dict | None:
    """Return the most recent reconciliation report."""
    if _last_report is None:
        return ReconciliationReportResponse(
            status="no_data",
            global_balance_ok=True,
            journal_integrity_ok=True,
            accounts_checked=0,
            mismatches=0,
            details=[],
        )
    return _last_report
