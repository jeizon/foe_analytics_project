"""Rebuild universal game-state tables from routed service events."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import text

from core_events.event_types import CapturedPacket, Event, EventType
from database.db_manager import DatabaseManager
from database.repositories import GameStateRepository
from modules.game_state.mapper import map_game_state_event


def main() -> None:
    parser = argparse.ArgumentParser(description="Reprocess universal game-state tables.")
    parser.add_argument("--keep-existing", action="store_true")
    args = parser.parse_args()

    load_env(PROJECT_ROOT / ".env")
    asyncio.run(reprocess_game_state(clear_existing=not args.keep_existing))


async def reprocess_game_state(clear_existing: bool) -> None:
    db_manager = DatabaseManager()
    try:
        await db_manager.create_schema()
        async with db_manager.session() as session:
            if clear_existing:
                for table_name in (
                    "player_resource_snapshots",
                    "player_profile_snapshots",
                    "game_domain_snapshots",
                    "service_catalog",
                ):
                    await session.execute(text(f"DELETE FROM {table_name}"))

            result = await session.execute(
                text(
                    """
                    SELECT
                        request_id,
                        player_id,
                        world_id,
                        service_name,
                        method_name,
                        endpoint,
                        http_method,
                        status_code,
                        service_payload,
                        captured_at
                    FROM routed_service_events
                    ORDER BY captured_at ASC
                    """
                )
            )
            rows = result.mappings().all()
            repository = GameStateRepository(session)

            profiles = 0
            resources = 0
            for row in rows:
                mapping = map_game_state_event(_row_to_event(row))
                if mapping.player_profile:
                    profiles += 1
                resources += len(mapping.resource_snapshots)
                await repository.save_mapping(mapping)

        print(f"Routed events scanned: {len(rows)}")
        print(f"Profile snapshots rebuilt: {profiles}")
        print(f"Resource snapshots rebuilt: {resources}")
    finally:
        await db_manager.dispose()


def _row_to_event(row: Any) -> Event:
    payload = row["service_payload"]
    packet = CapturedPacket(
        payload=payload,
        endpoint=row["endpoint"],
        http_method=row["http_method"],
        status_code=row["status_code"],
        player_id=row["player_id"],
        world_id=row["world_id"],
        request_id=row["request_id"],
        captured_at=row["captured_at"],
    )
    return Event(
        name=f"service.{row['service_name']}",
        event_type=EventType.SERVICE_PACKET_RECEIVED,
        packet=packet,
        service_name=row["service_name"],
        method_name=row["method_name"],
        payload=payload,
    )


def load_env(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


if __name__ == "__main__":
    main()

