"""Inspect captured FoE traffic and export real service payload samples."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import asyncpg

DEFAULT_SERVICE = "GuildBattlegroundService"


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect FoE Analytics captured traffic.")
    parser.add_argument("--service", default=DEFAULT_SERVICE, help="Service name to export.")
    parser.add_argument("--limit", type=int, default=5, help="Number of samples to export.")
    parser.add_argument(
        "--no-export",
        action="store_true",
        help="Only print counts; do not write payload samples.",
    )
    args = parser.parse_args()

    load_env(PROJECT_ROOT / ".env")
    database_url = normalize_database_url(
        os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://foe_analytics:foe_analytics_dev@localhost:5432/foe_analytics",
        )
    )
    asyncio.run(inspect_capture(database_url, args.service, args.limit, not args.no_export))


async def inspect_capture(
    database_url: str,
    service_name: str,
    sample_limit: int,
    export_samples: bool,
) -> None:
    connection = await asyncpg.connect(database_url)
    try:
        await connection.set_type_codec(
            "jsonb",
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )

        raw_count = await safe_fetchval(connection, "SELECT COUNT(*) FROM raw_packets")
        routed_count = await safe_fetchval(connection, "SELECT COUNT(*) FROM routed_service_events")
        print(f"Raw packets: {raw_count}")
        print(f"Routed service events: {routed_count}")

        print("\nTop services:")
        service_rows = await safe_fetch(
            connection,
            """
            SELECT service_name, method_name, COUNT(*) AS total, MAX(captured_at) AS last_seen
            FROM routed_service_events
            GROUP BY service_name, method_name
            ORDER BY total DESC, last_seen DESC
            LIMIT 30
            """,
        )
        if not service_rows:
            print("  No routed services captured yet.")
        for row in service_rows:
            method = row["method_name"] or "(unknown method)"
            print(f"  {row['service_name']}.{method}: {row['total']} last={row['last_seen']}")

        print(f"\nLatest {service_name} samples:")
        samples = await safe_fetch(
            connection,
            """
            SELECT request_id, method_name, player_id, world_id, captured_at, service_payload
            FROM routed_service_events
            WHERE service_name = $1
            ORDER BY captured_at DESC
            LIMIT $2
            """,
            service_name,
            sample_limit,
        )
        if not samples:
            print("  No samples for this service yet.")
            return

        output_dir = PROJECT_ROOT / "capture_samples" / safe_filename(service_name)
        if export_samples:
            output_dir.mkdir(parents=True, exist_ok=True)

        for index, row in enumerate(samples, start=1):
            print(
                "  "
                f"{index}. method={row['method_name']} "
                f"world={row['world_id']} player={row['player_id']} "
                f"captured={row['captured_at']}"
            )
            if export_samples:
                filename = build_sample_filename(row["captured_at"], row["method_name"], row["request_id"])
                target = output_dir / filename
                target.write_text(
                    json.dumps(
                        {
                            "request_id": row["request_id"],
                            "service_name": service_name,
                            "method_name": row["method_name"],
                            "player_id": row["player_id"],
                            "world_id": row["world_id"],
                            "captured_at": str(row["captured_at"]),
                            "service_payload": row["service_payload"],
                        },
                        ensure_ascii=False,
                        indent=2,
                        default=str,
                    ),
                    encoding="utf-8",
                )
                print(f"     exported={target}")
    finally:
        await connection.close()


async def safe_fetchval(connection: asyncpg.Connection, query: str, *args: Any) -> int:
    try:
        value = await connection.fetchval(query, *args)
    except asyncpg.UndefinedTableError:
        return 0
    return int(value or 0)


async def safe_fetch(connection: asyncpg.Connection, query: str, *args: Any) -> list[asyncpg.Record]:
    try:
        return list(await connection.fetch(query, *args))
    except asyncpg.UndefinedTableError:
        return []


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


def build_sample_filename(captured_at: datetime, method_name: str | None, request_id: str) -> str:
    timestamp = captured_at.strftime("%Y%m%d_%H%M%S") if captured_at else "unknown_time"
    method = safe_filename(method_name or "unknown_method")
    request = safe_filename(request_id)[:12]
    return f"{timestamp}_{method}_{request}.json"


def safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "unknown"


if __name__ == "__main__":
    main()

