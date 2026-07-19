from datetime import datetime

from pydantic import BaseModel


class ClusterCreate(BaseModel):
    name: str
    url: str
    username: str = ""
    password: str = ""
    verify_ssl: bool = True
    read_only: bool = False


class ClusterUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    username: str | None = None
    password: str | None = None
    verify_ssl: bool | None = None
    read_only: bool | None = None
    is_active: bool | None = None


class ClusterResponse(BaseModel):
    id: int
    name: str
    url: str
    username: str
    verify_ssl: bool
    is_active: bool
    read_only: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class ClusterHealthResponse(BaseModel):
    cluster_name: str
    status: str
    number_of_nodes: int
    active_shards: int
    relocating_shards: int
    unassigned_shards: int
