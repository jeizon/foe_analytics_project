"""Packet router that converts captured FoE JSON packets into events."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from typing import Any

from core_events.capture_queue import CaptureQueue
from core_events.dispatcher import EventDispatcher, SERVICE_EVENT_PREFIX, UNKNOWN_PACKET_EVENT
from core_events.event_types import CapturedPacket, Event, EventType, UNKNOWN_CONTEXT

LOGGER = logging.getLogger(__name__)


class PacketRouter:
    """Consumes raw packets from CaptureQueue and publishes classified events."""

    def __init__(self, capture_queue: CaptureQueue, dispatcher: EventDispatcher) -> None:
        self._capture_queue = capture_queue
        self._dispatcher = dispatcher
        self._player_context_by_world: dict[str, str] = {}
        self._workers: list[asyncio.Task[None]] = []
        self._running = False

    async def start(self, worker_count: int = 2) -> None:
        """Start packet routing workers."""

        if self._running:
            return

        self._running = True
        self._workers = [
            asyncio.create_task(self._worker(worker_id), name=f"foe-packet-router-{worker_id}")
            for worker_id in range(worker_count)
        ]

    async def stop(self) -> None:
        """Route all queued packets and stop workers."""

        if not self._running:
            return

        await self._capture_queue.join()
        self._running = False

        for worker in self._workers:
            worker.cancel()

        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    def route_packet(self, packet: CapturedPacket) -> Event:
        """Convert a captured packet into the first dispatcher event."""

        return self.route_packet_events(packet)[0]

    def route_packet_events(self, packet: CapturedPacket) -> list[Event]:
        """Convert a captured packet into one or more dispatcher events."""

        service_entries = extract_service_entries(packet.payload)
        if not service_entries:
            normalized_packet = replace(
                packet,
                player_id=packet.player_id or UNKNOWN_CONTEXT,
                world_id=packet.world_id or UNKNOWN_CONTEXT,
                metadata={
                    **packet.metadata,
                    "service_name": None,
                    "method_name": None,
                },
            )
            return [
                Event(
                    name=UNKNOWN_PACKET_EVENT,
                    event_type=EventType.UNKNOWN_PACKET_RECEIVED,
                    packet=normalized_packet,
                    payload=packet.payload,
                )
            ]

        return [
            self._build_service_event(packet, service_name, method_name, service_payload)
            for service_name, method_name, service_payload in service_entries
        ]

    def _build_service_event(
        self,
        packet: CapturedPacket,
        service_name: str,
        method_name: str | None,
        service_payload: dict[str, Any],
    ) -> Event:
        player_id = packet.player_id or UNKNOWN_CONTEXT
        if player_id == UNKNOWN_CONTEXT:
            player_id = (
                extract_player_context(service_payload)
                or self._player_context_by_world.get(packet.world_id)
                or UNKNOWN_CONTEXT
            )

        if player_id != UNKNOWN_CONTEXT and packet.world_id != UNKNOWN_CONTEXT:
            self._player_context_by_world[packet.world_id] = player_id

        normalized_packet = replace(
            packet,
            player_id=player_id,
            world_id=packet.world_id or UNKNOWN_CONTEXT,
            metadata={
                **packet.metadata,
                "service_name": service_name,
                "method_name": method_name,
            },
        )

        return Event(
            name=f"{SERVICE_EVENT_PREFIX}{service_name}",
            event_type=EventType.SERVICE_PACKET_RECEIVED,
            packet=normalized_packet,
            service_name=service_name,
            method_name=method_name,
            payload=service_payload,
        )

    async def _worker(self, worker_id: int) -> None:
        while self._running:
            packet = await self._capture_queue.get()
            try:
                for event in self.route_packet_events(packet):
                    await self._dispatcher.publish(event)
            except Exception:
                LOGGER.exception(
                    "Packet router worker %s failed for request_id=%s",
                    worker_id,
                    packet.request_id,
                )
            finally:
                self._capture_queue.task_done()


def extract_service_signature(payload: dict[str, Any] | list[Any]) -> tuple[str | None, str | None]:
    """Extract FoE request class and method names from a JSON payload."""

    service_entries = extract_service_entries(payload)
    if not service_entries:
        return None, None

    service_name, method_name, _service_payload = service_entries[0]
    return service_name, method_name


def extract_service_entries(payload: dict[str, Any] | list[Any]) -> list[tuple[str, str | None, dict[str, Any]]]:
    """Extract all service calls present in a FoE JSON payload."""

    entries: list[tuple[str, str | None, dict[str, Any]]] = []
    for candidate in _find_service_candidates(payload):
        service_name, method_name = _extract_candidate_signature(candidate)
        if service_name:
            entries.append((service_name, method_name, candidate))
    return entries


def extract_player_context(payload: dict[str, Any] | list[Any]) -> str | None:
    """Best-effort player context extraction from FoE service payloads.

    FoE endpoints do not consistently include the player id in the URL. Some
    service payloads carry explicit player ids, while CBG map snapshots carry
    the current battleground participant id instead.
    """

    if isinstance(payload, dict):
        explicit_player_id = _first_text(
            payload,
            "playerId",
            "player_id",
            "currentPlayerId",
            "current_player_id",
            "attackerPlayerId",
            "userId",
            "user_id",
        )
        if explicit_player_id:
            return explicit_player_id

    response_data = payload.get("responseData") if isinstance(payload, dict) else None
    if isinstance(response_data, dict):
        explicit_player_id = _first_text(
            response_data,
            "playerId",
            "player_id",
            "currentPlayerId",
            "current_player_id",
            "attackerPlayerId",
            "userId",
            "user_id",
        )
        if explicit_player_id:
            return explicit_player_id

        for player_key in ("currentPlayer", "player", "user"):
            player = response_data.get(player_key)
            if isinstance(player, dict):
                explicit_player_id = _first_text(player, "playerId", "player_id", "id")
                if explicit_player_id:
                    return explicit_player_id

        participant_id = _first_text(response_data, "currentParticipantId")
        if participant_id:
            return f"participant:{participant_id}"

    return None


def _extract_candidate_signature(candidate: dict[str, Any]) -> tuple[str | None, str | None]:
    service_name = _first_text(
        candidate,
        "requestClass",
        "request_class",
        "className",
        "serviceName",
        "service",
    )
    method_name = _first_text(
        candidate,
        "requestMethod",
        "request_method",
        "methodName",
        "method",
    )
    return service_name, method_name


def _find_service_candidates(value: Any) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen_ids: set[int] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if _has_service_signature(node) and id(node) not in seen_ids:
                candidates.append(node)
                seen_ids.add(id(node))

            for nested_value in node.values():
                walk(nested_value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(value)
    return candidates


def _has_service_signature(value: dict[str, Any]) -> bool:
    return any(
        key in value
        for key in (
            "requestClass",
            "request_class",
            "className",
            "serviceName",
            "service",
        )
    )


def _find_service_candidate(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        if _has_service_signature(value):
            return value

        for nested_value in value.values():
            candidate = _find_service_candidate(nested_value)
            if candidate:
                return candidate

    if isinstance(value, list):
        for item in value:
            candidate = _find_service_candidate(item)
            if candidate:
                return candidate

    return None


def _first_text(source: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, int):
            return str(value)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None

