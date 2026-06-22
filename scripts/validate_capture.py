"""Validate whether real FoE traffic is being captured into PostgreSQL."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import asyncpg

REQUIRED_TABLES = (
    "raw_packets",
    "routed_service_events",
    "service_catalog",
    "game_domain_snapshots",
    "player_profile_snapshots",
    "player_resource_snapshots",
    "player_identities",
    "player_identity_snapshots",
    "player_wallet_balances",
    "player_wallet_snapshots",
    "cbg_sector_snapshots",
    "cbg_personal_actions",
)


def main() -> None:
    load_env(PROJECT_ROOT / ".env")
    database_url = normalize_database_url(
        os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://foe_analytics:foe_analytics_dev@localhost:5432/foe_analytics",
        )
    )
    asyncio.run(validate_database(database_url))


async def validate_database(database_url: str) -> None:
    try:
        connection = await asyncpg.connect(database_url, timeout=5)
    except Exception as exc:
        print(f"DB_CONNECTION=FAIL {exc}")
        return

    try:
        await connection.set_type_codec(
            "jsonb",
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )

        print("DB_CONNECTION=OK")
        existing_tables = {
            row["table_name"]
            for row in await connection.fetch(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = ANY($1::text[])
                """,
                list(REQUIRED_TABLES),
            )
        }

        missing_tables = [table for table in REQUIRED_TABLES if table not in existing_tables]
        if missing_tables:
            print(f"SCHEMA=FAIL missing={', '.join(missing_tables)}")
            return
        print("SCHEMA=OK")

        raw_count = await fetch_count(connection, "raw_packets")
        routed_count = await fetch_count(connection, "routed_service_events")
        sector_count = await fetch_count(connection, "cbg_sector_snapshots")
        action_count = await fetch_count(connection, "cbg_personal_actions")
        catalog_count = await fetch_count(connection, "service_catalog")
        domain_snapshot_count = await fetch_count(connection, "game_domain_snapshots")
        profile_count = await fetch_count(connection, "player_profile_snapshots")
        resource_count = await fetch_count(connection, "player_resource_snapshots")
        identity_count = await fetch_count(connection, "player_identities")
        identity_snapshot_count = await fetch_count(connection, "player_identity_snapshots")
        wallet_balance_count = await fetch_count(connection, "player_wallet_balances")
        wallet_snapshot_count = await fetch_count(connection, "player_wallet_snapshots")
        cbg_count = await connection.fetchval(
            """
            SELECT COUNT(*)
            FROM routed_service_events
            WHERE service_name = 'GuildBattlegroundService'
            """
        )
        latest_raw = await connection.fetchval("SELECT MAX(captured_at) FROM raw_packets")
        latest_cbg = await connection.fetchval(
            """
            SELECT MAX(captured_at)
            FROM routed_service_events
            WHERE service_name = 'GuildBattlegroundService'
            """
        )

        print(f"RAW_PACKETS={raw_count}")
        print(f"ROUTED_SERVICE_EVENTS={routed_count}")
        print(f"CBG_SERVICE_EVENTS={int(cbg_count or 0)}")
        print(f"CBG_SECTOR_SNAPSHOTS={sector_count}")
        print(f"CBG_PERSONAL_ACTIONS={action_count}")
        print(f"SERVICE_CATALOG={catalog_count}")
        print(f"GAME_DOMAIN_SNAPSHOTS={domain_snapshot_count}")
        print(f"PLAYER_PROFILE_SNAPSHOTS={profile_count}")
        print(f"PLAYER_RESOURCE_SNAPSHOTS={resource_count}")
        print(f"PLAYER_IDENTITIES={identity_count}")
        print(f"PLAYER_IDENTITY_SNAPSHOTS={identity_snapshot_count}")
        print(f"PLAYER_WALLET_BALANCES={wallet_balance_count}")
        print(f"PLAYER_WALLET_SNAPSHOTS={wallet_snapshot_count}")
        print(f"LATEST_RAW_PACKET={latest_raw}")
        print(f"LATEST_CBG_EVENT={latest_cbg}")

        top_services = await connection.fetch(
            """
            SELECT service_name, method_name, COUNT(*) AS total, MAX(captured_at) AS last_seen
            FROM routed_service_events
            GROUP BY service_name, method_name
            ORDER BY total DESC, last_seen DESC
            LIMIT 15
            """
        )
        print("TOP_SERVICES:")
        if not top_services:
            print("  none")
        for row in top_services:
            method_name = row["method_name"] or "(unknown)"
            print(f"  {row['service_name']}.{method_name} total={row['total']} last={row['last_seen']}")

        if raw_count > 0 and routed_count > 0:
            print("CAPTURE_STATUS=OK")
        elif raw_count > 0:
            print("CAPTURE_STATUS=PARTIAL raw packets captured, but no routed service events")
        else:
            print("CAPTURE_STATUS=EMPTY no packets captured yet")
    finally:
        await connection.close()


async def fetch_count(connection: asyncpg.Connection, table_name: str) -> int:
    value = await connection.fetchval(f"SELECT COUNT(*) FROM {table_name}")
    return int(value or 0)


def load_env(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def normalize_database_url(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


if __name__ == "__main__":
    main()
