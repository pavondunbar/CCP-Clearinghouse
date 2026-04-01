"""Pydantic models for tradable instruments."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from ccp_shared.enums import InstrumentAssetClass, SettlementType


class Instrument(BaseModel):
    """Represents a tradable financial instrument.

    Attributes:
        id: Unique instrument identifier.
        symbol: Trading symbol (e.g., BTC-PERP).
        asset_class: Classification of the instrument.
        settlement_type: How the instrument settles.
        margin_rate_im: Initial margin rate as a decimal fraction.
        margin_rate_vm: Variation margin rate as a decimal fraction.
        chain_id: Optional blockchain chain ID for on-chain instruments.
        contract_address: Optional smart contract address.
        created_at: Timestamp of instrument creation.
    """

    id: UUID
    symbol: str
    asset_class: InstrumentAssetClass
    settlement_type: SettlementType
    margin_rate_im: Decimal
    margin_rate_vm: Decimal
    chain_id: int | None = None
    contract_address: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
