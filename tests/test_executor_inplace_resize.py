"""Tests for the in-place split/shrink executors (temp-copy + reindex-back, no suffixed index).

These exercise :func:`execute_split_shards` / :func:`execute_reduce_shards` against a ``FakeES``
that records the ordered call sequence and serves ``count()`` per index. The safety property under
test: the source is NEVER deleted without a verified equal-doc-count replacement, and no
``-split-<n>`` / ``-shrink-<n>`` index ever survives (the temp is ``<source>__resize``).
"""

from types import SimpleNamespace

import pytest

from backend.services.executor import (
    execute_reduce_shards,
    execute_split_shards,
    wait_until_primaries_on_node,
)


class FakeES:
    """Records the call sequence and serves per-index doc counts.

    ``counts`` maps an index name to its doc count; ``present`` is the live set of indices.
    ``count(temp)`` defaults to ``count(source)`` unless overridden, so the happy paths verify
    cleanly while mismatch tests can diverge the temp count explicitly.
    """

    def __init__(self, counts: dict[str, int], present: set[str]) -> None:
        self.calls: list[tuple] = []
        self.counts = counts
        self.present = set(present)
        self.pinned: dict[str, str] = {}

    async def index_health(self, index):
        if index not in self.present:
            raise RuntimeError("index_not_found_exception")
        return {"status": "green", "relocating_shards": 0}

    async def cat_nodes_detailed(self):
        return [
            {"name": "node-a", "node.role": "dim", "disk.total": "1000", "disk.used": "100"},
            {"name": "node-b", "node.role": "dim", "disk.total": "1000", "disk.used": "900"},
        ]

    async def cat_shards_detailed(self):
        # Model colocation as instantaneous: a pinned index's primary is STARTED on its pin node.
        # The shrink pre-flight waits on THIS table (not health), so the pin must be reflected here.
        return [
            {"index": idx, "shard": "0", "prirep": "p", "state": "STARTED", "node": self.pinned.get(idx, "node-a")}
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

    async def split_index(self, source, target, settings):
        self.calls.append(("split", source, target, settings))
        self.present.add(target)

    async def shrink_index(self, source, target, settings):
        self.calls.append(("shrink", source, target, settings))
        self.present.add(target)

    async def count(self, index):
        self.calls.append(("count", index))
        return self.counts[index]

    async def delete_index(self, index):
        self.calls.append(("delete", index))
        self.present.discard(index)

    async def create_index(self, index, settings):
        self.calls.append(("create", index, settings))
        self.present.add(index)

    async def reindex_async(self, source, dest):
        self.calls.append(("reindex", source, dest))
        return {"task": "node:1"}

    async def get_task(self, task_id):
        self.calls.append(("get_task", task_id))
        return {"completed": True}

    def ops(self) -> list[str]:
        return [c[0] for c in self.calls]

    def targets(self) -> list[str]:
        """Every index name that appears as the create/copy target across the recorded calls."""
        names: list[str] = []
        for c in self.calls:
            if c[0] in {"split", "shrink"}:
                names.append(c[2])
            elif c[0] in {"create", "delete", "count"}:
                names.append(c[1])
        return names


@pytest.mark.asyncio
async def test_should_split_in_place_with_verified_reindex_back():
    es = FakeES(counts={"idx": 100, "idx__resize": 100}, present={"idx"})
    job = SimpleNamespace(
        index_name="idx", current_shards=2, target_shards=6, current_replicas=1, detail="", task_id="x"
    )

    await execute_split_shards(es, job, delay=0)

    # Ordered safety sequence: copy -> verify -> delete source -> recreate -> reindex -> verify -> drop temp.
    split_i = es.ops().index("split")
    assert es.calls[split_i] == ("split", "idx", "idx__resize", es.calls[split_i][3])
    # count(temp) and count(source) BEFORE delete(idx).
    delete_src = es.calls.index(("delete", "idx"))
    assert ("count", "idx__resize") in es.calls[:delete_src]
    assert ("count", "idx") in es.calls[:delete_src]
    # recreate source with the new shard count, then reindex temp -> source.
    create_i = es.calls.index(("create", "idx", {"index.number_of_shards": 6, "index.number_of_replicas": 1}))
    reindex_i = es.calls.index(("reindex", "idx__resize", "idx"))
    assert delete_src < create_i < reindex_i
    # post-reindex verification, then drop temp last.
    assert reindex_i < es.calls.index(("delete", "idx__resize"))
    # No `-split-` index is ever created; temp is the deleted __resize index.
    assert not any("-split-" in n for n in es.targets())
    assert "idx__resize" not in es.present
    assert job.target_shards == 6
    assert job.task_id is None
    assert "in place" in job.detail


@pytest.mark.asyncio
async def test_should_shrink_in_place_with_verified_reindex_back():
    es = FakeES(counts={"idx": 80, "idx__resize": 80}, present={"idx"})
    job = SimpleNamespace(
        index_name="idx", current_shards=6, target_shards=2, current_replicas=0, detail="", task_id="x"
    )

    await execute_reduce_shards(es, job, delay=0)

    shrink_i = es.ops().index("shrink")
    assert es.calls[shrink_i][1:3] == ("idx", "idx__resize")
    assert es.calls[shrink_i][3]["index.number_of_shards"] == 2

    # Colocation: BEFORE shrink the source is pinned to a single node (most-free-disk = node-a) and
    # write-blocked. ``pick_target_node`` picks node-a (900 free) over node-b (100 free).
    pin_call = (
        "settings",
        "idx",
        {"index.blocks.write": True, "index.routing.allocation.require._name": "node-a"},
    )
    assert pin_call in es.calls
    assert es.calls.index(pin_call) < shrink_i
    # The temp clears the pin so its shards spread normally.
    assert es.calls[shrink_i][3]["index.routing.allocation.require._name"] is None
    # Cleanup restores the source: write-block AND node pin both cleared.
    clear_call = (
        "settings",
        "idx",
        {"index.blocks.write": None, "index.routing.allocation.require._name": None},
    )
    assert clear_call in es.calls

    delete_src = es.calls.index(("delete", "idx"))
    assert ("count", "idx__resize") in es.calls[:delete_src]
    assert ("count", "idx") in es.calls[:delete_src]
    assert ("reindex", "idx__resize", "idx") in es.calls
    assert es.calls.index(("reindex", "idx__resize", "idx")) < es.calls.index(("delete", "idx__resize"))
    assert not any("-shrink-" in n for n in es.targets())
    assert "idx__resize" not in es.present
    assert job.target_shards == 2
    assert job.task_id is None
    assert "in place" in job.detail


@pytest.mark.asyncio
async def test_should_abort_and_preserve_source_when_copy_count_mismatches():
    # temp ends up with fewer docs than source -> abort before deleting source.
    es = FakeES(counts={"idx": 100, "idx__resize": 99}, present={"idx"})
    job = SimpleNamespace(
        index_name="idx", current_shards=2, target_shards=6, current_replicas=1, detail="", task_id="x"
    )

    with pytest.raises(ValueError, match="mismatched doc count"):
        await execute_split_shards(es, job, delay=0)

    # Source is NEVER deleted; the bad temp IS deleted.
    assert ("delete", "idx") not in es.calls
    assert "idx" in es.present
    assert ("delete", "idx__resize") in es.calls
    assert "idx__resize" not in es.present
    # No reindex-back was attempted.
    assert "reindex" not in es.ops()


@pytest.mark.asyncio
async def test_should_resume_reindex_when_source_missing_but_temp_exists():
    # A prior attempt already deleted source after a verified copy; temp survives.
    es = FakeES(counts={"idx": 50, "idx__resize": 50}, present={"idx__resize"})
    job = SimpleNamespace(
        index_name="idx", current_shards=2, target_shards=6, current_replicas=1, detail="", task_id="x"
    )

    await execute_split_shards(es, job, delay=0)

    # No re-split: we recover straight into recreate + reindex-back.
    assert "split" not in es.ops()
    assert ("create", "idx", {"index.number_of_shards": 6, "index.number_of_replicas": 1}) in es.calls
    assert ("reindex", "idx__resize", "idx") in es.calls
    assert ("delete", "idx__resize") in es.calls
    assert "idx__resize" not in es.present
    assert "idx" in es.present
    assert job.target_shards == 6
    assert job.task_id is None


class _ShardSeqES:
    """Serves a scripted sequence of ``_cat/shards`` frames (last frame repeats)."""

    def __init__(self, frames: list[list[dict]]) -> None:
        self.frames = frames
        self.reads = 0

    async def cat_shards_detailed(self) -> list[dict]:
        frame = self.frames[min(self.reads, len(self.frames) - 1)]
        self.reads += 1
        return frame


@pytest.mark.asyncio
async def test_should_block_shrink_preflight_until_every_primary_is_started_on_node():
    """The wait reads the shard table, blocks while any primary RELOCATES, ignores off-node replicas.

    Regression: ``_cluster/health`` reports ``relocating==0`` right after a ``require._name`` pin,
    before the reroute surfaces — trusting it let ``_shrink`` fire mid-relocation and 500.
    """
    scattered = [
        {"index": "idx", "shard": "0", "prirep": "p", "state": "RELOCATING", "node": "es-d1 -> es-d2"},
        {"index": "idx", "shard": "1", "prirep": "p", "state": "STARTED", "node": "es-d2"},
    ]
    colocated = [
        {"index": "idx", "shard": "0", "prirep": "p", "state": "STARTED", "node": "es-d2"},
        {"index": "idx", "shard": "1", "prirep": "p", "state": "STARTED", "node": "es-d2"},
        {"index": "idx", "shard": "0", "prirep": "r", "state": "STARTED", "node": "es-d5"},  # replica off-node: OK
    ]
    es = _ShardSeqES([scattered, scattered, colocated])

    await wait_until_primaries_on_node(es, "idx", "es-d2", attempts=10, delay=0)

    assert es.reads == 3  # blocked through both scattered frames, returned on the colocated one


@pytest.mark.asyncio
async def test_should_time_out_when_primaries_never_colocate():
    es = _ShardSeqES([[{"index": "idx", "shard": "0", "prirep": "p", "state": "RELOCATING", "node": "a -> b"}]])
    with pytest.raises(TimeoutError, match="colocate"):
        await wait_until_primaries_on_node(es, "idx", "b", attempts=3, delay=0)
