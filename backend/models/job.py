from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"))
    cluster_id: Mapped[int] = mapped_column(ForeignKey("clusters.id"))
    index_name: Mapped[str] = mapped_column(String(512))
    job_type: Mapped[str] = mapped_column(String(50))
    tier: Mapped[int] = mapped_column(Integer)
    severity: Mapped[str] = mapped_column(String(20), default="low")
    detail: Mapped[str] = mapped_column(Text, default="")
    current_shards: Mapped[int] = mapped_column(Integer, default=0)
    target_shards: Mapped[int] = mapped_column(Integer, default=0)
    current_replicas: Mapped[int] = mapped_column(Integer, default=0)
    pri_store_bytes: Mapped[int] = mapped_column(Integer, default=0)
    doc_count: Mapped[int] = mapped_column(Integer, default=0)
    estimated_savings_shards: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    approved_at: Mapped[datetime | None] = mapped_column(nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
