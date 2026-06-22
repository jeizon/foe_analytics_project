"""Persistence helpers for raw packets and Phase 1 CBG entities."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import TYPE_CHECKING, Any
from decimal import Decimal, InvalidOperation

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core_events.event_types import Event

if TYPE_CHECKING:
    from modules.cbg_tracker.mapper import CbgPacketMapping
    from modules.game_state.mapper import GameStateMapping
    from modules.player_core.mapper import PlayerIdentityMapping
    from modules.wallet_tracker.mapper import WalletMapping

from database.models import (
    CbgPersonalAction,
    CbgSectorSnapshot,
    GameDomainSnapshot,
    PlayerProfileSnapshot,
    PlayerResourceSnapshot,
    PlayerIdentity,
    PlayerIdentitySnapshot,
    PlayerWalletBalance,
    PlayerWalletSnapshot,
    RawPacket,
    RoutedServiceEvent,
    ServiceCatalog,
)


class RawPacketRepository:
    """Stores raw routed packets as JSONB data lake entries."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_event(self, event: Event) -> None:
        """Persist the raw event payload, ignoring duplicate request ids."""

        packet = event.packet
        raw_statement = (
            insert(RawPacket)
            .values(
                request_id=packet.request_id,
                player_id=packet.player_id,
                world_id=packet.world_id,
                service_name=event.service_name,
                method_name=event.method_name,
                endpoint=packet.endpoint,
                http_method=packet.http_method,
                status_code=packet.status_code,
                payload=packet.payload,
                packet_metadata=_json_object(
                    {
                        **packet.metadata,
                        "event_name": event.name,
                        "headers": packet.headers,
                    }
                ),
                captured_at=packet.captured_at,
            )
            .on_conflict_do_nothing(index_elements=["request_id"])
        )
        await self._session.execute(raw_statement)

        if not event.service_name:
            return

        service_statement = (
            insert(RoutedServiceEvent)
            .values(
                event_fingerprint=_fingerprint(
                    {
                        "request_id": packet.request_id,
                        "service_name": event.service_name,
                        "method_name": event.method_name,
                        "payload": event.payload,
                    }
                ),
                request_id=packet.request_id,
                player_id=packet.player_id,
                world_id=packet.world_id,
                event_name=event.name,
                service_name=event.service_name,
                method_name=event.method_name,
                endpoint=packet.endpoint,
                http_method=packet.http_method,
                status_code=packet.status_code,
                service_payload=_json_object(event.payload),
                captured_at=packet.captured_at,
            )
            .on_conflict_do_nothing(index_elements=["event_fingerprint"])
        )
        await self._session.execute(service_statement)


class CbgRepository:
    """Stores mapped CBG sector snapshots and personal action logs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_mapping(self, mapping: "CbgPacketMapping") -> None:
        """Persist all CBG entities extracted from a single packet."""

        if mapping.sector_snapshots:
            await self._session.execute(
                insert(CbgSectorSnapshot),
                [
                    {
                        "request_id": mapping.request_id,
                        "player_id": mapping.player_id,
                        "world_id": mapping.world_id,
                        "sector_id": snapshot.sector_id,
                        "province_id": snapshot.province_id,
                        "owner_guild_id": snapshot.owner_guild_id,
                        "owner_guild_name": snapshot.owner_guild_name,
                        "state": snapshot.state,
                        "victory_points": snapshot.victory_points,
                        "max_victory_points": snapshot.max_victory_points,
                        "service_method": mapping.service_method,
                        "raw_sector": _json_object(snapshot.raw_sector),
                        "captured_at": mapping.captured_at,
                    }
                    for snapshot in mapping.sector_snapshots
                ],
            )

        if mapping.personal_actions:
            statement = insert(CbgPersonalAction).on_conflict_do_nothing(
                index_elements=["action_fingerprint"]
            )
            await self._session.execute(
                statement,
                [
                    {
                        "action_fingerprint": action.action_fingerprint,
                        "request_id": mapping.request_id,
                        "player_id": mapping.player_id,
                        "world_id": mapping.world_id,
                        "action_type": action.action_type,
                        "result": action.result,
                        "sector_id": action.sector_id,
                        "province_id": action.province_id,
                        "attrition": action.attrition,
                        "service_method": mapping.service_method,
                        "reward_payload": action.reward_payload,
                        "raw_action": action.raw_action,
                        "occurred_at": mapping.captured_at,
                    }
                    for action in mapping.personal_actions
                ],
            )


class GameStateRepository:
    """Stores universal game-state catalog and derived snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_mapping(self, mapping: "GameStateMapping") -> None:
        """Persist generic records extracted from a routed event."""

        if mapping.catalog_entry:
            catalog = mapping.catalog_entry
            statement = insert(ServiceCatalog).values(
                service_name=catalog.service_name,
                method_name=catalog.method_name,
                domain=catalog.domain,
                first_seen_at=catalog.first_seen_at,
                last_seen_at=catalog.last_seen_at,
                sample_payload=_json_object(catalog.sample_payload),
            )
            statement = statement.on_conflict_do_update(
                constraint="uq_service_catalog_service_method",
                set_={
                    "domain": catalog.domain,
                    "last_seen_at": catalog.last_seen_at,
                    "total_seen": ServiceCatalog.total_seen + 1,
                },
            )
            await self._session.execute(statement)

        if mapping.domain_snapshot:
            snapshot = mapping.domain_snapshot
            statement = insert(GameDomainSnapshot).values(
                request_id=mapping.request_id,
                player_id=mapping.player_id,
                world_id=mapping.world_id,
                domain=snapshot.domain,
                service_name=snapshot.service_name,
                method_name=snapshot.method_name,
                payload=_json_object(snapshot.payload),
                captured_at=snapshot.captured_at,
            )
            statement = statement.on_conflict_do_nothing(
                constraint="uq_game_domain_snapshot_event"
            )
            await self._session.execute(statement)

        if mapping.player_profile:
            profile = mapping.player_profile
            await self._session.execute(
                insert(PlayerProfileSnapshot).values(
                    request_id=mapping.request_id,
                    player_id=profile.player_id,
                    world_id=mapping.world_id,
                    player_name=profile.player_name,
                    guild_id=profile.guild_id,
                    guild_name=profile.guild_name,
                    era=profile.era,
                    raw_profile=_json_object(profile.raw_profile),
                    observed_at=profile.observed_at,
                )
            )

        if mapping.resource_snapshots:
            await self._session.execute(
                insert(PlayerResourceSnapshot),
                [
                    {
                        "request_id": mapping.request_id,
                        "player_id": mapping.player_id,
                        "world_id": mapping.world_id,
                        "resource_name": resource.resource_name,
                        "amount": str(resource.amount),
                        "source_service": resource.source_service,
                        "source_method": resource.source_method,
                        "raw_resource": _json_object(resource.raw_resource),
                        "observed_at": resource.observed_at,
                    }
                    for resource in mapping.resource_snapshots
                ],
            )


