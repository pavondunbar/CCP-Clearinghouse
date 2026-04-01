"""Pydantic models for trades, novated trades, and positions."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from ccp_shared.enums import (
    NovatedTradeSide,
    NovatedTradeStatus,
    TradeStatus,
)


class Trade(BaseModel):
    """Represents an incoming trade submitted by a member.

    Attributes:
        id: Unique trade identifier.
        buyer_member_id: UUID of the buying member.
        seller_member_id: UUID of the selling member.
        instrument_id: UUID of the traded instrument.
        quantity: Number of units traded.
        price: Trade execution price.
        status: Current processing status.
        submitted_at: When the trade was submitted.
        novated_at: When novation completed (if applicable).
    """

    id: UUID
    buyer_member_id: UUID
    seller_member_id: UUID
    instrument_id: UUID
    quantity: Decimal
    price: Decimal
    status: TradeStatus
    submitted_at: datetime
    novated_at: datetime | None = None

    model_config = {"from_attributes": True}


class NovatedTrade(BaseModel):
    """Represents one leg of a novated trade (member vs CCP).

    Attributes:
        id: Unique novated trade identifier.
        original_trade_id: Reference to the original trade.
        member_id: The member on this leg of the trade.
        instrument_id: The traded instrument.
        side: Whether the member is buyer or seller.
        quantity: Number of units.
        price: Execution price.
        status: Current status of this novated leg.
        novated_at: When novation occurred.
    """

    id: UUID
    original_trade_id: UUID
    member_id: UUID
    instrument_id: UUID
    side: NovatedTradeSide
    quantity: Decimal
    price: Decimal
    status: NovatedTradeStatus
    novated_at: datetime

    model_config = {"from_attributes": True}


class MemberPosition(BaseModel):
    """Aggregated net position for a member in an instrument.

    Attributes:
        member_id: The member holding the position.
        instrument_id: The instrument.
        net_quantity: Net quantity (positive = long, negative = short).
        avg_price: Volume-weighted average price.
        last_updated: When the position was last recalculated.
    """

    member_id: UUID
    instrument_id: UUID
    net_quantity: Decimal
    avg_price: Decimal
    last_updated: datetime

    model_config = {"from_attributes": True}
