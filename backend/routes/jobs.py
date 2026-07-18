import hashlib
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import require_cluster_access
from backend.database import get_db
from backend.dependencies import build_es_client, get_es_client, get_job_runner, require_writable_cluster
from backend.models.cluster import Cluster
from backend.models.job import Job
from backend.models.run import Run
from backend.routes.es import _parse_index, _parse_shard
from backend.schemas.job import (
    ConcurrencyResponse,
    DrainRequest,
    JobResponse,
    JobSummary,
    PromoteRequest,
    RecommendRequest,
    ReindexRequest,
    RelocateRequest,
    RunResponse,
)
from backend.services.analyzer import IndexAnalyzer
from backend.services.es_client import ESClient
from backend.services.job_runner import JobRunner
from backend.services.recommender import RecommendationEngine

router = APIRouter(
    prefix="/api/clusters/{cluster_id}/jobs",
    tags=["jobs"],
    dependencies=[Depends(require_cluster_access)],
)


# Every opportunity type the analyzer can emit.
ALL_DETECTORS = {"over-sharded", "under-sharded", "segment-fragmentation", "shard-imbalance", "deleted-docs"}

# Opportunity type -> recommended job_type. ``shard-imbalance`` is advisory only (no job), so it is absent here.
OPP_TO_JOB = {
    "over-sharded": "reduce_shards",
    "under-sharded": "split_shards",
    "segment-fragmentation": "force_merge",
    "deleted-docs": "expunge_deletes",
}

# Columns refreshed in place when a suggestion's fingerprint already exists as a pending job.
_REFRESHABLE_FIELDS = (
    "severity",
    "target_shards",
    "current_shards",
    "current_replicas",
    "detail",
    "pri_store_bytes",
    "doc_count",
    "tier",
    "estimated_savings_shards",
)


@router.post("/recommend", response_model=RunResponse)
async def recommend(
    cluster_id: int,
    body: RecommendRequest | None = None,
    es: ESClient = Depends(get_es_client),
    db: AsyncSession = Depends(get_db),
):
    """Run analysis and reconcile recommended jobs via per-suggestion fingerprints.

    Detectors can be scoped via ``body.detectors`` (None/empty = all). Reconciliation is
    fingerprint-based and scoped to the selected detectors' job_types: resolved suggestions are
    deleted, unchanged ones are updated in place (stable row id), and new ones are inserted —
    suggestions belonging to detectors not in scope are left untouched.
    """
    selected = (set(body.detectors) & ALL_DETECTORS) if (body and body.detectors) else set(ALL_DETECTORS)
    selected_job_types = {OPP_TO_JOB[d] for d in selected if d in OPP_TO_JOB}

    raw_indices = await es.cat_indices_detailed()
    raw_shards = await es.cat_shards_detailed()

    indices = [_parse_index(i).model_dump() for i in raw_indices]
    shards = [_parse_shard(s).model_dump() for s in raw_shards]

    analyzer = IndexAnalyzer(indices, shards)
    results = analyzer.analyze_all()
    for result in results:
        result["opportunities"] = [o for o in result.get("opportunities", []) if o["type"] in selected]
    job_dicts = RecommendationEngine.generate_jobs(results)

    for jd in job_dicts:
        jd["fingerprint"] = hashlib.sha256(f"{cluster_id}:{jd['index_name']}:{jd['job_type']}".encode()).hexdigest()[
            :16
        ]

    total_shards = sum(i.get("pri", 0) * (1 + i.get("rep", 0)) for i in indices)
    total_storage = sum(i.get("pri_store_size", 0) for i in indices)
    total_wasted = sum(j["estimated_savings_shards"] for j in job_dicts)

    run = Run(
        cluster_id=cluster_id,
        total_indices=len(results),
        total_shards=total_shards,
        total_storage_bytes=total_storage,
        total_opportunities=len(job_dicts),
        total_wasted_shards=total_wasted,
    )
    db.add(run)
    await db.flush()

    existing_result = await db.execute(
        select(Job).where(
            Job.cluster_id == cluster_id,
            Job.status == "pending",
            Job.job_type.in_(selected_job_types),
        )
    )
    existing = list(existing_result.scalars().all())

    # Fingerprints the operator has already acted on (approved, or in the execution pipeline). A new
    # suggestion matching one of these must NOT be regenerated as a fresh pending row — otherwise an
    # already-approved/queued/executing opportunity reappears on every Run Analysis.
    active_result = await db.execute(
        select(Job.fingerprint).where(
            Job.cluster_id == cluster_id,
            Job.status.in_(("approved", "queued", "executing")),
            Job.job_type.in_(selected_job_types),
        )
    )
    active_fps = {fp for (fp,) in active_result.all() if fp}

    new_by_fp = {jd["fingerprint"]: jd for jd in job_dicts}
    existing_by_fp = {j.fingerprint: j for j in existing if j.fingerprint}

    # Delete pending jobs whose suggestion is no longer produced (resolved).
    for job in existing:
        if job.fingerprint not in new_by_fp:
            await db.delete(job)

    for fp, jd in new_by_fp.items():
        match = existing_by_fp.get(fp)
        if match is not None:
            for field in _REFRESHABLE_FIELDS:
                setattr(match, field, jd[field])
            match.run_id = run.id
        elif fp in active_fps:
            continue  # already approved/queued/executing — operator owns it; don't regenerate
        else:
            db.add(Job(run_id=run.id, cluster_id=cluster_id, **jd))

    await db.commit()
    await db.refresh(run)
    return run


