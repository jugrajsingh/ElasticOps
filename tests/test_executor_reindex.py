"""Tests for the reindex executor (ES Tasks API, async polled)."""

from types import SimpleNamespace

import pytest

from backend.services.executor import execute_reindex


class FakeES:
    def __init__(
        self,
        completes_after: int = 2,
        *,
        raise_get_task_times: int = 0,
        no_task_id: bool = False,
    ) -> None:
        self.started = False
        self._n = 0
        self._after = completes_after
        self._raise_times = raise_get_task_times
        self._no_task_id = no_task_id

    async def reindex_async(self, source, dest):  # noqa: ARG002
        self.started = True
        if self._no_task_id:
            return {}
        return {"task": "node:1"}

    async def get_task(self, task_id):  # noqa: ARG002
        if self._raise_times > 0:
            self._raise_times -= 1
            raise ConnectionError("transient ES failure")  # noqa: TRY003
        self._n += 1
        return {"completed": self._n >= self._after}


@pytest.mark.asyncio
async def test_should_start_reindex_and_poll_to_completion():
    es = FakeES(completes_after=2)
    job = SimpleNamespace(index_name="src", target_index="dst", task_id=None, detail="")
    await execute_reindex(es, job, delay=0)
    assert es.started
    assert job.task_id == "node:1"
    assert "src" in job.detail


@pytest.mark.asyncio
async def test_should_raise_timeout_when_reindex_never_completes():
    es = FakeES(completes_after=999)
    job = SimpleNamespace(index_name="src", target_index="dst", task_id=None, detail="")
    with pytest.raises(TimeoutError):
        await execute_reindex(es, job, attempts=3, delay=0)


@pytest.mark.asyncio
async def test_should_complete_reindex_after_transient_get_task_failure():
    # get_task raises once (transient network blip), then succeeds; the job must still complete.
    es = FakeES(completes_after=2, raise_get_task_times=1)
    job = SimpleNamespace(index_name="src", target_index="dst", task_id=None, detail="")
    await execute_reindex(es, job, delay=0)
    assert job.task_id == "node:1"
    assert "src" in job.detail


@pytest.mark.asyncio
async def test_should_raise_when_reindex_submit_returns_no_task_id():
    es = FakeES(no_task_id=True)
    job = SimpleNamespace(index_name="src", target_index="dst", task_id=None, detail="")
    with pytest.raises(RuntimeError):
        await execute_reindex(es, job, delay=0)
