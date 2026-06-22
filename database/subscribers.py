"""Database-backed event subscribers."""

from __future__ import annotations

import logging

from core_events.dispatcher import EventDispatcher, RAW_PACKET_EVENT
from core_events.event_types import Event
from database.db_manager import DatabaseManager
from database.repositories import RawPacketRepository

LOGGER = logging.getLogger(__name__)


class RawPacketRecorder:
    """Subscriber that persists every routed packet into the JSONB data lake."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self._db_manager = db_manager

    def register(self, dispatcher: EventDispatcher) -> None:
        """Subscribe the recorder to all routed packet events."""

        dispatcher.subscribe(RAW_PACKET_EVENT, self.handle_event)

    async def handle_event(self, event: Event) -> None:
        """Persist a routed event without interrupting other subscribers."""

        async with self._db_manager.session() as session:
            await RawPacketRepository(session).save_event(event)
