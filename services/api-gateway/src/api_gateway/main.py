"""FastAPI application for the CCP Clearing House API Gateway."""

import logging
import uuid
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request

from ccp_shared.kafka.outbox import insert_outbox_event
from ccp_shared.trace import TraceContext

from api_gateway.dependencies import (
    get_ledger_conn,
    get_readonly_conn,
    require_permission,
)
from api_gateway.schemas import (
    AccountBalanceResponse,
    DeadLetterEventResponse,
    HealthResponse,
    MemberResponse,
    PositionResponse,
    ReconciliationAccountResult,
    ReconciliationReport,
    TradeResponse,
    TradeSubmitRequest,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="CCP Clearing House API Gateway", version="0.1.0")


@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    """Inject trace context into every request and response."""
    trace_id = request.headers.get(
        "x-trace-id", str(uuid.uuid4())
    )
    actor = request.headers.get("x-actor", "anonymous")
    request.state.trace = TraceContext(
        trace_id=trace_id, actor=f"api-gateway:{actor}"
    )
    response = await call_next(request)
    response.headers["X-Trace-Id"] = trace_id
    return response


@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Return service health status."""
    return HealthResponse(status="ok", service="api-gateway")


@app.post("/trades", response_model=TradeResponse, status_code=201)
def submit_trade(
    request: Request,
    trade_request: TradeSubmitRequest,
    conn: psycopg.Connection = Depends(get_ledger_conn),
    _role=Depends(require_permission("trade.submit")),
) -> TradeResponse:
    """Submit a new trade for clearing.

    Supports idempotency via the Idempotency-Key header. If the
    same key is resubmitted, the original trade is returned.

    Args:
        request: The HTTP request (for headers/trace).
        trade_request: Trade submission details.
        conn: Ledger database connection.

    Returns:
        The created trade with its assigned ID and status.
    """
    trace: TraceContext = request.state.trace
    idempotency_key = request.headers.get("idempotency-key")

    if idempotency_key:
        existing = _check_idempotency(conn, idempotency_key)
        if existing:
            return existing

    try:
        row = _insert_trade(conn, trade_request)
        _insert_trade_outbox_event(conn, row, trace)
        if idempotency_key:
            _mark_idempotent(conn, idempotency_key, row["id"])
        conn.commit()
    except psycopg.errors.ForeignKeyViolation as exc:
        conn.rollback()
        raise HTTPException(
            status_code=422,
            detail=f"Referenced entity not found: {exc}",
        ) from exc
    except psycopg.errors.UniqueViolation as exc:
        conn.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Trade already exists: {exc}",
        ) from exc

    return TradeResponse(
        id=row["id"],
        external_trade_id=row["external_trade_id"],
        instrument_id=row["instrument_id"],
        buyer_member_id=row["buyer_member_id"],
        seller_member_id=row["seller_member_id"],
        quantity=row["quantity"],
        price=row["price"],
        status=row["status"],
        submitted_at=row["submitted_at"],
    )


def _check_idempotency(
    conn: psycopg.Connection,
    idempotency_key: str,
) -> TradeResponse | None:
    """Check if this idempotency key was already processed.

    Returns the existing trade response, or None if new.
    """
    row = conn.execute(
        """
        SELECT reference_id FROM processed_events
        WHERE service_name = 'api-gateway'
          AND event_id = %s
        """,
        (idempotency_key,),
    ).fetchone()
    if row is None:
        return None

    trade_id = row[0]
    if trade_id is None:
        return None

    trade = conn.execute(
        """
        SELECT id, external_trade_id, instrument_id,
               buyer_member_id, seller_member_id,
               quantity, price, status, submitted_at
        FROM trades WHERE id = %s
        """,
        (str(trade_id),),
    ).fetchone()
    if trade is None:
        return None
    columns = ["id", "external_trade_id", "instrument_id",
               "buyer_member_id", "seller_member_id",
               "quantity", "price", "status", "submitted_at"]
    return TradeResponse(**dict(zip(columns, trade, strict=True)))


def _mark_idempotent(
    conn: psycopg.Connection,
    idempotency_key: str,
    trade_id: UUID,
) -> None:
    """Record that this idempotency key has been processed."""
    conn.execute(
        """
        INSERT INTO processed_events (service_name, event_id, reference_id)
        VALUES ('api-gateway', %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (idempotency_key, str(trade_id)),
    )


