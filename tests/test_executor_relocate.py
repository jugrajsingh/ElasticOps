from types import SimpleNamespace

import pytest

from backend.services.executor import execute_relocate_shard


class FakeES:
    """Scripted ES double: serves cat_shards rows, flips to 'after-move' rows once rerouted."""

    def __init__(self, before: list[dict], after: list[dict]) -> None:
        self.before = before
        self.after = after
        self.moved = False
        self.reroute_calls: list[list[dict]] = []

    async def cat_shards_detailed(self) -> list[dict]:
        return self.after if self.moved else self.before

    async def reroute(self, commands: list[dict]) -> dict:
        self.reroute_calls.append(commands)
        self.moved = True
        return {"acknowledged": True}


def _job() -> SimpleNamespace:
    return SimpleNamespace(index_name="i", shard_number=0, from_node="a", to_node="b", detail="")


async def test_relocate_moves_then_confirms_started_on_target():
    es = FakeES(
        before=[{"index": "i", "shard": "0", "prirep": "p", "node": "a", "state": "STARTED"}],
        after=[{"index": "i", "shard": "0", "prirep": "p", "node": "b", "state": "STARTED"}],
    )
    job = _job()
    await execute_relocate_shard(es, job, delay=0)
    assert es.moved is True
    assert len(es.reroute_calls) == 1
    move = es.reroute_calls[0][0]["move"]
    assert move == {"index": "i", "shard": 0, "from_node": "a", "to_node": "b"}
    assert "b" in job.detail


async def test_relocate_confirms_via_replica_copy_on_target():
    """Confirmation is 'any copy STARTED on to_node' — a replica row on to_node suffices."""
    es = FakeES(
        before=[
            {"index": "i", "shard": "0", "prirep": "p", "node": "a", "state": "STARTED"},
            {"index": "i", "shard": "0", "prirep": "r", "node": "c", "state": "STARTED"},
        ],
        after=[
            {"index": "i", "shard": "0", "prirep": "p", "node": "a", "state": "STARTED"},
            {"index": "i", "shard": "0", "prirep": "r", "node": "b", "state": "STARTED"},
        ],
    )
    job = _job()
    await execute_relocate_shard(es, job, delay=0)
    assert es.moved is True
    assert "b" in job.detail


async def test_relocate_is_idempotent_when_already_on_target():
    """A copy already STARTED on to_node → return without rerouting."""
    es = FakeES(
        before=[{"index": "i", "shard": "0", "prirep": "p", "node": "b", "state": "STARTED"}],
        after=[],
    )
    job = _job()
    await execute_relocate_shard(es, job, delay=0)
    assert es.moved is False
    assert es.reroute_calls == []
    assert "already" in job.detail.lower()
    assert "b" in job.detail


async def test_relocate_matches_shard_number_as_string_or_int():
    """Shard rows carry shard as a string; an int job.shard_number must still match."""
    es = FakeES(
        before=[{"index": "i", "shard": "3", "prirep": "p", "node": "b", "state": "STARTED"}],
        after=[],
    )
    job = SimpleNamespace(index_name="i", shard_number=3, from_node="a", to_node="b", detail="")
    await execute_relocate_shard(es, job, delay=0)
    assert es.moved is False  # idempotent — shard 3 already on b


async def test_relocate_relocating_state_does_not_confirm():
    """A copy on to_node that is still RELOCATING is not 'done' — neither idempotent nor confirmed."""
    es = FakeES(
        before=[{"index": "i", "shard": "0", "prirep": "p", "node": "b", "state": "RELOCATING"}],
        after=[{"index": "i", "shard": "0", "prirep": "p", "node": "b", "state": "RELOCATING"}],
    )
    job = _job()
    with pytest.raises(TimeoutError):
        await execute_relocate_shard(es, job, attempts=3, delay=0)
    assert es.moved is True  # not idempotent (state was RELOCATING), so reroute was issued


async def test_relocate_times_out_when_never_started_on_target():
    es = FakeES(
        before=[{"index": "i", "shard": "0", "prirep": "p", "node": "a", "state": "STARTED"}],
        after=[{"index": "i", "shard": "0", "prirep": "p", "node": "a", "state": "STARTED"}],
    )
    job = _job()
    with pytest.raises(TimeoutError):
        await execute_relocate_shard(es, job, attempts=3, delay=0)
    assert es.moved is True


async def test_relocate_reports_progress():
    es = FakeES(
        before=[{"index": "i", "shard": "0", "prirep": "p", "node": "a", "state": "STARTED"}],
        after=[{"index": "i", "shard": "0", "prirep": "p", "node": "b", "state": "STARTED"}],
    )
    job = _job()
    messages: list[str] = []

    async def on_progress(text: str) -> None:
        messages.append(text)

    await execute_relocate_shard(es, job, on_progress=on_progress, delay=0)
    assert messages
    assert any("b" in m for m in messages)
