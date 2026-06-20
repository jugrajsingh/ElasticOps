from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.services import executor


def test_largest_factor_le():
    assert executor.largest_factor_le(6, 4) == 3
    assert executor.largest_factor_le(6, 2) == 2
    assert executor.largest_factor_le(5, 2) == 1   # prime → 1
    assert executor.largest_factor_le(7, 4) == 1   # prime → 1
    assert executor.largest_factor_le(8, 8) == 4   # never returns current itself


def test_pick_target_node_prefers_data_node_with_most_free():
    nodes = [
        {"name": "m1", "node.role": "m", "disk.total": "100", "disk.used": "10"},
        {"name": "d1", "node.role": "dim", "disk.total": "100", "disk.used": "90"},
        {"name": "d2", "node.role": "dim", "disk.total": "100", "disk.used": "20"},
    ]
    assert executor.pick_target_node(nodes) == "d2"


def _fake_es_green():
    es = AsyncMock()
    es.cat_nodes_detailed.return_value = [
        {"name": "d1", "node.role": "dim", "disk.total": "100", "disk.used": "10"}
    ]
    es.index_health.return_value = {"status": "green", "relocating_shards": 0}
    es.set_index_settings.return_value = {}
    es.shrink_index.return_value = {}
    return es


async def test_reduce_shards_happy_path():
    es = _fake_es_green()
    job = SimpleNamespace(index_name="logs-2021", current_shards=6, target_shards=2, current_replicas=1)
    await executor.execute_reduce_shards(es, job, delay=0)
    es.shrink_index.assert_awaited_once()
    src, target, settings = es.shrink_index.await_args.args
    assert src == "logs-2021"
    assert target == "logs-2021-shrink-2"
    assert settings["index.number_of_shards"] == 2
    assert job.task_id == "logs-2021-shrink-2"
    assert job.target_shards == 2


async def test_reduce_shards_snaps_to_factor():
    es = _fake_es_green()
    job = SimpleNamespace(index_name="idx", current_shards=6, target_shards=4, current_replicas=0)
    await executor.execute_reduce_shards(es, job, delay=0)
    _src, target, settings = es.shrink_index.await_args.args
    assert settings["index.number_of_shards"] == 3
    assert target == "idx-shrink-3"


async def test_reduce_shards_rejects_unshrinkable():
    es = _fake_es_green()
    job = SimpleNamespace(index_name="idx", current_shards=1, target_shards=1, current_replicas=0)
    with pytest.raises(ValueError):
        await executor.execute_reduce_shards(es, job, delay=0)


async def test_reduce_shards_reverts_source_on_failure():
    es = _fake_es_green()
    es.shrink_index.side_effect = RuntimeError("boom")
    job = SimpleNamespace(index_name="idx", current_shards=4, target_shards=2, current_replicas=0)
    with pytest.raises(RuntimeError):
        await executor.execute_reduce_shards(es, job, delay=0)
    # last set_index_settings call clears the write block + allocation (revert)
    revert = es.set_index_settings.await_args.args[1]
    assert revert["index.blocks.write"] is None
    assert revert["index.routing.allocation.require._name"] is None


async def test_reduce_shards_clears_source_block_on_success():
    es = _fake_es_green()
    job = SimpleNamespace(index_name="idx", current_shards=6, target_shards=2, current_replicas=1)
    await executor.execute_reduce_shards(es, job, delay=0)
    last = es.set_index_settings.await_args  # finally-block clear is the last call
    assert last.args[0] == "idx"
    assert last.args[1]["index.blocks.write"] is None
    assert last.args[1]["index.routing.allocation.require._name"] is None


async def test_wait_until_green_tolerates_transient_error():
    es = AsyncMock()
    es.index_health.side_effect = [RuntimeError("not ready"), {"status": "green", "relocating_shards": 0}]
    health = await executor.wait_until_green(es, "idx", attempts=5, delay=0)
    assert health["status"] == "green"
    assert es.index_health.await_count == 2


async def test_force_merge_calls_forcemerge():
    es = AsyncMock()
    job = SimpleNamespace(index_name="idx")
    await executor.execute_force_merge(es, job)
    es.post.assert_awaited_once()
    assert es.post.await_args.args[0] == "/idx/_forcemerge"
