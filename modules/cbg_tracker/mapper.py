"""Map GuildBattlegroundService packets into Phase 1 CBG entities."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any

from core_events.event_types import Event

SERVICE_NAME = "GuildBattlegroundService"
SERVICE_EVENT_NAME = f"service.{SERVICE_NAME}"
BATTLEFIELD_SERVICE_NAME = "BattlefieldService"
BATTLEFIELD_SERVICE_EVENT_NAME = f"service.{BATTLEFIELD_SERVICE_NAME}"

BATTLE_METHOD_HINTS = (
    "startbattle",
    "finishbattle",
    "resolvebattle",
    "startbybattletype",
    "fight",
    "combat",
)
NEGOTIATION_METHOD_HINTS = ("startnegotiation", "finishnegotiation", "resolvenegotiation", "negotiate")
ACTION_TEXT_KEYS = ("action", "actionType", "type", "requestMethod", "method")

SECTOR_ID_KEYS = ("sectorId", "sector_id", "mapSectorId", "provinceId", "province_id", "id")
PROVINCE_ID_KEYS = ("provinceId", "province_id", "province_id", "mapProvinceId")
OWNER_GUILD_ID_KEYS = (
    "ownerGuildId",
    "owner_guild_id",
    "currentOwnerGuildId",
    "guildId",
    "guild_id",
    "ownerId",
)
OWNER_GUILD_NAME_KEYS = (
    "ownerGuildName",
    "owner_guild_name",
    "currentOwnerGuildName",
    "guildName",
    "guild_name",
    "ownerName",
)
STATE_KEYS = ("state", "status", "phase", "lockedState", "sectorState")
VICTORY_POINT_KEYS = (
    "victoryPoints",
    "currentVictoryPoints",
    "current_victory_points",
    "progress",
)
MAX_VICTORY_POINT_KEYS = (
    "maxVictoryPoints",
    "requiredVictoryPoints",
    "totalVictoryPoints",
    "max_victory_points",
)
RESULT_KEYS = ("result", "status", "outcome", "state")
ATTRITION_KEYS = ("attrition", "currentAttrition", "newAttrition", "attritionLevel")
_MISSING = object()


@dataclass(frozen=True, slots=True)
class CbgSectorSnapshotDTO:
    """Mapped sector snapshot ready for persistence."""

    sector_id: str
    province_id: str | None
    owner_guild_id: str | None
    owner_guild_name: str | None
    state: str | None
    victory_points: int | None
    max_victory_points: int | None
    raw_sector: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CbgPersonalActionDTO:
    """Mapped personal CBG battle or negotiation."""

    action_fingerprint: str
    action_type: str
    result: str | None
    sector_id: str | None
    province_id: str | None
    attrition: int | None
    reward_payload: dict[str, Any] | list[Any] | None
    raw_action: dict[str, Any] | list[Any]


@dataclass(frozen=True, slots=True)
class CbgPacketMapping:
    """All CBG facts extracted from a single service event."""

    request_id: str
    player_id: str
    world_id: str
    service_method: str | None
    captured_at: datetime
    sector_snapshots: list[CbgSectorSnapshotDTO]
    personal_actions: list[CbgPersonalActionDTO]

    @property
    def has_data(self) -> bool:
        """Return True when the packet produced persistable CBG facts."""

        return bool(self.sector_snapshots or self.personal_actions)


def map_cbg_event(event: Event) -> CbgPacketMapping:
    """Extract Phase 1 CBG sector snapshots and personal actions from an event."""

    packet = event.packet
    payload = event.payload if event.payload is not None else packet.payload

    if event.service_name not in {SERVICE_NAME, BATTLEFIELD_SERVICE_NAME}:
        return CbgPacketMapping(
            request_id=packet.request_id,
            player_id=packet.player_id,
            world_id=packet.world_id,
            service_method=event.method_name,
            captured_at=packet.captured_at,
            sector_snapshots=[],
            personal_actions=[],
        )

    objects = list(_walk_objects(payload))
    sector_snapshots = _extract_sector_snapshots(payload, objects) if event.service_name == SERVICE_NAME else []
    personal_actions = _extract_personal_actions(event, payload, objects, sector_snapshots)

    return CbgPacketMapping(
        request_id=packet.request_id,
        player_id=packet.player_id,
        world_id=packet.world_id,
        service_method=event.method_name,
        captured_at=packet.captured_at,
        sector_snapshots=sector_snapshots,
        personal_actions=personal_actions,
    )


def _extract_sector_snapshots(
    payload: dict[str, Any] | list[Any],
    objects: list[dict[str, Any]],
) -> list[CbgSectorSnapshotDTO]:
    battleground_snapshots = _extract_battleground_provinces(payload)
    if battleground_snapshots:
        return battleground_snapshots

    return _extract_generic_sector_snapshots(objects)


def _extract_battleground_provinces(
    payload: dict[str, Any] | list[Any],
) -> list[CbgSectorSnapshotDTO]:
    if not isinstance(payload, dict):
        return []

    response_data = _first_value(payload, "responseData")
    if not isinstance(response_data, dict):
        return []

    battleground_map = _first_value(response_data, "map")
    if not isinstance(battleground_map, dict):
        return []

    provinces = _first_value(battleground_map, "provinces")
    if not isinstance(provinces, list):
        return []

    participant_index = _build_participant_index(response_data)
    snapshots: list[CbgSectorSnapshotDTO] = []

    for index, province in enumerate(provinces):
        if not isinstance(province, dict):
            continue

        province_id = _first_text(province, "id")
        if province_id is None:
            province_id = str(index)

        owner_participant_id = _first_text(province, "ownerId")
        owner_participant = participant_index.get(owner_participant_id or "")
        owner_clan = _first_dict(owner_participant, "clan") if owner_participant else {}
        owner_guild_id = _first_text(owner_clan, "id") or owner_participant_id
        owner_guild_name = _first_text(owner_clan, "name")

        snapshots.append(
            CbgSectorSnapshotDTO(
                sector_id=province_id,
                province_id=province_id,
                owner_guild_id=owner_guild_id,
                owner_guild_name=owner_guild_name,
                state=_derive_province_state(province),
                victory_points=_first_int(province, "victoryPoints"),
                max_victory_points=None,
                raw_sector={
                    **province,
                    "mapId": _first_text(battleground_map, "id"),
                    "ownerParticipantId": owner_participant_id,
                    "ownerParticipantColour": _first_text(owner_participant, "colour")
                    if owner_participant
                    else None,
                },
            )
        )

    return snapshots


def _build_participant_index(response_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    participants = _first_value(response_data, "battlegroundParticipants")
    if not isinstance(participants, list):
        return {}

    index: dict[str, dict[str, Any]] = {}
    for participant in participants:
        if not isinstance(participant, dict):
            continue
        participant_id = _first_text(participant, "participantId")
        if participant_id:
            index[participant_id] = participant
    return index


def _derive_province_state(province: dict[str, Any]) -> str | None:
    if _first_bool(province, "isSpawnSpot"):
        return "spawn"
    if _first_int(province, "lockedUntil"):
        return "locked"
    if _first_bool(province, "isAttackBattleType"):
        return "attack"
    return "open"


def _extract_generic_sector_snapshots(objects: list[dict[str, Any]]) -> list[CbgSectorSnapshotDTO]:
    snapshots: list[CbgSectorSnapshotDTO] = []
    seen: set[tuple[str, str | None, str | None, str | None, int | None]] = set()

    for item in objects:
        if not _looks_like_sector(item):
            continue

        sector_id = _first_text(item, *SECTOR_ID_KEYS)
        if not sector_id:
            continue

        owner_guild = _first_dict(item, "ownerGuild", "guild", "owner")
        owner_guild_id = _first_text(item, *OWNER_GUILD_ID_KEYS) or _first_text(
            owner_guild, "id", "guildId"
        )
        owner_guild_name = _first_text(item, *OWNER_GUILD_NAME_KEYS) or _first_text(
            owner_guild, "name", "guildName"
        )
        province_id = _first_text(item, *PROVINCE_ID_KEYS)
        state = _first_text(item, *STATE_KEYS)
        victory_points = _first_int(item, *VICTORY_POINT_KEYS)
        max_victory_points = _first_int(item, *MAX_VICTORY_POINT_KEYS)

        dedupe_key = (sector_id, province_id, owner_guild_id, state, victory_points)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        snapshots.append(
            CbgSectorSnapshotDTO(
                sector_id=sector_id,
                province_id=province_id,
                owner_guild_id=owner_guild_id,
                owner_guild_name=owner_guild_name,
                state=state,
                victory_points=victory_points,
                max_victory_points=max_victory_points,
                raw_sector=item,
            )
        )

    return snapshots


def _extract_personal_actions(
    event: Event,
    payload: dict[str, Any] | list[Any],
    objects: list[dict[str, Any]],
    sectors: list[CbgSectorSnapshotDTO],
) -> list[CbgPersonalActionDTO]:
    if event.service_name == BATTLEFIELD_SERVICE_NAME and not _is_battleground_battle(payload):
        return []

    action_type = _detect_action_type(event, objects)
    if not action_type:
        return []

    action_node = _find_action_node(objects, action_type) or payload
    sector_id = _extract_action_sector_id(action_node)
    province_id = _extract_action_province_id(action_node)

    if not sector_id and sectors:
        sector_id = sectors[0].sector_id
    if not province_id and sectors:
        province_id = sectors[0].province_id

    result = _extract_result(action_node, objects)
    attrition = _first_int(action_node, *ATTRITION_KEYS) or _first_int_in_objects(
        objects, *ATTRITION_KEYS
    )
    reward_payload = _first_value(action_node, "reward", "rewards", "loot", "lootItems")
    if reward_payload is None:
        reward_payload = _first_value_in_objects(objects, "reward", "rewards", "loot", "lootItems")

    fingerprint = _fingerprint(
        {
            "request_id": event.packet.request_id,
            "action_type": action_type,
            "method": event.method_name,
            "sector_id": sector_id,
            "province_id": province_id,
            "result": result,
            "raw_action": action_node,
        }
    )

    return [
        CbgPersonalActionDTO(
            action_fingerprint=fingerprint,
            action_type=action_type,
            result=result,
            sector_id=sector_id,
            province_id=province_id,
            attrition=attrition,
            reward_payload=reward_payload,
            raw_action=action_node,
        )
    ]


def _detect_action_type(event: Event, objects: list[dict[str, Any]]) -> str | None:
    method = _normalize_key(event.method_name or "")
    if _contains_action_hint(method, NEGOTIATION_METHOD_HINTS):
        return "negotiation"
    if _contains_action_hint(method, BATTLE_METHOD_HINTS):
        return "battle"

    return None


def _is_battleground_battle(payload: dict[str, Any] | list[Any]) -> bool:
    response_data = _first_value(payload, "responseData") if isinstance(payload, dict) else None
    if not isinstance(response_data, dict):
        return False

    battle_type = _first_value(response_data, "battleType")
    if not isinstance(battle_type, dict):
        return False

    return _normalize_key(_first_text(battle_type, "type") or "") == "battleground"


def _extract_action_sector_id(action_node: dict[str, Any] | list[Any]) -> str | None:
    return _extract_action_province_id(action_node) or _first_text(action_node, *SECTOR_ID_KEYS)


def _extract_action_province_id(action_node: dict[str, Any] | list[Any]) -> str | None:
    if not isinstance(action_node, dict):
        return None

    direct_province_id = _first_text(action_node, *PROVINCE_ID_KEYS)
    if direct_province_id:
        return direct_province_id

    response_data = _first_value(action_node, "responseData")
    if isinstance(response_data, dict):
        direct_province_id = _first_text(response_data, *PROVINCE_ID_KEYS)
        if direct_province_id:
            return direct_province_id

        battle_type = _first_value(response_data, "battleType")
        if isinstance(battle_type, dict):
            return _first_text(battle_type, *PROVINCE_ID_KEYS)

    battle_type = _first_value(action_node, "battleType")
    if isinstance(battle_type, dict):
        return _first_text(battle_type, *PROVINCE_ID_KEYS)

    return None


def _find_action_node(objects: list[dict[str, Any]], action_type: str) -> dict[str, Any] | None:
    hints = NEGOTIATION_METHOD_HINTS if action_type == "negotiation" else BATTLE_METHOD_HINTS

    for item in objects:
        haystack = " ".join(
            _normalize_key(value)
            for value in (
                _first_text(item, *ACTION_TEXT_KEYS),
                _first_text(item, "event", "name"),
            )
            if value
        )
        if _contains_action_hint(haystack, hints):
            return item

    return None


def _looks_like_sector(item: dict[str, Any]) -> bool:
    normalized_keys = {_normalize_key(key) for key in item}

    class_name = _normalize_key(_first_text(item, "__class__") or "")

    if "requestclass" in normalized_keys or "requestmethod" in normalized_keys:
        return False
    if class_name in {"guildbattlegroundmap", "guildbattlegroundpendingupdate"}:
        return False
    if class_name and "province" not in class_name and "sector" not in class_name:
        return False

    has_identity = bool(_first_text(item, *SECTOR_ID_KEYS) or _first_text(item, "ownerId"))
    has_sector_hint = any("sector" in key or "province" in key for key in normalized_keys)
    has_cbg_state_hint = bool(
        normalized_keys
        & {
            "ownerguildid",
            "ownerguildname",
            "currentownerguildid",
            "victorypoints",
            "currentvictorypoints",
            "maxvictorypoints",
            "requiredvictorypoints",
            "lockedstate",
            "sectorstate",
            "conquestprogress",
            "ownerid",
        }
    )

    return has_identity and (has_sector_hint or has_cbg_state_hint)


def _extract_result(action_node: dict[str, Any] | list[Any], objects: list[dict[str, Any]]) -> str | None:
    if isinstance(action_node, dict):
        response_data = _first_value(action_node, "responseData")
        if isinstance(response_data, dict):
            state = _first_value(response_data, "state")
            if isinstance(state, dict):
                winner_bit = _first_int(state, "winnerBit")
                if winner_bit is not None:
                    return "won" if winner_bit == 1 else "lost"

        explicit_result = _first_text(action_node, *RESULT_KEYS)
        if explicit_result:
            return explicit_result

        victory = _first_bool(action_node, "victory", "won", "success", "isVictory")
        if victory is not None:
            return "won" if victory else "lost"

    for item in objects:
        explicit_result = _first_text(item, *RESULT_KEYS)
        if explicit_result:
            return explicit_result

        victory = _first_bool(item, "victory", "won", "success", "isVictory")
        if victory is not None:
            return "won" if victory else "lost"

    return None


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


def _first_text(source: dict[str, Any] | list[Any], *keys: str) -> str | None:
    if not isinstance(source, dict):
        return None

    for key in keys:
        value = _get_value(source, key)
        if value is _MISSING or value is None:
            continue
        if isinstance(value, bool):
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _first_int(source: dict[str, Any] | list[Any], *keys: str) -> int | None:
    if not isinstance(source, dict):
        return None

    for key in keys:
        value = _get_value(source, key)
        if value is _MISSING:
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value)
    return None


def _first_int_in_objects(objects: list[dict[str, Any]], *keys: str) -> int | None:
    for item in objects:
        value = _first_int(item, *keys)
        if value is not None:
            return value
    return None


def _first_bool(source: dict[str, Any], *keys: str) -> bool | None:
    for key in keys:
        value = _get_value(source, key)
        if isinstance(value, bool):
            return value
    return None


def _first_value(source: dict[str, Any] | list[Any], *keys: str) -> Any:
    if not isinstance(source, dict):
        return None

    for key in keys:
        value = _get_value(source, key)
        if value is not _MISSING:
            return value
    return None


def _first_value_in_objects(objects: list[dict[str, Any]], *keys: str) -> Any:
    for item in objects:
        value = _first_value(item, *keys)
        if value is not None:
            return value
    return None


def _fingerprint(value: Any) -> str:
    serialized = json.dumps(value, default=str, ensure_ascii=False, sort_keys=True)
    return sha256(serialized.encode("utf-8")).hexdigest()


def _normalize_key(key: Any) -> str:
    return str(key).replace("_", "").replace("-", "").lower()


def _contains_action_hint(value: str, hints: tuple[str, ...]) -> bool:
    normalized_value = _normalize_key(value)
    if "battleground" in normalized_value:
        normalized_value = normalized_value.replace("battleground", "")
    return any(hint in normalized_value for hint in hints)


def _get_value(source: dict[str, Any], key: str) -> Any:
    if key in source:
        return source[key]

    normalized_key = _normalize_key(key)
    for source_key, value in source.items():
        if _normalize_key(source_key) == normalized_key:
            return value

    return _MISSING
