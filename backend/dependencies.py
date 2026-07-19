from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.cluster import Cluster
from backend.services.es_client import ESClient
from backend.services.job_runner import JobRunner
from backend.services.secrets import decrypt


def get_job_runner(request: Request) -> JobRunner:
    """Return the app-wide :class:`JobRunner` set on app state during the lifespan."""
    return request.app.state.job_runner


async def require_writable_cluster(cluster_id: int, db: AsyncSession) -> Cluster:
    """Return the cluster, or 409/403 if it cannot accept writes right now.

    An inactive cluster is rejected with 409 before the read-only check runs: deactivation is a
    harder gate than read-only (it blocks all ES contact, not just writes), and every job-creating
    or job-execution route in ``routes/jobs.py`` (execute, execute-all, drain, promote, reindex,
    relocate) calls this helper, so gating here closes the submission-time hole where a deactivated
    cluster could still accept new job executions. Jobs already executing when a cluster is
    deactivated are not affected by this gate and run to completion, since ``JobRunner`` holds its
    own ES client independent of this dependency; cancelling those jobs remains available too, as
    ``cancel_job`` does not depend on this helper.
    """
    cluster = await db.get(Cluster, cluster_id)
    if cluster is None:
        raise HTTPException(404, "Cluster not found")
    if not cluster.is_active:
        raise HTTPException(409, "Cluster is inactive; reactivate it to perform ES operations")
    if cluster.read_only:
        raise HTTPException(403, "cluster is read-only")
    return cluster


def build_es_client(cluster: Cluster) -> ESClient:
    """Construct an ESClient from a cluster row, decrypting stored credentials.

    No active/read-only gating here by design: callers that need those gates apply them
    themselves (see ``get_es_client`` and ``require_writable_cluster``). This is the shared
    construction step for callers that must reach ES on their own terms, such as the
    undrain-on-cancel branch in ``routes/jobs.py.cancel_job``, which must work even on a
    deactivated cluster.
    """
    return ESClient(
        base_url=cluster.url,
        username=cluster.username,
        password=decrypt(cluster.password_encrypted),
        verify_ssl=cluster.verify_ssl,
    )


async def get_es_client(cluster_id: int, db: AsyncSession = Depends(get_db)) -> ESClient:
    """Resolve cluster ID to an ESClient instance, rejecting inactive clusters.

    This is the single chokepoint every ``/es/*`` read/write and ES-backed job route resolves a
    client through, so gating here blocks ES access cluster-wide while the cluster is deactivated.
    DB-only endpoints (job list/summary, cluster CRUD) do not depend on this and keep working.
    """
    result = await db.execute(select(Cluster).where(Cluster.id == cluster_id))
    cluster = result.scalar_one_or_none()
    if not cluster:
        raise HTTPException(404, "Cluster not found")
    if not cluster.is_active:
        raise HTTPException(409, "Cluster is inactive; reactivate it to perform ES operations")

    return build_es_client(cluster)
