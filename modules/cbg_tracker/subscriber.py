"""CBG tracker event subscriber."""

from __future__ import annotations

import logging

from core_events.dispatcher import EventDispatcher
from core_events.event_types import Event
from database.db_manager import DatabaseManager
from database.repositories import CbgRepository
from modules.cbg_tracker.mapper import BATTLEFIELD_SERVICE_EVENT_NAME, SERVICE_EVENT_NAME, map_cbg_event

LOGGER = logging.getLogger(__name__)


class CbgTrackerSubscriber:
    """Subscriber for GuildBattlegroundService packets."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self._db_manager = db_manager

    def register(self, dispatcher: EventDispatcher) -> None:
        """Subscribe the tracker to GuildBattlegroundService events."""

        dispatcher.subscribe(SERVICE_EVENT_NAME, self.handle_event)
        dispatcher.subscribe(BATTLEFIELD_SERVICE_EVENT_NAME, self.handle_event)

    async def handle_event(self, event: Event) -> None:
        """Map and persist CBG facts from a service packet."""

        mapping = map_cbg_event(event)
        if not mapping.has_data:
            return

        async with self._db_manager.session() as session:
            await CbgRepository(session).save_mapping(mapping)

        LOGGER.debug(
            "Persisted CBG packet request_id=%s sectors=%s actions=%s",
            mapping.request_id,
            len(mapping.sector_snapshots),
            len(mapping.personal_actions),
        )
