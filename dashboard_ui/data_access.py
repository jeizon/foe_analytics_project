"""Async data access for the Streamlit dashboard."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from database.db_manager import DatabaseManager

ALL_CONTEXT = "__all__"


async def fetch_contexts(db_manager: DatabaseManager) -> list[dict[str, Any]]:
    """Return available player/world pairs seen in captured tables."""

    query = text(
        """
        SELECT DISTINCT
            contexts.player_id,
            contexts.world_id,
            identity.player_name
        FROM (
            SELECT player_id, world_id FROM cbg_sector_snapshots
            UNION
            SELECT player_id, world_id FROM cbg_personal_actions
            UNION
            SELECT player_id, world_id FROM game_domain_snapshots
            UNION
            SELECT player_id, world_id FROM player_profile_snapshots
            UNION
            SELECT player_id, world_id FROM player_resource_snapshots
            UNION
            SELECT player_id, world_id FROM player_identities
            UNION
            SELECT player_id, world_id FROM player_wallet_balances
            UNION
            SELECT player_id, world_id FROM routed_service_events
        ) contexts
        LEFT JOIN player_identities identity
          ON identity.player_id = contexts.player_id
         AND identity.world_id = contexts.world_id
        ORDER BY contexts.world_id, contexts.player_id
        """
    )
    async with db_manager.engine.connect() as connection:
        result = await connection.execute(query)
        return [dict(row._mapping) for row in result]


async def fetch_capture_overview(
    db_manager: DatabaseManager,
    player_id: str = ALL_CONTEXT,
    world_id: str = ALL_CONTEXT,
) -> dict[str, Any]:
    """Return universal capture counters for the selected context."""

    raw_where, raw_params = _build_filter("r", player_id, world_id)
    domain_where, domain_params = _build_filter("d", player_id, world_id)
    profile_where, profile_params = _build_filter("p", player_id, world_id)
    resource_where, resource_params = _build_filter("res", player_id, world_id)

    query = text(
        f"""
        SELECT
            (SELECT COUNT(*) FROM raw_packets r {raw_where}) AS raw_packets,
            (SELECT COUNT(*) FROM routed_service_events r {raw_where}) AS routed_events,
            (SELECT COUNT(*) FROM service_catalog) AS catalog_entries,
            (SELECT COUNT(*) FROM game_domain_snapshots d {domain_where}) AS domain_snapshots,
            (SELECT COUNT(*) FROM player_profile_snapshots p {profile_where}) AS profile_snapshots,
            (SELECT COUNT(*) FROM player_resource_snapshots res {resource_where}) AS resource_snapshots,
            (SELECT MAX(captured_at) FROM game_domain_snapshots d {domain_where}) AS latest_capture
        """
    )
    params = {**raw_params, **domain_params, **profile_params, **resource_params}

    async with db_manager.engine.connect() as connection:
        result = (await connection.execute(query, params)).one()._mapping
        return dict(result)


async def fetch_domain_summary(
    db_manager: DatabaseManager,
    player_id: str = ALL_CONTEXT,
    world_id: str = ALL_CONTEXT,
) -> list[dict[str, Any]]:
    """Return per-domain counts based on universal snapshots."""

    where_clause, params = _build_filter("d", player_id, world_id)
    query = text(
        f"""
        SELECT
            d.domain,
            COUNT(*) AS events,
            COUNT(DISTINCT d.service_name || '.' || COALESCE(d.method_name, '(unknown)')) AS services,
            MAX(d.captured_at) AS last_seen
        FROM game_domain_snapshots d
        {where_clause}
        GROUP BY d.domain
        ORDER BY events DESC, d.domain ASC
        """
    )

    async with db_manager.engine.connect() as connection:
        result = await connection.execute(query, params)
        return [dict(row._mapping) for row in result]


async def fetch_service_catalog(
    db_manager: DatabaseManager,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return discovered service/method pairs."""

    query = text(
        """
        SELECT domain, service_name, method_name, total_seen, first_seen_at, last_seen_at
        FROM service_catalog
        ORDER BY total_seen DESC, last_seen_at DESC
        LIMIT :limit
        """
    )

    async with db_manager.engine.connect() as connection:
        result = await connection.execute(query, {"limit": limit})
        return [dict(row._mapping) for row in result]


