"""SQLAlchemy models for the FoE Analytics persistence layer."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from core_events.event_types import UNKNOWN_CONTEXT


class Base(DeclarativeBase):
    """Base class for all ORM models."""


class PlayerWorldMixin:
    """Mandatory tenant context for all non-static tables."""

    player_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=UNKNOWN_CONTEXT,
        server_default=text(f"'{UNKNOWN_CONTEXT}'"),
    )
    world_id: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=UNKNOWN_CONTEXT,
        server_default=text(f"'{UNKNOWN_CONTEXT}'"),
    )


class TimestampMixin:
    """Standard audit timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=text("CURRENT_TIMESTAMP"),
    )


class RawPacket(PlayerWorldMixin, TimestampMixin, Base):
    """Raw JSON packet persisted as a PostgreSQL JSONB data lake entry."""

    __tablename__ = "raw_packets"

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    service_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    method_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    http_method: Mapped[str] = mapped_column(String(16), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict[str, Any] | list[Any]] = mapped_column(JSONB, nullable=False)
    packet_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_raw_packets_player_world_captured", "player_id", "world_id", "captured_at"),
        Index("ix_raw_packets_service_method", "service_name", "method_name"),
        Index("ix_raw_packets_payload_gin", "payload", postgresql_using="gin"),
    )


class RoutedServiceEvent(PlayerWorldMixin, TimestampMixin, Base):
    """One classified service call extracted from a captured packet."""

    __tablename__ = "routed_service_events"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    event_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_name: Mapped[str] = mapped_column(String(192), nullable=False)
    service_name: Mapped[str] = mapped_column(String(128), nullable=False)
    method_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    http_method: Mapped[str] = mapped_column(String(16), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    service_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("event_fingerprint", name="uq_routed_service_events_fingerprint"),
        Index(
            "ix_routed_service_events_player_world_captured",
            "player_id",
            "world_id",
            "captured_at",
        ),
        Index("ix_routed_service_events_service_method", "service_name", "method_name"),
        Index("ix_routed_service_events_payload_gin", "service_payload", postgresql_using="gin"),
    )


class ServiceCatalog(TimestampMixin, Base):
    """Discovered service/method catalog from real game traffic."""

    __tablename__ = "service_catalog"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    service_name: Mapped[str] = mapped_column(String(128), nullable=False)
    method_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    domain: Mapped[str] = mapped_column(String(64), nullable=False)
    total_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sample_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        UniqueConstraint("service_name", "method_name", name="uq_service_catalog_service_method"),
        Index("ix_service_catalog_domain", "domain"),
        Index("ix_service_catalog_sample_gin", "sample_payload", postgresql_using="gin"),
    )


class GameDomainSnapshot(PlayerWorldMixin, TimestampMixin, Base):
    """Payload snapshot organized by game domain and source service."""

    __tablename__ = "game_domain_snapshots"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    domain: Mapped[str] = mapped_column(String(64), nullable=False)
    service_name: Mapped[str] = mapped_column(String(128), nullable=False)
    method_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("request_id", "service_name", "method_name", name="uq_game_domain_snapshot_event"),
        Index("ix_game_domain_snapshots_domain_captured", "domain", "captured_at"),
        Index("ix_game_domain_snapshots_player_world_domain", "player_id", "world_id", "domain"),
        Index("ix_game_domain_snapshots_payload_gin", "payload", postgresql_using="gin"),
    )


class PlayerProfileSnapshot(PlayerWorldMixin, TimestampMixin, Base):
    """Best-effort player identity/profile snapshot."""

    __tablename__ = "player_profile_snapshots"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    player_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    guild_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    guild_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    era: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_profile: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_player_profile_snapshots_player_world_observed", "player_id", "world_id", "observed_at"),
        Index("ix_player_profile_snapshots_name", "player_name"),
        Index("ix_player_profile_snapshots_raw_gin", "raw_profile", postgresql_using="gin"),
    )


class PlayerResourceSnapshot(PlayerWorldMixin, TimestampMixin, Base):
    """Best-effort player resource/currency snapshot."""

    __tablename__ = "player_resource_snapshots"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_name: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[str] = mapped_column(String(128), nullable=False)
    source_service: Mapped[str] = mapped_column(String(128), nullable=False)
    source_method: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_resource: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_player_resource_snapshots_player_world_resource", "player_id", "world_id", "resource_name"),
        Index("ix_player_resource_snapshots_observed", "observed_at"),
        Index("ix_player_resource_snapshots_raw_gin", "raw_resource", postgresql_using="gin"),
    )


