from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.services import executor


def test_largest_factor_le():
    assert executor.largest_factor_le(6, 4) == 3
    assert executor.largest_factor_le(6, 2) == 2
    assert executor.largest_factor_le(5, 2) == 1  # prime → 1
    assert executor.largest_factor_le(7, 4) == 1  # prime → 1
    assert executor.largest_factor_le(8, 8) == 4  # never returns current itself


def test_pick_target_node_prefers_data_node_with_most_free():
    nodes = [
        {"name": "m1", "node.role": "m", "disk.total": "100", "disk.used": "10"},
        {"name": "d1", "node.role": "dim", "disk.total": "100", "disk.used": "90"},
        {"name": "d2", "node.role": "dim", "disk.total": "100", "disk.used": "20"},
    ]
    assert executor.pick_target_node(nodes) == "d2"


def test_should_exclude_coordinating_node_when_picking_shrink_target():
    # A coord node has the most free disk but holds no shards; "coord" contains a 'd' so the old
    # substring check wrongly treated it as data. It must never be chosen as the shrink target.
    nodes = [
        {"name": "coord1", "node.role": "coord", "disk.total": "100", "disk.used": "0"},
        {"name": "d1", "node.role": "dim", "disk.total": "100", "disk.used": "50"},
    ]
    assert executor.pick_target_node(nodes) == "d1"


def test_should_include_hot_data_node_without_literal_d_when_picking_target():
    # A hot+ingest+search node (role "his") carries shards but has no literal 'd'; the old check
    # missed it and could fall back to a master node. It must be data-eligible.
    nodes = [
        {"name": "hot1", "node.role": "his", "disk.total": "100", "disk.used": "50"},
        {"name": "m1", "node.role": "m", "disk.total": "100", "disk.used": "0"},
    ]
    assert executor.pick_target_node(nodes) == "hot1"


class _InPlaceES:
    """Minimal fake modelling the in-place shrink sequence (temp copy + reindex-back).

    ``count`` returns a constant per index so the happy-path doc-count verifications pass; tests
    that need a failure point inject ``shrink_error``.
    """

    def __init__(self, *, shrink_error: Exception | None = None) -> None:
        self.calls: list[tuple] = []
        self.present: set[str] = set()
        self.pinned: dict[str, str] = {}
        self._shrink_error = shrink_error

    def seed(self, index: str) -> "_InPlaceES":
        self.present.add(index)
        return self

    async def index_health(self, index):
        if index not in self.present:
            raise RuntimeError("index_not_found_exception")
        return {"status": "green", "relocating_shards": 0}

    async def cat_nodes_detailed(self):
        # Shrink colocates source shards onto one data node first; pick_target_node reads name/disk.
        return [{"name": "d1", "node.role": "dim", "disk.total": "100", "disk.used": "10"}]

    async def cat_shards_detailed(self):
        # The shrink pre-flight waits on the shard table for primaries to land on the pin node.
        return [
            {"index": idx, "shard": "0", "prirep": "p", "state": "STARTED", "node": self.pinned.get(idx, "d1")}
            for idx in self.present
        ]

    async def set_index_settings(self, index, settings):
        self.calls.append(("settings", index, settings))
        if "index.routing.allocation.require._name" in settings:
            node = settings["index.routing.allocation.require._name"]
            if node:
                self.pinned[index] = node
            else:
                self.pinned.pop(index, None)

    async def shrink_index(self, source, target, settings):
        self.calls.append(("shrink", source, target, settings))
        if self._shrink_error is not None:
            raise self._shrink_error
        self.present.add(target)

    async def count(self, _index):
        return 100

    async def delete_index(self, index):
        self.calls.append(("delete", index))
        self.present.discard(index)

    async def create_index(self, index, settings):
        self.calls.append(("create", index, settings))
        self.present.add(index)

    async def reindex_async(self, source, dest):
        self.calls.append(("reindex", source, dest))
        return {"task": "node:1"}

    async def get_task(self, _task_id):
        return {"completed": True}


async def test_reduce_shards_happy_path():
    es = _InPlaceES().seed("logs-2021")
    job = SimpleNamespace(
        index_name="logs-2021", current_shards=6, target_shards=2, current_replicas=1, detail="", task_id="x"
    )
    await executor.execute_reduce_shards(es, job, delay=0)
    shrink = next(c for c in es.calls if c[0] == "shrink")
    assert shrink[1:3] == ("logs-2021", "logs-2021__resize")  # temp copy, not a suffixed survivor
    assert shrink[3]["index.number_of_shards"] == 2
    # Shrink colocates source shards onto one node (write-block + require._name) before copying.
    shrink_idx = es.calls.index(shrink)
    pin = next(
        c
        for c in es.calls[:shrink_idx]
        if c[0] == "settings" and c[1] == "logs-2021" and c[2].get("index.routing.allocation.require._name") == "d1"
    )
    assert pin[2]["index.blocks.write"] is True
    # The temp copy clears the colocation pin so its shards spread normally.
    assert shrink[3]["index.routing.allocation.require._name"] is None
    # In place: source rebuilt, reindexed back from temp, temp dropped, no suffixed index retained.
    assert ("create", "logs-2021", {"index.number_of_shards": 2, "index.number_of_replicas": 1}) in es.calls
    assert ("reindex", "logs-2021__resize", "logs-2021") in es.calls
    assert ("delete", "logs-2021__resize") in es.calls
    assert not any("logs-2021-shrink-" in str(c) for c in es.calls)
    assert job.task_id is None
    assert job.target_shards == 2


