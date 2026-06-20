from datetime import datetime

from pydantic import BaseModel


class JobResponse(BaseModel):
    id: int
    run_id: int
    cluster_id: int
    index_name: str
    job_type: str
    tier: int
    severity: str
    detail: str
    current_shards: int
    target_shards: int
    current_replicas: int
    pri_store_bytes: int
    doc_count: int
    estimated_savings_shards: int
    status: str
    approved_at: datetime | None
    executed_at: datetime | None
    completed_at: datetime | None
    task_id: str | None
    error_message: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class JobSummary(BaseModel):
    total: int
    pending: int
    approved: int
    executing: int
    completed: int
    failed: int


class RunResponse(BaseModel):
    id: int
    cluster_id: int
    run_date: datetime
    total_indices: int
    total_shards: int
    total_storage_bytes: int
    total_opportunities: int
    total_wasted_shards: int

    model_config = {"from_attributes": True}