async def fetch_latest_player_profiles(
    db_manager: DatabaseManager,
    player_id: str = ALL_CONTEXT,
    world_id: str = ALL_CONTEXT,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return the latest plausible player profiles."""

    where_clause, params = _build_filter("p", player_id, world_id)
    params["limit"] = limit
    query = text(
        f"""
        SELECT
            p.observed_at,
            p.player_id,
            COALESCE(identity.player_name, p.player_name) AS player_name,
            p.world_id,
            p.guild_name,
            p.era
        FROM player_profile_snapshots p
        LEFT JOIN player_identities identity
          ON identity.player_id = p.player_id
         AND identity.world_id = p.world_id
        {where_clause}
          AND p.player_id ~ '^[0-9]+$'
        ORDER BY p.observed_at DESC
        LIMIT :limit
        """
    )

    async with db_manager.engine.connect() as connection:
        result = await connection.execute(query, params)
        return [dict(row._mapping) for row in result]


async def fetch_player_identities(
    db_manager: DatabaseManager,
    player_id: str = ALL_CONTEXT,
    world_id: str = ALL_CONTEXT,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return current canonical player identities."""

    where_clause, params = _build_filter("p", player_id, world_id)
    params["limit"] = limit
    query = text(
        f"""
        SELECT
            p.last_seen_at,
            p.player_id,
            p.player_name,
            p.world_id,
            p.guild_name,
            p.era,
            p.source_service,
            p.source_method
        FROM player_identities p
        {where_clause}
        ORDER BY p.last_seen_at DESC
        LIMIT :limit
        """
    )

    async with db_manager.engine.connect() as connection:
        result = await connection.execute(query, params)
        return [dict(row._mapping) for row in result]


async def fetch_wallet_candidates(
    db_manager: DatabaseManager,
    player_id: str = ALL_CONTEXT,
    world_id: str = ALL_CONTEXT,
) -> list[dict[str, Any]]:
    """Return latest known values for core wallet-like resources."""

    where_clause, params = _build_filter("res", player_id, world_id)
    query = text(
        f"""
        SELECT DISTINCT ON (LOWER(res.resource_name))
            res.observed_at,
            res.player_id,
            identity.player_name,
            res.world_id,
            res.resource_name,
            res.amount,
            res.source_service,
            res.source_method
        FROM player_resource_snapshots res
        LEFT JOIN player_identities identity
          ON identity.player_id = res.player_id
         AND identity.world_id = res.world_id
        {where_clause}
          AND LOWER(res.resource_name) IN (
              'money',
              'coins',
              'coin',
              'supplies',
              'supply',
              'strategy_points',
              'forge_points',
              'forgepoints',
              'premium',
              'diamonds',
              'medals',
              'population',
              'happiness'
          )
        ORDER BY LOWER(res.resource_name), res.observed_at DESC
        """
    )

    async with db_manager.engine.connect() as connection:
        result = await connection.execute(query, params)
        return [dict(row._mapping) for row in result]


async def fetch_wallet_balances(
    db_manager: DatabaseManager,
    player_id: str = ALL_CONTEXT,
    world_id: str = ALL_CONTEXT,
) -> list[dict[str, Any]]:
    """Return current consolidated wallet balances."""

    where_clause, params = _build_filter("w", player_id, world_id)
    query = text(
        f"""
        SELECT
            w.last_seen_at,
            w.player_id,
            identity.player_name,
            w.world_id,
            w.resource_name,
            w.amount_text AS amount,
            w.source_service,
            w.source_method
        FROM player_wallet_balances w
        LEFT JOIN player_identities identity
          ON identity.player_id = w.player_id
         AND identity.world_id = w.world_id
        {where_clause}
        ORDER BY w.resource_name ASC
        """
    )

    async with db_manager.engine.connect() as connection:
        result = await connection.execute(query, params)
        return [dict(row._mapping) for row in result]


async def fetch_wallet_history(
    db_manager: DatabaseManager,
    player_id: str = ALL_CONTEXT,
    world_id: str = ALL_CONTEXT,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return recent consolidated wallet observations with deltas."""

    where_clause, params = _build_filter("w", player_id, world_id)
    params["limit"] = limit
    query = text(
        f"""
        SELECT
            w.observed_at,
            w.player_id,
            identity.player_name,
            w.world_id,
            w.resource_name,
            w.amount_text AS amount,
            w.delta_amount,
            w.source_service,
            w.source_method
        FROM player_wallet_snapshots w
        LEFT JOIN player_identities identity
          ON identity.player_id = w.player_id
         AND identity.world_id = w.world_id
        {where_clause}
        ORDER BY w.observed_at DESC
        LIMIT :limit
        """
    )

    async with db_manager.engine.connect() as connection:
        result = await connection.execute(query, params)
        return [dict(row._mapping) for row in result]


async def fetch_latest_resources(
    db_manager: DatabaseManager,
    player_id: str = ALL_CONTEXT,
    world_id: str = ALL_CONTEXT,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return recent generic resource snapshots."""

    where_clause, params = _build_filter("res", player_id, world_id)
    params["limit"] = limit
    query = text(
        f"""
        SELECT
            res.observed_at,
            res.player_id,
            identity.player_name,
            res.world_id,
            res.resource_name,
            res.amount,
            res.source_service,
            res.source_method
        FROM player_resource_snapshots res
        LEFT JOIN player_identities identity
          ON identity.player_id = res.player_id
         AND identity.world_id = res.world_id
        {where_clause}
          AND res.source_service NOT IN ('BattlefieldService', 'ArmyUnitManagementService')
        ORDER BY res.observed_at DESC
        LIMIT :limit
        """
    )

    async with db_manager.engine.connect() as connection:
        result = await connection.execute(query, params)
        return [dict(row._mapping) for row in result]


async def fetch_overview(
    db_manager: DatabaseManager,
    player_id: str = ALL_CONTEXT,
    world_id: str = ALL_CONTEXT,
) -> dict[str, Any]:
    """Return Phase 1 CBG counters for the selected context."""

    sector_where, sector_params = _build_filter("s", player_id, world_id)
    action_where, action_params = _build_filter("a", player_id, world_id)
    event_where, event_params = _build_filter("e", player_id, world_id)
    event_where = f"{event_where} AND e.service_name = :service_name"
    event_params["service_name"] = "GuildBattlegroundService"

    sector_query = text(
        f"""
        SELECT
            COUNT(*) AS sector_snapshots,
            COUNT(DISTINCT s.sector_id) AS tracked_sectors
        FROM cbg_sector_snapshots s
        {sector_where}
        """
    )
    action_query = text(
        f"""
        SELECT
            COUNT(*) AS total_actions,
            COUNT(*) FILTER (WHERE a.action_type = 'battle') AS battles,
            COUNT(*) FILTER (WHERE a.action_type = 'negotiation') AS negotiations
        FROM cbg_personal_actions a
        {action_where}
        """
    )
    raw_query = text(
        f"""
        SELECT COUNT(*) AS cbg_packets
        FROM routed_service_events e
        {event_where}
        """
    )

    async with db_manager.engine.connect() as connection:
        sector_result = (await connection.execute(sector_query, sector_params)).one()._mapping
        action_result = (await connection.execute(action_query, action_params)).one()._mapping
        raw_result = (await connection.execute(raw_query, event_params)).one()._mapping

    return {
        "cbg_packets": raw_result["cbg_packets"],
        "sector_snapshots": sector_result["sector_snapshots"],
        "tracked_sectors": sector_result["tracked_sectors"],
        "total_actions": action_result["total_actions"],
        "battles": action_result["battles"],
        "negotiations": action_result["negotiations"],
    }


async def fetch_latest_sectors(
    db_manager: DatabaseManager,
    player_id: str = ALL_CONTEXT,
    world_id: str = ALL_CONTEXT,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return the latest known snapshot for each tracked sector."""

    where_clause, params = _build_filter("s", player_id, world_id)
    params["limit"] = limit

    query = text(
        f"""
        SELECT *
        FROM (
            SELECT DISTINCT ON (s.player_id, s.world_id, s.sector_id)
                s.captured_at,
                s.player_id,
                identity.player_name,
                s.world_id,
                s.sector_id,
                s.province_id,
                s.owner_guild_name,
                s.owner_guild_id,
                s.state,
                s.victory_points,
                s.max_victory_points
            FROM cbg_sector_snapshots s
            LEFT JOIN player_identities identity
              ON identity.player_id = s.player_id
             AND identity.world_id = s.world_id
            {where_clause}
            ORDER BY s.player_id, s.world_id, s.sector_id, s.captured_at DESC
        ) latest
        ORDER BY captured_at DESC
        LIMIT :limit
        """
    )

    async with db_manager.engine.connect() as connection:
        result = await connection.execute(query, params)
        return [dict(row._mapping) for row in result]


async def fetch_recent_actions(
    db_manager: DatabaseManager,
    player_id: str = ALL_CONTEXT,
    world_id: str = ALL_CONTEXT,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return recent personal CBG actions."""

    where_clause, params = _build_filter("a", player_id, world_id)
    params["limit"] = limit

    query = text(
        f"""
        SELECT
            a.occurred_at,
            a.player_id,
            identity.player_name,
            a.world_id,
            a.action_type,
            a.result,
            a.sector_id,
            a.province_id,
            a.attrition,
            a.service_method
        FROM cbg_personal_actions a
        LEFT JOIN player_identities identity
          ON identity.player_id = a.player_id
         AND identity.world_id = a.world_id
        {where_clause}
        ORDER BY a.occurred_at DESC
        LIMIT :limit
        """
    )

    async with db_manager.engine.connect() as connection:
        result = await connection.execute(query, params)
        return [dict(row._mapping) for row in result]


def _build_filter(alias: str, player_id: str, world_id: str) -> tuple[str, dict[str, Any]]:
    clauses = ["1 = 1"]
    params: dict[str, Any] = {}

    if player_id != ALL_CONTEXT:
        clauses.append(f"{alias}.player_id = :player_id")
        params["player_id"] = player_id

    if world_id != ALL_CONTEXT:
        clauses.append(f"{alias}.world_id = :world_id")
        params["world_id"] = world_id

    return f"WHERE {' AND '.join(clauses)}", params