async def test_reduce_shards_snaps_to_factor():
    es = _InPlaceES().seed("idx")
    job = SimpleNamespace(
        index_name="idx", current_shards=6, target_shards=4, current_replicas=0, detail="", task_id="x"
    )
    await executor.execute_reduce_shards(es, job, delay=0)
    shrink = next(c for c in es.calls if c[0] == "shrink")
    assert shrink[3]["index.number_of_shards"] == 3
    assert shrink[2] == "idx__resize"  # snapped factor goes into the temp copy
    assert job.target_shards == 3
    # Colocation pin is set on the source before the shrink copy.
    shrink_idx = es.calls.index(shrink)
    assert any(
        c[0] == "settings" and c[1] == "idx" and c[2].get("index.routing.allocation.require._name") == "d1"
        for c in es.calls[:shrink_idx]
    )


async def test_reduce_shards_rejects_unshrinkable():
    es = _InPlaceES().seed("idx")
    job = SimpleNamespace(
        index_name="idx", current_shards=1, target_shards=1, current_replicas=0, detail="", task_id="x"
    )
    with pytest.raises(ValueError):
        await executor.execute_reduce_shards(es, job, delay=0)


async def test_reduce_shards_preserves_source_when_copy_fails():
    # The copy raises before any verified replacement; source must survive and never be deleted.
    es = _InPlaceES(shrink_error=RuntimeError("boom")).seed("idx")
    job = SimpleNamespace(
        index_name="idx", current_shards=4, target_shards=2, current_replicas=0, detail="", task_id="x"
    )
    with pytest.raises(RuntimeError):
        await executor.execute_reduce_shards(es, job, delay=0)
    assert ("delete", "idx") not in es.calls
    assert "idx" in es.present


async def test_reduce_shards_clears_source_block_when_copy_fails():
    # On a failed copy the source still exists, so the finally-block restores it to writable.
    es = _InPlaceES(shrink_error=RuntimeError("boom")).seed("idx")
    job = SimpleNamespace(
        index_name="idx", current_shards=6, target_shards=2, current_replicas=1, detail="", task_id="x"
    )
    with pytest.raises(RuntimeError):
        await executor.execute_reduce_shards(es, job, delay=0)
    clear = next(c for c in reversed(es.calls) if c[0] == "settings" and c[2].get("index.blocks.write") is None)
    assert clear[1] == "idx"
    # Cleanup also unpins the colocation requirement so the source allocates normally again.
    assert clear[2].get("index.routing.allocation.require._name") is None


class _MetaES(_InPlaceES):
    """``_InPlaceES`` that also exposes an index definition (``get_index``) and records the
    mappings/aliases passed to ``create_index`` — so a resize can be asserted to preserve them.
    """

    def __init__(self, *, mappings: dict, aliases: dict) -> None:
        super().__init__()
        self._defs: dict[str, dict] = {}
        self.created_mappings: dict[str, dict | None] = {}
        self.created_aliases: dict[str, dict | None] = {}
        self._seed_mappings = mappings
        self._seed_aliases = aliases

    def seed(self, index: str) -> "_MetaES":
        super().seed(index)
        self._defs[index] = {
            "mappings": self._seed_mappings,
            "aliases": self._seed_aliases,
            "settings": {"index": {}},
        }
        return self

    async def get_index(self, index):
        return self._defs.get(index, {})

    async def create_index(self, index, settings, *, mappings=None, aliases=None):
        self.calls.append(("create", index, settings))
        self.present.add(index)
        self.created_mappings[index] = mappings
        self.created_aliases[index] = aliases


async def test_should_preserve_mappings_and_aliases_when_resizing_in_place():
    # An in-place resize recreates the source; it must carry the original mappings and aliases, not
    # bare shard/replica counts — otherwise field types, analyzers, and aliases are silently lost.
    es = _MetaES(
        mappings={"properties": {"ts": {"type": "date"}}},
        aliases={"logs_read": {}},
    ).seed("logs")
    job = SimpleNamespace(
        id=7, index_name="logs", current_shards=6, target_shards=2, current_replicas=1, detail="", task_id="x"
    )
    await executor.execute_reduce_shards(es, job, delay=0)
    assert es.created_mappings["logs"] == {"properties": {"ts": {"type": "date"}}}
    assert es.created_aliases["logs"] == {"logs_read": {}}


async def test_wait_until_green_tolerates_transient_error():
    es = AsyncMock()
    es.index_health.side_effect = [RuntimeError("not ready"), {"status": "green", "relocating_shards": 0}]
    health = await executor.wait_until_green(es, "idx", attempts=5, delay=0)
    assert health["status"] == "green"
    assert es.index_health.await_count == 2
