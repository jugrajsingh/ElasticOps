from pydantic import BaseModel


class ClusterHealthResponse(BaseModel):
    cluster_name: str
    status: str
    number_of_nodes: int
    number_of_data_nodes: int
    active_primary_shards: int
    active_shards: int
    relocating_shards: int
    initializing_shards: int
    unassigned_shards: int


class NodeInfo(BaseModel):
    name: str
    role: str
    ip: str
    version: str
    disk_total: int
    disk_used: int
    disk_used_percent: float
    heap_max: int
    heap_current: int
    heap_percent: float
    cpu: float
    load_1m: float
    segments_count: int


class IndexInfo(BaseModel):
    health: str
    status: str
    index: str
    pri: int
    rep: int
    docs_count: int
    store_size: int
    pri_store_size: int


class ShardInfo(BaseModel):
    index: str
    shard: int
    prirep: str
    state: str
    docs: int
    store: int
    node: str | None
    segments_count: int


class RecoveryInfo(BaseModel):
    index: str
    shard: int
    source_node: str
    target_node: str
    bytes_total: int
    bytes_recovered: int
    bytes_percent: str


class StorageGroup(BaseModel):
    name: str
    size_bytes: int


class NodeRoleCounts(BaseModel):
    master: int = 0
    data: int = 0
    coord: int = 0
    ingest: int = 0
    other: int = 0


class OverviewResponse(BaseModel):
    health: ClusterHealthResponse
    index_count: int
    nodes: list[NodeInfo]
    recoveries: list[RecoveryInfo]
    storage_breakdown: list[StorageGroup]
    node_role_counts: NodeRoleCounts


class ShardMapResponse(BaseModel):
    nodes: list[NodeInfo]
    indices: list[IndexInfo]
    shards: list[ShardInfo]
