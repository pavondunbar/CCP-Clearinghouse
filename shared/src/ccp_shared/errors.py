"""Exception hierarchy for the CCP Clearing House."""

from decimal import Decimal
from uuid import UUID

from ccp_shared.enums import StateEntityType


class CCPError(Exception):
    """Base exception for all CCP Clearing House errors."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class ValidationError(CCPError):
    """Raised when input validation fails."""


class InsufficientMarginError(CCPError):
    """Raised when a member lacks sufficient margin."""

    def __init__(
        self,
        message: str,
        member_id: UUID,
        required: Decimal,
        available: Decimal,
    ) -> None:
        self.member_id = member_id
        self.required = required
        self.available = available
        super().__init__(message)


class NovationError(CCPError):
    """Raised when trade novation fails."""

    def __init__(self, message: str, trade_id: UUID) -> None:
        self.trade_id = trade_id
        super().__init__(message)


class NettingError(CCPError):
    """Raised when a netting cycle fails."""

    def __init__(self, message: str, cycle_id: UUID) -> None:
        self.cycle_id = cycle_id
        super().__init__(message)


class SettlementError(CCPError):
    """Raised when settlement processing fails."""

    def __init__(self, message: str, instruction_id: UUID) -> None:
        self.instruction_id = instruction_id
        super().__init__(message)


class DefaultError(CCPError):
    """Raised during default event processing failures."""

    def __init__(self, message: str, member_id: UUID) -> None:
        self.member_id = member_id
        super().__init__(message)


class LedgerImbalanceError(CCPError):
    """Raised when journal debits and credits do not balance."""

    def __init__(
        self,
        message: str,
        journal_id: UUID,
        debit_sum: Decimal,
        credit_sum: Decimal,
    ) -> None:
        self.journal_id = journal_id
        self.debit_sum = debit_sum
        self.credit_sum = credit_sum
        super().__init__(message)


class StateTransitionError(CCPError):
    """Raised when an invalid state transition is attempted."""

    def __init__(
        self,
        message: str,
        *,
        entity_type: StateEntityType,
        entity_id: UUID,
        from_status: str,
        to_status: str,
    ) -> None:
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(message)
