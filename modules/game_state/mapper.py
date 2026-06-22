"""Extract generic game-state facts from routed FoE service events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core_events.event_types import Event, UNKNOWN_CONTEXT
from modules.game_state.classifier import classify_service

RESOURCE_KEYS = {
    "coins",
    "coin",
    "money",
    "supplies",
    "supply",
    "strategypoints",
    "forgepoints",
    "forgepoints",
    "premium",
    "diamonds",
    "medals",
    "population",
    "happiness",
    "expansions",
}

PLAYER_NAME_KEYS = ("name", "playerName", "player_name", "username", "nick", "nickname")
PLAYER_ID_KEYS = ("player_id", "playerId", "user_id", "userId")
PLAYER_CLASS_HINTS = ("player", "user", "profile", "participant", "member", "avatar")
NON_PLAYER_CLASS_HINTS = (
    "reward",
    "resource",
    "item",
    "product",
    "building",
    "bonus",
    "quest",
    "unit",
    "era",
    "league",
    "chest",
    "package",
)
RESOURCE_DOMAINS = {"player", "resources", "city", "map", "events", "market", "quests"}


@dataclass(frozen=True, slots=True)
class ServiceCatalogDTO:
    """Service/method pair discovered from real game traffic."""

    service_name: str
    method_name: str | None
    domain: str
    first_seen_at: datetime
    last_seen_at: datetime
    sample_payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DomainSnapshotDTO:
    """Latest payload snapshot organized by domain and service."""

    domain: str
    service_name: str
    method_name: str | None
    payload: dict[str, Any]
    captured_at: datetime


@dataclass(frozen=True, slots=True)
class PlayerProfileDTO:
    """Best-effort player profile extraction."""

    player_id: str
    player_name: str | None
    guild_id: str | None
    guild_name: str | None
    era: str | None
    raw_profile: dict[str, Any]
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class ResourceSnapshotDTO:
    """Best-effort resource/currency snapshot."""

    resource_name: str
    amount: int | float | str
    source_service: str
    source_method: str | None
    raw_resource: dict[str, Any]
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class GameStateMapping:
    """All generic game-state facts extracted from one routed service event."""

    request_id: str
    player_id: str
    world_id: str
    catalog_entry: ServiceCatalogDTO | None
    domain_snapshot: DomainSnapshotDTO | None
    player_profile: PlayerProfileDTO | None
    resource_snapshots: list[ResourceSnapshotDTO]


def map_game_state_event(event: Event) -> GameStateMapping:
    """Map a routed service event into generic game-state records."""

    packet = event.packet
    payload = event.payload if isinstance(event.payload, dict) else {"value": event.payload}
    service_name = event.service_name or "unknown"
    domain = classify_service(event.service_name, event.method_name)

    catalog_entry = ServiceCatalogDTO(
        service_name=service_name,
        method_name=event.method_name,
        domain=domain,
        first_seen_at=packet.captured_at,
        last_seen_at=packet.captured_at,
        sample_payload=payload,
    )
    domain_snapshot = DomainSnapshotDTO(
        domain=domain,
        service_name=service_name,
        method_name=event.method_name,
        payload=payload,
        captured_at=packet.captured_at,
    )

    player_profile = _extract_player_profile(
        packet.player_id,
        payload,
        packet.captured_at,
        service_name,
        event.method_name,
    )
    resource_snapshots = [
        ResourceSnapshotDTO(
            resource_name=name,
            amount=amount,
            source_service=service_name,
            source_method=event.method_name,
            raw_resource=raw_resource,
            observed_at=packet.captured_at,
        )
        for name, amount, raw_resource in _extract_resources(payload, domain)
    ]

    return GameStateMapping(
        request_id=packet.request_id,
        player_id=packet.player_id,
        world_id=packet.world_id,
        catalog_entry=catalog_entry,
        domain_snapshot=domain_snapshot,
        player_profile=player_profile,
        resource_snapshots=resource_snapshots,
    )


def _extract_player_profile(
    packet_player_id: str,
    payload: dict[str, Any],
    observed_at: datetime,
    service_name: str,
    method_name: str | None,
) -> PlayerProfileDTO | None:
    candidates = [
        item
        for item in _walk_objects(payload)
        if _looks_like_player(item, service_name, method_name)
    ]
    if not candidates:
        return None

    profile = _prefer_named_player(candidates) or candidates[0]
    player_id = _extract_player_id(profile) or packet_player_id
    if player_id == UNKNOWN_CONTEXT and not _first_text(profile, *PLAYER_NAME_KEYS):
        return None

    guild = _first_dict(profile, "guild", "clan")
    return PlayerProfileDTO(
        player_id=player_id,
        player_name=_first_text(profile, *PLAYER_NAME_KEYS),
        guild_id=_first_text(guild, "id", "guildId", "clanId"),
        guild_name=_first_text(guild, "name", "guildName", "clanName"),
        era=_first_text(profile, "era", "currentEra", "age"),
        raw_profile=profile,
        observed_at=observed_at,
    )


def _extract_resources(
    payload: dict[str, Any],
    domain: str,
) -> list[tuple[str, int | float | str, dict[str, Any]]]:
    if domain not in RESOURCE_DOMAINS:
        return []

    resources: list[tuple[str, int | float | str, dict[str, Any]]] = []
    seen: set[tuple[str, str]] = set()

    for item in _walk_objects(payload):
        if _looks_like_resource_item(item):
            name = _first_text(item, "name", "id", "resourceId", "type", "currency")
            amount = _first_scalar(item, "amount", "value", "count", "balance", "stock")
            if name is not None and amount is not None:
                key = (name, str(amount))
                if key not in seen:
                    seen.add(key)
                    resources.append((name, amount, item))

        for key, value in item.items():
            normalized_key = _normalize_key(key)
            if normalized_key in RESOURCE_KEYS and isinstance(value, int | float | str):
                dedupe_key = (normalized_key, str(value))
                if dedupe_key not in seen:
                    seen.add(dedupe_key)
                    resources.append((str(key), value, {key: value}))

    return resources


def _looks_like_player(
    item: dict[str, Any],
    service_name: str,
    method_name: str | None,
) -> bool:
    keys = {_normalize_key(key) for key in item}
    has_name = bool(keys & {_normalize_key(key) for key in PLAYER_NAME_KEYS})
    if not has_name:
        return False

    class_name = str(item.get("__class__", ""))
    class_hint = class_name.lower()
    if any(hint in class_hint for hint in NON_PLAYER_CLASS_HINTS):
        return False

    has_explicit_player_id = bool(keys & {_normalize_key(key) for key in PLAYER_ID_KEYS})
    has_generic_id = "id" in keys
    has_player_class = any(hint in class_hint for hint in PLAYER_CLASS_HINTS)
    service_context = f"{service_name}.{method_name or ''}".lower()
    service_mentions_player = any(hint in service_context for hint in ("player", "user", "profile"))

    if has_explicit_player_id:
        return True

    if has_generic_id and (has_player_class or service_mentions_player):
        player_id = _first_text(item, "id")
        return bool(player_id and _looks_like_player_identifier(player_id))

    return False


def _looks_like_resource_item(item: dict[str, Any]) -> bool:
    keys = {_normalize_key(key) for key in item}
    has_name = bool(keys & {"name", "id", "resourceid", "type", "currency"})
    has_amount = bool(keys & {"amount", "value", "count", "balance", "stock"})
    return has_name and has_amount


def _prefer_named_player(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    for candidate in candidates:
        if _first_text(candidate, *PLAYER_NAME_KEYS):
            return candidate
    return None


def _extract_player_id(item: dict[str, Any]) -> str | None:
    explicit_id = _first_text(item, *PLAYER_ID_KEYS)
    if explicit_id:
        return explicit_id

    class_name = str(item.get("__class__", "")).lower()
    if any(hint in class_name for hint in PLAYER_CLASS_HINTS):
        generic_id = _first_text(item, "id")
        if generic_id and _looks_like_player_identifier(generic_id):
            return generic_id

    return None


def _looks_like_player_identifier(value: str) -> bool:
    text = value.strip()
    if not text or "#" in text:
        return False
    if text.startswith(("resource", "fragment", "castle_", "event_", "daily_")):
        return False
    return text.isdigit()


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


def _first_dict(source: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = _get_value(source, key)
        if isinstance(value, dict):
            return value
    return {}


def _first_text(source: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _get_value(source, key)
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, int | float | str):
            text = str(value).strip()
            if text:
                return text
    return None


def _first_scalar(source: dict[str, Any], *keys: str) -> int | float | str | None:
    for key in keys:
        value = _get_value(source, key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float | str):
            return value
    return None


def _get_value(source: dict[str, Any], key: str) -> Any:
    if key in source:
        return source[key]
    normalized_key = _normalize_key(key)
    for source_key, value in source.items():
        if _normalize_key(source_key) == normalized_key:
            return value
    return None


def _normalize_key(value: Any) -> str:
    return str(value).replace("_", "").replace("-", "").lower()
