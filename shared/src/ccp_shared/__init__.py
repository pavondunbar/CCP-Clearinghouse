"""CCP Clearing House shared library.

Provides configuration, domain models, database helpers,
Kafka integration, blockchain adapters, and MPC signing.
"""

from ccp_shared.config import CCPSettings
from ccp_shared.enums import (
    AccountType,
    DefaultEventStatus,
    InstrumentAssetClass,
    JournalStatus,
    JournalType,
    MarginCallStatus,
    MarginType,
    MemberStatus,
    NettingCycleStatus,
    NettingCycleType,
    NovatedTradeSide,
    NovatedTradeStatus,
    PoolType,
    SettlementInstructionStatus,
    SettlementType,
    StateEntityType,
    TradeStatus,
    WaterfallStepType,
)
from ccp_shared.errors import (
    CCPError,
    DefaultError,
    InsufficientMarginError,
    LedgerImbalanceError,
    NettingError,
    NovationError,
    SettlementError,
    StateTransitionError,
    ValidationError,
)
from ccp_shared.models.instrument import Instrument
from ccp_shared.models.journal import AccountBalance, Journal, JournalEntry
from ccp_shared.models.margin import MarginCall, MarginRequirement
from ccp_shared.models.member import Member
from ccp_shared.models.trade import MemberPosition, NovatedTrade, Trade

__all__ = [
    # Config
    "CCPSettings",
    # Enums
    "AccountType",
    "DefaultEventStatus",
    "InstrumentAssetClass",
    "JournalStatus",
    "JournalType",
    "MarginCallStatus",
    "MarginType",
    "MemberStatus",
    "NettingCycleStatus",
    "NettingCycleType",
    "NovatedTradeSide",
    "NovatedTradeStatus",
    "PoolType",
    "SettlementInstructionStatus",
    "SettlementType",
    "StateEntityType",
    "TradeStatus",
    "WaterfallStepType",
    # Errors
    "CCPError",
    "DefaultError",
    "InsufficientMarginError",
    "LedgerImbalanceError",
    "NettingError",
    "NovationError",
    "SettlementError",
    "StateTransitionError",
    "ValidationError",
    # Models
    "AccountBalance",
    "Instrument",
    "Journal",
    "JournalEntry",
    "MarginCall",
    "MarginRequirement",
    "Member",
    "MemberPosition",
    "NovatedTrade",
    "Trade",
]
