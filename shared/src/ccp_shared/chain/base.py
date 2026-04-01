"""Abstract base class and data types for blockchain adapters."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from uuid import UUID


class TransactionStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"


@dataclass(frozen=True)
class TransferInstruction:
    """On-chain token transfer parameters.

    Attributes:
        chain_id: Target blockchain identifier.
        from_address: Sender address.
        to_address: Recipient address.
        token_address: Token contract address.
        amount: Transfer amount.
        instruction_id: CCP settlement instruction reference.
    """

    chain_id: int
    from_address: str
    to_address: str
    token_address: str
    amount: Decimal
    instruction_id: UUID


@dataclass(frozen=True)
class DVPInstruction:
    """Delivery-versus-payment instruction for atomic settlement.

    Attributes:
        chain_id: Target blockchain identifier.
        seller_address: Address delivering the asset.
        buyer_address: Address receiving the asset.
        asset_token_address: Token representing the asset.
        asset_amount: Amount of asset to deliver.
        payment_token_address: Token used for payment.
        payment_amount: Payment amount.
        instruction_id: CCP settlement instruction reference.
    """

    chain_id: int
    seller_address: str
    buyer_address: str
    asset_token_address: str
    asset_amount: Decimal
    payment_token_address: str
    payment_amount: Decimal
    instruction_id: UUID


@dataclass(frozen=True)
class TransactionResult:
    """Result of a blockchain transaction submission or status check.

    Attributes:
        tx_hash: On-chain transaction hash.
        status: Current transaction status.
        confirmations: Number of block confirmations.
        error: Error message if the transaction failed.
    """

    tx_hash: str
    status: TransactionStatus
    confirmations: int = 0
    error: str | None = None


class ChainAdapter(ABC):
    """Abstract interface for blockchain interactions.

    Each supported blockchain implements this interface to provide
    transaction building, submission, and status tracking.
    """

    @abstractmethod
    def build_transfer_tx(
        self, instruction: TransferInstruction,
    ) -> bytes:
        """Build an unsigned transfer transaction.

        Args:
            instruction: Transfer parameters.

        Returns:
            Unsigned transaction bytes ready for signing.
        """

    @abstractmethod
    def build_dvp_tx(
        self, instruction: DVPInstruction,
    ) -> bytes:
        """Build an unsigned delivery-versus-payment transaction.

        Args:
            instruction: DVP parameters.

        Returns:
            Unsigned transaction bytes ready for signing.
        """

    @abstractmethod
    def submit_signed_tx(
        self, signed_tx: bytes,
    ) -> TransactionResult:
        """Submit a signed transaction to the blockchain.

        Args:
            signed_tx: Signed transaction bytes.

        Returns:
            Result with tx_hash and initial status.
        """

    @abstractmethod
    def get_tx_status(
        self, tx_hash: str,
    ) -> TransactionResult:
        """Query the current status of a submitted transaction.

        Args:
            tx_hash: On-chain transaction hash.

        Returns:
            Current transaction result with confirmation count.
        """

    @abstractmethod
    def get_required_confirmations(self) -> int:
        """Return the number of confirmations required for finality.

        Returns:
            Minimum confirmations before a transaction is final.
        """
