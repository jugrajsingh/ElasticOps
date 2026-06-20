from datetime import datetime

from sqlalchemy import ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    cluster_id: Mapped[int] = mapped_column(ForeignKey("clusters.id"))
    run_date: Mapped[datetime] = mapped_column(server_default=func.now())
    total_indices: Mapped[int] = mapped_column(Integer, default=0)
    total_shards: Mapped[int] = mapped_column(Integer, default=0)
    total_storage_bytes: Mapped[int] = mapped_column(Integer, default=0)
    total_opportunities: Mapped[int] = mapped_column(Integer, default=0)
    total_wasted_shards: Mapped[int] = mapped_column(Integer, default=0)
