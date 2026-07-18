"""Tests for POST /api/clusters/{cluster_id}/jobs/relocate endpoint (Task 8)."""

from httpx import AsyncClient

from backend.dependencies import get_job_runner
from backend.main import app
from backend.models.cluster import Cluster
from backend.models.job import Job
from backend.models.run import Run
from backend.schemas.job import JobResponse
from tests.conftest import test_session_factory


async def _create_cluster(
    client: AsyncClient,
    *,
    name: str = "test-cluster",
    read_only: bool = False,
) -> int:
    """Create a cluster via the API and return its id."""
    resp = await client.post(
        "/api/clusters",
        json={"name": name, "url": "https://es.example.com:9200"},
    )
    cluster_id: int = resp.json()["id"]

    if read_only:
        # Patch directly so we don't depend on a settings route
        async with test_session_factory() as s:
            cluster = await s.get(Cluster, cluster_id)
            cluster.read_only = True
            await s.commit()

    return cluster_id


class _FakeRunner:
    """Minimal stand-in for JobRunner that records submit calls."""

    def __init__(self) -> None:
        self.submitted: list[int] = []

    def submit(self, job_id: int) -> None:  # noqa: D401
        self.submitted.append(job_id)


# ---------------------------------------------------------------------------
# Happy-path test
# ---------------------------------------------------------------------------


async def test_should_create_relocate_job_and_hand_off_to_runner(
    authed_client: AsyncClient,
) -> None:
    """POST /relocate creates a queued job, calls runner.submit, returns the job."""
    cluster_id = await _create_cluster(authed_client, name="cluster-relo")

    fake_runner = _FakeRunner()
    app.dependency_overrides[get_job_runner] = lambda: fake_runner

    try:
        resp = await authed_client.post(
            f"/api/clusters/{cluster_id}/jobs/relocate",
            json={
                "index": "my_index",
                "shard": 2,
                "from_node": "node-a",
                "to_node": "node-b",
            },
        )
    finally:
        app.dependency_overrides.pop(get_job_runner, None)

    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Status must be 'queued' immediately (runner promotes to 'executing' on slot acquisition)
    assert body["status"] == "queued"
    assert body["job_type"] == "relocate_shard"
    assert body["index_name"] == "my_index"
    assert body["cluster_id"] == cluster_id

    # Relocate-specific fields must be present on the response
    assert body["shard_number"] == 2
    assert body["from_node"] == "node-a"
    assert body["to_node"] == "node-b"
    assert body["node_name"] == "node-b"  # node_name == to_node
    assert body["progress"] == "queued"

    # Runner must have been called with the new job id
    assert len(fake_runner.submitted) == 1
    assert fake_runner.submitted[0] == body["id"]


# ---------------------------------------------------------------------------
# Read-only cluster → 403, runner NOT called
# ---------------------------------------------------------------------------


async def test_should_reject_relocate_on_read_only_cluster(
    authed_client: AsyncClient,
) -> None:
    """POST /relocate returns 403 for a read-only cluster and does not submit."""
    cluster_id = await _create_cluster(authed_client, name="cluster-ro", read_only=True)

    fake_runner = _FakeRunner()
    app.dependency_overrides[get_job_runner] = lambda: fake_runner

    try:
        resp = await authed_client.post(
            f"/api/clusters/{cluster_id}/jobs/relocate",
            json={
                "index": "my_index",
                "shard": 0,
                "from_node": "node-a",
                "to_node": "node-b",
            },
        )
    finally:
        app.dependency_overrides.pop(get_job_runner, None)

    assert resp.status_code == 403
    assert fake_runner.submitted == []


# ---------------------------------------------------------------------------
# Schema serialization test: progress round-trips through JobResponse
# ---------------------------------------------------------------------------


async def test_should_serialize_progress_through_job_response() -> None:
    """A Job with progress set must expose it via JobResponse."""
    async with test_session_factory() as s:
        cluster = Cluster(name="schema-test", url="https://es.example.com:9200")
        s.add(cluster)
        await s.flush()

        run = Run(cluster_id=cluster.id)
        s.add(run)
        await s.flush()

        job = Job(
            run_id=run.id,
            cluster_id=cluster.id,
            index_name="idx",
            job_type="relocate_shard",
            tier=0,
            status="executing",
            shard_number=3,
            from_node="n1",
            to_node="n2",
            node_name="n2",
            progress="moving",
        )
        s.add(job)
        await s.commit()
        await s.refresh(job)

        schema = JobResponse.model_validate(job)
        assert schema.progress == "moving"
        assert schema.shard_number == 3
        assert schema.from_node == "n1"
        assert schema.to_node == "n2"
        assert schema.node_name == "n2"
