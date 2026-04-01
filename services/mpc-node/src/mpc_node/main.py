"""MPC Node — holds one key share and produces partial signatures."""

import hashlib
import hmac
import logging
import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
app = FastAPI(title="CCP MPC Node")

NODE_ID = os.environ.get("MPC_NODE_ID", "0")
KEY_SHARE_PATH = os.environ.get("MPC_KEY_SHARE_PATH", "")

_key_share: bytes | None = None


def _load_key_share() -> bytes:
    """Load key share from file or generate a deterministic one for MVP."""
    global _key_share
    if _key_share is not None:
        return _key_share

    if KEY_SHARE_PATH and os.path.exists(KEY_SHARE_PATH):
        with open(KEY_SHARE_PATH, "rb") as f:
            _key_share = f.read()
    else:
        _key_share = hashlib.sha256(f"mpc-key-share-{NODE_ID}".encode()).digest()
        logger.info("Using generated key share for node %s", NODE_ID)

    return _key_share


class PartialSignRequest(BaseModel):
    tx_hash: str
    chain_id: str


class PartialSignResponse(BaseModel):
    node_id: str
    partial_signature: str


@app.get("/health")
def health():
    return {"status": "ok", "service": f"mpc-node-{NODE_ID}"}


@app.post("/partial-sign", response_model=PartialSignResponse)
def partial_sign(request: PartialSignRequest):
    """Produce a partial signature using this node's key share.

    In a real MPC system this would use Shamir secret sharing
    and a threshold ECDSA protocol. For the MVP, we use
    HMAC-SHA256 with the node's key share.
    """
    key_share = _load_key_share()

    message = f"{request.tx_hash}:{request.chain_id}".encode()
    partial_sig = hmac.new(key_share, message, hashlib.sha256).hexdigest()

    logger.info(
        "Node %s produced partial signature for tx %s",
        NODE_ID, request.tx_hash[:16],
    )

    return PartialSignResponse(
        node_id=NODE_ID,
        partial_signature=partial_sig,
    )
