"""Pydantic request/response schemas for the API Gateway."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class TradeSubmitRequest(BaseModel):
    """Request body for submitting a new trade.

    Attributes:
        external_trade_id: Client-assigned trade identifier.
        instrument_id: UUID of the traded instrument.
        buyer_member_id: UUID of the buying member.
        seller_member_id: UUID of the selling member.
        quantity: Number of units traded.
        price: Execution price per unit.
    """

    external_trade_id: str
    instrument_id: UUID
    buyer_member_id: UUID
    seller_member_id: UUID
    quantity: Decimal
    price: Decimal


class TradeResponse(BaseModel):
    """Response body for trade queries.

    Attributes:
        id: Internal trade UUID.
        external_trade_id: Client-assigned trade identifier.
        instrument_id: UUID of the traded instrument.
        buyer_member_id: UUID of the buying member.
        seller_member_id: UUID of the selling member.
        quantity: Number of units traded.
        price: Execution price per unit.
        status: Current processing status.
        submitted_at: When the trade was submitted.
    """

    id: UUID
    external_trade_id: str
    instrument_id: UUID
    buyer_member_id: UUID
    seller_member_id: UUID
    quantity: Decimal
    price: Decimal
    status: str
    submitted_at: datetime

    model_config = {"from_attributes": True}


class MemberResponse(BaseModel):
    """Response body for member queries.

    Attributes:
        id: Member UUID.
        lei: Legal Entity Identifier.
        name: Human-readable member name.
        status: Current membership status.
        credit_limit: Maximum credit exposure.
    """

    id: UUID
    lei: str
    name: str
    status: str
    credit_limit: Decimal

    model_config = {"from_attributes": True}


class PositionResponse(BaseModel):
    """Response body for member position queries.

    Attributes:
        instrument_id: The instrument UUID.
        long_quantity: Total long quantity.
        short_quantity: Total short quantity.
        net_quantity: Net position (long - short).
        avg_price: Volume-weighted average price.
    """

    instrument_id: UUID
    long_quantity: Decimal
    short_quantity: Decimal
    net_quantity: Decimal
    avg_price: Decimal

    model_config = {"from_attributes": True}


class AccountBalanceResponse(BaseModel):
    """Response body for account balance queries.

    Attributes:
        account_id: Ledger account UUID.
        account_type: Type of account.
        currency: Account currency code.
        pool: Whether funds are available or locked.
        balance: Current balance.
    """

    account_id: UUID
    account_type: str
    currency: str
    pool: str
    balance: Decimal

    model_config = {"from_attributes": True}


class HealthResponse(BaseModel):
    """Response body for health check endpoint.

    Attributes:
        status: Service health status.
        service: Service name.
    """

    status: str
    service: str


class DeadLetterEventResponse(BaseModel):
    """Response body for dead letter queue entries."""

    id: UUID
    service_name: str
    topic: str
    event_key: str | None
    error_message: str
    created_at: datetime
    retry_count: int

    model_config = {"from_attributes": True}


class ReconciliationAccountResult(BaseModel):
    """Per-account reconciliation result."""

    account_id: str
    expected_balance: str
    actual_balance: str
    difference: str
    status: str


class ReconciliationReport(BaseModel):
    """Response body for reconciliation results."""

    status: str
    global_balance_ok: bool
    journal_integrity_ok: bool
    accounts_checked: int
    mismatches: int
    details: list[ReconciliationAccountResult]