def _insert_trade(
    conn: psycopg.Connection,
    request: TradeSubmitRequest,
) -> dict:
    """Insert a trade row into the trades table.

    Args:
        conn: Database connection.
        request: Trade submission request.

    Returns:
        Dict with the inserted trade columns.
    """
    cur = conn.execute(
        """
        INSERT INTO trades
            (external_trade_id, instrument_id,
             buyer_member_id, seller_member_id,
             quantity, price, status)
        VALUES (%s, %s, %s, %s, %s, %s, 'submitted')
        RETURNING id, external_trade_id, instrument_id,
                  buyer_member_id, seller_member_id,
                  quantity, price, status, submitted_at
        """,
        (
            request.external_trade_id,
            str(request.instrument_id),
            str(request.buyer_member_id),
            str(request.seller_member_id),
            request.quantity,
            request.price,
        ),
    )
    result = cur.fetchone()
    if result is None:
        raise HTTPException(status_code=500, detail="Trade insert failed")
    columns = [desc.name for desc in cur.description]
    return dict(zip(columns, result, strict=True))


def _insert_trade_outbox_event(
    conn: psycopg.Connection,
    trade_row: dict,
    trace: TraceContext,
) -> None:
    """Insert an outbox event for a newly submitted trade.

    Args:
        conn: Database connection (same transaction as trade insert).
        trade_row: Dict of the inserted trade columns.
        trace: Trace context for audit correlation.
    """
    insert_outbox_event(
        conn=conn,
        aggregate_type="trade",
        aggregate_id=trade_row["id"],
        event_type="trade.submitted",
        topic="trades.submitted",
        payload={
            "trade_id": str(trade_row["id"]),
            "external_trade_id": trade_row["external_trade_id"],
            "instrument_id": str(trade_row["instrument_id"]),
            "buyer_member_id": str(trade_row["buyer_member_id"]),
            "seller_member_id": str(trade_row["seller_member_id"]),
            "quantity": str(trade_row["quantity"]),
            "price": str(trade_row["price"]),
            "actor": trace.actor,
        },
        trace_id=trace.trace_id,
    )


