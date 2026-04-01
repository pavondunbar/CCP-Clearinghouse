#!/usr/bin/env python3
"""Self-contained CCP Clearing House demo.

Simulates the full clearing house lifecycle in-memory using only
Python stdlib. No Docker, no Postgres, no Kafka required.

Faithfully mirrors the production system's data models, algorithms,
and business logic from the actual microservice source code.

Usage:
    python run_demo.py
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum


# ── Enums (from ccp_shared/enums.py) ────────────────────────────


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


# ── Data Models (from ccp_shared/models/) ───────────────────────


@dataclass
class Member:
    id: uuid.UUID
    lei: str
    name: str
    status: MemberStatus
    credit_limit: Decimal
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class Account:
    id: uuid.UUID
    member_id: uuid.UUID
    account_type: AccountType
    pool_type: PoolType
    balance: Decimal = Decimal("0")


@dataclass
class Instrument:
    id: uuid.UUID
    symbol: str
    asset_class: InstrumentAssetClass
    settlement_type: SettlementType
    margin_rate_im: Decimal
    margin_rate_vm: Decimal
    chain_id: str | None = None
    contract_address: str | None = None


@dataclass
class Trade:
    id: uuid.UUID
    buyer_member_id: uuid.UUID
    seller_member_id: uuid.UUID
    instrument_id: uuid.UUID
    quantity: Decimal
    price: Decimal
    status: TradeStatus
    submitted_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class NovatedTrade:
    id: uuid.UUID
    original_trade_id: uuid.UUID
    member_id: uuid.UUID
    instrument_id: uuid.UUID
    side: NovatedTradeSide
    quantity: Decimal
    price: Decimal
    status: NovatedTradeStatus
    novated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class JournalEntry:
    id: uuid.UUID
    journal_id: uuid.UUID
    account_id: uuid.UUID
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")


@dataclass
class Journal:
    id: uuid.UUID
    journal_type: JournalType
    status: JournalStatus
    reference_id: uuid.UUID | None = None
    description: str = ""
    entries: list[JournalEntry] = field(default_factory=list)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class MarginRequirement:
    member_id: uuid.UUID
    instrument_id: uuid.UUID
    margin_type: MarginType
    required_amount: Decimal
    held_amount: Decimal = Decimal("0")
    deficit: Decimal = Decimal("0")


@dataclass
class MarginCall:
    id: uuid.UUID
    member_id: uuid.UUID
    margin_type: MarginType
    amount: Decimal
    status: MarginCallStatus
    issued_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    deadline: datetime = field(
        default_factory=lambda: (
            datetime.now(timezone.utc) + timedelta(hours=2)
        )
    )


@dataclass
class SettlementInstruction:
    id: uuid.UUID
    from_member_id: uuid.UUID
    to_member_id: uuid.UUID
    instrument_id: uuid.UUID
    quantity: Decimal
    amount: Decimal
    settlement_type: SettlementType
    status: str = "pending"
    tx_hash: str | None = None


@dataclass
class NetObligation:
    member_id: uuid.UUID
    instrument_id: uuid.UUID
    net_quantity: Decimal
    net_amount: Decimal
    settlement_amount: Decimal
    settlement_type: SettlementType


@dataclass
class Event:
    event_type: str
    payload: dict
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ── In-Memory State (replaces PostgreSQL + Kafka) ───────────────


class ClearingHouse:
    """In-memory clearing house state and operations."""

    def __init__(self) -> None:
        self.members: dict[uuid.UUID, Member] = {}
        self.accounts: dict[uuid.UUID, Account] = {}
        self.instruments: dict[uuid.UUID, Instrument] = {}
        self.trades: dict[uuid.UUID, Trade] = {}
        self.novated_trades: dict[uuid.UUID, NovatedTrade] = {}
        self.journals: dict[uuid.UUID, Journal] = {}
        self.margin_requirements: list[MarginRequirement] = []
        self.margin_calls: list[MarginCall] = []
        self.settlement_instructions: list[SettlementInstruction] = []
        self.net_obligations: list[NetObligation] = []
        self.events: list[Event] = []
        self.ccp_id: uuid.UUID | None = None
        self.member_name_to_id: dict[str, uuid.UUID] = {}
        self.instrument_symbol_to_id: dict[str, uuid.UUID] = {}

    def emit_event(self, event_type: str, payload: dict) -> None:
        self.events.append(Event(event_type=event_type, payload=payload))

    def find_account(
        self,
        member_id: uuid.UUID,
        account_type: AccountType,
        pool_type: PoolType,
    ) -> Account | None:
        for acct in self.accounts.values():
            if (
                acct.member_id == member_id
                and acct.account_type == account_type
                and acct.pool_type == pool_type
            ):
                return acct
        return None

    def create_journal(
        self,
        journal_type: JournalType,
        description: str,
        reference_id: uuid.UUID | None,
        debit_account_id: uuid.UUID,
        credit_account_id: uuid.UUID,
        amount: Decimal,
    ) -> Journal:
        journal_id = uuid.uuid4()
        debit_entry = JournalEntry(
            id=uuid.uuid4(),
            journal_id=journal_id,
            account_id=debit_account_id,
            debit=amount,
        )
        credit_entry = JournalEntry(
            id=uuid.uuid4(),
            journal_id=journal_id,
            account_id=credit_account_id,
            credit=amount,
        )
        journal = Journal(
            id=journal_id,
            journal_type=journal_type,
            status=JournalStatus.CONFIRMED,
            reference_id=reference_id,
            description=description,
            entries=[debit_entry, credit_entry],
        )
        self.journals[journal_id] = journal

        debit_acct = self.accounts[debit_account_id]
        credit_acct = self.accounts[credit_account_id]
        debit_acct.balance += amount
        credit_acct.balance += amount

        return journal


# ── Seed Data (from scripts/seed-members.py) ────────────────────


MEMBERS_DATA = [
    {
        "lei": "529900HNOAA1KXQJUQ27",
        "name": "Alpha Capital Markets",
        "credit_limit": Decimal("50000000.00"),
    },
    {
        "lei": "213800WSGIIZCXF1P572",
        "name": "Beta Securities LLC",
        "credit_limit": Decimal("75000000.00"),
    },
    {
        "lei": "549300MLUDYVRQOOXS22",
        "name": "Gamma Digital Assets",
        "credit_limit": Decimal("30000000.00"),
    },
    {
        "lei": "353800KFBP72XHSW7E44",
        "name": "Delta Institutional Trading",
        "credit_limit": Decimal("100000000.00"),
    },
    {
        "lei": "815600OPPT9MZBGEE678",
        "name": "Epsilon Fund Services",
        "credit_limit": Decimal("60000000.00"),
    },
]

INSTRUMENTS_DATA = [
    {
        "symbol": "BTC-PERP",
        "asset_class": InstrumentAssetClass.CRYPTO_PERPETUAL,
        "settlement_type": SettlementType.CASH,
        "margin_rate_im": Decimal("0.100000"),
        "margin_rate_vm": Decimal("0.050000"),
    },
    {
        "symbol": "ETH-FUTURE-Q2",
        "asset_class": InstrumentAssetClass.CRYPTO_FUTURE,
        "settlement_type": SettlementType.CASH,
        "margin_rate_im": Decimal("0.120000"),
        "margin_rate_vm": Decimal("0.060000"),
    },
    {
        "symbol": "BTC-OPTION-30K",
        "asset_class": InstrumentAssetClass.CRYPTO_OPTION,
        "settlement_type": SettlementType.CASH,
        "margin_rate_im": Decimal("0.150000"),
        "margin_rate_vm": Decimal("0.070000"),
    },
    {
        "symbol": "AAPL-TOKEN",
        "asset_class": InstrumentAssetClass.TOKENIZED_EQUITY,
        "settlement_type": SettlementType.DVP,
        "margin_rate_im": Decimal("0.050000"),
        "margin_rate_vm": Decimal("0.025000"),
        "chain_id": "ethereum-mainnet",
        "contract_address": (
            "0x1234567890abcdef1234567890abcdef12345678"
        ),
    },
    {
        "symbol": "TBOND-10Y",
        "asset_class": InstrumentAssetClass.TOKENIZED_BOND,
        "settlement_type": SettlementType.DVP,
        "margin_rate_im": Decimal("0.030000"),
        "margin_rate_vm": Decimal("0.015000"),
        "chain_id": "ethereum-mainnet",
        "contract_address": (
            "0xabcdef1234567890abcdef1234567890abcdef12"
        ),
    },
    {
        "symbol": "REALESTATE-RWA-1",
        "asset_class": InstrumentAssetClass.TOKENIZED_RWA,
        "settlement_type": SettlementType.DVP,
        "margin_rate_im": Decimal("0.200000"),
        "margin_rate_vm": Decimal("0.100000"),
        "chain_id": "polygon-mainnet",
        "contract_address": (
            "0x9876543210fedcba9876543210fedcba98765432"
        ),
    },
]

DEFAULT_FUND_AMOUNTS = {
    "Alpha Capital Markets": Decimal("5000000.00"),
    "Beta Securities LLC": Decimal("7500000.00"),
    "Gamma Digital Assets": Decimal("3000000.00"),
    "Delta Institutional Trading": Decimal("10000000.00"),
    "Epsilon Fund Services": Decimal("6000000.00"),
}

MEMBER_ACCOUNT_TYPES = [
    AccountType.MARGIN_IM,
    AccountType.MARGIN_VM,
    AccountType.DEFAULT_FUND,
    AccountType.COLLATERAL,
    AccountType.SETTLEMENT,
]

CCP_ACCOUNT_TYPES = [
    *MEMBER_ACCOUNT_TYPES,
    AccountType.CCP_EQUITY,
]

POOLS = [PoolType.AVAILABLE, PoolType.LOCKED]


# ── Trade Scenarios ─────────────────────────────────────────────


TRADE_SCENARIOS = [
    {
        "buyer": "Alpha Capital Markets",
        "seller": "Beta Securities LLC",
        "instrument": "BTC-PERP",
        "quantity": Decimal("10"),
        "price": Decimal("67500.00"),
    },
    {
        "buyer": "Gamma Digital Assets",
        "seller": "Delta Institutional Trading",
        "instrument": "ETH-FUTURE-Q2",
        "quantity": Decimal("100"),
        "price": Decimal("3800.00"),
    },
    {
        "buyer": "Beta Securities LLC",
        "seller": "Epsilon Fund Services",
        "instrument": "BTC-OPTION-30K",
        "quantity": Decimal("5"),
        "price": Decimal("5200.00"),
    },
    {
        "buyer": "Delta Institutional Trading",
        "seller": "Alpha Capital Markets",
        "instrument": "AAPL-TOKEN",
        "quantity": Decimal("500"),
        "price": Decimal("185.50"),
    },
    {
        "buyer": "Epsilon Fund Services",
        "seller": "Gamma Digital Assets",
        "instrument": "TBOND-10Y",
        "quantity": Decimal("1000"),
        "price": Decimal("98.75"),
    },
    {
        "buyer": "Alpha Capital Markets",
        "seller": "Gamma Digital Assets",
        "instrument": "REALESTATE-RWA-1",
        "quantity": Decimal("25"),
        "price": Decimal("150000.00"),
    },
]

PRICE_MOVEMENTS = {
    "BTC-PERP": Decimal("69200.00"),
    "ETH-FUTURE-Q2": Decimal("3650.00"),
    "BTC-OPTION-30K": Decimal("5800.00"),
    "AAPL-TOKEN": Decimal("182.00"),
    "TBOND-10Y": Decimal("99.50"),
    "REALESTATE-RWA-1": Decimal("148000.00"),
}


# ── Output Formatting ──────────────────────────────────────────


def header(title: str) -> None:
    width = 72
    print()
    print("=" * width)
    print(f"  {title}")
    print("=" * width)


def subheader(title: str) -> None:
    print(f"\n  --- {title} ---")


def bullet(text: str) -> None:
    print(f"    * {text}")


def detail(label: str, value: object) -> None:
    print(f"      {label}: {value}")


def money(amount: Decimal) -> str:
    return f"${amount:,.2f}"


def short_id(uid: uuid.UUID) -> str:
    return str(uid)[:8]


# ── Phase 1: Initialization ────────────────────────────────────


def phase_1_initialization(ch: ClearingHouse) -> None:
    header("PHASE 1: INITIALIZATION")

    subheader("CCP House Account")
    ccp_id = uuid.uuid4()
    ccp = Member(
        id=ccp_id,
        lei="CCP000000000000000",
        name="CCP House Account",
        status=MemberStatus.ACTIVE,
        credit_limit=Decimal("0"),
    )
    ch.members[ccp_id] = ccp
    ch.ccp_id = ccp_id
    ch.member_name_to_id["CCP House Account"] = ccp_id

    for acct_type in CCP_ACCOUNT_TYPES:
        for pool in POOLS:
            acct_id = uuid.uuid4()
            ch.accounts[acct_id] = Account(
                id=acct_id,
                member_id=ccp_id,
                account_type=acct_type,
                pool_type=pool,
            )

    ccp_equity_acct = ch.find_account(
        ccp_id, AccountType.CCP_EQUITY, PoolType.AVAILABLE
    )
    if ccp_equity_acct:
        ccp_equity_acct.balance = Decimal("25000000.00")

    bullet(f"Created: {ccp.name} (LEI: {ccp.lei})")
    bullet(f"ID: {ccp_id}")
    bullet(f"CCP Equity: {money(Decimal('25000000.00'))}")

    subheader("Clearing Members")
    for mdata in MEMBERS_DATA:
        mid = uuid.uuid4()
        member = Member(
            id=mid,
            lei=mdata["lei"],
            name=mdata["name"],
            status=MemberStatus.ACTIVE,
            credit_limit=mdata["credit_limit"],
        )
        ch.members[mid] = member
        ch.member_name_to_id[mdata["name"]] = mid

        for acct_type in MEMBER_ACCOUNT_TYPES:
            for pool in POOLS:
                acct_id = uuid.uuid4()
                ch.accounts[acct_id] = Account(
                    id=acct_id,
                    member_id=mid,
                    account_type=acct_type,
                    pool_type=pool,
                )

        collateral_acct = ch.find_account(
            mid, AccountType.COLLATERAL, PoolType.AVAILABLE
        )
        if collateral_acct:
            collateral_acct.balance = mdata["credit_limit"]

        margin_im_acct = ch.find_account(
            mid, AccountType.MARGIN_IM, PoolType.AVAILABLE
        )
        if margin_im_acct:
            margin_im_acct.balance = mdata["credit_limit"] * Decimal(
                "0.1"
            )

        bullet(
            f"{member.name} | LEI: {member.lei} "
            f"| Credit Limit: {money(member.credit_limit)}"
        )

    subheader("Instruments")
    for idata in INSTRUMENTS_DATA:
        iid = uuid.uuid4()
        inst = Instrument(
            id=iid,
            symbol=idata["symbol"],
            asset_class=idata["asset_class"],
            settlement_type=idata["settlement_type"],
            margin_rate_im=idata["margin_rate_im"],
            margin_rate_vm=idata["margin_rate_vm"],
            chain_id=idata.get("chain_id"),
            contract_address=idata.get("contract_address"),
        )
        ch.instruments[iid] = inst
        ch.instrument_symbol_to_id[idata["symbol"]] = iid
        settlement_info = f"Settlement: {inst.settlement_type.value}"
        if inst.chain_id:
            settlement_info += f" ({inst.chain_id})"
        bullet(
            f"{inst.symbol} | {inst.asset_class.value} "
            f"| IM: {inst.margin_rate_im * 100}% "
            f"| VM: {inst.margin_rate_vm * 100}% "
            f"| {settlement_info}"
        )

    subheader("Account Structure (per member)")
    bullet("MARGIN_IM  [AVAILABLE / LOCKED]")
    bullet("MARGIN_VM  [AVAILABLE / LOCKED]")
    bullet("DEFAULT_FUND [AVAILABLE / LOCKED]")
    bullet("COLLATERAL [AVAILABLE / LOCKED]")
    bullet("SETTLEMENT [AVAILABLE / LOCKED]")

    ch.emit_event(
        "system.initialized",
        {
            "members": len(MEMBERS_DATA),
            "instruments": len(INSTRUMENTS_DATA),
        },
    )
    print(
        f"\n  Initialization complete: {len(MEMBERS_DATA)} members, "
        f"{len(INSTRUMENTS_DATA)} instruments, "
        f"{sum(1 for _ in ch.accounts.values())} accounts"
    )


# ── Phase 2: Default Fund Seeding ──────────────────────────────


def phase_2_default_fund(ch: ClearingHouse) -> None:
    header("PHASE 2: DEFAULT FUND SEEDING")

    assert ch.ccp_id is not None
    ccp_settlement = ch.find_account(
        ch.ccp_id, AccountType.SETTLEMENT, PoolType.AVAILABLE
    )
    assert ccp_settlement is not None

    total = Decimal("0")
    for name, amount in DEFAULT_FUND_AMOUNTS.items():
        mid = ch.member_name_to_id[name]
        member_df_acct = ch.find_account(
            mid, AccountType.DEFAULT_FUND, PoolType.AVAILABLE
        )
        assert member_df_acct is not None

        journal = ch.create_journal(
            journal_type=JournalType.DEFAULT_FUND_CONTRIBUTION,
            description=(
                f"Default fund contribution from {name}"
            ),
            reference_id=mid,
            debit_account_id=member_df_acct.id,
            credit_account_id=ccp_settlement.id,
            amount=amount,
        )

        ch.emit_event(
            "default_fund.contribution",
            {
                "member": name,
                "amount": str(amount),
                "journal_id": str(journal.id),
            },
        )

        bullet(
            f"{name}: {money(amount)} "
            f"(journal {short_id(journal.id)})"
        )
        total += amount

    print(f"\n  Total default fund: {money(total)}")


# ── Phase 3: Trade Submission ──────────────────────────────────


def phase_3_trade_submission(ch: ClearingHouse) -> None:
    header("PHASE 3: TRADE SUBMISSION")

    for i, scenario in enumerate(TRADE_SCENARIOS, 1):
        trade_id = uuid.uuid4()
        buyer_id = ch.member_name_to_id[scenario["buyer"]]
        seller_id = ch.member_name_to_id[scenario["seller"]]
        instrument_id = ch.instrument_symbol_to_id[
            scenario["instrument"]
        ]
        notional = scenario["quantity"] * scenario["price"]

        trade = Trade(
            id=trade_id,
            buyer_member_id=buyer_id,
            seller_member_id=seller_id,
            instrument_id=instrument_id,
            quantity=scenario["quantity"],
            price=scenario["price"],
            status=TradeStatus.SUBMITTED,
        )
        ch.trades[trade_id] = trade

        ch.emit_event(
            "trade.submitted",
            {
                "trade_id": str(trade_id),
                "buyer": scenario["buyer"],
                "seller": scenario["seller"],
                "instrument": scenario["instrument"],
            },
        )

        bullet(
            f"Trade #{i}: {scenario['buyer']} buys "
            f"{scenario['quantity']} {scenario['instrument']} "
            f"from {scenario['seller']} "
            f"@ {money(scenario['price'])} "
            f"(notional: {money(notional)})"
        )

    print(f"\n  {len(TRADE_SCENARIOS)} trades submitted")


# ── Phase 4: Novation ─────────────────────────────────────────


def phase_4_novation(ch: ClearingHouse) -> None:
    """Validate and novate trades.

    Mirrors novation.py: validate -> split into BUY/SELL legs ->
    lock initial margin (qty * price * margin_rate_im per side).
    """
    header("PHASE 4: NOVATION")

    for trade in list(ch.trades.values()):
        if trade.status != TradeStatus.SUBMITTED:
            continue

        inst = ch.instruments[trade.instrument_id]
        buyer = ch.members[trade.buyer_member_id]
        seller = ch.members[trade.seller_member_id]

        subheader(
            f"Novating: {inst.symbol} "
            f"({buyer.name} <-> {seller.name})"
        )

        # Validation (from novation.py validate_trade)
        if buyer.status != MemberStatus.ACTIVE:
            bullet(f"REJECTED: buyer {buyer.name} not active")
            trade.status = TradeStatus.FAILED
            continue
        if seller.status != MemberStatus.ACTIVE:
            bullet(f"REJECTED: seller {seller.name} not active")
            trade.status = TradeStatus.FAILED
            continue
        if trade.quantity <= 0 or trade.price <= 0:
            bullet("REJECTED: invalid quantity or price")
            trade.status = TradeStatus.FAILED
            continue

        bullet("Validation passed")

        # Create BUY leg (buyer vs CCP)
        buy_nov_id = uuid.uuid4()
        buy_nov = NovatedTrade(
            id=buy_nov_id,
            original_trade_id=trade.id,
            member_id=trade.buyer_member_id,
            instrument_id=trade.instrument_id,
            side=NovatedTradeSide.BUY,
            quantity=trade.quantity,
            price=trade.price,
            status=NovatedTradeStatus.OPEN,
        )
        ch.novated_trades[buy_nov_id] = buy_nov

        # Create SELL leg (seller vs CCP)
        sell_nov_id = uuid.uuid4()
        sell_nov = NovatedTrade(
            id=sell_nov_id,
            original_trade_id=trade.id,
            member_id=trade.seller_member_id,
            instrument_id=trade.instrument_id,
            side=NovatedTradeSide.SELL,
            quantity=trade.quantity,
            price=trade.price,
            status=NovatedTradeStatus.OPEN,
        )
        ch.novated_trades[sell_nov_id] = sell_nov

        bullet(
            f"BUY leg: {buyer.name} vs CCP "
            f"(id: {short_id(buy_nov_id)})"
        )
        bullet(
            f"SELL leg: {seller.name} vs CCP "
            f"(id: {short_id(sell_nov_id)})"
        )

        # Lock initial margin (from novation.py _lock_margin)
        margin_amount = (
            trade.quantity * trade.price * inst.margin_rate_im
        )
        for member_id, nov_id, name in [
            (trade.buyer_member_id, buy_nov_id, buyer.name),
            (trade.seller_member_id, sell_nov_id, seller.name),
        ]:
            avail = ch.find_account(
                member_id,
                AccountType.MARGIN_IM,
                PoolType.AVAILABLE,
            )
            locked = ch.find_account(
                member_id,
                AccountType.MARGIN_IM,
                PoolType.LOCKED,
            )
            if avail and locked and avail.balance >= margin_amount:
                avail.balance -= margin_amount
                locked.balance += margin_amount
                journal_id = uuid.uuid4()
                journal = Journal(
                    id=journal_id,
                    journal_type=JournalType.MARGIN_LOCK,
                    status=JournalStatus.CONFIRMED,
                    reference_id=nov_id,
                    description=(
                        f"IM lock for {name} on {inst.symbol}"
                    ),
                    entries=[
                        JournalEntry(
                            id=uuid.uuid4(),
                            journal_id=journal_id,
                            account_id=avail.id,
                            credit=margin_amount,
                        ),
                        JournalEntry(
                            id=uuid.uuid4(),
                            journal_id=journal_id,
                            account_id=locked.id,
                            debit=margin_amount,
                        ),
                    ],
                )
                ch.journals[journal_id] = journal
                bullet(
                    f"Margin locked for {name}: "
                    f"{money(margin_amount)} "
                    f"({trade.quantity} x {money(trade.price)} "
                    f"x {inst.margin_rate_im * 100}%)"
                )
            else:
                bullet(
                    f"WARNING: Insufficient margin for {name} "
                    f"(need {money(margin_amount)})"
                )

        trade.status = TradeStatus.NOVATED

        ch.emit_event(
            "trade.novated",
            {
                "trade_id": str(trade.id),
                "buyer_novated_id": str(buy_nov_id),
                "seller_novated_id": str(sell_nov_id),
            },
        )

    novated_count = sum(
        1
        for t in ch.trades.values()
        if t.status == TradeStatus.NOVATED
    )
    print(
        f"\n  Novation complete: {novated_count} trades novated, "
        f"{len(ch.novated_trades)} CCP-facing legs created"
    )


# ── Phase 5: Margin Calculation ────────────────────────────────


def phase_5_margin_calculation(ch: ClearingHouse) -> None:
    """Recalculate IM/VM with simulated price movements.

    Mirrors calculator.py: calculate_initial_margin,
    calculate_variation_margin, and margin call issuance.
    """
    header("PHASE 5: MARGIN CALCULATION")

    subheader("Simulated Price Movements")
    for symbol, new_price in PRICE_MOVEMENTS.items():
        inst_id = ch.instrument_symbol_to_id[symbol]
        inst = ch.instruments[inst_id]
        old_trades = [
            nt
            for nt in ch.novated_trades.values()
            if nt.instrument_id == inst_id
        ]
        old_price = old_trades[0].price if old_trades else new_price
        change = new_price - old_price
        pct = (
            (change / old_price * 100) if old_price != 0 else Decimal("0")
        )
        direction = "+" if change >= 0 else ""
        bullet(
            f"{symbol}: {money(old_price)} -> {money(new_price)} "
            f"({direction}{pct:.2f}%)"
        )

    # Build net positions per (member, instrument)
    positions: dict[
        tuple[uuid.UUID, uuid.UUID], dict[str, Decimal]
    ] = {}
    for nt in ch.novated_trades.values():
        if nt.status != NovatedTradeStatus.OPEN:
            continue
        key = (nt.member_id, nt.instrument_id)
        if key not in positions:
            positions[key] = {
                "buy_qty": Decimal("0"),
                "sell_qty": Decimal("0"),
                "avg_price": Decimal("0"),
                "count": Decimal("0"),
            }
        if nt.side == NovatedTradeSide.BUY:
            positions[key]["buy_qty"] += nt.quantity
        else:
            positions[key]["sell_qty"] += nt.quantity
        positions[key]["avg_price"] += nt.price * nt.quantity
        positions[key]["count"] += nt.quantity

    subheader("Initial Margin Recalculation")
    for (member_id, instrument_id), pos_data in positions.items():
        member = ch.members[member_id]
        inst = ch.instruments[instrument_id]
        net_qty = pos_data["buy_qty"] - pos_data["sell_qty"]
        symbol = inst.symbol
        new_price = PRICE_MOVEMENTS.get(symbol, inst.margin_rate_im)

        # IM = abs(net_qty) * latest_price * margin_rate_im
        im_required = abs(net_qty) * new_price * inst.margin_rate_im

        avg_price = (
            pos_data["avg_price"] / pos_data["count"]
            if pos_data["count"] > 0
            else new_price
        )

        ch.margin_requirements.append(
            MarginRequirement(
                member_id=member_id,
                instrument_id=instrument_id,
                margin_type=MarginType.INITIAL,
                required_amount=im_required,
            )
        )

        bullet(
            f"{member.name} | {symbol}: "
            f"net qty={net_qty}, "
            f"IM required={money(im_required)}"
        )

    subheader("Variation Margin (Mark-to-Market)")
    margin_calls_issued: list[MarginCall] = []
    for (member_id, instrument_id), pos_data in positions.items():
        member = ch.members[member_id]
        inst = ch.instruments[instrument_id]
        net_qty = pos_data["buy_qty"] - pos_data["sell_qty"]
        symbol = inst.symbol
        new_price = PRICE_MOVEMENTS.get(symbol, Decimal("0"))
        avg_price = (
            pos_data["avg_price"] / pos_data["count"]
            if pos_data["count"] > 0
            else new_price
        )

        # VM = (current_price - previous_mark) * net_quantity
        vm_amount = (new_price - avg_price) * net_qty

        if vm_amount == Decimal("0"):
            continue

        vm_avail = ch.find_account(
            member_id, AccountType.MARGIN_VM, PoolType.AVAILABLE
        )
        vm_locked = ch.find_account(
            member_id, AccountType.MARGIN_VM, PoolType.LOCKED
        )
        if vm_avail and vm_locked:
            abs_vm = abs(vm_amount)
            if vm_amount > Decimal("0"):
                debit_acct, credit_acct = vm_avail, vm_locked
                direction_label = "owes"
            else:
                debit_acct, credit_acct = vm_locked, vm_avail
                direction_label = "receives"

            journal_id = uuid.uuid4()
            journal = Journal(
                id=journal_id,
                journal_type=JournalType.VARIATION_MARGIN,
                status=JournalStatus.CONFIRMED,
                reference_id=instrument_id,
                description=(
                    f"VM for {member.name} on {symbol}"
                ),
                entries=[
                    JournalEntry(
                        id=uuid.uuid4(),
                        journal_id=journal_id,
                        account_id=debit_acct.id,
                        debit=abs_vm,
                    ),
                    JournalEntry(
                        id=uuid.uuid4(),
                        journal_id=journal_id,
                        account_id=credit_acct.id,
                        credit=abs_vm,
                    ),
                ],
            )
            ch.journals[journal_id] = journal

            ch.margin_requirements.append(
                MarginRequirement(
                    member_id=member_id,
                    instrument_id=instrument_id,
                    margin_type=MarginType.VARIATION,
                    required_amount=abs_vm,
                )
            )

            bullet(
                f"{member.name} | {symbol}: "
                f"VM = {money(abs_vm)} ({direction_label}) "
                f"[price {money(avg_price)} -> {money(new_price)}]"
            )

            # Simulate margin call for shortfall
            im_acct = ch.find_account(
                member_id,
                AccountType.MARGIN_IM,
                PoolType.AVAILABLE,
            )
            if (
                im_acct
                and vm_amount > Decimal("0")
                and abs_vm > im_acct.balance * Decimal("0.5")
            ):
                call = MarginCall(
                    id=uuid.uuid4(),
                    member_id=member_id,
                    margin_type=MarginType.INITIAL,
                    amount=abs_vm,
                    status=MarginCallStatus.ISSUED,
                )
                ch.margin_calls.append(call)
                margin_calls_issued.append(call)

                ch.emit_event(
                    "margin.call.issued",
                    {
                        "margin_call_id": str(call.id),
                        "member": member.name,
                        "amount": str(abs_vm),
                        "deadline": call.deadline.isoformat(),
                    },
                )

    if margin_calls_issued:
        subheader("Margin Calls Issued")
        for call in margin_calls_issued:
            member = ch.members[call.member_id]
            bullet(
                f"{member.name}: "
                f"{money(call.amount)} due by "
                f"{call.deadline.strftime('%Y-%m-%d %H:%M UTC')}"
            )
    else:
        print("\n    No margin calls required")

    print(
        f"\n  Margin recalculation complete: "
        f"{len(ch.margin_requirements)} requirements, "
        f"{len(margin_calls_issued)} margin calls"
    )


# ── Phase 6: Netting ──────────────────────────────────────────


def phase_6_netting(ch: ClearingHouse) -> None:
    """Multilateral netting cycle.

    Mirrors netting.py calculate_net_obligations: aggregate open
    novated trades by (member, instrument, side), compute net
    obligations, generate settlement instructions.
    """
    header("PHASE 6: NETTING CYCLE")

    assert ch.ccp_id is not None

    # Aggregate positions (from netting.py _fetch_open_positions)
    grouped: dict[
        tuple[uuid.UUID, uuid.UUID],
        dict[str, Decimal | SettlementType],
    ] = {}
    for nt in ch.novated_trades.values():
        if nt.status != NovatedTradeStatus.OPEN:
            continue
        key = (nt.member_id, nt.instrument_id)
        if key not in grouped:
            inst = ch.instruments[nt.instrument_id]
            grouped[key] = {
                "buy_qty": Decimal("0"),
                "sell_qty": Decimal("0"),
                "latest_price": PRICE_MOVEMENTS.get(
                    inst.symbol, nt.price
                ),
                "settlement_type": inst.settlement_type,
            }
        if nt.side == NovatedTradeSide.BUY:
            grouped[key]["buy_qty"] += nt.quantity
        else:
            grouped[key]["sell_qty"] += nt.quantity

    # Calculate net obligations
    # (from netting.py calculate_net_obligations)
    subheader("Net Obligation Calculation")
    obligations: list[NetObligation] = []
    for (member_id, instrument_id), data in grouped.items():
        buy_qty = data["buy_qty"]
        sell_qty = data["sell_qty"]
        net_qty = buy_qty - sell_qty
        if net_qty == Decimal("0"):
            continue

        latest_price = data["latest_price"]
        net_amount = net_qty * latest_price

        obl = NetObligation(
            member_id=member_id,
            instrument_id=instrument_id,
            net_quantity=net_qty,
            net_amount=net_amount,
            settlement_amount=abs(net_amount),
            settlement_type=data["settlement_type"],
        )
        obligations.append(obl)
        ch.net_obligations.append(obl)

        member = ch.members[member_id]
        inst = ch.instruments[instrument_id]
        direction = "LONG" if net_qty > 0 else "SHORT"
        bullet(
            f"{member.name} | {inst.symbol}: "
            f"{direction} {abs(net_qty)} @ {money(latest_price)} "
            f"= {money(obl.settlement_amount)}"
        )

    # Generate settlement instructions
    # (from netting.py _insert_obligations_and_instructions)
    subheader("Settlement Instructions")
    for obl in obligations:
        instr_id = uuid.uuid4()
        if obl.net_amount > Decimal("0"):
            from_member = obl.member_id
            to_member = ch.ccp_id
        else:
            from_member = ch.ccp_id
            to_member = obl.member_id

        si = SettlementInstruction(
            id=instr_id,
            from_member_id=from_member,
            to_member_id=to_member,
            instrument_id=obl.instrument_id,
            quantity=abs(obl.net_quantity),
            amount=obl.settlement_amount,
            settlement_type=obl.settlement_type,
        )
        ch.settlement_instructions.append(si)

        from_name = ch.members[from_member].name
        to_name = ch.members[to_member].name
        inst = ch.instruments[obl.instrument_id]
        bullet(
            f"{from_name} -> {to_name}: "
            f"{abs(obl.net_quantity)} {inst.symbol} "
            f"({money(obl.settlement_amount)}, "
            f"{obl.settlement_type.value})"
        )

    # Mark trades as netted
    for nt in ch.novated_trades.values():
        if nt.status == NovatedTradeStatus.OPEN:
            nt.status = NovatedTradeStatus.NETTED

    ch.emit_event(
        "netting.cycle.completed",
        {
            "obligation_count": len(obligations),
            "instruction_count": len(ch.settlement_instructions),
            "trades_netted": sum(
                1
                for nt in ch.novated_trades.values()
                if nt.status == NovatedTradeStatus.NETTED
            ),
        },
    )

    print(
        f"\n  Netting complete: {len(obligations)} net obligations, "
        f"{len(ch.settlement_instructions)} settlement instructions"
    )


# ── Phase 7: Settlement ───────────────────────────────────────


def phase_7_settlement(ch: ClearingHouse) -> None:
    """Execute settlement instructions.

    Mirrors settler.py: cash settlement via journal entries,
    DVP via simulated on-chain settlement with MPC signing.
    """
    header("PHASE 7: SETTLEMENT")

    assert ch.ccp_id is not None
    cash_settled = 0
    dvp_settled = 0

    for si in ch.settlement_instructions:
        inst = ch.instruments[si.instrument_id]
        from_name = ch.members[si.from_member_id].name
        to_name = ch.members[si.to_member_id].name

        if si.settlement_type == SettlementType.CASH:
            subheader(f"Cash Settlement: {inst.symbol}")
            # Cash settlement via journal (from settler.py)
            from_acct = ch.find_account(
                si.from_member_id,
                AccountType.SETTLEMENT,
                PoolType.AVAILABLE,
            )
            to_acct = ch.find_account(
                si.to_member_id,
                AccountType.SETTLEMENT,
                PoolType.AVAILABLE,
            )

            if from_acct and to_acct:
                journal = ch.create_journal(
                    journal_type=JournalType.SETTLEMENT,
                    description=(
                        f"Cash settlement: {from_name} -> "
                        f"{to_name} for {inst.symbol}"
                    ),
                    reference_id=si.id,
                    debit_account_id=to_acct.id,
                    credit_account_id=from_acct.id,
                    amount=si.amount,
                )
                si.status = "confirmed"
                cash_settled += 1

                bullet(f"From: {from_name}")
                bullet(f"To: {to_name}")
                bullet(f"Amount: {money(si.amount)}")
                bullet(
                    f"Journal: {short_id(journal.id)} (confirmed)"
                )

                ch.emit_event(
                    "settlement.completed",
                    {
                        "instruction_id": str(si.id),
                        "type": "cash",
                        "amount": str(si.amount),
                    },
                )

        elif si.settlement_type == SettlementType.DVP:
            subheader(f"DVP Settlement: {inst.symbol}")

            # Simulate MPC threshold signing (3-of-5)
            key_shares = [
                secrets.token_hex(16) for _ in range(5)
            ]
            signing_quorum = key_shares[:3]
            combined = "".join(signing_quorum)
            tx_hash = (
                "0x"
                + hashlib.sha256(
                    combined.encode()
                    + str(si.id).encode()
                ).hexdigest()
            )

            bullet(f"Chain: {inst.chain_id}")
            bullet(f"Contract: {inst.contract_address}")
            bullet(
                f"MPC signing: 3-of-5 threshold "
                f"(shares: {key_shares[0][:8]}..., "
                f"{key_shares[1][:8]}..., "
                f"{key_shares[2][:8]}...)"
            )
            bullet(f"Transaction hash: {tx_hash[:18]}...")

            # Simulate DVP: asset transfer + cash settlement
            from_acct = ch.find_account(
                si.from_member_id,
                AccountType.SETTLEMENT,
                PoolType.AVAILABLE,
            )
            to_acct = ch.find_account(
                si.to_member_id,
                AccountType.SETTLEMENT,
                PoolType.AVAILABLE,
            )

            if from_acct and to_acct:
                journal = ch.create_journal(
                    journal_type=JournalType.SETTLEMENT,
                    description=(
                        f"DVP settlement: {from_name} -> "
                        f"{to_name} for {inst.symbol} "
                        f"(tx: {tx_hash[:18]}...)"
                    ),
                    reference_id=si.id,
                    debit_account_id=to_acct.id,
                    credit_account_id=from_acct.id,
                    amount=si.amount,
                )

            si.status = "confirmed"
            si.tx_hash = tx_hash
            dvp_settled += 1

            bullet(f"From: {from_name}")
            bullet(f"To: {to_name}")
            bullet(
                f"Quantity: {si.quantity} | "
                f"Amount: {money(si.amount)}"
            )
            bullet("Status: confirmed (6 block confirmations)")

            ch.emit_event(
                "settlement.completed",
                {
                    "instruction_id": str(si.id),
                    "type": "dvp",
                    "tx_hash": tx_hash,
                    "amount": str(si.amount),
                },
            )

    print(
        f"\n  Settlement complete: {cash_settled} cash, "
        f"{dvp_settled} DVP"
    )


# ── Phase 8: Default Waterfall ─────────────────────────────────


def phase_8_default_waterfall(ch: ClearingHouse) -> None:
    """Simulate a member default and 5-step waterfall.

    Mirrors waterfall.py execute_waterfall: apply losses in order
    through defaulter's margin, default fund, CCP equity,
    surviving members' default fund, and loss allocation.
    """
    header("PHASE 8: DEFAULT WATERFALL SIMULATION")

    assert ch.ccp_id is not None

    # Pick Gamma Digital Assets as the defaulter
    defaulter_name = "Gamma Digital Assets"
    defaulter_id = ch.member_name_to_id[defaulter_name]
    defaulter = ch.members[defaulter_id]

    total_exposure = Decimal("8500000.00")

    subheader(f"Default Declaration: {defaulter_name}")
    bullet(f"Member: {defaulter_name}")
    bullet(f"LEI: {defaulter.lei}")
    bullet(f"Trigger: Missed margin call deadline")
    bullet(f"Total exposure: {money(total_exposure)}")

    defaulter.status = MemberStatus.DEFAULTED
    ch.emit_event(
        "default.declared",
        {
            "member": defaulter_name,
            "total_exposure": str(total_exposure),
        },
    )

    remaining = total_exposure
    event_id = uuid.uuid4()

    # Step 1: Defaulter's posted margin
    # (from waterfall.py _step_defaulter_margin)
    subheader("Step 1: Defaulter's Margin")
    margin_balance = Decimal("0")
    for acct in ch.accounts.values():
        if acct.member_id != defaulter_id:
            continue
        if acct.account_type in (
            AccountType.MARGIN_IM,
            AccountType.MARGIN_VM,
        ):
            margin_balance += acct.balance

    applied_1 = min(margin_balance, remaining)
    remaining -= applied_1

    if applied_1 > Decimal("0"):
        ccp_settlement = ch.find_account(
            ch.ccp_id, AccountType.SETTLEMENT, PoolType.AVAILABLE
        )
        for acct in ch.accounts.values():
            if acct.member_id != defaulter_id:
                continue
            if acct.account_type in (
                AccountType.MARGIN_IM,
                AccountType.MARGIN_VM,
            ):
                if acct.balance > Decimal("0") and ccp_settlement:
                    to_apply = min(acct.balance, remaining + applied_1)
                    journal = ch.create_journal(
                        journal_type=(
                            JournalType.DEFAULT_WATERFALL_STEP
                        ),
                        description=(
                            f"Waterfall step 1: {defaulter_name} "
                            f"margin liquidation"
                        ),
                        reference_id=event_id,
                        debit_account_id=ccp_settlement.id,
                        credit_account_id=acct.id,
                        amount=to_apply,
                    )
                    break

    bullet(f"Available margin: {money(margin_balance)}")
    bullet(f"Applied: {money(applied_1)}")
    bullet(f"Remaining loss: {money(remaining)}")

    # Step 2: Defaulter's default fund
    # (from waterfall.py _step_defaulter_default_fund)
    subheader("Step 2: Defaulter's Default Fund")
    df_acct = ch.find_account(
        defaulter_id, AccountType.DEFAULT_FUND, PoolType.AVAILABLE
    )
    df_balance = df_acct.balance if df_acct else Decimal("0")
    applied_2 = min(df_balance, remaining)
    remaining -= applied_2

    if applied_2 > Decimal("0") and df_acct:
        ccp_settlement = ch.find_account(
            ch.ccp_id, AccountType.SETTLEMENT, PoolType.AVAILABLE
        )
        if ccp_settlement:
            ch.create_journal(
                journal_type=JournalType.DEFAULT_WATERFALL_STEP,
                description=(
                    f"Waterfall step 2: {defaulter_name} "
                    f"default fund"
                ),
                reference_id=event_id,
                debit_account_id=ccp_settlement.id,
                credit_account_id=df_acct.id,
                amount=applied_2,
            )

    bullet(f"Default fund balance: {money(df_balance)}")
    bullet(f"Applied: {money(applied_2)}")
    bullet(f"Remaining loss: {money(remaining)}")

    # Step 3: CCP equity (skin in the game)
    # (from waterfall.py _step_ccp_equity)
    subheader("Step 3: CCP Equity (Skin in the Game)")
    ccp_equity = ch.find_account(
        ch.ccp_id, AccountType.CCP_EQUITY, PoolType.AVAILABLE
    )
    ccp_eq_balance = (
        ccp_equity.balance if ccp_equity else Decimal("0")
    )
    applied_3 = min(ccp_eq_balance, remaining)
    remaining -= applied_3

    if applied_3 > Decimal("0") and ccp_equity:
        ccp_settlement = ch.find_account(
            ch.ccp_id, AccountType.SETTLEMENT, PoolType.AVAILABLE
        )
        if ccp_settlement:
            ch.create_journal(
                journal_type=JournalType.DEFAULT_WATERFALL_STEP,
                description="Waterfall step 3: CCP equity",
                reference_id=event_id,
                debit_account_id=ccp_settlement.id,
                credit_account_id=ccp_equity.id,
                amount=applied_3,
            )

    bullet(f"CCP equity available: {money(ccp_eq_balance)}")
    bullet(f"Applied: {money(applied_3)}")
    bullet(f"Remaining loss: {money(remaining)}")

    # Step 4: Surviving members' default fund (pro-rata)
    # (from waterfall.py _step_surviving_default_fund)
    subheader("Step 4: Surviving Members' Default Fund (Pro-Rata)")
    survivors = [
        (mid, m)
        for mid, m in ch.members.items()
        if m.status == MemberStatus.ACTIVE
        and mid != defaulter_id
        and mid != ch.ccp_id
    ]

    survivor_funds: list[tuple[uuid.UUID, str, Decimal]] = []
    total_survivor_fund = Decimal("0")
    for mid, m in survivors:
        s_df = ch.find_account(
            mid, AccountType.DEFAULT_FUND, PoolType.AVAILABLE
        )
        bal = s_df.balance if s_df else Decimal("0")
        survivor_funds.append((mid, m.name, bal))
        total_survivor_fund += bal

    applied_4 = Decimal("0")
    if total_survivor_fund > Decimal("0") and remaining > Decimal("0"):
        for mid, name, bal in survivor_funds:
            if bal <= Decimal("0"):
                continue
            share = (bal / total_survivor_fund) * remaining
            contribution = min(share, bal)
            if contribution > Decimal("0"):
                s_df = ch.find_account(
                    mid,
                    AccountType.DEFAULT_FUND,
                    PoolType.AVAILABLE,
                )
                ccp_settlement = ch.find_account(
                    ch.ccp_id,
                    AccountType.SETTLEMENT,
                    PoolType.AVAILABLE,
                )
                if s_df and ccp_settlement:
                    ch.create_journal(
                        journal_type=(
                            JournalType.DEFAULT_WATERFALL_STEP
                        ),
                        description=(
                            f"Waterfall step 4: {name} "
                            f"default fund mutualization"
                        ),
                        reference_id=event_id,
                        debit_account_id=ccp_settlement.id,
                        credit_account_id=s_df.id,
                        amount=contribution,
                    )
                    applied_4 += contribution
                    bullet(
                        f"{name}: {money(contribution)} "
                        f"({bal / total_survivor_fund * 100:.1f}% "
                        f"share)"
                    )

    remaining -= applied_4
    bullet(f"Total survivor fund: {money(total_survivor_fund)}")
    bullet(f"Total applied: {money(applied_4)}")
    bullet(f"Remaining loss: {money(remaining)}")

    # Step 5: Loss allocation (capped at 10% of credit limit)
    # (from waterfall.py _step_loss_allocation)
    subheader(
        "Step 5: Loss Allocation (Capped at 10% Credit Limit)"
    )
    total_limits = sum(
        ch.members[mid].credit_limit for mid, _, _ in survivor_funds
    )
    applied_5 = Decimal("0")

    if total_limits > Decimal("0") and remaining > Decimal("0"):
        for mid, name, _ in survivor_funds:
            limit = ch.members[mid].credit_limit
            if limit <= Decimal("0"):
                continue
            share = (limit / total_limits) * remaining
            cap = limit * Decimal("0.1")
            allocation = min(share, cap)
            if allocation > Decimal("0"):
                s_settle = ch.find_account(
                    mid,
                    AccountType.SETTLEMENT,
                    PoolType.AVAILABLE,
                )
                ccp_settlement = ch.find_account(
                    ch.ccp_id,
                    AccountType.SETTLEMENT,
                    PoolType.AVAILABLE,
                )
                if s_settle and ccp_settlement:
                    ch.create_journal(
                        journal_type=(
                            JournalType.DEFAULT_WATERFALL_STEP
                        ),
                        description=(
                            f"Waterfall step 5: {name} "
                            f"loss allocation"
                        ),
                        reference_id=event_id,
                        debit_account_id=ccp_settlement.id,
                        credit_account_id=s_settle.id,
                        amount=allocation,
                    )
                    applied_5 += allocation
                    bullet(
                        f"{name}: {money(allocation)} "
                        f"(cap: {money(cap)})"
                    )

    remaining -= applied_5
    bullet(f"Total allocated: {money(applied_5)}")
    bullet(f"Final remaining loss: {money(remaining)}")

    # Waterfall summary
    final_status = (
        "resolved"
        if remaining <= Decimal("0")
        else "partially_resolved"
    )
    subheader("Waterfall Summary")
    bullet(f"Total exposure: {money(total_exposure)}")
    bullet(f"Step 1 (Defaulter margin): {money(applied_1)}")
    bullet(f"Step 2 (Defaulter default fund): {money(applied_2)}")
    bullet(f"Step 3 (CCP equity): {money(applied_3)}")
    bullet(
        f"Step 4 (Surviving default fund): {money(applied_4)}"
    )
    bullet(f"Step 5 (Loss allocation): {money(applied_5)}")
    total_recovered = (
        applied_1 + applied_2 + applied_3 + applied_4 + applied_5
    )
    bullet(f"Total recovered: {money(total_recovered)}")
    bullet(f"Unrecovered: {money(max(remaining, Decimal('0')))}")
    bullet(f"Status: {final_status}")

    ch.emit_event(
        "default.resolved",
        {
            "default_event_id": str(event_id),
            "status": final_status,
            "remaining_loss": str(max(remaining, Decimal("0"))),
        },
    )


# ── Ledger Audit ───────────────────────────────────────────────


def ledger_audit(ch: ClearingHouse) -> None:
    header("LEDGER AUDIT")

    total_debits = Decimal("0")
    total_credits = Decimal("0")
    journal_count = len(ch.journals)
    entry_count = 0

    for journal in ch.journals.values():
        for entry in journal.entries:
            total_debits += entry.debit
            total_credits += entry.credit
            entry_count += 1

    balanced = total_debits == total_credits
    bullet(f"Total journals: {journal_count}")
    bullet(f"Total entries: {entry_count}")
    bullet(f"Total debits: {money(total_debits)}")
    bullet(f"Total credits: {money(total_credits)}")
    bullet(f"Balanced: {'YES' if balanced else 'NO'}")

    if not balanced:
        diff = total_debits - total_credits
        bullet(f"DISCREPANCY: {money(abs(diff))}")

    subheader("Event Log Summary")
    event_types: dict[str, int] = {}
    for event in ch.events:
        event_types[event.event_type] = (
            event_types.get(event.event_type, 0) + 1
        )
    for etype, count in sorted(event_types.items()):
        bullet(f"{etype}: {count}")

    bullet(f"Total events: {len(ch.events)}")


# ── Main ───────────────────────────────────────────────────────


def main() -> None:
    print()
    print(
        "  CCP CLEARING HOUSE - "
        "Self-Contained Demo"
    )
    print(
        "  Full lifecycle simulation "
        "(no Docker, no infrastructure)"
    )

    ch = ClearingHouse()

    phase_1_initialization(ch)
    phase_2_default_fund(ch)
    phase_3_trade_submission(ch)
    phase_4_novation(ch)
    phase_5_margin_calculation(ch)
    phase_6_netting(ch)
    phase_7_settlement(ch)
    phase_8_default_waterfall(ch)
    ledger_audit(ch)

    print()
    print("=" * 72)
    print("  DEMO COMPLETE")
    print("=" * 72)
    print()


if __name__ == "__main__":
    main()
