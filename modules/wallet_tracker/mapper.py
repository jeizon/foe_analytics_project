"""Map routed FoE service events into consolidated wallet balance facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core_events.event_types import Event

WALLET_KEYS = {
    "money",
    "coins",
    "coin",
    "supplies",
    "supply",
    "strategypoints",
    "forgepoints",
    "forge_points",
    "premium",
    "diamonds",
    "medals",
    "population",
    "happiness",
}
RESOURCE_DOMAINS = ("ResourceService", "RewardService", "PremiumService", "InventoryService")
SKIP_SERVICES = {"BattlefieldService", "ArmyUnitManagementService"}
SKIP_SERVICE_METHODS = {("ResourceService", "getPlayerAutoRefills")}
RESOURCE_ALIASES = {
    "coins": "money",
    "coin": "money",
    "supply": "supplies",
    "strategypoints": "forge_points",
    "strategy_points": "forge_points",
    "forgepoints": "forge_points",
    "premium": "diamonds",
}


@dataclass(frozen=True, slots=True)
class WalletResourceDTO:
    """One resource balance observation."""

    resource_name: str
    amount: int | float | str
    source_service: str
    source_method: str | None
    raw_resource: dict[str, Any]
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class WalletMapping:
    """Wallet records extracted from one service event."""

    request_id: str
    player_id: str
    world_id: str
    resources: list[WalletResourceDTO]


def map_wallet_event(event: Event) -> WalletMapping:
    """Extract wallet/resource balances from one routed service event."""

    service_name = event.service_name or "unknown"
    if not _is_numeric_player_id(event.packet.player_id):
        return WalletMapping(
            request_id=event.packet.request_id,
            player_id=event.packet.player_id,
            world_id=event.packet.world_id,
            resources=[],
        )

    payload = event.payload if isinstance(event.payload, dict) else {"value": event.payload}
    resources = [
        WalletResourceDTO(
            resource_name=name,
            amount=amount,
            source_service=service_name,
            source_method=event.method_name,
            raw_resource=raw_resource,
            observed_at=event.packet.captured_at,
        )
        for name, amount, raw_resource in _extract_wallet_resources(
            payload,
            service_name,
            event.method_name,
        )
    ]
    return WalletMapping(
        request_id=event.packet.request_id,
        player_id=event.packet.player_id,
        world_id=event.packet.world_id,
        resources=resources,
    )


def _extract_wallet_resources(
    payload: dict[str, Any],
    service_name: str,
    method_name: str | None,
) -> list[tuple[str, int | float | str, dict[str, Any]]]:
    if service_name in SKIP_SERVICES:
        return []

    if (service_name, method_name or "") in SKIP_SERVICE_METHODS:
        return []

    if not _is_likely_resource_service(service_name, payload):
        return []

    resources: list[tuple[str, int | float | str, dict[str, Any]]] = []
    seen: set[str] = set()
    for item in _walk_objects(payload):
        for key, value in item.items():
            normalized_key = _normalize_key(key)
            if normalized_key not in WALLET_KEYS:
                continue
            if not isinstance(value, int | float | str) or isinstance(value, bool):
                continue
            resource_name = _canonical_resource_name(str(key))
            if resource_name in seen:
                continue
            seen.add(resource_name)
            resources.append((resource_name, value, {str(key): value}))

    return resources


def _is_likely_resource_service(service_name: str, payload: dict[str, Any]) -> bool:
    if any(service_name.startswith(prefix) for prefix in RESOURCE_DOMAINS):
        return True

    for item in _walk_objects(payload):
        keys = {_normalize_key(key) for key in item}
        if keys & WALLET_KEYS:
            return True

    return False


def _canonical_resource_name(value: str) -> str:
    normalized = _normalize_key(value)
    return RESOURCE_ALIASES.get(normalized, value)


def _walk_objects(value: Any) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    if isinstance(value, dict):
        objects.append(value)
        for nested_value in value.values():
            objects.extend(_walk_objects(nested_value))
    elif isinstance(value, list):
        for item in value:
            objects.extend(_walk_objects(item))
    return objects


def _normalize_key(value: Any) -> str:
    return str(value).replace("_", "").replace("-", "").lower()


def _is_numeric_player_id(value: str) -> bool:
    return value.isdigit()
