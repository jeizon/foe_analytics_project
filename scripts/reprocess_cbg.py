"""Rebuild CBG derived tables from already captured routed service events."""

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

from core_events.event_types import CapturedPacket, Event, EventType, UNKNOWN_CONTEXT
from core_events.packet_router import extract_player_context
from database.db_manager import DatabaseManager
from database.repositories import CbgRepository
from modules.cbg_tracker.mapper import (
    BATTLEFIELD_SERVICE_EVENT_NAME,
    BATTLEFIELD_SERVICE_NAME,
    SERVICE_EVENT_NAME,
    SERVICE_NAME,
    map_cbg_event,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Reprocess CBG derived tables.")
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="Do not clear existing CBG derived tables before reprocessing.",
    )
    args = parser.parse_args()

    load_env(PROJECT_ROOT / ".env")
    asyncio.run(reprocess_cbg(clear_existing=not args.keep_existing))


async def reprocess_cbg(clear_existing: bool) -> None:
    db_manager = DatabaseManager()
    try:
        await db_manager.create_schema()
        async with db_manager.session() as session:
            if clear_existing:
                await session.execute(text("DELETE FROM cbg_personal_actions"))
                await session.execute(text("DELETE FROM cbg_sector_snapshots"))

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
                    WHERE service_name IN (:guild_battleground_service, :battlefield_service)
                    ORDER BY captured_at ASC
                    """
                ),
                {
                    "guild_battleground_service": SERVICE_NAME,
                    "battlefield_service": BATTLEFIELD_SERVICE_NAME,
                },
            )
            rows = result.mappings().all()
            repository = CbgRepository(session)

            mapped_events = 0
            sector_snapshots = 0
            personal_actions = 0

            for row in rows:
                mapping = map_cbg_event(_row_to_event(row))
                if not mapping.has_data:
                    continue

                await repository.save_mapping(mapping)
                mapped_events += 1
                sector_snapshots += len(mapping.sector_snapshots)
                personal_actions += len(mapping.personal_actions)

        print(f"CBG routed events scanned: {len(rows)}")
        print(f"CBG events mapped: {mapped_events}")
        print(f"CBG sector snapshots rebuilt: {sector_snapshots}")
        print(f"CBG personal actions rebuilt: {personal_actions}")
    finally:
        await db_manager.dispose()


def _row_to_event(row: Any) -> Event:
    payload = row["service_payload"]
    player_id = row["player_id"]
    if player_id == UNKNOWN_CONTEXT:
        player_id = extract_player_context(payload) or UNKNOWN_CONTEXT

    packet = CapturedPacket(
        payload=payload,
        endpoint=row["endpoint"],
        http_method=row["http_method"],
        status_code=row["status_code"],
        player_id=player_id,
        world_id=row["world_id"],
        request_id=row["request_id"],
        captured_at=row["captured_at"],
    )
    event_name = (
        BATTLEFIELD_SERVICE_EVENT_NAME
        if row["service_name"] == BATTLEFIELD_SERVICE_NAME
        else SERVICE_EVENT_NAME
    )
    return Event(
        name=event_name,
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
