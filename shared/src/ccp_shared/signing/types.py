"""Data types for MPC signing requests and responses."""

from pydantic import BaseModel


class SigningRequest(BaseModel):
    """Request to sign a transaction via the MPC signing gateway.

    Attributes:
        tx_bytes: Base64-encoded unsigned transaction bytes.
        chain_id: Target blockchain identifier.
    """

    tx_bytes: str
    chain_id: int


class SigningResponse(BaseModel):
    """Response from the MPC signing gateway.

    Attributes:
        signed_tx_bytes: Base64-encoded signed transaction.
        signatures: List of base64-encoded partial signatures.
    """

    signed_tx_bytes: str
    signatures: list[str]
