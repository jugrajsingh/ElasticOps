"""Per-cluster background pollers that keep the snapshot cache warm.

A :class:`ClusterPoller` owns **one** cluster's polling loop and a single reused HTTP client (one
pooled ``httpx.AsyncClient`` per cluster, injected into an :class:`ESClient`; credentials decrypted
once at construction). It runs two cadences:

* **light** (``health_seconds``, default 30s): refresh only cheap data (cluster health) — never
  re-pulling the ~56K-row ``_cat/shards`` payload on the fast tick.
* **heavy** (``heavy_seconds``, default 90s): the full :func:`refresh_cluster` — fetches nodes,
  indices, the heavy shards, and recoveries once, then builds and upserts every kind.

The non-negotiable load constraint is satisfied structurally: ``_cat/shards`` is fetched **only** on
the heavy tick (inside :func:`refresh_cluster`). The light tick calls ``cluster_health`` only.

A :class:`ClusterPollManager` starts/stops one poller per active cluster, and exposes
``add_cluster`` / ``remove_cluster`` for clusters created/deleted at runtime, plus ``start_all`` /
``stop_all`` for lifespan wiring.

Read-only against ES: pollers issue only ``GET _cluster/health`` and ``GET _cat/*`` (via
:func:`refresh_cluster` and ``cluster_health``). Errors in any cycle are logged and swallowed so a
single unreachable cluster never crashes the app or the other pollers.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

import httpx
from sqlalchemy import select

from backend.database import async_session_factory
from backend.models.cluster import Cluster
from backend.services import snapshot_repo
from backend.services.es_client import ESClient
from backend.services.secrets import decrypt
from backend.services.snapshot_service import refresh_cluster
from config.settings import PollingSettings, get_settings

logger = logging.getLogger("elasticops")


class ClusterPoller:
    """Owns a single cluster's polling loop and its reused :class:`ESClient`."""

    def __init__(
        self,
        cluster_id: int,
        es: ESClient,
        polling: PollingSettings,
        *,
        http_client: httpx.AsyncClient | None = None,
        refresh: Callable[..., Awaitable[dict[str, int]]] = refresh_cluster,
        session_factory=async_session_factory,
    ) -> None:
        self._cluster_id = cluster_id
        self._es = es
        self._polling = polling
        self._http_client = http_client
        self._refresh = refresh
        self._session_factory = session_factory
        self._stop = asyncio.Event()
        # Elapsed-second counters per cadence.
        self._light_elapsed = 0
        self._heavy_elapsed = 0

    async def run(self) -> None:
        """Loop until stopped, advancing the two cadences once per second.

        The heavy cycle runs the full :func:`refresh_cluster` (pulls the heavy shards). The light
        cycle refreshes only cheap health. Both tolerate errors and keep looping.
        """
        # Run a heavy cycle immediately so the cache warms without waiting a full interval.
        await self._heavy_cycle()

        while not self._stop.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=1.0)
            if self._stop.is_set():
                break

            self._light_elapsed += 1
            self._heavy_elapsed += 1

            if self._heavy_elapsed >= self._polling.heavy_seconds:
                await self._heavy_cycle()
                # A heavy cycle also refreshes health, so reset the light timer too.
                self._heavy_elapsed = 0
                self._light_elapsed = 0
            elif self._light_elapsed >= self._polling.health_seconds:
                await self._light_cycle()
                self._light_elapsed = 0

    async def _heavy_cycle(self) -> None:
        """Full refresh: fetch raw ES once (incl. the heavy shards) and upsert every kind."""
        try:
            async with self._session_factory() as session:
                counts = await self._refresh(
                    self._es,
                    self._cluster_id,
                    session,
                    sep=self._polling.pivot_separator,
                )
            logger.debug("Heavy poll cycle complete for cluster %s: %s", self._cluster_id, counts)
        except Exception:
            logger.exception("Heavy poll cycle failed for cluster %s", self._cluster_id)

    async def _light_cycle(self) -> None:
        """Cheap refresh: cluster health only. Never fetches the heavy ``_cat/shards`` payload."""
        try:
            health = await self._es.cluster_health()
            async with self._session_factory() as session:
                await snapshot_repo.upsert_snapshot(
                    session, self._cluster_id, "health", health, item_count=1, duration_ms=0
                )
            logger.debug("Light poll cycle complete for cluster %s", self._cluster_id)
        except Exception:
            logger.exception("Light poll cycle failed for cluster %s", self._cluster_id)

    def stop(self) -> None:
        """Signal the loop to exit at the next tick."""
        self._stop.set()

    async def aclose(self) -> None:
        """Close the pooled HTTP client this poller owns (if any)."""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None


class ClusterPollManager:
    """Starts/stops :class:`ClusterPoller`s for active clusters and routes runtime add/remove."""

    def __init__(
        self,
        *,
        polling: PollingSettings | None = None,
        session_factory=async_session_factory,
        poller_factory: Callable[[Cluster], ClusterPoller] | None = None,
    ) -> None:
        self._polling = polling or get_settings().polling
        self._session_factory = session_factory
        self._poller_factory = poller_factory or self._default_poller_factory
        self._pollers: dict[int, ClusterPoller] = {}
        self._tasks: dict[int, asyncio.Task] = {}

    async def start_all(self) -> None:
        """Read active clusters from the DB and start a poller for each."""
        async with self._session_factory() as session:
            result = await session.execute(select(Cluster).where(Cluster.is_active.is_(True)))
            clusters = result.scalars().all()

        for cluster in clusters:
            self._start_one(cluster)

    async def add_cluster(self, cluster_id: int) -> None:
        """Start polling a cluster created at runtime (no-op if already polling)."""
        if cluster_id in self._tasks:
            return
        async with self._session_factory() as session:
            cluster = await session.get(Cluster, cluster_id)
        if cluster is None or not cluster.is_active:
            logger.warning("add_cluster: cluster %s missing or inactive; skipping", cluster_id)
            return
        self._start_one(cluster)

    async def remove_cluster(self, cluster_id: int) -> None:
        """Stop and clean up a cluster's poller (cancel task, close its HTTP client)."""
        poller = self._pollers.pop(cluster_id, None)
        task = self._tasks.pop(cluster_id, None)
        if poller is not None:
            poller.stop()
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if poller is not None:
            await poller.aclose()

    async def stop_all(self) -> None:
        """Cancel every poller task, await cancellation, and close every HTTP client."""
        for poller in self._pollers.values():
            poller.stop()
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for poller in self._pollers.values():
            await poller.aclose()
        self._pollers.clear()
        self._tasks.clear()

    def _start_one(self, cluster: Cluster) -> None:
        """Build the poller and launch its task."""
        poller = self._poller_factory(cluster)
        self._pollers[cluster.id] = poller
        self._tasks[cluster.id] = asyncio.create_task(poller.run())
        logger.info("Started poller for cluster %s (%s)", cluster.id, cluster.name)

    def _default_poller_factory(self, cluster: Cluster) -> ClusterPoller:
        """Build the pooled HTTP client + :class:`ESClient` + poller for one cluster."""
        http_client = httpx.AsyncClient(verify=cluster.verify_ssl, timeout=30.0)
        es = ESClient(
            base_url=cluster.url,
            username=cluster.username,
            password=decrypt(cluster.password_encrypted),
            verify_ssl=cluster.verify_ssl,
            pooled_client=http_client,
        )
        return ClusterPoller(
            cluster.id,
            es,
            self._polling,
            http_client=http_client,
            session_factory=self._session_factory,
        )
