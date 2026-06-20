from pydantic import BaseModel


class Opportunity(BaseModel):
    type: str
    severity: str
    detail: str
    wasted_shards: int
    target_shards: int


class AnalyzedIndex(BaseModel):
    name: str
    health: str
    status: str
    pri_count: int
    rep_count: int
    doc_count: int
    pri_store_bytes: int
    store_bytes: int
    avg_shard_size_gb: float
    max_shard_size_gb: float
    max_segments_per_shard: int
    shard_size_cv: float
    opportunities: list[Opportunity]
    opportunity_count: int
    wasted_shards: int


class AnalysisResponse(BaseModel):
    total_indices: int
    total_with_opportunities: int
    total_wasted_shards: int
    indices: list[AnalyzedIndex]