class PlayerCoreRepository:
    """Stores canonical player identity data."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_mapping(self, mapping: "PlayerIdentityMapping") -> None:
        """Persist current identity and append-only identity history."""

        if not mapping.identity:
            return

        identity = mapping.identity
        current_statement = insert(PlayerIdentity).values(
            player_id=identity.player_id,
            world_id=mapping.world_id,
            player_name=identity.player_name,
            guild_id=identity.guild_id,
            guild_name=identity.guild_name,
            era=identity.era,
            source_service=identity.source_service,
            source_method=identity.source_method,
            raw_profile=_json_object(identity.raw_profile),
            first_seen_at=identity.observed_at,
            last_seen_at=identity.observed_at,
        )
        current_statement = current_statement.on_conflict_do_update(
            constraint="uq_player_identities_player_world",
            set_={
                "player_name": identity.player_name,
                "guild_id": identity.guild_id,
                "guild_name": identity.guild_name,
                "era": identity.era,
                "source_service": identity.source_service,
                "source_method": identity.source_method,
                "raw_profile": _json_object(identity.raw_profile),
                "last_seen_at": identity.observed_at,
            },
        )
        await self._session.execute(current_statement)

        history_statement = insert(PlayerIdentitySnapshot).values(
            request_id=mapping.request_id,
            player_id=identity.player_id,
            world_id=mapping.world_id,
            player_name=identity.player_name,
            guild_id=identity.guild_id,
            guild_name=identity.guild_name,
            era=identity.era,
            source_service=identity.source_service,
            source_method=identity.source_method,
            raw_profile=_json_object(identity.raw_profile),
            observed_at=identity.observed_at,
        )
        history_statement = history_statement.on_conflict_do_nothing(
            constraint="uq_player_identity_snapshots_request_player_world"
        )
        await self._session.execute(history_statement)


class WalletRepository:
    """Stores current wallet balances and balance history."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_mapping(self, mapping: "WalletMapping") -> None:
        """Persist wallet balance observations."""

        for resource in mapping.resources:
            amount = _decimal_or_none(resource.amount)
            previous_amount = await self._fetch_current_amount(
                mapping.player_id,
                mapping.world_id,
                resource.resource_name,
            )
            delta_amount = None
            if amount is not None and previous_amount is not None:
                delta_amount = amount - previous_amount

            balance_statement = insert(PlayerWalletBalance).values(
                player_id=mapping.player_id,
                world_id=mapping.world_id,
                resource_name=resource.resource_name,
                amount=amount,
                amount_text=str(resource.amount),
                source_service=resource.source_service,
                source_method=resource.source_method,
                raw_resource=_json_object(resource.raw_resource),
                first_seen_at=resource.observed_at,
                last_seen_at=resource.observed_at,
            )
            balance_statement = balance_statement.on_conflict_do_update(
                constraint="uq_player_wallet_balance_resource",
                set_={
                    "amount": amount,
                    "amount_text": str(resource.amount),
                    "source_service": resource.source_service,
                    "source_method": resource.source_method,
                    "raw_resource": _json_object(resource.raw_resource),
                    "last_seen_at": resource.observed_at,
                },
            )
            await self._session.execute(balance_statement)

            snapshot_statement = insert(PlayerWalletSnapshot).values(
                request_id=mapping.request_id,
                player_id=mapping.player_id,
                world_id=mapping.world_id,
                resource_name=resource.resource_name,
                amount=amount,
                amount_text=str(resource.amount),
                delta_amount=delta_amount,
                source_service=resource.source_service,
                source_method=resource.source_method,
                raw_resource=_json_object(resource.raw_resource),
                observed_at=resource.observed_at,
            )
            snapshot_statement = snapshot_statement.on_conflict_do_nothing(
                constraint="uq_player_wallet_snapshots_request_resource"
            )
            await self._session.execute(snapshot_statement)

    async def _fetch_current_amount(
        self,
        player_id: str,
        world_id: str,
        resource_name: str,
    ) -> Decimal | None:
        result = await self._session.execute(
            select(PlayerWalletBalance.amount).where(
                PlayerWalletBalance.player_id == player_id,
                PlayerWalletBalance.world_id == world_id,
                PlayerWalletBalance.resource_name == resource_name,
            )
        )
        return result.scalar_one_or_none()


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {"value": value}


def _fingerprint(value: Any) -> str:
    serialized = json.dumps(value, default=str, ensure_ascii=False, sort_keys=True)
    return sha256(serialized.encode("utf-8")).hexdigest()


def _decimal_or_none(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
