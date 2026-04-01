"""Signing Gateway — coordinates threshold signing with MPC nodes."""

import base64
import hashlib
import logging
from typing import Annotated

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from ccp_shared.config import CCPSettings

logger = logging.getLogger(__name__)
app = FastAPI(title="CCP Signing Gateway")
settings = CCPSettings()

MPC_NODE_URLS = [
    f"http://mpc-node-{i}:8020" for i in range(1, settings.mpc_total_nodes + 1)
]


class SignRequest(BaseModel):
    tx_bytes: str  # base64-encoded unsigned transaction
    chain_id: str


class SignResponse(BaseModel):
    signed_tx_bytes: str  # base64-encoded signed transaction
    signatures: list[str]
    threshold_met: bool


@app.get("/health")
def health():
    return {"status": "ok", "service": "signing-gateway"}


@app.post("/sign", response_model=SignResponse)
async def sign_transaction(request: SignRequest):
    """Coordinate threshold signing across MPC nodes.

    Sends signing request to all MPC nodes, collects partial
    signatures, and combines them if threshold is met.
    """
    partial_signatures = []
    tx_hash = hashlib.sha256(base64.b64decode(request.tx_bytes)).hexdigest()

    async with httpx.AsyncClient(timeout=30.0) as client:
        for node_url in MPC_NODE_URLS:
            try:
                resp = await client.post(
                    f"{node_url}/partial-sign",
                    json={
                        "tx_hash": tx_hash,
                        "chain_id": request.chain_id,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    partial_signatures.append(data["partial_signature"])
                    logger.info("Got partial signature from %s", node_url)
                else:
                    logger.warning(
                        "MPC node %s returned %d", node_url, resp.status_code,
                    )
            except httpx.RequestError as exc:
                logger.warning("MPC node %s unreachable: %s", node_url, exc)

    threshold_met = len(partial_signatures) >= settings.mpc_threshold
    if not threshold_met:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Threshold not met: got {len(partial_signatures)} "
                f"of {settings.mpc_threshold} required signatures"
            ),
        )

    combined = _combine_signatures(
        request.tx_bytes, partial_signatures,
    )

    return SignResponse(
        signed_tx_bytes=combined,
        signatures=partial_signatures,
        threshold_met=True,
    )


def _combine_signatures(tx_bytes_b64: str, partial_sigs: list[str]) -> str:
    """Combine partial signatures into a final signed transaction.

    In a real MPC implementation this would perform Shamir secret
    sharing recombination. For the MVP, we concatenate the tx bytes
    with the combined signature hash.
    """
    tx_bytes = base64.b64decode(tx_bytes_b64)
    sig_material = "|".join(sorted(partial_sigs))
    combined_sig = hashlib.sha256(sig_material.encode()).digest()
    signed_tx = tx_bytes + combined_sig
    return base64.b64encode(signed_tx).decode()
