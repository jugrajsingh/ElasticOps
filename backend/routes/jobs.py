from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.dependencies import get_es_client
from backend.models.job import Job
from backend.models.run import Run
from backend.routes.es import _parse_index, _parse_shard
from backend.schemas.job import JobResponse, JobSummary, RunResponse
from backend.services import executor
from backend.services.analyzer import IndexAnalyzer
from backend.services.es_client import ESClient
from backend.services.recommender import RecommendationEngine

router = APIRouter(prefix="/api/clusters/{cluster_id}/jobs", tags=["jobs"])


@router.post("/recommend", response_model=RunResponse)
async def recommend(
    cluster_id: int,
    es: ESClient = Depends(get_es_client),
    db: AsyncSession = Depends(get_db),
):
    """Run analysis and create recommended jobs."""
    raw_indices = await es.cat_indices_detailed()
    raw_shards = await es.cat_shards_detailed()

    indices = [_parse_index(i).model_dump() for i in raw_indices]
    shards = [_parse_shard(s).model_dump() for s in raw_shards]

    analyzer = IndexAnalyzer(indices, shards)
    results = analyzer.analyze_all()
    job_dicts = RecommendationEngine.generate_jobs(results)

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

    for j in job_dicts:
        job = Job(run_id=run.id, cluster_id=cluster_id, **j)
        db.add(job)

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
        executing=counts.get("executing", 0),
        completed=counts.get("completed", 0),
        failed=counts.get("failed", 0),
    )


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
    es: ESClient = Depends(get_es_client),
    db: AsyncSession = Depends(get_db),
):
    job = await _get_job(job_id, db)
    if job.status != "approved":
        raise HTTPException(400, f"Job is {job.status}, not approved")

    job.status = "executing"
    job.executed_at = datetime.now(UTC)
    await db.commit()

    try:
        if job.job_type == "force_merge":
            await executor.execute_force_merge(es, job)
        elif job.job_type == "reduce_shards":
            await executor.execute_reduce_shards(es, job)
        else:
            raise ValueError(f"Unknown job type: {job.job_type}")  # noqa: TRY003, TRY301
        job.status = "completed"
    except Exception as exc:
        job.status = "failed"
        job.error_message = str(exc)

    job.completed_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(job)
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


async def _get_job(job_id: int, db: AsyncSession) -> Job:
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Job not found")
    return job
