"""Pydantic models for the double-entry ledger."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from ccp_shared.enums import (
    AccountType,
    JournalStatus,
    JournalType,
    PoolType,
)


class JournalEntry(BaseModel):
    """A single debit or credit line within a journal.

    Attributes:
        id: Unique entry identifier.
        journal_id: Parent journal.
        account_id: Target ledger account.
        direction: Either 'debit' or 'credit'.
        amount: Entry amount (always positive).
    """

    id: UUID
    journal_id: UUID
    account_id: UUID
    direction: str
    amount: Decimal

    model_config = {"from_attributes": True}


class Journal(BaseModel):
    """A double-entry journal recording a financial event.

    Attributes:
        id: Unique journal identifier.
        journal_type: Classification of the financial event.
        status: Processing status.
        reference_id: UUID of the related entity (trade, margin call, etc).
        description: Human-readable description.
        entries: Line items (debits and credits).
        created_at: When the journal was created.
    """

    id: UUID
    journal_type: JournalType
    status: JournalStatus
    reference_id: UUID | None = None
    description: str = ""
    entries: list[JournalEntry] = []
    created_at: datetime

    model_config = {"from_attributes": True}


class AccountBalance(BaseModel):
    """Current balance of a ledger account.

    Attributes:
        account_id: The ledger account.
        member_id: Owning member (None for CCP-owned accounts).
        account_type: Type of account.
        pool_type: Whether funds are available or locked.
        balance: Current balance.
        as_of: Timestamp of last update.
    """

    account_id: UUID
    member_id: UUID | None = None
    account_type: AccountType
    pool_type: PoolType
    balance: Decimal
    as_of: datetime

    model_config = {"from_attributes": True}
