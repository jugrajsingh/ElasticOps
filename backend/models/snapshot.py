from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class ClusterSnapshot(Base):
    """Precomputed, ready-to-serve snapshot of one cluster view (one row per cluster+kind)."""

    __tablename__ = "cluster_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    cluster_id: Mapped[int] = mapped_column(
        ForeignKey("clusters.id", ondelete="CASCADE"),
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict | list] = mapped_column(JSON)
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    fetched_at: Mapped[datetime] = mapped_column(server_default=func.now(), index=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (UniqueConstraint("cluster_id", "kind", name="uq_snapshot_cluster_kind"),)
