"""Unit tests for chain abstraction layer."""

from decimal import Decimal

from ccp_shared.chain.base import (
    DVPInstruction,
    TransactionStatus,
    TransferInstruction,
)
from ccp_shared.chain.registry import ChainRegistry
from ccp_shared.chain.stubs import StubChainAdapter


class TestStubChainAdapter:
    """Test the in-memory stub chain adapter."""

    def setup_method(self):
        self.adapter = StubChainAdapter()

    def test_build_transfer_tx(self):
        instruction = TransferInstruction(
            from_address="0xaaa",
            to_address="0xbbb",
            amount=Decimal("1000"),
            chain_id="ethereum-mainnet",
        )
        tx_bytes = self.adapter.build_transfer_tx(instruction)
        assert isinstance(tx_bytes, bytes)
        assert len(tx_bytes) > 0

    def test_build_dvp_tx(self):
        instruction = DVPInstruction(
            from_address="0xaaa",
            to_address="0xbbb",
            token_address="0xccc",
            quantity=Decimal("10"),
            amount=Decimal("5000"),
            chain_id="ethereum-mainnet",
        )
        tx_bytes = self.adapter.build_dvp_tx(instruction)
        assert isinstance(tx_bytes, bytes)
        assert len(tx_bytes) > 0

    def test_submit_and_confirm(self):
        instruction = TransferInstruction(
            from_address="0xaaa",
            to_address="0xbbb",
            amount=Decimal("1000"),
            chain_id="ethereum-mainnet",
        )
        tx_bytes = self.adapter.build_transfer_tx(instruction)
        result = self.adapter.submit_signed_tx(tx_bytes)
        assert result.tx_hash is not None
        assert result.status == TransactionStatus.PENDING

        status = self.adapter.get_tx_status(result.tx_hash)
        assert status.status == TransactionStatus.CONFIRMED
        assert status.confirmations >= self.adapter.get_required_confirmations()

    def test_get_required_confirmations(self):
        assert self.adapter.get_required_confirmations() > 0


class TestChainRegistry:
    """Test the chain adapter registry."""

    def test_register_and_get(self):
        registry = ChainRegistry()
        adapter = StubChainAdapter()
        registry.register("ethereum-mainnet", adapter)

        result = registry.get("ethereum-mainnet")
        assert result is adapter

    def test_get_unknown_chain(self):
        registry = ChainRegistry()
        result = registry.get("unknown-chain")
        assert result is None

    def test_register_multiple_chains(self):
        registry = ChainRegistry()
        eth_adapter = StubChainAdapter()
        poly_adapter = StubChainAdapter()
        registry.register("ethereum-mainnet", eth_adapter)
        registry.register("polygon-mainnet", poly_adapter)

        assert registry.get("ethereum-mainnet") is eth_adapter
        assert registry.get("polygon-mainnet") is poly_adapter
