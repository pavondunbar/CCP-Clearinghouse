"""Ethereum/EVM blockchain adapter placeholder.

This module will provide a ChainAdapter implementation for EVM-compatible
blockchains (Ethereum, Polygon, Arbitrum, etc.) using web3.py. Currently
raises NotImplementedError for all methods. The implementation will include:

- RPC connection management via web3.py
- ERC-20 transfer transaction building
- DvP smart contract interaction
- Transaction submission and receipt polling
- Configurable gas estimation and nonce management
"""

from ccp_shared.chain.base import (
    ChainAdapter,
    DVPInstruction,
    TransactionResult,
    TransferInstruction,
)


class EthereumAdapter(ChainAdapter):
    """EVM-compatible blockchain adapter (not yet implemented).

    This adapter will connect to Ethereum and EVM-compatible chains
    via JSON-RPC to build, submit, and track transactions.
    """

    def __init__(self, rpc_url: str, chain_id: int) -> None:
        self._rpc_url = rpc_url
        self._chain_id = chain_id

    def build_transfer_tx(
        self, instruction: TransferInstruction,
    ) -> bytes:
        """Build an ERC-20 transfer transaction."""
        raise NotImplementedError(
            "EthereumAdapter.build_transfer_tx not yet implemented"
        )

    def build_dvp_tx(
        self, instruction: DVPInstruction,
    ) -> bytes:
        """Build a DvP smart contract transaction."""
        raise NotImplementedError(
            "EthereumAdapter.build_dvp_tx not yet implemented"
        )

    def submit_signed_tx(
        self, signed_tx: bytes,
    ) -> TransactionResult:
        """Submit a signed transaction via JSON-RPC."""
        raise NotImplementedError(
            "EthereumAdapter.submit_signed_tx not yet implemented"
        )

    def get_tx_status(
        self, tx_hash: str,
    ) -> TransactionResult:
        """Query transaction receipt from the EVM node."""
        raise NotImplementedError(
            "EthereumAdapter.get_tx_status not yet implemented"
        )

    def get_required_confirmations(self) -> int:
        """Return confirmations required for EVM chain finality."""
        raise NotImplementedError(
            "EthereumAdapter.get_required_confirmations "
            "not yet implemented"
        )
