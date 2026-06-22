"""Shared event contracts used by the passive analytics pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


UNKNOWN_CONTEXT = "unknown"


class EventType(StrEnum):
    """Canonical event types emitted by the dispatcher."""

    RAW_PACKET_CAPTURED = "raw_packet_captured"
    SERVICE_PACKET_RECEIVED = "service_packet_received"
    UNKNOWN_PACKET_RECEIVED = "unknown_packet_received"


@dataclass(frozen=True, slots=True)
class CapturedPacket:
    """Immutable network payload captured by the mitmproxy addon.

    The proxy should only create this envelope and enqueue it. It must not call
    domain processors directly or perform heavy analysis in the request path.
    """

    payload: dict[str, Any] | list[Any]
    endpoint: str
    http_method: str
    status_code: int | None = None
    player_id: str = UNKNOWN_CONTEXT
    world_id: str = UNKNOWN_CONTEXT
    request_id: str = field(default_factory=lambda: str(uuid4()))
    headers: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    captured_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class Event:
    """Application event delivered to independent subscribers."""

    name: str
    event_type: EventType
    packet: CapturedPacket
    service_name: str | None = None
    method_name: str | None = None
    payload: dict[str, Any] | list[Any] | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

