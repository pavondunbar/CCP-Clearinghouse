"""Enumerations for the CCP Clearing House domain model."""

from enum import Enum


class MemberStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEFAULTED = "defaulted"


class AccountType(str, Enum):
    MARGIN_IM = "MARGIN_IM"
    MARGIN_VM = "MARGIN_VM"
    DEFAULT_FUND = "DEFAULT_FUND"
    COLLATERAL = "COLLATERAL"
    SETTLEMENT = "SETTLEMENT"
    CCP_EQUITY = "CCP_EQUITY"


class PoolType(str, Enum):
    AVAILABLE = "AVAILABLE"
    LOCKED = "LOCKED"


class InstrumentAssetClass(str, Enum):
    CRYPTO_FUTURE = "crypto_future"
    CRYPTO_OPTION = "crypto_option"
    CRYPTO_PERPETUAL = "crypto_perpetual"
    TOKENIZED_EQUITY = "tokenized_equity"
    TOKENIZED_BOND = "tokenized_bond"
    TOKENIZED_RWA = "tokenized_rwa"


class SettlementType(str, Enum):
    CASH = "cash"
    PHYSICAL = "physical"
    DVP = "dvp"


class TradeStatus(str, Enum):
    SUBMITTED = "submitted"
    VALIDATED = "validated"
    NOVATED = "novated"
    SETTLED = "settled"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NovatedTradeStatus(str, Enum):
    OPEN = "open"
    NETTED = "netted"
    SETTLED = "settled"
    DEFAULTED = "defaulted"


class NovatedTradeSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class JournalType(str, Enum):
    TRADE_INITIATION = "TRADE_INITIATION"
    MARGIN_LOCK = "MARGIN_LOCK"
    MARGIN_RELEASE = "MARGIN_RELEASE"
    VARIATION_MARGIN = "VARIATION_MARGIN"
    SETTLEMENT = "SETTLEMENT"
    COLLATERAL_DEPOSIT = "COLLATERAL_DEPOSIT"
    COLLATERAL_WITHDRAWAL = "COLLATERAL_WITHDRAWAL"
    DEFAULT_FUND_CONTRIBUTION = "DEFAULT_FUND_CONTRIBUTION"
    DEFAULT_WATERFALL_STEP = "DEFAULT_WATERFALL_STEP"
    NETTING_OBLIGATION = "NETTING_OBLIGATION"


class JournalStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class MarginType(str, Enum):
    INITIAL = "INITIAL"
    VARIATION = "VARIATION"


class MarginCallStatus(str, Enum):
    ISSUED = "issued"
    MET = "met"
    PARTIAL = "partial"
    BREACHED = "breached"


class SettlementInstructionStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    SIGNED = "signed"
    BROADCASTED = "broadcasted"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NettingCycleStatus(str, Enum):
    INITIATED = "initiated"
    CALCULATING = "calculating"
    CALCULATED = "calculated"
    CONFIRMED = "confirmed"
    SETTLED = "settled"
    FAILED = "failed"


class NettingCycleType(str, Enum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"
    INTRADAY = "intraday"


class DefaultEventStatus(str, Enum):
    DETECTED = "detected"
    MARGIN_LIQUIDATED = "margin_liquidated"
    DEFAULT_FUND_APPLIED = "default_fund_applied"
    CCP_EQUITY_APPLIED = "ccp_equity_applied"
    MUTUALIZED = "mutualized"
    RESOLVED = "resolved"
    PARTIALLY_RESOLVED = "partially_resolved"


class WaterfallStepType(str, Enum):
    DEFAULTER_MARGIN = "defaulter_margin"
    DEFAULTER_DEFAULT_FUND = "defaulter_default_fund"
    CCP_EQUITY = "ccp_equity"
    SURVIVING_MEMBERS_DEFAULT_FUND = "surviving_members_default_fund"
    LOSS_ALLOCATION = "loss_allocation"


class StateEntityType(str, Enum):
    TRADE = "trade"
    NOVATED_TRADE = "novated_trade"
    NETTING_CYCLE = "netting_cycle"
    SETTLEMENT_INSTRUCTION = "settlement_instruction"
    MARGIN_CALL = "margin_call"
    DEFAULT_EVENT = "default_event"
    MEMBER = "member"
