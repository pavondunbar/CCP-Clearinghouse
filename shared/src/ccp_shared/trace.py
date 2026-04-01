"""Distributed trace context for audit trails."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TraceContext:
    """Carries trace_id and actor through a request/event chain.

    Attributes:
        trace_id: Correlation UUID for the entire request flow.
        actor: Identity of who initiated the action.
        parent_event_id: Optional link to the triggering event.
    """

    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    actor: str = "system"
    parent_event_id: str | None = None

    @classmethod
    def from_request(cls, request) -> TraceContext:
        """Extract trace context from FastAPI request headers.

        Args:
            request: A FastAPI/Starlette Request object.

        Returns:
            TraceContext populated from headers or defaults.
        """
        trace_id = request.headers.get(
            "x-trace-id", str(uuid.uuid4())
        )
        actor = request.headers.get("x-actor", "anonymous")
        return cls(trace_id=trace_id, actor=actor)

    @classmethod
    def from_kafka_payload(cls, payload: dict) -> TraceContext:
        """Extract trace context from a Kafka event payload.

        Args:
            payload: Deserialized event dict with optional
                trace_id, actor, and event_id fields.

        Returns:
            TraceContext populated from payload or defaults.
        """
        return cls(
            trace_id=payload.get("trace_id", str(uuid.uuid4())),
            actor=payload.get("actor", "system"),
            parent_event_id=payload.get("event_id"),
        )

    @classmethod
    def new_system(cls, service_name: str) -> TraceContext:
        """Create a trace context for system-initiated operations.

        Args:
            service_name: Name of the service creating the trace.

        Returns:
            TraceContext with actor set to 'system:<service_name>'.
        """
        return cls(actor=f"system:{service_name}")

    def to_dict(self) -> dict:
        """Serialize trace context for inclusion in event payloads.

        Returns:
            Dict with trace_id, actor, and parent_event_id.
        """
        return {
            "trace_id": self.trace_id,
            "actor": self.actor,
            "parent_event_id": self.parent_event_id,
        }
