"""Universal game-state subscriber."""

from __future__ import annotations

from core_events.dispatcher import EventDispatcher, RAW_PACKET_EVENT
from core_events.event_types import Event
from database.db_manager import DatabaseManager
from database.repositories import GameStateRepository
from modules.game_state.mapper import map_game_state_event


class GameStateSubscriber:
    """Subscriber that organizes every routed service event by game domain."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self._db_manager = db_manager

    def register(self, dispatcher: EventDispatcher) -> None:
        """Subscribe to the raw event stream after routing."""

        dispatcher.subscribe(RAW_PACKET_EVENT, self.handle_event)

    async def handle_event(self, event: Event) -> None:
        """Persist generic game-state facts from a routed event."""

        if not event.service_name:
            return

        mapping = map_game_state_event(event)
        async with self._db_manager.session() as session:
            await GameStateRepository(session).save_mapping(mapping)

