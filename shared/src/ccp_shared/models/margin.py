"""Pydantic models for margin requirements and calls."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from ccp_shared.enums import MarginCallStatus, MarginType


class MarginRequirement(BaseModel):
    """Calculated margin requirement for a member.

    Attributes:
        id: Unique requirement identifier.
        member_id: The member this requirement applies to.
        margin_type: Initial or variation margin.
        required_amount: Calculated required margin.
        held_amount: Currently held margin.
        deficit: Shortfall amount (required - held, floored at 0).
        calculated_at: When this was last computed.
    """

    id: UUID
    member_id: UUID
    margin_type: MarginType
    required_amount: Decimal
    held_amount: Decimal
    deficit: Decimal
    calculated_at: datetime

    model_config = {"from_attributes": True}


class MarginCall(BaseModel):
    """A margin call issued to a member.

    Attributes:
        id: Unique margin call identifier.
        member_id: The member being called.
        margin_type: Initial or variation margin.
        amount: Amount of margin required.
        status: Current call status.
        issued_at: When the call was issued.
        deadline: When the member must meet the call.
        met_at: When the call was satisfied (if applicable).
    """

    id: UUID
    member_id: UUID
    margin_type: MarginType
    amount: Decimal
    status: MarginCallStatus
    issued_at: datetime
    deadline: datetime
    met_at: datetime | None = None

    model_config = {"from_attributes": True}
