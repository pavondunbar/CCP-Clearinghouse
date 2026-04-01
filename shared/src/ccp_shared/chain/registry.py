"""Registry mapping chain IDs to their blockchain adapters."""

from ccp_shared.chain.base import ChainAdapter


class ChainRegistry:
    """Maps chain IDs to ChainAdapter instances.

    Allows services to look up the correct adapter for a given
    blockchain without hard-coding chain-specific logic.
    """

    def __init__(self) -> None:
        self._adapters: dict[int, ChainAdapter] = {}

    def register(
        self, chain_id: int, adapter: ChainAdapter,
    ) -> None:
        """Register an adapter for a chain ID.

        Args:
            chain_id: Blockchain network identifier.
            adapter: ChainAdapter implementation for this chain.
        """
        self._adapters[chain_id] = adapter

    def get(self, chain_id: int) -> ChainAdapter:
        """Retrieve the adapter for a chain ID.

        Args:
            chain_id: Blockchain network identifier.

        Returns:
            The registered ChainAdapter.

        Raises:
            KeyError: If no adapter is registered for the chain ID.
        """
        try:
            return self._adapters[chain_id]
        except KeyError:
            raise KeyError(
                f"No ChainAdapter registered for chain_id={chain_id}"
            ) from None