@app.get("/trades/{trade_id}", response_model=TradeResponse)
def get_trade(
    trade_id: UUID,
    conn: psycopg.Connection = Depends(get_readonly_conn),
    _role=Depends(require_permission("trade.read")),
) -> TradeResponse:
    """Retrieve a trade by its ID.

    Args:
        trade_id: UUID of the trade to look up.
        conn: Read-only database connection.

    Returns:
        The trade details.
    """
    cur = conn.execute(
        """
        SELECT id, external_trade_id, instrument_id,
               buyer_member_id, seller_member_id,
               quantity, price, status, submitted_at
        FROM trades WHERE id = %s
        """,
        (str(trade_id),),
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Trade not found")
    columns = [desc.name for desc in cur.description]
    return TradeResponse(**dict(zip(columns, row, strict=True)))


@app.get("/members", response_model=list[MemberResponse])
def list_members(
    conn: psycopg.Connection = Depends(get_readonly_conn),
    _role=Depends(require_permission("member.read")),
) -> list[MemberResponse]:
    """List all active clearing members.

    Args:
        conn: Read-only database connection.

    Returns:
        List of active members.
    """
    cur = conn.execute(
        """
        SELECT id, lei, name, status, credit_limit
        FROM members WHERE status = 'active'
        ORDER BY name
        """
    )
    columns = [desc.name for desc in cur.description]
    return [
        MemberResponse(**dict(zip(columns, row, strict=True)))
        for row in cur.fetchall()
    ]


@app.get(
    "/members/{member_id}/positions",
    response_model=list[PositionResponse],
)
def get_member_positions(
    member_id: UUID,
    conn: psycopg.Connection = Depends(get_readonly_conn),
    _role=Depends(require_permission("member.read")),
) -> list[PositionResponse]:
    """Get positions for a specific member.

    Args:
        member_id: UUID of the member.
        conn: Read-only database connection.

    Returns:
        List of positions for the member.
    """
    cur = conn.execute(
        """
        SELECT instrument_id, long_quantity, short_quantity,
               net_quantity, avg_price
        FROM member_positions WHERE member_id = %s
        """,
        (str(member_id),),
    )
    columns = [desc.name for desc in cur.description]
    return [
        PositionResponse(**dict(zip(columns, row, strict=True)))
        for row in cur.fetchall()
    ]


@app.get(
    "/members/{member_id}/accounts",
    response_model=list[AccountBalanceResponse],
)
def get_member_accounts(
    member_id: UUID,
    conn: psycopg.Connection = Depends(get_readonly_conn),
    _role=Depends(require_permission("member.read")),
) -> list[AccountBalanceResponse]:
    """Get account balances for a specific member.

    Args:
        member_id: UUID of the member.
        conn: Read-only database connection.

    Returns:
        List of account balances for the member.
    """
    cur = conn.execute(
        """
        SELECT account_id, account_type, currency, pool, balance
        FROM account_balances WHERE member_id = %s
        """,
        (str(member_id),),
    )
    columns = [desc.name for desc in cur.description]
    return [
        AccountBalanceResponse(
            **dict(zip(columns, row, strict=True))
        )
        for row in cur.fetchall()
    ]


@app.get(
    "/admin/dlq",
    response_model=list[DeadLetterEventResponse],
)
def list_dead_letter_events(
    limit: int = 50,
    conn: psycopg.Connection = Depends(get_readonly_conn),
    _role=Depends(require_permission("dlq.read")),
) -> list[DeadLetterEventResponse]:
    """List recent dead letter queue entries.

    Args:
        limit: Maximum number of entries to return.
        conn: Read-only database connection.

    Returns:
        List of recent DLQ entries.
    """
    cur = conn.execute(
        """
        SELECT id, service_name, topic, event_key,
               error_message, created_at, retry_count
        FROM dead_letter_events
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (min(limit, 200),),
    )
    columns = [desc.name for desc in cur.description]
    return [
        DeadLetterEventResponse(
            **dict(zip(columns, row, strict=True))
        )
        for row in cur.fetchall()
    ]


@app.post(
    "/reconcile",
    response_model=ReconciliationReport,
)
def run_reconciliation(
    conn: psycopg.Connection = Depends(get_readonly_conn),
    _role=Depends(require_permission("reconcile.run")),
) -> ReconciliationReport:
    """Run a reconciliation check across all accounts.

    Replays the ledger, recomputes balances, and compares
    against the derived account_balances view.

    Args:
        conn: Read-only database connection.

    Returns:
        Reconciliation report with per-account results.
    """
    global_ok = _check_global_balance(conn)
    journal_ok = _check_journal_integrity(conn)

    recomputed = conn.execute(
        """
        SELECT je.account_id,
               SUM(je.debit) - SUM(je.credit) AS computed
        FROM journal_entries je
        JOIN journals j ON j.id = je.journal_id
        WHERE j.status = 'confirmed'
        GROUP BY je.account_id
        """
    ).fetchall()

    actual_balances = {}
    actual_rows = conn.execute(
        "SELECT account_id, balance FROM account_balances"
    ).fetchall()
    for row in actual_rows:
        actual_balances[str(row[0])] = row[1]

    details = []
    mismatches = 0
    for row in recomputed:
        account_id = str(row[0])
        expected = row[1]
        actual = actual_balances.get(account_id, 0)
        diff = expected - actual if actual is not None else expected
        status = "ok" if diff == 0 else "mismatch"
        if diff != 0:
            mismatches += 1
        details.append(ReconciliationAccountResult(
            account_id=account_id,
            expected_balance=str(expected),
            actual_balance=str(actual),
            difference=str(diff),
            status=status,
        ))

    overall = "pass" if mismatches == 0 and global_ok and journal_ok else "fail"

    return ReconciliationReport(
        status=overall,
        global_balance_ok=global_ok,
        journal_integrity_ok=journal_ok,
        accounts_checked=len(recomputed),
        mismatches=mismatches,
        details=details,
    )


def _check_global_balance(conn: psycopg.Connection) -> bool:
    """Verify total system debits equal total system credits."""
    row = conn.execute(
        """
        SELECT SUM(je.debit) AS total_debits,
               SUM(je.credit) AS total_credits
        FROM journal_entries je
        JOIN journals j ON j.id = je.journal_id
        WHERE j.status = 'confirmed'
        """
    ).fetchone()
    if row is None or row[0] is None:
        return True
    return row[0] == row[1]


def _check_journal_integrity(conn: psycopg.Connection) -> bool:
    """Verify every confirmed journal has balanced entries."""
    row = conn.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT j.id
            FROM journals j
            JOIN journal_entries je ON je.journal_id = j.id
            WHERE j.status = 'confirmed'
            GROUP BY j.id
            HAVING SUM(je.debit) != SUM(je.credit)
        ) unbalanced
        """
    ).fetchone()
    return row is not None and row[0] == 0
