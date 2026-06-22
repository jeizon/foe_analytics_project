"""mitmproxy addon for passive FoE traffic capture.

Run from the project root with:

    mitmproxy -s proxy_interceptor/mitm_addon.py

This addon does no domain processing. It decodes JSON responses, wraps them in
an immutable packet envelope, and enqueues them into the central capture queue.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mitmproxy import ctx, http

from core_events.capture_queue import CaptureQueue
from core_events.dispatcher import EventDispatcher
from core_events.event_types import CapturedPacket, UNKNOWN_CONTEXT
from core_events.packet_router import PacketRouter
from database.db_manager import DEFAULT_DATABASE_URL, DatabaseManager
from database.subscribers import RawPacketRecorder
from modules.cbg_tracker.subscriber import CbgTrackerSubscriber
from modules.game_state.subscriber import GameStateSubscriber
from modules.player_core.subscriber import PlayerCoreSubscriber
from modules.wallet_tracker.subscriber import WalletTrackerSubscriber
from proxy_interceptor.payload_cleaner import decode_json_body, is_json_response

LOGGER = logging.getLogger(__name__)


class FoeAnalyticsAddon:
    """Passive mitmproxy addon that publishes captured JSON to CaptureQueue."""

    def __init__(self) -> None:
        self.capture_queue = CaptureQueue()
        self.dispatcher = EventDispatcher()
        self.packet_router = PacketRouter(self.capture_queue, self.dispatcher)
        self.database: DatabaseManager | None = None
        self.raw_packet_recorder: RawPacketRecorder | None = None
        self.cbg_tracker: CbgTrackerSubscriber | None = None
        self.game_state: GameStateSubscriber | None = None
        self.player_core: PlayerCoreSubscriber | None = None
        self.wallet_tracker: WalletTrackerSubscriber | None = None
        self._database_subscribers_registered = False

    def load(self, loader) -> None:  # noqa: ANN001
        """Declare addon options visible in mitmproxy."""

        loader.add_option(
            name="foe_capture_queue_size",
            typespec=int,
            default=50_000,
            help="Maximum number of captured packets waiting for routing.",
        )
        loader.add_option(
            name="foe_packet_router_workers",
            typespec=int,
            default=2,
            help="Number of async workers used by the packet router.",
        )
        loader.add_option(
            name="foe_dispatcher_workers",
            typespec=int,
            default=2,
            help="Number of async workers used by the Pub/Sub dispatcher.",
        )
        loader.add_option(
            name="foe_database_url",
            typespec=str,
            default=DEFAULT_DATABASE_URL,
            help="Async SQLAlchemy PostgreSQL URL used by FoE Analytics.",
        )
        loader.add_option(
            name="foe_auto_create_schema",
            typespec=bool,
            default=True,
            help="Create FoE Analytics tables on startup for local development.",
        )
        loader.add_option(
            name="foe_enable_game_state",
            typespec=bool,
            default=True,
            help="Enable universal game-state capture into domain snapshots.",
        )
        loader.add_option(
            name="foe_enable_cbg_tracker",
            typespec=bool,
            default=True,
            help="Enable the specialized CBG tracker subscriber.",
        )
        loader.add_option(
            name="foe_enable_player_core",
            typespec=bool,
            default=True,
            help="Enable canonical player identity consolidation.",
        )
        loader.add_option(
            name="foe_enable_wallet_tracker",
            typespec=bool,
            default=True,
            help="Enable consolidated wallet/resource tracking.",
        )
        ctx.log.info("FoE Analytics passive addon loaded.")

    async def running(self) -> None:
        """Start queue consumers once mitmproxy is running."""

        self.capture_queue = CaptureQueue(maxsize=ctx.options.foe_capture_queue_size)
        self.packet_router = PacketRouter(self.capture_queue, self.dispatcher)
        self.database = DatabaseManager(database_url=ctx.options.foe_database_url)
        self._register_database_subscribers()

        if ctx.options.foe_auto_create_schema:
            try:
                await self.database.create_schema()
            except Exception:
                LOGGER.exception("Could not create FoE Analytics database schema")
                ctx.log.warn("FoE Analytics database schema could not be created.")

        await self.dispatcher.start(worker_count=ctx.options.foe_dispatcher_workers)
        await self.packet_router.start(worker_count=ctx.options.foe_packet_router_workers)
        ctx.log.info("FoE Analytics capture queue, router, and dispatcher started.")

    async def done(self) -> None:
        """Flush pending packets and events when mitmproxy is shutting down."""

        await self.packet_router.stop()
        await self.dispatcher.stop()
        if self.database:
            await self.database.dispose()
        ctx.log.info("FoE Analytics capture pipeline stopped.")

    async def response(self, flow: http.HTTPFlow) -> None:
        """Capture JSON responses without blocking browser traffic."""

        if not is_json_response(flow):
            return

        payload = decode_json_body(flow)
        if payload is None:
            return

        packet = CapturedPacket(
            payload=payload,
            endpoint=flow.request.pretty_url,
            http_method=flow.request.method,
            status_code=flow.response.status_code if flow.response else None,
            player_id=_extract_query_value(flow.request.pretty_url, "player_id"),
            world_id=_extract_world_id(flow.request.pretty_url),
            headers=dict(flow.response.headers.items()) if flow.response else {},
            metadata={
                "host": flow.request.host,
                "path": flow.request.path,
                "scheme": flow.request.scheme,
            },
        )

        accepted = self.capture_queue.enqueue_nowait(packet)
        if not accepted:
            ctx.log.warn("FoE Analytics dropped packet because the capture queue is full.")

    def _register_database_subscribers(self) -> None:
        if self._database_subscribers_registered or not self.database:
            return

        self.raw_packet_recorder = RawPacketRecorder(self.database)
        self.raw_packet_recorder.register(self.dispatcher)

        if ctx.options.foe_enable_game_state:
            self.game_state = GameStateSubscriber(self.database)
            self.game_state.register(self.dispatcher)

        if ctx.options.foe_enable_player_core:
            self.player_core = PlayerCoreSubscriber(self.database)
            self.player_core.register(self.dispatcher)

        if ctx.options.foe_enable_wallet_tracker:
            self.wallet_tracker = WalletTrackerSubscriber(self.database)
            self.wallet_tracker.register(self.dispatcher)

        if ctx.options.foe_enable_cbg_tracker:
            self.cbg_tracker = CbgTrackerSubscriber(self.database)
            self.cbg_tracker.register(self.dispatcher)

        self._database_subscribers_registered = True


def _extract_query_value(url: str, key: str) -> str:
    parsed = urlparse(url)
    values = parse_qs(parsed.query).get(key)
    if not values:
        return UNKNOWN_CONTEXT
    return values[0] or UNKNOWN_CONTEXT


def _extract_world_id(url: str) -> str:
    parsed = urlparse(url)

    host_parts = parsed.hostname.split(".") if parsed.hostname else []
    if host_parts:
        possible_world = host_parts[0]
        if possible_world:
            return possible_world

    return _extract_query_value(url, "world_id")


addons = [FoeAnalyticsAddon()]
