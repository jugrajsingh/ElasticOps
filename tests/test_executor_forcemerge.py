"""Tests for the force-merge / expunge executors (ES Tasks API, async polled)."""

from types import SimpleNamespace

import pytest

from backend.services.executor import execute_expunge_deletes, execute_force_merge


class FakeES:
    """Scripted ES double: submits a force-merge task, then completes after N polls.

    ``task_result`` is merged into the completed task response so a test can inject a task-level
    failure (top-level ``error`` or per-shard ``response._shards`` failures).
    """

    def __init__(self, *, completes_after: int = 2, task_result: dict | None = None) -> None:
        self.submitted_index: str | None = None
        self.only_expunge_deletes: bool | None = None
        self.poll_count = 0
        self._after = completes_after
        self._result = task_result or {}

    async def forcemerge_async(self, index: str, *, only_expunge_deletes: bool = False) -> dict:
        self.submitted_index = index
        self.only_expunge_deletes = only_expunge_deletes
        return {"task": "node:7"}

    async def get_task(self, task_id: str) -> dict:  # noqa: ARG002
        self.poll_count += 1
        if self.poll_count >= self._after:
            return {"completed": True, **self._result}
        return {"completed": False}


@pytest.mark.asyncio
async def test_should_submit_forcemerge_async_and_poll_to_completion():
    # A long merge completes only after several polls; no synchronous POST, so no read timeout.
    es = FakeES(completes_after=3)
    job = SimpleNamespace(index_name="idx", task_id=None, detail="")
    await execute_force_merge(es, job, delay=0)
    assert es.submitted_index == "idx"
    assert es.only_expunge_deletes is False
    assert es.poll_count >= 3
    assert job.task_id == "node:7"
    assert "idx" in job.detail


@pytest.mark.asyncio
async def test_should_submit_expunge_deletes_with_only_expunge_flag():
    es = FakeES(completes_after=2)
    job = SimpleNamespace(index_name="idx", task_id=None, detail="")
    await execute_expunge_deletes(es, job, delay=0)
    assert es.only_expunge_deletes is True
    assert job.task_id == "node:7"
    assert "idx" in job.detail


@pytest.mark.asyncio
async def test_should_raise_when_forcemerge_task_reports_shard_failure():
    es = FakeES(
        completes_after=1,
        task_result={
            "response": {"_shards": {"total": 5, "successful": 4, "failed": 1, "failures": [{"reason": "disk full"}]}}
        },
    )
    job = SimpleNamespace(index_name="idx", task_id=None, detail="")
    with pytest.raises(RuntimeError, match="disk full"):
        await execute_force_merge(es, job, delay=0)


@pytest.mark.asyncio
async def test_should_raise_when_forcemerge_task_reports_top_level_error():
    es = FakeES(completes_after=1, task_result={"error": {"type": "x", "reason": "node crashed"}})
    job = SimpleNamespace(index_name="idx", task_id=None, detail="")
    with pytest.raises(RuntimeError, match="node crashed"):
        await execute_force_merge(es, job, delay=0)


@pytest.mark.asyncio
async def test_should_raise_timeout_when_forcemerge_never_completes():
    es = FakeES(completes_after=999)
    job = SimpleNamespace(index_name="idx", task_id=None, detail="")
    with pytest.raises(TimeoutError):
        await execute_force_merge(es, job, attempts=3, delay=0)
