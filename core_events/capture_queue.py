"""Central non-blocking queue for raw packets captured by mitmproxy."""

from __future__ import annotations

import asyncio
import logging

from core_events.event_types import CapturedPacket

LOGGER = logging.getLogger(__name__)


class CaptureQueue:
    """Absorbs captured packets before routing and event dispatch.

    The mitmproxy addon only attempts a non-blocking enqueue into this queue.
    Packet routing and subscriber dispatch run in independent background tasks,
    keeping browser traffic isolated from analytics load.
    """

    def __init__(self, maxsize: int = 50_000) -> None:
        self._queue: asyncio.Queue[CapturedPacket] = asyncio.Queue(maxsize=maxsize)

    @property
    def queue_size(self) -> int:
        """Return the number of packets waiting to be routed."""

        return self._queue.qsize()

    async def enqueue(self, packet: CapturedPacket) -> None:
        """Enqueue a packet with async backpressure."""

        await self._queue.put(packet)

    def enqueue_nowait(self, packet: CapturedPacket) -> bool:
        """Enqueue a packet without blocking the caller."""

        try:
            self._queue.put_nowait(packet)
        except asyncio.QueueFull:
            LOGGER.warning("Capture queue full; dropped packet %s", packet.request_id)
            return False
        return True

    async def get(self) -> CapturedPacket:
        """Wait for and return the next captured packet."""

        return await self._queue.get()

    def task_done(self) -> None:
        """Mark the current packet as routed."""

        self._queue.task_done()

    async def join(self) -> None:
        """Wait until all queued packets have been routed."""

        await self._queue.join()

