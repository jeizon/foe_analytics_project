"""Player identity subscriber."""

from __future__ import annotations

from core_events.dispatcher import EventDispatcher, RAW_PACKET_EVENT
from core_events.event_types import Event
from database.db_manager import DatabaseManager
from database.repositories import PlayerCoreRepository
from modules.player_core.mapper import map_player_identity_event


class PlayerCoreSubscriber:
    """Subscriber that maintains canonical player identity records."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self._db_manager = db_manager

    def register(self, dispatcher: EventDispatcher) -> None:
        """Subscribe to the routed event stream."""

        dispatcher.subscribe(RAW_PACKET_EVENT, self.handle_event)

    async def handle_event(self, event: Event) -> None:
        """Persist player identity facts from a routed event."""

        if not event.service_name:
            return

        mapping = map_player_identity_event(event)
        if not mapping.identity:
            return

        async with self._db_manager.session() as session:
            await PlayerCoreRepository(session).save_mapping(mapping)
