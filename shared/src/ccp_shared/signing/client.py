"""HTTP client for the MPC signing gateway."""

import base64
import json
import urllib.request
from urllib.error import URLError

from ccp_shared.config import CCPSettings
from ccp_shared.signing.types import SigningRequest, SigningResponse


class SigningClient:
    """Sends signing requests to the MPC signing gateway over HTTP.

    Args:
        settings: CCP configuration with signing gateway host/port.
    """

    def __init__(self, settings: CCPSettings) -> None:
        self._base_url = (
            f"http://{settings.signing_gateway_host}"
            f":{settings.signing_gateway_port}"
        )

    def sign(self, tx_bytes: bytes, chain_id: int) -> SigningResponse:
        """Request the signing gateway to sign a transaction.

        Args:
            tx_bytes: Raw unsigned transaction bytes.
            chain_id: Target blockchain identifier.

        Returns:
            SigningResponse with signed transaction and signatures.

        Raises:
            ConnectionError: If the signing gateway is unreachable.
            ValueError: If the response cannot be parsed.
        """
        request_body = SigningRequest(
            tx_bytes=base64.b64encode(tx_bytes).decode("ascii"),
            chain_id=chain_id,
        )
        return self._post("/sign", request_body)

    def _post(
        self, path: str, body: SigningRequest,
    ) -> SigningResponse:
        """Send a POST request to the signing gateway.

        Args:
            path: URL path (e.g., '/sign').
            body: Request payload.

        Returns:
            Parsed SigningResponse.

        Raises:
            ConnectionError: If the gateway is unreachable.
            ValueError: If the response is malformed.
        """
        url = f"{self._base_url}{path}"
        data = body.model_dump_json().encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                return SigningResponse(**resp_data)
        except URLError as exc:
            raise ConnectionError(
                f"Failed to reach signing gateway at {url}: {exc}"
            ) from exc
