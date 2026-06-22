"""Asynchronous Pub/Sub dispatcher for FoE analytics events."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable

from core_events.event_types import Event

Subscriber = Callable[[Event], Awaitable[None] | None]

LOGGER = logging.getLogger(__name__)

WILDCARD_EVENT = "*"
RAW_PACKET_EVENT = "packet.raw"
UNKNOWN_PACKET_EVENT = "packet.unknown"
SERVICE_EVENT_PREFIX = "service."


class EventDispatcher:
    """Delivers classified events to independent subscribers.

    The dispatcher does not inspect FoE packet payloads. The Packet Router
    classifies captured packets first, then publishes concrete events here.
    Service modules subscribe to names such as
    ``service.GuildBattlegroundService``.
    """

    def __init__(self, queue_maxsize: int = 10_000) -> None:
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=queue_maxsize)
        self._subscribers: dict[str, list[Subscriber]] = defaultdict(list)
        self._workers: list[asyncio.Task[None]] = []
        self._running = False

    @property
    def queue_size(self) -> int:
        """Return the number of events waiting to be delivered."""

        return self._queue.qsize()

    def subscribe(self, event_name: str, callback: Subscriber) -> None:
        """Register a subscriber for a specific event name."""

        if callback in self._subscribers[event_name]:
            return
        self._subscribers[event_name].append(callback)

    def unsubscribe(self, event_name: str, callback: Subscriber) -> None:
        """Remove a subscriber from an event name if it is registered."""

        if callback in self._subscribers[event_name]:
            self._subscribers[event_name].remove(callback)

    async def start(self, worker_count: int = 2) -> None:
        """Start background delivery workers."""

        if self._running:
            return

        self._running = True
        self._workers = [
            asyncio.create_task(self._worker(worker_id), name=f"foe-dispatcher-{worker_id}")
            for worker_id in range(worker_count)
        ]

    async def stop(self) -> None:
        """Drain pending events and stop all workers."""

        if not self._running:
            return

        await self._queue.join()
        self._running = False

        for worker in self._workers:
            worker.cancel()

        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    async def publish(self, event: Event) -> None:
        """Enqueue a classified event, applying async backpressure."""

        await self._queue.put(event)

    def publish_nowait(self, event: Event) -> bool:
        """Enqueue a classified event without blocking the caller.

        Returns ``False`` when the dispatch queue is full.
        """

        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            LOGGER.warning(
                "Dispatcher queue full; dropped event %s request_id=%s",
                event.name,
                event.packet.request_id,
            )
            return False
        return True

    async def _worker(self, worker_id: int) -> None:
        while self._running:
            event = await self._queue.get()
            try:
                await self._deliver(event)
            except Exception:
                LOGGER.exception("Dispatcher worker %s failed while delivering event", worker_id)
            finally:
                self._queue.task_done()

    async def _deliver(self, event: Event) -> None:
        callbacks = [
            *self._subscribers.get(WILDCARD_EVENT, []),
            *self._subscribers.get(RAW_PACKET_EVENT, []),
            *self._subscribers.get(event.name, []),
        ]

        for callback in callbacks:
            try:
                result = callback(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                LOGGER.exception(
                    "Subscriber failed for event %s request_id=%s",
                    event.name,
                    event.packet.request_id,
                )
