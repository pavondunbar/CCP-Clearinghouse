"""Pydantic models for clearing members."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from ccp_shared.enums import MemberStatus


class Member(BaseModel):
    """Represents a clearing member of the CCP.

    Attributes:
        id: Unique member identifier.
        lei: Legal Entity Identifier (ISO 17442).
        name: Human-readable member name.
        status: Current membership status.
        credit_limit: Maximum credit exposure permitted.
        created_at: Timestamp of member registration.
        updated_at: Timestamp of last modification.
    """

    id: UUID
    lei: str
    name: str
    status: MemberStatus
    credit_limit: Decimal
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
