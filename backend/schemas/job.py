from datetime import datetime

from pydantic import BaseModel


class RelocateRequest(BaseModel):
    index: str
    shard: int
    from_node: str
    to_node: str


class DrainRequest(BaseModel):
    node: str


class PromoteRequest(BaseModel):
    source: str
    target: str
    alias: str
    delete_source: bool = False


class ReindexRequest(BaseModel):
    source: str
    dest: str


class RecommendRequest(BaseModel):
    detectors: list[str] | None = None  # opportunity types to include; None/[] = all


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
    fingerprint: str | None = None
    status: str
    approved_at: datetime | None
    executed_at: datetime | None
    completed_at: datetime | None
    task_id: str | None
    error_message: str | None
    # Relocate / drain / promote fields — optional so existing job types still serialize cleanly
    progress: str | None = None
    node_name: str | None = None
    target_index: str | None = None
    shard_number: int | None = None
    from_node: str | None = None
    to_node: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class JobSummary(BaseModel):
    total: int
    pending: int
    approved: int
    queued: int
    executing: int
    completed: int
    failed: int
    cancelled: int = 0
    rejected: int = 0


class ConcurrencyResponse(BaseModel):
    max_concurrent: int


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
