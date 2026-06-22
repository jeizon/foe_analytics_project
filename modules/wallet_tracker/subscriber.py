"""Wallet tracker subscriber."""

from __future__ import annotations

from core_events.dispatcher import EventDispatcher, RAW_PACKET_EVENT
from core_events.event_types import Event
from database.db_manager import DatabaseManager
from database.repositories import WalletRepository
from modules.wallet_tracker.mapper import map_wallet_event


class WalletTrackerSubscriber:
    """Subscriber that maintains consolidated wallet balances."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self._db_manager = db_manager

    def register(self, dispatcher: EventDispatcher) -> None:
        """Subscribe to the routed event stream."""

        dispatcher.subscribe(RAW_PACKET_EVENT, self.handle_event)

    async def handle_event(self, event: Event) -> None:
        """Persist wallet facts from a routed event."""

        if not event.service_name:
            return

        mapping = map_wallet_event(event)
        if not mapping.resources:
            return

        async with self._db_manager.session() as session:
            await WalletRepository(session).save_mapping(mapping)
