"""Map routed FoE service events into canonical player identity facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core_events.event_types import Event, UNKNOWN_CONTEXT

PLAYER_NAME_KEYS = ("playerName", "player_name", "name", "username", "nickname", "nick")
PLAYER_ID_KEYS = ("player_id", "playerId", "user_id", "userId")
PLAYER_CLASS_HINTS = ("player", "user", "profile", "participant", "member", "avatar")
NON_PLAYER_HINTS = (
    "reward",
    "resource",
    "item",
    "product",
    "building",
    "bonus",
    "quest",
    "unit",
    "league",
    "chest",
    "package",
)


@dataclass(frozen=True, slots=True)
class PlayerIdentityDTO:
    """Canonical identity observation for one player/world."""

    player_id: str
    player_name: str | None
    guild_id: str | None
    guild_name: str | None
    era: str | None
    source_service: str
    source_method: str | None
    raw_profile: dict[str, Any]
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class PlayerIdentityMapping:
    """Player identity records extracted from one service event."""

    request_id: str
    player_id: str
    world_id: str
    identity: PlayerIdentityDTO | None


def map_player_identity_event(event: Event) -> PlayerIdentityMapping:
    """Extract the best identity observation from a routed service event."""

    payload = event.payload if isinstance(event.payload, dict) else {"value": event.payload}
    service_name = event.service_name or "unknown"
    identity = _extract_identity(
        packet_player_id=event.packet.player_id,
        payload=payload,
        observed_at=event.packet.captured_at,
        source_service=service_name,
        source_method=event.method_name,
    )
    mapped_player_id = identity.player_id if identity else event.packet.player_id
    return PlayerIdentityMapping(
        request_id=event.packet.request_id,
        player_id=mapped_player_id,
        world_id=event.packet.world_id,
        identity=identity,
    )


def _extract_identity(
    packet_player_id: str,
    payload: dict[str, Any],
    observed_at: datetime,
    source_service: str,
    source_method: str | None,
) -> PlayerIdentityDTO | None:
    candidates = [
        item
        for item in _walk_objects(payload)
        if _looks_like_player(item, source_service, source_method)
    ]
    if not candidates:
        return None

    profile = _prefer_packet_player(candidates, packet_player_id) or candidates[0]
    player_id = _extract_player_id(profile) or packet_player_id
    if not _looks_like_player_identifier(player_id):
        return None

    guild = _first_dict(profile, "guild", "clan")
    return PlayerIdentityDTO(
        player_id=player_id,
        player_name=_first_text(profile, *PLAYER_NAME_KEYS),
        guild_id=_first_text(guild, "id", "guildId", "clanId"),
        guild_name=_first_text(guild, "name", "guildName", "clanName"),
        era=_first_text(profile, "era", "currentEra", "age"),
        source_service=source_service,
        source_method=source_method,
        raw_profile=profile,
        observed_at=observed_at,
    )


def _looks_like_player(
    item: dict[str, Any],
    service_name: str,
    method_name: str | None,
) -> bool:
    keys = {_normalize_key(key) for key in item}
    if not keys & {_normalize_key(key) for key in PLAYER_NAME_KEYS}:
        return False

    class_name = str(item.get("__class__", "")).lower()
    if any(hint in class_name for hint in NON_PLAYER_HINTS):
        return False

    service_context = f"{service_name}.{method_name or ''}".lower()
    has_explicit_id = bool(keys & {_normalize_key(key) for key in PLAYER_ID_KEYS})
    has_player_class = any(hint in class_name for hint in PLAYER_CLASS_HINTS)
    service_mentions_player = any(hint in service_context for hint in ("player", "user", "profile"))

    if has_explicit_id:
        return True

    if "id" in keys and (has_player_class or service_mentions_player):
        player_id = _first_text(item, "id")
        return bool(player_id and _looks_like_player_identifier(player_id))

    return False


def _prefer_packet_player(
    candidates: list[dict[str, Any]],
    packet_player_id: str,
) -> dict[str, Any] | None:
    if packet_player_id == UNKNOWN_CONTEXT:
        return None

    for candidate in candidates:
        if _extract_player_id(candidate) == packet_player_id:
            return candidate

    return None


def _extract_player_id(item: dict[str, Any]) -> str | None:
    explicit_id = _first_text(item, *PLAYER_ID_KEYS)
    if explicit_id:
        return explicit_id

    class_name = str(item.get("__class__", "")).lower()
    if any(hint in class_name for hint in PLAYER_CLASS_HINTS):
        return _first_text(item, "id")

    return None


def _looks_like_player_identifier(value: str | None) -> bool:
    if not value:
        return False
    text = value.strip()
    return text.isdigit() and text != UNKNOWN_CONTEXT


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
