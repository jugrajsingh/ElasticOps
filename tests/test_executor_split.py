"""Tests for the split_shards executor (in-place ES _split + reindex-back workflow).

The split is now IN PLACE: ``idx`` is split into a temp ``idx__resize`` copy, verified, then
reindexed back so ``idx`` keeps its name with the new shard count and no ``idx-split-<n>`` survives.
"""

from types import SimpleNamespace

import pytest

from backend.services.executor import execute_split_shards, smallest_multiple_ge


def test_should_return_smallest_multiple_ge():
    assert smallest_multiple_ge(2, 5) == 6  # multiples of 2 >= 5 -> 6
    assert smallest_multiple_ge(3, 7) == 9
    assert smallest_multiple_ge(4, 4) == 4


class FakeES:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.present = {"idx"}

    async def set_index_settings(self, index, settings):
        self.calls.append(("settings", index, settings))

    async def split_index(self, source, target, settings):
        self.calls.append(("split", source, target, settings))
        self.present.add(target)

    async def index_health(self, index):
        if index not in self.present:
            raise RuntimeError("index_not_found_exception")
        return {"status": "green", "relocating_shards": 0}

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


@pytest.mark.asyncio
async def test_should_split_into_target_with_multiple_shards():
    es = FakeES()
    job = SimpleNamespace(
        index_name="idx",
        current_shards=2,
        target_shards=5,
        current_replicas=1,
        detail="",
        task_id=None,
    )
    await execute_split_shards(es, job, delay=0)
    split = next(c for c in es.calls if c[0] == "split")
    assert split[2] == "idx__resize"  # temp copy, not a suffixed survivor
    assert split[3]["index.number_of_shards"] == 6
    # In place: source is rebuilt with the new shard count and the temp is dropped.
    assert ("create", "idx", {"index.number_of_shards": 6, "index.number_of_replicas": 1}) in es.calls
    assert ("reindex", "idx__resize", "idx") in es.calls
    assert ("delete", "idx__resize") in es.calls
    assert not any("idx-split-" in str(c) for c in es.calls)
    assert job.task_id is None  # no suffixed index retained
    assert "in place" in job.detail.lower()
