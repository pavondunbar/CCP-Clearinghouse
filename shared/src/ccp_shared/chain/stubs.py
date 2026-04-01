"""Stub blockchain adapter for testing and development."""

import hashlib
from dataclasses import dataclass, field

from ccp_shared.chain.base import (
    ChainAdapter,
    DVPInstruction,
    TransactionResult,
    TransactionStatus,
    TransferInstruction,
)


@dataclass
class _TrackedTx:
    """Internal tracking state for a stub transaction."""

    signed_tx: bytes
    poll_count: int = 0


class StubChainAdapter(ChainAdapter):
    """In-memory chain adapter that simulates transaction processing.

    Transactions are tracked locally and automatically confirm
    after a configurable number of status checks.

    Args:
        confirmations_required: Polls before a transaction confirms.
    """

    def __init__(self, confirmations_required: int = 2) -> None:
        self._confirmations_required = confirmations_required
        self._transactions: dict[str, _TrackedTx] = {}

    def build_transfer_tx(
        self, instruction: TransferInstruction,
    ) -> bytes:
        """Build a stub unsigned transfer transaction.

        Args:
            instruction: Transfer parameters.

        Returns:
            Deterministic bytes derived from the instruction.
        """
        payload = (
            f"transfer:{instruction.chain_id}"
            f":{instruction.from_address}"
            f":{instruction.to_address}"
            f":{instruction.amount}"
            f":{instruction.instruction_id}"
        )
        return payload.encode("utf-8")

    def build_dvp_tx(
        self, instruction: DVPInstruction,
    ) -> bytes:
        """Build a stub unsigned DVP transaction.

        Args:
            instruction: DVP parameters.

        Returns:
            Deterministic bytes derived from the instruction.
        """
        payload = (
            f"dvp:{instruction.chain_id}"
            f":{instruction.seller_address}"
            f":{instruction.buyer_address}"
            f":{instruction.asset_amount}"
            f":{instruction.payment_amount}"
            f":{instruction.instruction_id}"
        )
        return payload.encode("utf-8")

    def submit_signed_tx(
        self, signed_tx: bytes,
    ) -> TransactionResult:
        """Submit a signed transaction to the in-memory store.

        Args:
            signed_tx: Signed transaction bytes.

        Returns:
            Result with a deterministic hash and pending status.
        """
        tx_hash = hashlib.sha256(signed_tx).hexdigest()
        self._transactions[tx_hash] = _TrackedTx(signed_tx=signed_tx)
        return TransactionResult(
            tx_hash=tx_hash,
            status=TransactionStatus.PENDING,
            confirmations=0,
        )

    def get_tx_status(
        self, tx_hash: str,
    ) -> TransactionResult:
        """Check transaction status, auto-confirming after N polls.

        Args:
            tx_hash: Transaction hash from submit_signed_tx.

        Returns:
            Updated status with incremented confirmation count.
        """
        tracked = self._transactions.get(tx_hash)
        if tracked is None:
            return TransactionResult(
                tx_hash=tx_hash,
                status=TransactionStatus.FAILED,
                error=f"Unknown transaction: {tx_hash}",
            )
        tracked.poll_count += 1
        if tracked.poll_count >= self._confirmations_required:
            return TransactionResult(
                tx_hash=tx_hash,
                status=TransactionStatus.CONFIRMED,
                confirmations=tracked.poll_count,
            )
        return TransactionResult(
            tx_hash=tx_hash,
            status=TransactionStatus.PENDING,
            confirmations=tracked.poll_count,
        )

    def get_required_confirmations(self) -> int:
        """Return the configured confirmations threshold.

        Returns:
            Number of polls before transactions confirm.
        """
        return self._confirmations_required
