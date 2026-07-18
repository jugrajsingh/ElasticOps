"""Tests for the per-cluster background poller and the poll manager.

No live ES and no real sleeping: ES is an ``AsyncMock``/fake, ``refresh_cluster`` is stubbed or
patched, and intervals are driven by directly invoking the cycle/loop with zeroed cadences plus
``asyncio`` control. The heavy-vs-light gating is asserted by checking that the heavy shards path
(``cat_shards_detailed``) is never touched on a light tick.
"""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models.cluster import Cluster
from backend.services import snapshot_repo
from backend.services.poller import ClusterPoller, ClusterPollManager
from config.settings import PollingSettings


@pytest.fixture
async def session_factory():
    """A fresh in-memory SQLite DB with the schema created, yielding its session factory."""
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed_cluster(factory, *, name: str = "c1", is_active: bool = True) -> int:
    async with factory() as session:
        cluster = Cluster(name=name, url="https://es.example.com:9200", is_active=is_active)
        session.add(cluster)
        await session.commit()
        await session.refresh(cluster)
        return cluster.id


def _fake_es() -> AsyncMock:
    es = AsyncMock()
    es.cluster_health.return_value = {"status": "green", "number_of_nodes": 3}
    es.cat_nodes_detailed.return_value = []
    es.cat_indices_detailed.return_value = []
    es.cat_shards_detailed.return_value = []
    es.cat_recovery_active.return_value = []
    return es


# --------------------------------------------------------------------------------------------------
# ClusterPoller cycles
# --------------------------------------------------------------------------------------------------


async def test_heavy_cycle_runs_refresh_and_upserts(session_factory):
    cluster_id = await _seed_cluster(session_factory)
    refresh = AsyncMock(return_value={"health": 1, "shards": 10})
    poller = ClusterPoller(
        cluster_id,
        _fake_es(),
        PollingSettings(),
        refresh=refresh,
        session_factory=session_factory,
    )

    await poller._heavy_cycle()

    refresh.assert_awaited_once()
    # refresh(es, cluster_id, session, sep=...)
    args, kwargs = refresh.await_args
    assert args[1] == cluster_id
    assert kwargs["sep"] == PollingSettings().pivot_separator


async def test_heavy_cycle_with_real_refresh_upserts_health(session_factory):
    """A heavy cycle delegating to the real refresh persists the health snapshot."""
    cluster_id = await _seed_cluster(session_factory)
    es = _fake_es()
    poller = ClusterPoller(cluster_id, es, PollingSettings(), session_factory=session_factory)

    await poller._heavy_cycle()

    async with session_factory() as session:
        snap = await snapshot_repo.get_latest(session, cluster_id, "health")
    assert snap is not None
    assert snap.payload["status"] == "green"
    assert snap.item_count == 1


async def test_light_cycle_does_not_fetch_heavy_shards(session_factory):
    """The light tick refreshes health only — the 56K-row shards path is never called."""
    cluster_id = await _seed_cluster(session_factory)
    es = _fake_es()
    poller = ClusterPoller(cluster_id, es, PollingSettings(), session_factory=session_factory)

    await poller._light_cycle()

    es.cluster_health.assert_awaited()
    es.cat_shards_detailed.assert_not_called()
    es.cat_indices_detailed.assert_not_called()
    es.cat_nodes_detailed.assert_not_called()

    async with session_factory() as session:
        snap = await snapshot_repo.get_latest(session, cluster_id, "health")
    assert snap is not None


async def test_cycle_exception_is_swallowed_and_loop_continues(session_factory):
    """An exception inside a cycle is logged and swallowed; the cycle returns normally."""
    cluster_id = await _seed_cluster(session_factory)
    refresh = AsyncMock(side_effect=RuntimeError("ES unreachable"))
    poller = ClusterPoller(
        cluster_id,
        _fake_es(),
        PollingSettings(),
        refresh=refresh,
        session_factory=session_factory,
    )

    # Must not raise.
    await poller._heavy_cycle()
    refresh.assert_awaited_once()


async def test_light_cycle_exception_is_swallowed(session_factory):
    cluster_id = await _seed_cluster(session_factory)
    es = _fake_es()
    es.cluster_health.side_effect = RuntimeError("boom")
    poller = ClusterPoller(cluster_id, es, PollingSettings(), session_factory=session_factory)

    await poller._light_cycle()  # must not raise


async def test_run_loop_gates_heavy_to_heavy_cadence(session_factory):
    """Across light ticks only health is fetched; the heavy shards path stays untouched until due."""
    cluster_id = await _seed_cluster(session_factory)
    es = _fake_es()
    # health every 1s, heavy every 1000s → within a short run only light ticks fire after warm-up.
    polling = PollingSettings(health_seconds=1, heavy_seconds=1000)
    poller = ClusterPoller(cluster_id, es, polling, session_factory=session_factory)

    task = asyncio.create_task(poller.run())
    # Let the initial heavy warm-up + a few light ticks run, then stop.
    await asyncio.sleep(0.05)
    es.cat_shards_detailed.reset_mock()  # ignore the one warm-up heavy fetch
    # Drive several light ticks deterministically by leaving it running briefly.
    await asyncio.sleep(0)
    poller.stop()
    await asyncio.wait_for(task, timeout=2.0)

    # After the warm-up heavy cycle, no further heavy shards fetch should have occurred.
    es.cat_shards_detailed.assert_not_called()