@router.get("", response_model=list[JobResponse])
async def list_jobs(
    cluster_id: int,
    status: str | None = None,
    tier: int | None = None,
    job_type: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(Job).where(Job.cluster_id == cluster_id)
    if status:
        query = query.where(Job.status == status)
    if tier is not None:
        query = query.where(Job.tier == tier)
    if job_type:
        query = query.where(Job.job_type == job_type)
    query = query.order_by(Job.tier, Job.pri_store_bytes.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/summary", response_model=JobSummary)
async def job_summary(cluster_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job.status, func.count()).where(Job.cluster_id == cluster_id).group_by(Job.status))
    counts = dict(result.all())
    total = sum(counts.values())
    return JobSummary(
        total=total,
        pending=counts.get("pending", 0),
        approved=counts.get("approved", 0),
        queued=counts.get("queued", 0),
        executing=counts.get("executing", 0),
        completed=counts.get("completed", 0),
        failed=counts.get("failed", 0),
        cancelled=counts.get("cancelled", 0),
        rejected=counts.get("rejected", 0),
    )


@router.get("/concurrency", response_model=ConcurrencyResponse)
async def job_concurrency(
    cluster_id: int,  # noqa: ARG001 — path param for router prefix; the cap is global
    runner: JobRunner = Depends(get_job_runner),
) -> ConcurrencyResponse:
    """Report the runner's global concurrency cap so the UI can show how deep the queue runs."""
    return ConcurrencyResponse(max_concurrent=runner.max_concurrent)


@router.put("/{job_id}/approve", response_model=JobResponse)
async def approve_job(job_id: int, db: AsyncSession = Depends(get_db)):
    job = await _get_job(job_id, db)
    if job.status != "pending":
        raise HTTPException(400, f"Job is {job.status}, not pending")
    job.status = "approved"
    job.approved_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(job)
    return job


@router.put("/{job_id}/reject", response_model=JobResponse)
async def reject_job(job_id: int, db: AsyncSession = Depends(get_db)):
    job = await _get_job(job_id, db)
    if job.status != "pending":
        raise HTTPException(400, f"Job is {job.status}, not pending")
    job.status = "rejected"
    await db.commit()
    await db.refresh(job)
    return job


@router.post("/{job_id}/execute", response_model=JobResponse)
async def execute_job(
    job_id: int,
    cluster_id: int,
    db: AsyncSession = Depends(get_db),
    runner: JobRunner = Depends(get_job_runner),
):
    """Queue an approved job and hand it to the background runner.

    Returns immediately with status ``queued``; the runner flips it to ``executing`` once a
    concurrency slot is free, then drives it to its terminal state.
    """
    job = await _get_job(job_id, db)
    if job.status != "approved":
        raise HTTPException(400, f"Job is {job.status}, not approved")
    await require_writable_cluster(cluster_id, db)

    job.status = "queued"
    job.executed_at = datetime.now(UTC)
    job.progress = "queued"
    await db.commit()
    await db.refresh(job)

    runner.submit(job.id)
    return job


@router.put("/bulk-approve")
async def bulk_approve(
    cluster_id: int,
    tier: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(Job).where(Job.cluster_id == cluster_id, Job.status == "pending")
    if tier is not None:
        query = query.where(Job.tier == tier)
    result = await db.execute(query)
    jobs = result.scalars().all()
    now = datetime.now(UTC)
    for job in jobs:
        job.status = "approved"
        job.approved_at = now
    await db.commit()
    return {"approved": len(jobs)}


@router.post("/execute-all")
async def execute_all(
    cluster_id: int,
    db: AsyncSession = Depends(get_db),
    runner: JobRunner = Depends(get_job_runner),
):
    """Enqueue every approved job for the cluster (sets queued + submits to the runner).

    Jobs are flipped to ``queued`` and submitted; the runner promotes at most
    ``max_concurrent`` of them to ``executing`` at a time, leaving the rest visibly queued.
    """
    await require_writable_cluster(cluster_id, db)
    result = await db.execute(select(Job).where(Job.cluster_id == cluster_id, Job.status == "approved"))
    jobs = result.scalars().all()

    # Gate: at most one in-flight job per index. Two operations on the same index running at once
    # (e.g. force_merge racing an in-place resize) corrupt each other, so a job whose index already
    # has a queued/executing job — or one enqueued earlier in this same batch — is left ``approved``
    # for a later run. The temp-index isolation that would make same-index concurrency fully safe is
    # tracked in the operations-subsystem refactor.
    busy_result = await db.execute(
        select(Job.index_name).where(Job.cluster_id == cluster_id, Job.status.in_(("queued", "executing")))
    )
    busy_indexes = {name for (name,) in busy_result.all()}

    now = datetime.now(UTC)
    ids = []
    for job in jobs:
        if job.index_name in busy_indexes:
            continue  # another job for this index is already in flight; leave this one approved
        busy_indexes.add(job.index_name)
        job.status = "queued"
        job.executed_at = now
        job.progress = "queued"
        ids.append(job.id)
    await db.commit()
    for jid in ids:
        runner.submit(jid)
    return {"queued": len(ids), "skipped": len(jobs) - len(ids)}


@router.post("/clear-queue")
async def clear_queue(
    cluster_id: int,
    db: AsyncSession = Depends(get_db),
    runner: JobRunner = Depends(get_job_runner),
):
    """Dequeue everything not yet running for the cluster (leaves ``executing`` jobs alone).

    ``approved`` jobs were never submitted, so they are simply deleted. ``queued`` jobs are waiting
    on a runner slot, so we cancel their tasks (the runner flips them to ``cancelled``) and leave the
    rows in place. Returns the combined count of approved + queued jobs that were cleared.
    """
    result = await db.execute(select(Job).where(Job.cluster_id == cluster_id, Job.status.in_(("approved", "queued"))))
    jobs = result.scalars().all()
    queued_ids = [job.id for job in jobs if job.status == "queued"]
    for job in jobs:
        if job.status == "approved":
            await db.delete(job)
    await db.commit()
    for jid in queued_ids:
        await runner.cancel(jid)
    return {"cleared": len(jobs)}


@router.post("/clear-history")
async def clear_history(cluster_id: int, db: AsyncSession = Depends(get_db)):
    """Delete all terminal-status jobs (completed/failed/cancelled/rejected) for the cluster."""
    result = await db.execute(
        delete(Job).where(
            Job.cluster_id == cluster_id,
            Job.status.in_(("completed", "failed", "cancelled", "rejected")),
        )
    )
    await db.commit()
    return {"cleared": result.rowcount}


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: int,
    cluster_id: int,
    db: AsyncSession = Depends(get_db),
    runner: JobRunner = Depends(get_job_runner),
):
    """Cancel a queued or executing job. For drain_node jobs, removes the allocation exclusion first.

    Does not depend on ``get_es_client``: cancelling a job must stay available even when the
    cluster has been deactivated (an admin deactivating a misbehaving cluster must still be able
    to cancel a still-executing job on it, rather than being forced to reactivate first). Only the
    drain_node undrain branch below needs ES access, so it resolves its own client directly from
    the cluster row, unaffected by the ``is_active`` gate that ``get_es_client`` enforces.
    """
    job = await _get_job(job_id, db)
    if job.status not in ("queued", "executing"):
        raise HTTPException(400, f"Job is {job.status}, not queued or executing")
    if job.job_type == "drain_node" and job.node_name:
        from backend.services import executor

        cluster = await db.get(Cluster, cluster_id)
        if cluster is None:
            raise HTTPException(404, "Cluster not found")
        es = build_es_client(cluster)
        await executor.undrain_node(es, job.node_name)
    await runner.cancel(job_id)
    return job  # runner sets terminal status asynchronously; client re-polls


async def _get_job(job_id: int, db: AsyncSession) -> Job:
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Job not found")
    return job


async def _ensure_run(db: AsyncSession, cluster_id: int) -> Run:
    """Create a fresh Run row for an operator-initiated job (relocate/drain) and return it.

    Run has no status column, so each manual operation gets its own run grouping rather than
    reusing a prior analysis run.
    """
    run = Run(cluster_id=cluster_id)
    db.add(run)
    await db.flush()
    return run


@router.post("/drain", response_model=JobResponse)
async def drain_node(
    cluster_id: int,
    body: DrainRequest,
    db: AsyncSession = Depends(get_db),
    es: ESClient = Depends(get_es_client),
    runner: JobRunner = Depends(get_job_runner),
) -> Job:
    """Run drain pre-flight and, if safe, create a drain_node job and hand it to the runner."""
    await require_writable_cluster(cluster_id, db)
    from backend.services import drain

    ok, reason = drain.preflight(body.node, await es.cat_nodes_detailed(), await es.cat_shards_detailed())
    if not ok:
        raise HTTPException(400, reason)
    run = await _ensure_run(db, cluster_id)
    job = Job(
        run_id=run.id,
        cluster_id=cluster_id,
        index_name="",
        job_type="drain_node",
        tier=0,
        status="queued",
        node_name=body.node,
        executed_at=datetime.now(UTC),
        progress="queued",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    runner.submit(job.id)
    return job


@router.post("/promote", response_model=JobResponse)
async def promote_index(
    cluster_id: int,
    body: PromoteRequest,
    db: AsyncSession = Depends(get_db),
    runner: JobRunner = Depends(get_job_runner),
) -> Job:
    """Promote a shrunk/split copy: swap an alias onto it (and optionally delete the old source)."""
    await require_writable_cluster(cluster_id, db)
    run = await _ensure_run(db, cluster_id)
    job = Job(
        run_id=run.id,
        cluster_id=cluster_id,
        index_name=body.source,
        job_type="promote_index",
        tier=0,
        status="queued",
        node_name=body.alias,
        target_index=body.target,
        from_node="delete" if body.delete_source else None,
        executed_at=datetime.now(UTC),
        progress="queued",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    runner.submit(job.id)
    return job


@router.post("/reindex", response_model=JobResponse)
async def reindex(
    cluster_id: int,
    body: ReindexRequest,
    db: AsyncSession = Depends(get_db),
    runner: JobRunner = Depends(get_job_runner),
) -> Job:
    """Reindex ``source`` into ``dest`` via the ES Tasks API (async, non-destructive)."""
    await require_writable_cluster(cluster_id, db)
    run = await _ensure_run(db, cluster_id)
    job = Job(
        run_id=run.id,
        cluster_id=cluster_id,
        index_name=body.source,
        job_type="reindex",
        tier=0,
        status="queued",
        target_index=body.dest,
        executed_at=datetime.now(UTC),
        progress="queued",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    runner.submit(job.id)
    return job


@router.post("/relocate", response_model=JobResponse)
async def relocate_shard(
    cluster_id: int,
    body: RelocateRequest,
    db: AsyncSession = Depends(get_db),
    runner: JobRunner = Depends(get_job_runner),
) -> Job:
    """Create a relocate_shard job and immediately hand it to the background runner."""
    await require_writable_cluster(cluster_id, db)
    run = await _ensure_run(db, cluster_id)
    job = Job(
        run_id=run.id,
        cluster_id=cluster_id,
        index_name=body.index,
        job_type="relocate_shard",
        tier=0,
        status="queued",
        shard_number=body.shard,
        from_node=body.from_node,
        to_node=body.to_node,
        node_name=body.to_node,
        executed_at=datetime.now(UTC),
        progress="queued",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    runner.submit(job.id)
    return job
