import pytest
from fastapi import HTTPException

from backend.dependencies import require_writable_cluster
from backend.models.cluster import Cluster
from tests.conftest import test_session_factory  # in-memory; autouse setup_db creates/drops tables


@pytest.mark.asyncio
async def test_should_reject_writes_on_readonly_cluster():
    async with test_session_factory() as s:
        c = Cluster(name="ro", url="http://es.example.com", read_only=True)
        s.add(c)
        await s.commit()
        with pytest.raises(HTTPException) as ei:
            await require_writable_cluster(c.id, s)
        assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_should_allow_writes_on_writable_cluster():
    async with test_session_factory() as s:
        c = Cluster(name="rw", url="http://es.example.com", read_only=False)
        s.add(c)
        await s.commit()
        assert (await require_writable_cluster(c.id, s)).id == c.id


@pytest.mark.asyncio
async def test_should_raise_404_when_cluster_missing():
    async with test_session_factory() as s:
        with pytest.raises(HTTPException) as ei:
            await require_writable_cluster(9999, s)
        assert ei.value.status_code == 404