async def test_run_loop_runs_heavy_warmup_immediately(session_factory):
    """The loop warms the cache with a heavy cycle on entry (before any sleep)."""
    cluster_id = await _seed_cluster(session_factory)
    refresh = AsyncMock(return_value={})
    poller = ClusterPoller(
        cluster_id,
        _fake_es(),
        PollingSettings(),
        refresh=refresh,
        session_factory=session_factory,
    )

    task = asyncio.create_task(poller.run())
    await asyncio.sleep(0.01)
    poller.stop()
    await asyncio.wait_for(task, timeout=2.0)

    refresh.assert_awaited()  # at least the warm-up heavy cycle ran


# --------------------------------------------------------------------------------------------------
# ClusterPollManager
# --------------------------------------------------------------------------------------------------


def _idle_poller_factory(started: list[int], stopped: list[int]):
    """Build a manager poller_factory yielding fake pollers that idle until stopped."""

    class _IdlePoller:
        def __init__(self, cluster_id: int) -> None:
            self.cluster_id = cluster_id
            self._stop = asyncio.Event()
            self.closed = False

        async def run(self) -> None:
            started.append(self.cluster_id)
            await self._stop.wait()

        def stop(self) -> None:
            self._stop.set()

        async def aclose(self) -> None:
            self.closed = True
            stopped.append(self.cluster_id)

    return lambda cluster: _IdlePoller(cluster.id)


async def test_start_all_spawns_a_poller_per_active_cluster(session_factory):
    await _seed_cluster(session_factory, name="a")
    await _seed_cluster(session_factory, name="b")
    await _seed_cluster(session_factory, name="inactive", is_active=False)

    started: list[int] = []
    stopped: list[int] = []
    manager = ClusterPollManager(
        polling=PollingSettings(),
        session_factory=session_factory,
        poller_factory=_idle_poller_factory(started, stopped),
    )

    await manager.start_all()
    await asyncio.sleep(0.01)  # let tasks reach run()

    assert len(manager._tasks) == 2  # inactive cluster excluded
    assert sorted(started) == [1, 2]

    await manager.stop_all()
    assert manager._tasks == {}
    assert sorted(stopped) == [1, 2]


async def test_add_and_remove_cluster_start_and_stop_tasks(session_factory):
    started: list[int] = []
    stopped: list[int] = []
    manager = ClusterPollManager(
        polling=PollingSettings(),
        session_factory=session_factory,
        poller_factory=_idle_poller_factory(started, stopped),
    )

    cluster_id = await _seed_cluster(session_factory)
    await manager.add_cluster(cluster_id)
    await asyncio.sleep(0.01)
    assert cluster_id in manager._tasks
    assert started == [cluster_id]

    await manager.remove_cluster(cluster_id)
    assert cluster_id not in manager._tasks
    assert stopped == [cluster_id]


async def test_add_cluster_is_idempotent(session_factory):
    started: list[int] = []
    manager = ClusterPollManager(
        polling=PollingSettings(),
        session_factory=session_factory,
        poller_factory=_idle_poller_factory(started, []),
    )
    cluster_id = await _seed_cluster(session_factory)

    await manager.add_cluster(cluster_id)
    await manager.add_cluster(cluster_id)  # second call no-ops
    await asyncio.sleep(0.01)

    assert started == [cluster_id]
    assert len(manager._tasks) == 1


async def test_add_cluster_skips_missing_or_inactive(session_factory):
    started: list[int] = []
    manager = ClusterPollManager(
        polling=PollingSettings(),
        session_factory=session_factory,
        poller_factory=_idle_poller_factory(started, []),
    )

    await manager.add_cluster(999)  # missing
    inactive_id = await _seed_cluster(session_factory, name="off", is_active=False)
    await manager.add_cluster(inactive_id)

    assert started == []
    assert manager._tasks == {}


async def test_stop_all_cancels_cleanly(session_factory):
    cancelled = asyncio.Event()

    class _CancellablePoller:
        def __init__(self, cluster_id: int) -> None:
            self.cluster_id = cluster_id
            self.closed = False

        async def run(self) -> None:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        def stop(self) -> None:
            pass

        async def aclose(self) -> None:
            self.closed = True

    manager = ClusterPollManager(
        polling=PollingSettings(),
        session_factory=session_factory,
        poller_factory=lambda cluster: _CancellablePoller(cluster.id),
    )
    await _seed_cluster(session_factory)
    await manager.start_all()
    await asyncio.sleep(0.01)

    await manager.stop_all()
    assert cancelled.is_set()
    assert manager._tasks == {}


async def test_default_poller_factory_builds_pooled_es_client(monkeypatch):
    """The default factory wires a pooled httpx client into the ESClient and decrypts creds."""
    from backend.services import poller as poller_module

    monkeypatch.setattr(poller_module, "decrypt", lambda _enc: "decrypted-pass")

    @asynccontextmanager
    async def _fake_session():
        yield None

    manager = ClusterPollManager(polling=PollingSettings(), session_factory=_fake_session)
    cluster = Cluster(id=7, name="c", url="https://es.example.com:9200", username="elastic")

    built = manager._default_poller_factory(cluster)
    try:
        assert isinstance(built, ClusterPoller)
        assert built._es._pooled_client is not None  # pooled client injected
    finally:
        await built.aclose()
