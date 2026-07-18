import pytest
from sqlalchemy import select

from backend.models.cluster import Cluster
from backend.models.job import Job
from backend.models.run import Run
from tests.conftest import test_session_factory


@pytest.mark.asyncio
async def test_should_persist_new_job_and_cluster_columns():
    async with test_session_factory() as s:
        c = Cluster(name="t", url="http://es.example.com", read_only=True)
        s.add(c)
        await s.flush()
        run = Run(cluster_id=c.id)
        s.add(run)
        await s.flush()
        j = Job(
            run_id=run.id,
            cluster_id=c.id,
            index_name="",
            job_type="drain_node",
            tier=0,
            node_name="es01",
            shard_number=2,
            from_node="es01",
            to_node="es02",
            progress="shards left: 3",
        )
        s.add(j)
        await s.commit()
        got = (await s.execute(select(Job).where(Job.id == j.id))).scalar_one()
        assert got.node_name == "es01"
        assert got.progress == "shards left: 3"
        assert (await s.get(Cluster, c.id)).read_only is True
