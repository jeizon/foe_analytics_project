"""Rebuild consolidated player identity and wallet tables from routed events."""

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
from database.repositories import PlayerCoreRepository, WalletRepository
from modules.player_core.mapper import map_player_identity_event
from modules.wallet_tracker.mapper import map_wallet_event


def main() -> None:
    parser = argparse.ArgumentParser(description="Reprocess consolidated FoE module tables.")
    parser.add_argument("--keep-existing", action="store_true")
    args = parser.parse_args()

    load_env(PROJECT_ROOT / ".env")
    asyncio.run(reprocess_consolidated(clear_existing=not args.keep_existing))


async def reprocess_consolidated(clear_existing: bool) -> None:
    db_manager = DatabaseManager()
    try:
        await db_manager.create_schema()
        async with db_manager.session() as session:
            if clear_existing:
                for table_name in (
                    "player_wallet_snapshots",
                    "player_wallet_balances",
                    "player_identity_snapshots",
                    "player_identities",
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
            player_repository = PlayerCoreRepository(session)
            wallet_repository = WalletRepository(session)

            identities = 0
            wallet_records = 0
            for row in rows:
                event = _row_to_event(row)

                player_mapping = map_player_identity_event(event)
                if player_mapping.identity:
                    identities += 1
                    await player_repository.save_mapping(player_mapping)

                wallet_mapping = map_wallet_event(event)
                if wallet_mapping.resources:
                    wallet_records += len(wallet_mapping.resources)
                    await wallet_repository.save_mapping(wallet_mapping)

        print(f"Routed events scanned: {len(rows)}")
        print(f"Identity observations rebuilt: {identities}")
        print(f"Wallet observations rebuilt: {wallet_records}")
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