class PlayerIdentity(PlayerWorldMixin, TimestampMixin, Base):
    """Current canonical player identity for one player/world context."""

    __tablename__ = "player_identities"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    player_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    guild_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    guild_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    era: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_service: Mapped[str] = mapped_column(String(128), nullable=False)
    source_method: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_profile: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("player_id", "world_id", name="uq_player_identities_player_world"),
        Index("ix_player_identities_name", "player_name"),
        Index("ix_player_identities_raw_gin", "raw_profile", postgresql_using="gin"),
    )


class PlayerIdentitySnapshot(PlayerWorldMixin, TimestampMixin, Base):
    """Append-only player identity observation history."""

    __tablename__ = "player_identity_snapshots"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    player_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    guild_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    guild_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    era: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_service: Mapped[str] = mapped_column(String(128), nullable=False)
    source_method: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_profile: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "request_id",
            "player_id",
            "world_id",
            name="uq_player_identity_snapshots_request_player_world",
        ),
        Index("ix_player_identity_snapshots_player_world_observed", "player_id", "world_id", "observed_at"),
        Index("ix_player_identity_snapshots_raw_gin", "raw_profile", postgresql_using="gin"),
    )


class PlayerWalletBalance(PlayerWorldMixin, TimestampMixin, Base):
    """Current known balance for a player resource/currency."""

    __tablename__ = "player_wallet_balances"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    resource_name: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[Any] = mapped_column(Numeric(32, 4), nullable=True)
    amount_text: Mapped[str] = mapped_column(String(128), nullable=False)
    source_service: Mapped[str] = mapped_column(String(128), nullable=False)
    source_method: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_resource: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("player_id", "world_id", "resource_name", name="uq_player_wallet_balance_resource"),
        Index("ix_player_wallet_balances_player_world", "player_id", "world_id"),
        Index("ix_player_wallet_balances_raw_gin", "raw_resource", postgresql_using="gin"),
    )


class PlayerWalletSnapshot(PlayerWorldMixin, TimestampMixin, Base):
    """Append-only wallet/resource balance observation history."""

    __tablename__ = "player_wallet_snapshots"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_name: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[Any] = mapped_column(Numeric(32, 4), nullable=True)
    amount_text: Mapped[str] = mapped_column(String(128), nullable=False)
    delta_amount: Mapped[Any | None] = mapped_column(Numeric(32, 4), nullable=True)
    source_service: Mapped[str] = mapped_column(String(128), nullable=False)
    source_method: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_resource: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "request_id",
            "player_id",
            "world_id",
            "resource_name",
            name="uq_player_wallet_snapshots_request_resource",
        ),
        Index("ix_player_wallet_snapshots_player_world_resource", "player_id", "world_id", "resource_name"),
        Index("ix_player_wallet_snapshots_observed", "observed_at"),
        Index("ix_player_wallet_snapshots_raw_gin", "raw_resource", postgresql_using="gin"),
    )


class CbgSectorSnapshot(PlayerWorldMixin, TimestampMixin, Base):
    """Point-in-time snapshot of a Guild Battleground sector."""

    __tablename__ = "cbg_sector_snapshots"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sector_id: Mapped[str] = mapped_column(String(64), nullable=False)
    province_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    owner_guild_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    owner_guild_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    victory_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_victory_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    service_method: Mapped[str | None] = mapped_column(String(128), nullable=True)
    raw_sector: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index(
            "ix_cbg_sector_snapshots_player_world_sector_captured",
            "player_id",
            "world_id",
            "sector_id",
            "captured_at",
        ),
        Index("ix_cbg_sector_snapshots_owner", "world_id", "owner_guild_id"),
        Index("ix_cbg_sector_snapshots_raw_gin", "raw_sector", postgresql_using="gin"),
    )


class CbgPersonalAction(PlayerWorldMixin, TimestampMixin, Base):
    """Personal CBG battle or negotiation log entry."""

    __tablename__ = "cbg_personal_actions"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    action_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    result: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sector_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    province_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attrition: Mapped[int | None] = mapped_column(Integer, nullable=True)
    service_method: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reward_payload: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB, nullable=True)
    raw_action: Mapped[dict[str, Any] | list[Any]] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("action_fingerprint", name="uq_cbg_personal_actions_fingerprint"),
        Index(
            "ix_cbg_personal_actions_player_world_occurred",
            "player_id",
            "world_id",
            "occurred_at",
        ),
        Index("ix_cbg_personal_actions_type", "world_id", "action_type"),
        Index("ix_cbg_personal_actions_raw_gin", "raw_action", postgresql_using="gin"),
    )
